#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Kevin Russell (Aperture / Project Forty Two)
# -*- coding: utf-8 -*-
"""nulltest — does this honesty benchmark measure honesty, or string shape?

An honesty/hallucination benchmark labels items REAL vs FABRICATED. If a classifier that never
sees a model — only the surface form of the item text — can recover those labels, then any score
on that benchmark is partly a measure of string shape, not of the system under test.

This tool measures how much of a benchmark's label signal is recoverable from surface alone, and
returns a verdict. It scores no model. It needs no GPU, no network, and no access to whoever built
the benchmark. Point it at anyone's battery, including ours.

    python3 nulltest.py battery.json
    python3 nulltest.py battery.csv --text-key statement --label-key label --positive-label 0
    python3 nulltest.py qa.jsonl --text-key answer --label-key hallucinated --stratum-key question_type
    python3 nulltest.py battery.json --json          # machine-readable
    python3 nulltest.py battery.json --jobs 8        # permutations in parallel
    python3 nulltest.py --selftest                   # planted-failure control

Input: JSON (a list, or an object holding a list), JSONL, CSV or TSV. One text field, or several
joined with --text-key a,b. Labels may be 0/1, true/false, or any two strings; when the tool cannot
tell which value means "fabricated", it stops and asks for --positive-label rather than guessing.

WHAT IT MEASURES  (six surface probes, each a classifier or score with no model access)
    lexicality   character 3-5grams of the item text        (does the string LOOK fake?)
    words        word unigrams and bigrams                  (does the wording or template leak the label?)
    length       character and word count                   (are fakes shorter/longer?)
    shape        digit/punct/case/token-pattern signature    (are reals ID-shaped and fakes word-shaped?)
    alpha_first  alphabet position of the first word's initial  (was one class sampled from the top of a sorted list?)
    alpha_last   alphabet position of the last word's initial   (same, for lists sorted by surname)

    The null is STRATIFIED: labels are shuffled within each stratum, so every cell is compared
    against batteries with its own label rate. The relation between the category and the label is
    therefore conditioned on, not tested (v1.3 had a "stratum" probe for it, which could never
    score: a per-stratum rate is constant within a cell). The report prints the label rate per
    stratum as a plain description instead.

    The two alphabet probes were added in v1.3 because prominence-people-v1 PASSED the four
    probes of v1.2 and was broken anyway: its builder took the alphabetically-first 200 members
    of each Wikipedia category, and biography categories sort by surname. The surname initial
    alone recovers its labels at A* 0.661. Alphabetical sampling is a common way to build a
    battery, so the probe is general, not a patch for one file.

THREE RULES THIS TOOL ENFORCES, each learned by getting it wrong first:

  1. TWO-SIDED.  A* = max(AUROC, 1 - AUROC). A strongly anti-correlated confound is not "no
     signal" — an attacker inverts a classifier for free. We published a certificate on
     2026-07-24 whose char-ngram null read 0.163 ("clean") and was 0.837 two-sided. It was
     wrong for two hours and it flattered us.

  2. WORST CELL, NOT MEAN.  A mean over strata hides one separable stratum. Same certificate:
     mean 0.679, worst cell 0.837. The mean is the number that let it ship.

  3. PERMUTATION-CALIBRATED, NOT A MAGIC CONSTANT.  "A* < 0.60 is clean" is arbitrary and, at
     small n, wrong: with 20 items a stratum can hit 0.75 on noise. The threshold here is the
     95th percentile of A* under label shuffles of the SAME data — so it adapts to n, to class
     balance, and to the number of strata searched. A stratum is only disqualified when it beats
     the null distribution its own size generates.

A PASS IS NOT A CERTIFICATE OF QUALITY. It says surface features did not recover the labels under
these six probes. A benchmark can still be circular (labels drawn from the same store the system
retrieves from), contaminated, or mislabeled, and pass cleanly. Circularity in particular is
invisible here — it is a provenance property, not a surface one.

WHAT THIS IS, IN THE LITERATURE. The idea is the "hypothesis-only" / partial-input baseline of
Gururangan et al. 2018 and Poliak et al. 2018, and the artifact filtering of AFLite (Le Bras et
al. 2020): if a model that cannot see the task recovers the labels, the task leaks. What this
tool adds is not the idea but the packaging and the statistics: two-sided scoring, worst cell
rather than mean, permutation calibration with the classifier refit inside every permutation,
family-wise correction, a measured false-positive rate, and a browser port that computes the
same bits as the CLI. Do not cite it as a new method.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys

# --------------------------------------------------------------------------------------
# AUROC + two-sided separability, stdlib only (no numpy/sklearn required to READ a verdict)
# --------------------------------------------------------------------------------------
def auroc(y, s):
    """Rank-based AUROC with tie handling. y in {0,1}, s = scores."""
    pairs = sorted(zip(s, y))
    n = len(pairs)
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = r
        i = j + 1
    npos = sum(1 for _, yy in pairs if yy == 1)
    nneg = n - npos
    if npos == 0 or nneg == 0:
        return None
    rsum = sum(r for r, (_, yy) in zip(ranks, pairs) if yy == 1)
    return (rsum - npos * (npos + 1) / 2.0) / (npos * nneg)


def astar(y, s):
    """RULE 1 — two-sided separability. Direction-agnostic, because an attacker inverts for free."""
    a = auroc(y, s)
    return None if a is None else max(a, 1.0 - a)


# --------------------------------------------------------------------------------------
# the six surface probes — each maps item text to ONE score, using no model
# --------------------------------------------------------------------------------------
def _ngrams(t, lo=3, hi=5):
    t = " %s " % t.lower()
    out = set()
    for n in range(lo, hi + 1):
        for i in range(len(t) - n + 1):
            out.add(t[i : i + n])
    # SORTED, not a bare set. The naive-Bayes score is a SUM over these features, and float
    # addition is not associative, so iteration order changes the last bits of the score. A
    # set's order depends on string hashing (randomised per process in CPython) and does not
    # match JavaScript's insertion order — which made two cells of the browser/CLI parity
    # check disagree by one permutation in 600. Sorting makes both sides bit-identical.
    return sorted(out)


_WORD = re.compile(r"\w+")


def _words(t):
    """Word unigrams and adjacent bigrams, lowercased. \\w is Unicode-aware here and the JS port
    uses [\\p{L}\\p{N}_] for the same class."""
    ws = _WORD.findall(t.lower())
    out = set(ws)
    for a, b in zip(ws, ws[1:]):
        out.add(a + " " + b)
    return sorted(out)


_SHAPE = re.compile(r"[A-Z]{2,}|\d+|[^\w\s]")


def _shape_sig(t):
    """Token-shape signature: digit runs, ALLCAPS runs, punctuation. This is the probe that catches
    'reals are ID-shaped (NGC 6315, NCT02921971) and fakes are pronounceable words'."""
    return sorted({"S:" + ("D" if x.isdigit() else "U" if x.isupper() else "P") + str(min(len(x), 4))
                   for x in _SHAPE.findall(t)} | {"len%d" % min(len(t) // 4, 12)})


def _alpha_pos(ch):
    """1..26 for an ASCII letter (case-folded), else 0. Deliberately ASCII-only so that the Python
    and JavaScript engines agree on every input; a non-Latin initial scores 0 in both."""
    ch = ch.lower()
    # len check: lower() can expand one code point into two (U+0130 -> "i" + combining dot)
    return ord(ch) - 96 if len(ch) == 1 and "a" <= ch <= "z" else 0


def _alpha_first(t):
    ws = _WORD.findall(t)
    return _alpha_pos(ws[0][0]) if ws else 0


def _alpha_last(t):
    ws = _WORD.findall(t)
    return _alpha_pos(ws[-1][0]) if ws else 0


class _NB:
    """K-fold naive-Bayes log-odds over binary features, prepared once and refit per label vector.

    NOT leave-one-out. A LOO variant that subtracts an item's own counts from the class totals
    leaks its label: the subtraction itself leaves a systematic per-class offset, and this tool's
    own selftest caught that scoring a pure-noise battery at A* = 1.000. Counts are built on the
    training folds ONLY, so a test item never contributes to the statistics that score it.

    WHY A CLASS. v1.2 re-featurised every item and rebuilt every count dictionary on every one
    of the 600 permutations, so a 700-item battery took a quarter of an hour. Everything that
    does not depend on the labels — the features, the fold split, the per-fold vocabulary and
    its total counts — is now computed once here; score() does only the label-dependent half.
    The arithmetic is unchanged: the same log terms are summed in the same (sorted) order, so
    every score is bit-identical to v1.2's, which the parity harness checks against the JS port.
    """

    def __init__(self, texts, featfn, k=5, seed=20260724):
        feats = [featfn(t) for t in texts]
        vocab = sorted({g for f in feats for g in f})
        idx_of = {g: i for i, g in enumerate(vocab)}
        # ints in the SAME order as the sorted feature strings, so summation order is preserved
        self.items = [[idx_of[g] for g in f] for f in feats]
        n = len(texts)
        idx = list(range(n))
        random.Random(seed).shuffle(idx)
        self.folds = []
        for f in range(k):
            f_te = idx[f::k]
            te = set(f_te)
            tr = [i for i in idx if i not in te]
            if not tr or not f_te:
                continue
            total = [0] * len(vocab)
            for i in tr:
                for g in self.items[i]:
                    total[g] += 1
            # drop hapax (seen once in the training folds): pure memorisation
            te_feats = [(i, [g for g in self.items[i] if total[g] >= 2]) for i in f_te]
            self.folds.append((tr, te_feats, total))

    def score(self, y):
        scores = [0.0] * len(self.items)
        for tr, te_feats, total in self.folds:
            pos = [0] * len(total)
            npos = 0
            for i in tr:
                if y[i] == 1:
                    npos += 1
                    for g in self.items[i]:
                        pos[g] += 1
            nneg = len(tr) - npos
            if npos == 0 or nneg == 0:
                continue
            # log((count + 0.5) / (class + 1)) tabulated once per fold — the identical double the
            # per-feature expression produced, looked up instead of recomputed
            top = max(total) if total else 0
            lp = [math.log((c + 0.5) / (npos + 1.0)) for c in range(top + 1)]
            ln = [math.log((c + 0.5) / (nneg + 1.0)) for c in range(top + 1)]
            for i, fs in te_feats:
                sc = 0.0
                for g in fs:
                    p = pos[g]
                    sc += lp[p] - ln[total[g] - p]
                # QUANTIZE before ranking. The score is a sum of ~200 log terms, and CPython's
                # libm log and V8's Math.log may differ by 1 ulp — enough that two items which
                # tie exactly in one language differ by 1e-16 in the other, which changes a tie
                # group and moves the AUROC by half a rank. Caught in browser/CLI parity on
                # lexicality/firms (0.795 vs 0.800). 1e-9 is far above the noise and far below
                # any difference that could matter to a log-odds. floor(x*1e9+0.5) is exactly
                # what JavaScript's Math.round does, including for negatives.
                scores[i] = math.floor(sc * 1e9 + 0.5) / 1e9
        return scores


def _nb_scores(texts, y, featfn, k=5, seed=20260724):
    """One-shot form of _NB, kept for callers and tests that score a single label vector."""
    return _NB(texts, featfn, k=k, seed=seed).score(y)


# name -> ("nb", feature function) for a fitted probe, ("score", text function) for an unfitted
# one. Order matters only for the report; the verdict is order-free. v1.3 also carried a "stratum"
# probe (the per-stratum label rate); it was degenerate in every per-stratum cell by construction
# and never scored, and under the stratified null of v1.4 it is held fixed. It is gone.
NULLS = {
    "lexicality": ("nb", _ngrams),
    "words": ("nb", _words),
    "length": ("score", lambda t: len(t) + 0.001 * len(t.split())),
    "shape": ("nb", _shape_sig),
    "alpha_first": ("score", _alpha_first),
    "alpha_last": ("score", _alpha_last),
}


class _Prepared:
    """Everything about a battery that does not depend on the labels, computed once so that the
    observation and all permutations share it. Unfitted probes (length, alphabet) are a fixed
    score vector; fitted probes carry a prepared _NB."""

    def __init__(self, texts, strata):
        self.texts = texts
        self.strata = strata
        self.n = len(texts)
        self.has_strata = strata is not None and len(set(strata)) > 1
        self.fixed, self.nb = {}, {}
        for name, (kind, fn) in NULLS.items():
            if kind == "score":
                self.fixed[name] = [float(fn(t)) for t in texts]
            elif kind == "nb":
                self.nb[name] = _NB(texts, fn)

    def scores(self, name, y):
        kind = NULLS[name][0]
        if kind == "score":
            return self.fixed[name]
        return self.nb[name].score(y)


# Backwards-compatible single-shot probes (used by tests and by anyone who imported v1.2's names).
def null_lexicality(texts, y, strata):
    return _nb_scores(texts, y, _ngrams)


def null_words(texts, y, strata):
    return _nb_scores(texts, y, _words)


def null_length(texts, y, strata):
    return [NULLS["length"][1](t) for t in texts]


def null_shape(texts, y, strata):
    return _nb_scores(texts, y, _shape_sig)


def null_alpha_first(texts, y, strata):
    return [float(_alpha_first(t)) for t in texts]


def null_alpha_last(texts, y, strata):
    return [float(_alpha_last(t)) for t in texts]


# --------------------------------------------------------------------------------------
# RULE 3 — permutation calibration, done properly.
#
# v1.0 SHIPPED A BENT RULER. It scored a battery with NO signal in it as DISQUALIFIED up to
# 22 times in 25, and how often depended entirely on how the noise was built:
#
#     planted-clean as shipped (alternating labels, 1 stratum)   1/25   <- the selftest ran ONLY this
#     coin-flip labels, 1 stratum                               10/25
#     coin-flip, 2 strata                                       16/25
#     coin-flip, 4 strata                                       21/25
#     coin-flip, 6 strata                                       22/25
#
# Two independent causes, both fixed here:
#
#   (a) THE NULL DID NOT REFIT. permutation_threshold() shuffled the labels against a score
#       vector that had ALREADY been fitted on the true labels. The scorer's own overfitting
#       was therefore baked into both the observed statistic and its null, so the null could
#       not see it. Fixed: every permutation refits all four nulls from scratch on the
#       shuffled labels (_score_all_cells below), so the null distribution includes exactly
#       as much fitting slack as the observation does.
#
#   (b) NO FAMILY-WISE CORRECTION. A battery is 4 nulls x K strata tests, each judged against
#       its own 95th percentile. At 24 tests you EXPECT about one false fire per battery by
#       construction. Fixed: Westfall-Young min-p over the whole family, which controls the
#       probability of ANY false cell.
#
# WHY min-p AND NOT max-A*: A* is not comparable across cells of different size — a 16-item
# cell reaches 1.000 on noise far more easily than a 120-item one, so correcting on the raw
# maximum is dominated by the smallest cells and flips genuinely separable batteries to PASS.
# min-p standardises each cell against its OWN null distribution first, then takes the family
# minimum. Do not "simplify" this back to max-A*.
# --------------------------------------------------------------------------------------
SCOPE = (
    "SCOPE: this measures how much of the label signal is recoverable from SURFACE FORM alone "
    "by six model-free probes, two-sided, refit inside every permutation (labels shuffled within stratum) and family-wise "
    "corrected across all cells (Westfall-Young min-p). A PASS does NOT certify the benchmark "
    "is good: it cannot see circularity (labels drawn from the same store the system under test "
    "retrieves from), contamination, or mislabelling. It scores no model."
)


LABEL_VALIDITY_NOTE = """A battery must pass TWO independent checks, and passing only the first
is worse than failing both, because it looks clean.

  1. SURFACE FLOOR  — a model-free classifier must NOT recover the labels (this tool).
  2. LABEL VALIDITY — the labels must correspond to a real difference in the model's state.

There are at least two ways to pass (1) while failing (2), and we have now built both by
accident:

  NOVELTY COLLAPSE — make the fabricated entities near-copies of the real ones. They then share
      the real n-gram distribution by construction and no surface probe can separate them.
      Measured: our family battery passes the floor with median novelty 0.55 and ZERO of 70
      fabricated entities fully novel.

  LABEL COLLAPSE — choose entities the model knows NOTHING about in either class. The battery is
      then trivially surface-blind and measures nothing. Measured: a post-cutoff clinical-trial
      battery passed the floor cleanly (A* 0.526, held out, powered, novelty 0.80) — and the
      model's own gauge could not tell the classes apart either. Known entities read
      off_distribution 0.232 / familiarity 0.696; unknown read 1.000 / 0.185; BOTH trial classes
      read ~0.76 / ~0.29. The labels split dates, not knowledge.

So: report the surface floor, the novelty, AND a label-validity measurement. A battery that
passes the floor because the task is meaningless is the most expensive kind of clean result."""


def novelty(items, text_key="entity", label_key="label"):
    """Median novelty of the fabricated half: 1 - (longest substring shared with any single real
    entity) / length.

    WHY THIS SHIPS NEXT TO THE VERDICT. A surface PASS can always be manufactured by making the
    fabricated entities near-copies of real ones — they then share the real n-gram distribution
    by construction and no surface probe can separate them. Measured on real batteries: the one
    battery of ours that PASSES the surface floor has median novelty 0.55 and ZERO fully-novel
    fakes, while the two that fail have novelty 0.67-0.71. A PASS reported without novelty hides
    exactly the defect that produced it.

    Low novelty is not always cheating: in a DENSE-ID namespace (NCT ids, OEIS A-numbers) every
    invented identifier is one character from a real one, and no construction avoids that. That
    is itself the finding — such namespaces cannot host a surface-blind existence test.
    """
    reals = " | ".join(str(i[text_key]).lower() for i in items if int(i[label_key]) == 0)
    out = []
    for i in items:
        if int(i[label_key]) != 1:
            continue
        f = str(i[text_key]).lower()
        best = 0
        for a in range(len(f)):
            for b in range(a + best + 1, len(f) + 1):
                if f[a:b] in reals:
                    best = b - a
                else:
                    break
        out.append(1.0 - best / max(len(f), 1))
    if not out:
        return None
    out.sort()
    return round(out[len(out) // 2], 3)


def _cell_defs(strata):
    """The family of cells under test: one per (null, stratum). Fixed before any permutation
    so the observation and every permutation are scored over the identical family."""
    out = []
    for st in sorted(set(strata)):
        out.append((st, [i for i, x in enumerate(strata) if x == st]))
    return out


N_FOLDS = 5


def _fold_of(n, k=N_FOLDS, seed=20260724):
    """The fold each item lands in — the SAME assignment _nb_scores uses."""
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    f = [0] * n
    for pos, i in enumerate(idx):
        f[i] = pos % k
    return f


def _degenerate(scores, folds):
    """True when a cell's scores are a function of FOLD ASSIGNMENT ALONE.

    Some features are CONSTANT WITHIN A STRATUM by construction — a category one-hot, or a
    per-stratum rate. Sliced to one stratum, every item in a given fold then receives the
    identical out-of-fold score, so the only variation left is which fold you landed in, and
    A* = max(A, 1-A) rectifies that arbitrary tie pattern UPWARD. It looks like separability
    and it is arithmetic. Our published certificate reports six such numbers (category_onehot
    per stratum, 0.579-0.722); this tool reported them too, in the stratum null.

    THE TEST IS NOT "few distinct values". A first version of this guard used that, and it
    killed a TRUE positive: length/astronomy separates perfectly (real NGC ids are 6-8 chars,
    every fabricated one is 9) using only four distinct values, and dropping it flipped our own
    photon battery from DISQUALIFIED to PASS. A guard that hides a real defect in our own
    benchmark is worse than the artifact it removes. So the test is exact: one distinct score
    per fold means the feature never varied within the stratum.
    """
    if len(set(folds)) < 2:
        return True
    return len(set(zip(folds, scores))) == len(set(folds))


def _score_all_cells(prep, y, cells, folds=None):
    """Fit every probe on THESE labels and return A* for every (probe, stratum) cell.

    Called once for the observation and once per permutation. The refit is the point: it is
    what makes the null aware of the scorer's own capacity to overfit.
    """
    out = {}
    if folds is None:
        folds = _fold_of(len(y))
    for name in NULLS:
        s = prep.scores(name, y)
        if s is None:
            continue
        for st, idx in cells:
            ys = [y[i] for i in idx]
            ss = [s[i] for i in idx]
            if len(set(ys)) < 2 or _degenerate(ss, [folds[i] for i in idx]):
                out[(name, st)] = None
            else:
                out[(name, st)] = astar(ys, ss)
    return out


# ---- parallel permutations -------------------------------------------------------------
# The permutations are drawn in order from one seeded generator, so the sequence is fixed before
# any scoring happens; scoring them on several processes changes nothing but the wall clock.
# fork() lets the workers inherit the prepared battery without pickling it; on a platform
# without fork the tool simply runs serially, and says nothing, because the result is the same.
_PAR = {}


def _perm_worker(args):
    b, ys = args
    return b, _score_all_cells(_PAR["prep"], ys, _PAR["cells"], _PAR["folds"])


def _permutation_draws(prep, y, cells, folds, keys, n_perm, rng, jobs, progress):
    """Draw n_perm label vectors under the null, scoring each over every cell.

    THE NULL IS STRATIFIED. Labels are shuffled WITHIN each stratum, never across them, so every
    permuted battery has exactly the observed label rate in every cell. v1.3 shuffled across the
    whole battery: a cell with 85% label-1 was then compared against shuffles that gave it about
    50%, whose A* distribution is narrower, and on no-signal text the tool fired 44% of the time
    at 85/15 (0.9/0.1: 67%). Found 2026-10-24 by an outside statistical review. The cost of the
    fix is that the category-to-label relation is no longer something this test can see; the
    report describes it instead.

    Draws are kept ALIGNED by permutation index, None where a cell could not be scored on that
    shuffle (single-class after shuffling, or degenerate), so the min-p pass below sees the same
    permutation across all cells. v1.3 dropped the Nones and silently shifted the columns."""
    groups = [idx for _, idx in cells]
    perms = []
    for _ in range(n_perm):
        ys = list(y)
        for idx in groups:
            vals = [y[i] for i in idx]
            rng.shuffle(vals)
            for i, v in zip(idx, vals):
                ys[i] = v
        perms.append(ys)
    draws = {k: [] for k in keys}

    def take(sc):
        for k in keys:
            draws[k].append(sc.get(k))

    use_pool = jobs and jobs > 1 and n_perm >= 2 * jobs
    if use_pool:
        try:
            import multiprocessing as mp
            ctx = mp.get_context("fork")
        except (ImportError, ValueError):
            use_pool = False
    if use_pool and __name__ not in sys.modules:
        # Loaded by path (importlib.util.spec_from_file_location, as honest.py and the audit do)
        # rather than imported, this module is absent from sys.modules and the pool cannot pickle
        # a reference to _perm_worker. Register a module object that shares these globals.
        import types
        m = types.ModuleType(__name__)
        m.__dict__.update(globals())
        sys.modules[__name__] = m
    if use_pool:
        _PAR.update(prep=prep, cells=cells, folds=folds)
        results = [None] * n_perm
        done = 0
        with ctx.Pool(jobs) as pool:
            for b, sc in pool.imap_unordered(_perm_worker, list(enumerate(perms)), chunksize=4):
                results[b] = sc
                done += 1
                if progress and (done % 25 == 0):
                    progress(done, n_perm)
        _PAR.clear()
        for sc in results:        # in draw order, so the min-p pass sees the same columns serially
            take(sc)
    else:
        for b, ys_b in enumerate(perms):
            take(_score_all_cells(prep, ys_b, cells, folds))
            if progress and (b % 25 == 0):
                progress(b, n_perm)
    return draws


def _pval(sorted_col, t):
    """P(A* >= t) under this cell's own null. +1 in numerator and denominator: a permutation
    p-value must never be 0, or an adjusted p of 0 would claim infinite evidence from B draws."""
    import bisect
    b = len(sorted_col)
    if b == 0 or t is None:
        return 1.0
    return (b - bisect.bisect_left(sorted_col, t) + 1.0) / (b + 1.0)


def item_text(it, text_key):
    """The text the probes see. text_key may be one field or a list of fields, joined by a
    newline so that a question and its answer are scored together when asked to be."""
    if isinstance(text_key, (list, tuple)):
        return "\n".join(str(it.get(k, "")) for k in text_key)
    return str(it[text_key])


def evaluate(items, text_key, label_key, stratum_key, n_perm=600, seed=20260724,
             min_cell=12, alpha=0.05, progress=None, jobs=1):
    import bisect

    texts = [item_text(it, text_key) for it in items]
    y = [int(it[label_key]) for it in items]
    strata = [str(it.get(stratum_key, "_all")) for it in items] if stratum_key else ["_all"] * len(items)

    cells = _cell_defs(strata)
    folds = _fold_of(len(y))
    rng = random.Random(seed)
    prep = _Prepared(texts, strata)
    obs = _score_all_cells(prep, y, cells, folds)
    keys = sorted([k for k, v in obs.items() if v is not None])

    # ENOUGH PERMUTATIONS FOR THE FAMILY. Under min-p the smallest adjusted p a family of K cells
    # can reach is about (K+1)/(B+1): with K cells there are about K permutation draws whose own
    # min-p sits at the floor, and the observed cell cannot beat them. With K = 222 and B = 600 the
    # tool could reject nothing honestly, and v1.3 rejected anyway (see the Westfall-Young pass
    # below). So B is raised to at least 2(K+1)/alpha, rounded up to a hundred, and the raise is
    # recorded. --n-perm is a floor, not a ceiling.
    n_perm_requested = n_perm
    need = int(math.ceil(2.0 * (len(keys) + 1) / alpha / 100.0)) * 100
    if keys and n_perm < need:
        n_perm = need

    report = {"tool": "nulltest", "version": VERSION, "probes": list(NULLS),
              "n": len(items), "n_fake": sum(y), "n_real": len(y) - sum(y),
              "strata": sorted(set(strata)), "min_cell": min_cell, "n_perm": n_perm,
              "n_perm_requested": n_perm_requested,
              "alpha": alpha, "family_size": len(keys), "correction": "westfall_young_min_p",
              "null": "labels shuffled within stratum (stratified permutation), every probe refit",
              "label_rate_by_stratum": {st: {"n": len(idx), "label1_rate": round(sum(y[i] for i in idx) / len(idx), 3)}
                                        for st, idx in cells},
              "nulls": {}, "underpowered_cells": []}
    if n_perm != n_perm_requested:
        report["n_perm_note"] = ("%d permutations requested; %d cells need at least %d to resolve "
                                 "alpha=%.2f under min-p, so %d were run."
                                 % (n_perm_requested, len(keys), need, alpha, n_perm))

    if not keys:
        # NOT_SCORABLE, never PASS. A battery on which nothing could be scored was returning the
        # same verdict as one that survived 600 refits — so anyone could earn a clean bill from this
        # tool by handing it a corpus with no scorable cell. That is the vacuous green this
        # instrument exists to catch, sitting in the instrument. Found 2026-07-26 by an outside
        # judge reading the source, not by us running it.
        report["worst_cell"] = {"astar": None, "null": None, "stratum": None, "adj_p": None}
        report["n_separating_cells"] = 0
        report["verdict"] = "NOT_SCORABLE"
        report["headline"] = ("no scorable cell — nothing was tested. This is NOT a pass: a corpus "
                              "with no scorable stratum has not been checked, it has been skipped.")
        report["power"] = {"n": report["n"], "measured_mde": None,
                           "comparable_across_batteries": False,
                           "reading": "nothing was scored, so there is no power to report."}
        report["scope"] = SCOPE
        return report

    # ---- the null: refit everything, every permutation --------------------------------
    draws = _permutation_draws(prep, y, cells, folds, keys, n_perm, rng, jobs, progress)

    cols = {k: sorted(v for v in draws[k] if v is not None) for k in keys}

    # ---- Westfall-Young min-p ---------------------------------------------------------
    # The observed statistic and the B permuted ones are B+1 exchangeable values under the null,
    # and every one of them gets its p-value from the SAME pool: the count of values at or above
    # it, out of B+1. v1.3 gave the observed value p = (#draws >= obs + 1)/(B+1), floor 1/(B+1),
    # but each permuted value p = (#draws >= it)/(B+1) with itself counted and the observation
    # not, floor 2/(B+1). The observed could therefore always undercut every permuted min-p by
    # beating all B draws in ANY one cell, and the family-wise error was about K/(B+1) instead of
    # alpha: 8% at K=24, 32% at K=222 (simulated on iid nulls, 2026-10-24). The README called the
    # 8.4% a small-B discreteness effect; it was this.
    raw = {k: _pval(cols[k], obs[k]) for k in keys}
    q = []
    for b in range(n_perm):
        best = 1.0
        for k in keys:
            t = draws[k][b]
            if t is None:
                continue
            col = cols[k]
            p = (len(col) - bisect.bisect_left(col, t) + (1.0 if obs[k] >= t else 0.0)) / (len(col) + 1.0)
            if p < best:
                best = p
        q.append(best)
    q.sort()
    adj = {k: (bisect.bisect_right(q, raw[k]) + 1.0) / (n_perm + 1.0) for k in keys}

    # ---- report -----------------------------------------------------------------------
    # `_adj_p_exact` is the UNROUNDED adjusted p, kept only for comparison. Comparing the unrounded
    # adj[k] against the ROUNDED value stored below made `adj[k] < worst["adj_p"]` true for every
    # cell tied at the permutation floor (0.0016638 < 0.0017), so the reported worst cell was
    # whichever tied cell came LAST in NULLS order rather than the one with the largest effect.
    # Measured: the 147-claim battery reported "worst A* 0.778 in shape" while lexicality sat at
    # 0.967. The VERDICT was never affected (it is driven by the minimum adjusted p, and the tied
    # cells share it), but the headline understated how badly a battery failed.
    # Ties on the adjusted p are broken by EFFECT, (A* - 0.5) * sqrt(n), then by A*: a cell at
    # A* 1.000 with 21 items is less evidence than one at 0.989 with 130, and v1.3's tie-break on
    # A* alone put the small one in the headline (TruthfulQA, 2026-10-24).
    worst = {"astar": 0.0, "adj_p": 1.0, "_adj_p_exact": 2.0, "_effect": -1.0,
             "null": None, "stratum": None, "n": 0, "threshold": None}
    for name in NULLS:
        entry = {"per_stratum": {}}
        for st, idx in cells:
            k = (name, st)
            if k not in obs or obs[k] is None:
                continue
            col = cols.get(k, [])
            thr = col[min(len(col) - 1, int(round(0.95 * (len(col) - 1))))] if col else None
            cell = {"n": len(idx), "astar": round(obs[k], 3),
                    "threshold": round(thr, 3) if thr is not None else None,
                    "raw_p": round(raw[k], 4), "adj_p": round(adj[k], 4),
                    "separates": bool(adj[k] < alpha),
                    "underpowered": len(idx) < min_cell}
            entry["per_stratum"][st] = cell
            if cell["underpowered"]:
                tag = "%s/%s (n=%d)" % (name, st, len(idx))
                if tag not in report["underpowered_cells"]:
                    report["underpowered_cells"].append(tag)
            # the family verdict is driven by the SMALLEST adjusted p, ties broken by effect size
            effect = (obs[k] - 0.5) * math.sqrt(len(idx))
            if (adj[k] < worst["_adj_p_exact"]) or (adj[k] == worst["_adj_p_exact"] and (
                    effect > worst["_effect"] or (effect == worst["_effect"] and obs[k] > worst["astar"]))):
                worst = {"astar": round(obs[k], 3), "adj_p": round(adj[k], 4),
                         "_adj_p_exact": adj[k], "_effect": effect,
                         "raw_p": round(raw[k], 4), "null": name, "stratum": st,
                         "n": len(idx), "threshold": cell["threshold"],
                         "underpowered": cell["underpowered"]}
        if entry["per_stratum"]:
            report["nulls"][name] = entry

    worst.pop("_adj_p_exact", None)      # comparison scratch, never part of the published report
    worst.pop("_effect", None)
    report["worst_cell"] = worst
    report["n_separating_cells"] = sum(1 for k in keys if adj[k] < alpha)
    report["verdict"] = "DISQUALIFIED" if worst["adj_p"] < alpha else "PASS"
    # BORDERLINE. The verdict is binary because a gate has to be, but a family-adjusted p of 0.057
    # and one of 0.043 are the same evidence, and the difference between them can be the number of
    # cells in the family. Our own grounding-coordinate battery sat at adj p 0.030 with 18 cells in
    # v1.2 and 0.057 with 35 cells in v1.3: same worst cell, same A*, opposite verdict. A verdict
    # that a reader can see is near the line is worth more than one that pretends it is not.
    # Two-sided since v1.4: a DISQUALIFIED at 0.043 is as close to the line as a PASS at 0.057.
    report["borderline"] = bool(alpha / 2 <= worst["adj_p"] < 2 * alpha)
    if report["borderline"]:
        report["borderline_note"] = (
            "%s, but the worst cell's family-adjusted p (%s) is within a factor of two of alpha "
            "(%.2f). Treat this as 'close to the line at this n and this family size', not as %s. "
            "More items, or a different family size, could flip it either way."
            % (report["verdict"], worst["adj_p"], alpha,
               "clean" if report["verdict"] == "PASS" else "settled"))
    report["headline"] = (
        "worst cell A* = %s in %s/%s (n=%s), family-adjusted p = %s over %d cells"
        % (worst["astar"], worst["null"], worst["stratum"], worst.get("n"),
           worst["adj_p"], len(keys))
    )
    # SATURATION. A permutation p cannot go below 1/(B+1). When it lands exactly there the value is
    # a BOUND, not a measurement, and printing "adj p = 0.0017" invites reading it as one. Three
    # third-party rows in our published audit table sat at exactly 1/601 with nothing saying so.
    floor_p = 1.0 / (n_perm + 1.0)
    report["p_floor"] = round(floor_p, 6)
    report["saturated"] = bool(worst["adj_p"] <= round(floor_p, 4) + 1e-12)
    if report["saturated"]:
        report["saturation_note"] = (
            "adjusted p is AT the permutation floor 1/(%d+1) = %.5f. This is the smallest value %d "
            "permutations can express, so the true p is '<= %.5f', not '= %.5f'. Raise --n-perm to "
            "resolve further; it cannot change the verdict." % (n_perm, floor_p, n_perm, floor_p, floor_p))
    report["power"] = _power_note(report["n"], report["verdict"])
    report["scope"] = SCOPE
    return report


# --------------------------------------------------------------------------------------
# EXPLAIN — what, concretely, carries a separating cell.
#
# A verdict tells an author that the labels leak; it does not tell them where. The most useful
# thing this tool can print after DISQUALIFIED is the handful of features an author can go and
# look at: the n-grams, the words, the length gap, the initial letters. These are IN-SAMPLE
# descriptions of the cell (fit on all its labels), which is the right thing for a description
# and the wrong thing for a verdict — so they are printed under the verdict, never used for it.
# --------------------------------------------------------------------------------------
def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def _show_feature(name, g):
    if name == "lexicality":
        return "'%s'" % g.replace(" ", "␣")        # make padding spaces visible
    return "'%s'" % g


def explain_cell(name, texts, y, top=8, min_count=3):
    """Describe one (probe, cell): feature table for a fitted probe, class medians for a score."""
    kind, fn = NULLS[name]
    n1 = sum(y)
    n0 = len(y) - n1
    out = {"probe": name, "n": len(y), "n_label0": n0, "n_label1": n1}
    if kind == "nb":
        pos, neg = {}, {}
        feats = [fn(t) for t in texts]
        for f, yy in zip(feats, y):
            d = pos if yy == 1 else neg
            for g in f:
                d[g] = d.get(g, 0) + 1
        rows = []
        for g in set(pos) | set(neg):
            p, q = pos.get(g, 0), neg.get(g, 0)
            if p + q < min_count:
                continue
            lo = math.log((p + 0.5) / (n1 + 1.0)) - math.log((q + 0.5) / (n0 + 1.0))
            rows.append((lo, g, p, q))
        rows.sort()
        fav1 = [{"feature": g, "in_label1": p, "in_label0": q, "log_odds": round(lo, 2)}
                for lo, g, p, q in reversed(rows[-top:]) if lo > 0]
        fav0 = [{"feature": g, "in_label1": p, "in_label0": q, "log_odds": round(lo, 2)}
                for lo, g, p, q in rows[:top] if lo < 0]
        out["favours_label1"] = fav1
        out["favours_label0"] = fav0
        # the two items of each class that carry the most of these features
        score = {}
        for i, f in enumerate(feats):
            score[i] = sum(r["log_odds"] for r in fav1 if r["feature"] in f) + \
                       sum(r["log_odds"] for r in fav0 if r["feature"] in f)
        ones = sorted((i for i in range(len(y)) if y[i] == 1), key=lambda i: -score[i])[:2]
        zeros = sorted((i for i in range(len(y)) if y[i] == 0), key=lambda i: score[i])[:2]
        out["examples"] = {"label1": [texts[i][:120] for i in ones], "label0": [texts[i][:120] for i in zeros]}
        out["reading"] = ("features over-represented in label-1: %s; in label-0: %s"
                          % (", ".join(_show_feature(name, r["feature"]) for r in fav1[:5]) or "none",
                             ", ".join(_show_feature(name, r["feature"]) for r in fav0[:5]) or "none"))
    elif kind == "score":
        s = [float(fn(t)) for t in texts]
        m0 = _median([v for v, yy in zip(s, y) if yy == 0])
        m1 = _median([v for v, yy in zip(s, y) if yy == 1])
        out["median_label0"] = m0
        out["median_label1"] = m1
        if name == "length":
            out["reading"] = ("label-1 items are %s: median %.0f vs %.0f characters"
                              % ("longer" if m1 > m0 else "shorter" if m1 < m0 else "the same length", m1, m0))
        else:
            def letter(v):
                return chr(96 + int(round(v))) if 1 <= v <= 26 else "non-letter"
            out["reading"] = ("%s-word initials: label-1 median '%s' vs label-0 median '%s' "
                              "(alphabet position %.1f vs %.1f)"
                              % ("first" if name == "alpha_first" else "last", letter(m1), letter(m0), m1, m0))
    else:
        out["reading"] = "the label-1 rate differs between strata; see the per-stratum counts"
    return out


def explain(items, text_key, label_key, stratum_key, rep, max_cells=8):
    texts = [item_text(it, text_key) for it in items]
    y = [int(it[label_key]) for it in items]
    strata = [str(it.get(stratum_key, "_all")) for it in items] if stratum_key else ["_all"] * len(items)
    cells = [(e_name, st, c) for e_name, e in rep.get("nulls", {}).items()
             for st, c in e["per_stratum"].items() if c.get("separates")]
    w = rep.get("worst_cell") or {}
    if not cells and w.get("null"):
        c = rep["nulls"][w["null"]]["per_stratum"][w["stratum"]]
        cells = [(w["null"], w["stratum"], c)]
    cells.sort(key=lambda t: (t[2]["adj_p"], -t[2]["astar"]))
    # one cell per probe first, so a corpus whose `length` cells all separate still shows what the
    # words/shape/lexicality readings say; then the remaining cells in order
    first, rest, seen = [], [], set()
    for t in cells:
        (first if t[0] not in seen else rest).append(t)
        seen.add(t[0])
    cells = first + rest
    out = {"note": ("In-sample description of the separating cells, for finding the artifact. The "
                    "verdict above is held-out; these tables are not evidence for it."),
           "cells": []}
    for name, st, c in cells[:max_cells]:
        idx = [i for i, x in enumerate(strata) if x == st]
        d = explain_cell(name, [texts[i] for i in idx], [y[i] for i in idx])
        d.update({"stratum": st, "astar": c["astar"], "adj_p": c["adj_p"]})
        out["cells"].append(d)
    return out


# --------------------------------------------------------------------------------------
# MEASURED POWER — what this tool can and cannot see at a given n.
#
# Procedure (`--measure-power` runs it; the numbers below are its output, not a promise):
# build a clean synthetic base of n pronounceable nonsense words (CV syllables, 3-5 of them,
# seeded), assign labels by a seeded coin, then append ONE character to a fraction of the label-1
# half and record whether the verdict is DISQUALIFIED in >=3 of 4 seeds. The grid of fractions
# is coarse — 15%, 30%, 60%, 100% — so "60%" means "caught at 60%, missed at 30%".
#
# v1.2 (four probes), measured 2026-07-25:    n=156 60%   n=324 60%   n=702 60%   n=1496 30%
# v1.3 (seven probes, unstratified null), measured 2026-10-24:   n=156 60%   n=324 60%   n=702 30%   n=1496 15%
# v1.4 (six probes, stratified null): re-measured by `--power`; see README for the current row.
#
# The two rows are not the same base text and should not be read as "v1.3 is more powerful";
# the v1.2 base is not in this repository. The v1.3 row is reproducible from this file.
#
# Corroborated on real data: geometry-of-truth/cities is DISQUALIFIED at A* 0.765 with n=1496 and
# PASSES 5 of 5 random subsamples at n=354 (v1.2 measurement). A* is NOT a stable effect size —
# the lexicality probe is a fitted classifier, so with less data it learns an artifact less well
# and measured separability falls. Two corpora of different n are therefore NOT comparable.
_MDE = ((1496, 0.15), (702, 0.30), (324, 0.60), (156, 0.60))
_POWER_SIZES = (156, 324, 702, 1496)
_POWER_FRACTIONS = (0.15, 0.30, 0.60, 1.00)


def _power_base(r, n):
    return ["".join(r.choice("bcdfgklmnprst") + r.choice("aeiou") for _ in range(r.randrange(3, 6)))
            for _ in range(n)]


def measure_power(sizes=_POWER_SIZES, fractions=_POWER_FRACTIONS, seeds=4, n_perm=600, jobs=1):
    """Re-derive the _MDE table. Prints one line per (n, coverage) and the smallest coverage
    caught in >= 3 of `seeds` seeds for each n. Takes a few minutes with --jobs 4."""
    table = {}
    for n in sizes:
        mde = None
        for frac in fractions:
            fired = 0
            for seed in range(seeds):
                r = random.Random(1000 + seed)
                texts = _power_base(r, n)
                y = [i % 2 for i in range(n)]
                r.shuffle(y)
                ones = [i for i in range(n) if y[i] == 1]
                r.shuffle(ones)
                for i in ones[:int(round(frac * len(ones)))]:
                    texts[i] = texts[i] + "x"
                items = [{"entity": t, "label": yy, "category": "s"} for t, yy in zip(texts, y)]
                rep = evaluate(items, "entity", "label", "category", n_perm=n_perm, jobs=jobs)
                fired += rep["verdict"] == "DISQUALIFIED"
            print("  n=%-5d coverage %3.0f%%  DISQUALIFIED in %d/%d seeds" % (n, frac * 100, fired, seeds),
                  flush=True)
            if mde is None and fired * 4 >= 3 * seeds:
                mde = frac
        table[n] = mde
        print("  n=%-5d smallest coverage caught: %s" % (n, "%.0f%%" % (mde * 100) if mde else "none"))
    shipped = dict(_MDE)
    print()
    print("  shipped _MDE: %s" % ", ".join("n>=%d: %.0f%%" % (k, v * 100) for k, v in _MDE))
    print("  measured now: %s" % ", ".join("n>=%d: %s" % (k, "%.0f%%" % (v * 100) if v else "none")
                                           for k, v in sorted(table.items(), reverse=True)))
    agree = all(shipped.get(k) == v for k, v in table.items())
    print("  %s" % ("AGREES with the shipped table" if agree else
                    "DISAGREES with the shipped table — update _MDE or explain why not"))
    return 0 if agree else 1


def _power_note(n, verdict):
    mde = next((f for lo, f in _MDE if n >= lo), None)
    out = {"n": n, "measured_mde": mde,
           "mde_basis": ("one planted spelling/length artifact (a character appended to a fraction of "
                         "the label-1 items) in a single stratum, 4 seeds; a wider family, a smaller "
                         "cell or an artifact of another shape lowers power below this"),
           "comparable_across_batteries": False,
           "note_on_comparison": ("A* depends on n. Do not rank this battery against one of a "
                                  "different size: cities.csv is DISQUALIFIED at n=1496 and PASSES "
                                  "5 of 5 subsamples at n=354.")}
    # The asymmetry is the point: low power produces false NEGATIVES, not false positives. A test
    # that fired is evidence whatever its n; a test that stayed silent at small n may simply be blind.
    if mde is None and verdict == "DISQUALIFIED":
        out["reading"] = ("DISQUALIFIED at n=%d, below the smallest size we have measured (156). "
                          "Low power costs us DETECTIONS, not false alarms, so a verdict that fired "
                          "at this size stands: the artifact was large enough to see anyway." % n)
    elif mde is None:
        out["reading"] = ("PASS at n=%d, below the smallest size we have measured (156). We have not "
                          "established what this test can detect here, so this PASS is not evidence "
                          "of cleanliness." % n)
    elif verdict == "PASS":
        out["reading"] = ("PASS at n=%d. Measured: an artifact must cover about %.0f%% of the "
                          "label-1 half before this test catches it at this size. A PASS here does "
                          "NOT exclude a weaker artifact." % (n, mde * 100))
    else:
        out["reading"] = ("DISQUALIFIED at n=%d, which is above the measured detection threshold "
                          "(~%.0f%% coverage) — the artifact is large enough to see at this size."
                          % (n, mde * 100))
    return out


# --------------------------------------------------------------------------------------
TEXT_KEYS = ("entity", "text", "claim", "statement", "question", "answer", "response", "name",
             "prompt", "title", "sentence")
LABEL_KEYS = ("label", "y", "is_fake", "fabricated", "hallucinated", "hallucination", "is_true",
              "truth", "type", "kind")
STRATUM_KEYS = ("category", "domain", "stratum", "cell", "topic", "source", "task")

# Label strings that mean "the fabricated / false / hallucinated class" without being told.
POSITIVE_WORDS = ("fake", "fabrication", "fabricated", "false", "1", "coined", "hallucinated",
                  "hallucination", "unfaithful", "incorrect", "wrong", "no", "yes_hallucinated")
NEGATIVE_WORDS = ("real", "true", "0", "genuine", "faithful", "correct", "right", "yes", "known",
                  "grounded")


class LabelError(ValueError):
    pass


def coerce_labels(items, label_key, positive=None):
    """Map whatever the label column holds onto 0/1, or refuse.

    v1.2 mapped any string it did not recognise to 0, silently. A corpus labelled
    hallucinated/faithful therefore scored as all-zeros-plus-nothing, and a corpus labelled
    yes/no was coded backwards. Both looked like ordinary runs. Now: two distinct values are
    required, booleans and 0/1 are accepted, a known word pair is accepted, and anything else
    stops with the two values it saw and asks which one is the positive class.
    """
    vals = []
    for it in items:
        v = it[label_key]
        if isinstance(v, bool):
            v = "1" if v else "0"
        vals.append(str(v).strip())
    distinct = sorted(set(vals))
    if len(distinct) != 2:
        raise LabelError("the label field %r holds %d distinct values (%s); this test needs exactly "
                         "two. Filter the file first, or pick another --label-key."
                         % (label_key, len(distinct), ", ".join(repr(d) for d in distinct[:6])))
    if positive is not None:
        pos = str(positive).strip()
        if pos not in distinct:
            # label values are compared case-folded below, so the flag is too
            fold = [d for d in distinct if d.lower() == pos.lower()]
            if len(fold) != 1:
                raise LabelError("--positive-label %r is not one of the two label values %r"
                                 % (pos, distinct))
            pos = fold[0]
    else:
        low = [d.lower() for d in distinct]
        if low[0] in POSITIVE_WORDS and low[1] in NEGATIVE_WORDS:
            pos = distinct[0]
        elif low[1] in POSITIVE_WORDS and low[0] in NEGATIVE_WORDS:
            pos = distinct[1]
        elif low == ["0", "1"]:
            pos = distinct[1]
        elif low == ["0.0", "1.0"]:
            pos = distinct[1]
        else:
            raise LabelError("the label field %r holds %r and %r and the tool cannot tell which one is "
                             "the fabricated/false class. Say so with --positive-label VALUE. (It will "
                             "not guess: a guess that is wrong only flips the sign, and this test is "
                             "two-sided, but a guess reported as a finding is still a guess.)"
                             % (label_key, distinct[0], distinct[1]))
    return [{**it, label_key: 1 if v == pos else 0} for it, v in zip(items, vals)], pos


def read_items(path):
    """Read a JSON list, a JSON object holding a list, JSONL, CSV or TSV into a list of dicts."""
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            raw = fh.read()
    except FileNotFoundError:
        raise LabelError("no such file: %s" % path)
    except IsADirectoryError:
        raise LabelError("%s is a directory, not a battery file" % path)
    except UnicodeDecodeError as e:
        raise LabelError("%s is not UTF-8 text (%s); this tool reads JSON, JSONL, CSV and TSV" % (path, e.reason))
    low = path.lower()
    if low.endswith((".csv", ".tsv")):
        import csv
        import io
        dialect = "excel-tab" if low.endswith(".tsv") else "excel"
        return list(csv.DictReader(io.StringIO(raw), dialect=dialect))
    raw = raw.strip()
    if not raw:
        raise LabelError("%s is empty" % path)
    if low.endswith(".jsonl") or low.endswith(".ndjson"):
        return _read_json_lines(raw, path)
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        # a .json that is really JSON lines; otherwise say where the JSON broke
        try:
            items = _read_json_lines(raw, path)
        except LabelError:
            raise LabelError("%s is not valid JSON: %s (line %d column %d)" % (path, e.msg, e.lineno, e.colno))
    if isinstance(items, dict):
        for k in ("items", "battery", "data", "rows", "examples", "instances"):
            if isinstance(items.get(k), list):
                return items[k]
        raise LabelError("could not find a list of items in %s (looked for items / battery / data / "
                         "rows / examples / instances)" % path)
    if not isinstance(items, list):
        raise LabelError("could not find a list of items in %s" % path)
    return items


def _read_json_lines(raw, path):
    out = []
    for n, l in enumerate(raw.splitlines(), 1):
        if not l.strip():
            continue
        try:
            out.append(json.loads(l))
        except json.JSONDecodeError as e:
            raise LabelError("%s line %d is not valid JSON: %s" % (path, n, e.msg))
    return out


def sniff_keys(items, text_key=None, label_key=None, stratum_key=None):
    """Pick the text, label and stratum fields from the items' own keys, unless told.

    `--stratum-key none` (or an empty value) switches the automatic stratum off, which is what
    the BORDERLINE note means by "--stratum-key omitted" when a stratum WAS sniffed."""
    if stratum_key is not None and str(stratum_key).strip().lower() in ("", "none"):
        text_key_, label_key_ = text_key, label_key
        keys = set()
        for it in items[:200]:
            if isinstance(it, dict):
                keys.update(it.keys())
        return (text_key_ or next((k for k in TEXT_KEYS if k in keys), None),
                label_key_ or next((k for k in LABEL_KEYS if k in keys), None), None)
    keys = set()
    for it in items[:200]:
        if isinstance(it, dict):
            keys.update(it.keys())
    tk = text_key or next((k for k in TEXT_KEYS if k in keys), None)
    lk = label_key or next((k for k in LABEL_KEYS if k in keys), None)
    sk = stratum_key or next((k for k in STRATUM_KEYS if k in keys), None)
    return tk, lk, sk


def parse_explode(spec):
    """"right_answer=0,hallucinated_answer=1" -> [("right_answer", 0), ("hallucinated_answer", 1)]."""
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise LabelError("--explode needs FIELD=LABEL pairs, got %r" % part)
        f, v = part.rsplit("=", 1)
        out.append((f.strip(), v.strip()))
    if not out:
        raise LabelError("--explode was given but names no fields")
    return out


def explode_items(items, mapping, split=None, text_key="text", label_key="label"):
    """Turn question-answer rows into one item per answer.

    Most QA benchmarks keep a right and a wrong answer on the same row (HaluEval), or several of
    each in one cell separated by ';' (TruthfulQA). This test needs one text and one label per
    item, and the question it asks of such data is: can the answer be told right from wrong
    WITHOUT the question? So each named field becomes an item carrying that field's label, the
    row's other fields are kept (the question's category makes a good stratum), and the source
    row index is kept as `_row` so per-question cells are possible.
    """
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        for field, lab in mapping:
            if field not in it or it[field] is None:
                continue
            raw = it[field]
            vals = raw if isinstance(raw, list) else ([v for v in str(raw).split(split)] if split else [raw])
            for v in vals:
                v = str(v).strip()
                if not v:
                    continue
                row = {k: x for k, x in it.items() if k not in dict(mapping)}
                row[text_key] = v
                row[label_key] = lab
                row["_row"] = i
                row["_field"] = field
                out.append(row)
    seen = {f for it in items if isinstance(it, dict) for f, _ in mapping if f in it}
    unseen = [f for f, _ in mapping if f not in seen]
    if unseen:
        have = sorted({k for it in items[:50] if isinstance(it, dict) for k in it})
        raise LabelError("--explode names %s, which no row carries. The rows carry: %s"
                         % (", ".join(repr(f) for f in unseen), ", ".join(have[:20])))
    if not out:
        raise LabelError("--explode produced no items; are the field names right? (%s)"
                         % ", ".join(f for f, _ in mapping))
    return out


def load(path, text_key, label_key, positive=None, explode=None, split=None, info=None):
    """Items with the text field(s) and the label field, labels coerced to 0/1.

    `info`, if a dict, receives what happened on the way: rows read, rows dropped for lacking
    the label or text field, empty texts, non-string texts coerced, and the raw value that
    became label-1. The report prints it, because a silent drop is a silent change of corpus.

    text_key may be "a,b" or a list: the fields are kept separate on the item and joined only
    when the probes read them (see item_text). `explode` is a parse_explode() mapping that turns
    each row into one item per answer field first."""
    if isinstance(text_key, str) and "," in text_key:
        text_key = [k.strip() for k in text_key.split(",") if k.strip()]
    tkeys = list(text_key) if isinstance(text_key, (list, tuple)) else [text_key]
    try:
        items = read_items(path)
        if explode:
            items = explode_items(items, explode, split=split, text_key=tkeys[0], label_key=label_key)
    except LabelError as e:
        sys.exit(str(e))
    out = [it for it in items if isinstance(it, dict) and label_key in it
           and all(k in it for k in tkeys)]
    if not out:
        sys.exit("no items had both --text-key %r and --label-key %r" % (text_key, label_key))
    try:
        out, pos = coerce_labels(out, label_key, positive)
    except LabelError as e:
        sys.exit(str(e))
    if info is not None:
        raw_vals = sorted({str(it[label_key]).strip() if not isinstance(it[label_key], bool)
                           else ("1" if it[label_key] else "0")
                           for it in items if isinstance(it, dict) and label_key in it})
        info.update({
            "rows_read": len(items),
            "rows_dropped_missing_field": len(items) - len(out),
            "empty_texts": sum(1 for it in out if not item_text(it, tkeys).strip()),
            "non_string_texts": sum(1 for it in out if any(not isinstance(it.get(k), str) for k in tkeys)),
            "label1_raw_value": pos,
            "label0_raw_value": next((v for v in raw_vals if v != pos), None),
        })
    return out


def _noise_battery(seed, strata, mode, n=120):
    """A battery with NO signal in it: identical surface forms, labels assigned by noise.

    `mode` is the whole point of the grid. "alt" alternates labels by position; "coin" flips a
    coin. v1.0's selftest ran ONLY ("alt", 1 stratum) — the single construction it passed — and
    printed "selftest: PASS". The construction IS the finding, so we publish a grid, not a number.
    """
    r = random.Random(seed)
    out = []
    # Two pronounceable nonsense words per item, drawn from a 40-word pool so that word unigrams
    # recur and the `words` probe has something to fit. On the NCT-id rows the word, alphabet and
    # shape probes are constant across items and drop out as degenerate, so those rows say nothing
    # about whether the probes added in v1.3 over-fire. This construction keeps all six live.
    rp = random.Random(seed * 7919 + 1)        # its own stream, so the NCT rows stay v1.2-identical
    pool = ["".join(rp.choice("bcdfgklmnprst") + rp.choice("aeiou") for _ in range(rp.randrange(2, 5)))
            for _ in range(40)]
    if mode == "coinword_small":
        n = 60
    for i in range(n):
        st = i % strata
        if mode == "alt":
            y = i % 2
        elif mode == "coinword_imb":
            # unequal label rates per stratum (85% / 15%): the construction the unstratified null
            # of v1.3 false-fired on 44% of the time
            y = int(r.random() < (0.85 if st % 2 == 0 else 0.15))
        else:
            y = r.randrange(2)
        if mode.startswith("coinword"):
            text = "%s %s" % (r.choice(pool), r.choice(pool))
        else:
            text = "NCT%08d" % r.randrange(10 ** 7)
        out.append({"entity": text, "label": y, "category": "s%d" % st})
    return out


def _log_comb(n, k):
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def _binom_cdf(k, n, p):
    """P(X <= k) for Binomial(n, p), in log space so n=500 does not underflow."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    lp, lq = math.log(p), math.log1p(-p)
    return min(1.0, sum(math.exp(_log_comb(n, i) + i * lp + (n - i) * lq)
                        for i in range(0, k + 1)))


def clopper_pearson(k, n, conf=0.95):
    """Exact binomial interval by bisecting the CDF (monotone in p). No scipy.

    WHY THIS EXISTS. v1.1 compared a 25-seed POINT ESTIMATE of a ~5% rate against a 10% ceiling.
    That is 4 percentage points of resolution per seed, so FAIL required >=3/25 in any row, and
    against a null calibrated at exactly nominal 5% it fires with probability 0.493. A control
    that fails a correct tool half the time is not a control. The interval is the smallest honest
    repair: it makes the tool say "I cannot tell at this seed count" instead of guessing.
    """
    if n <= 0:
        return (0.0, 1.0)
    a = (1.0 - conf) / 2.0
    lo, hi = 0.0, 1.0
    if k > 0:
        x0, x1 = 0.0, 1.0
        for _ in range(100):
            m = 0.5 * (x0 + x1)
            if 1.0 - _binom_cdf(k - 1, n, m) < a:
                x0 = m
            else:
                x1 = m
        lo = 0.5 * (x0 + x1)
    if k < n:
        x0, x1 = 0.0, 1.0
        for _ in range(100):
            m = 0.5 * (x0 + x1)
            if _binom_cdf(k, n, m) > a:
                x0 = m
            else:
                x1 = m
        hi = 0.5 * (x0 + x1)
    return (lo, hi)


GRID = (("planted-clean as shipped (alternating, 1 stratum)", "alt", 1),
        ("coin-flip labels, 1 stratum", "coin", 1),
        ("coin-flip, 2 strata", "coin", 2),
        ("coin-flip, 4 strata", "coin", 4),
        ("coin-flip, 6 strata", "coin", 6),
        ("coin-flip, word-shaped text (all 6 probes live), 1 stratum", "coinword", 1),
        ("coin-flip, word-shaped text (all 6 probes live), 4 strata", "coinword", 4),
        ("coin-flip, word-shaped, 2 strata with 85/15 label rates", "coinword_imb", 2),
        ("coin-flip, word-shaped, 6 strata (36 cells)", "coinword", 6),
        ("coin-flip, word-shaped, 3 strata of 20 items", "coinword_small", 3))

VERSION = "1.4"
FALSE_FIRE_CEILING = 0.10


def _grid_cell(args):
    """One no-signal battery, scored. A module-level function so a process pool can run it."""
    seed, k, mode, n_perm = args
    return evaluate(_noise_battery(seed, k, mode), "entity", "label", "category",
                    n_perm=n_perm)["verdict"] == "DISQUALIFIED"


def _run_grid_row(mode, k, seeds, seed_base, n_perm, jobs):
    work = [(seed_base + s, k, mode, n_perm) for s in range(seeds)]
    if jobs and jobs > 1 and seeds >= 2 * jobs:
        try:
            import multiprocessing as mp
            with mp.get_context("fork").Pool(jobs) as pool:
                return sum(pool.map(_grid_cell, work, chunksize=1))
        except (ImportError, ValueError):
            pass
    return sum(_grid_cell(w) for w in work)


def selftest(seeds=25, n_perm=200, seed_base=9000, emit=None, jobs=1):
    """Planted-failure control, BOTH directions, across a grid of noise constructions.

    A null test that cannot fire is decoration. One that fires on noise is a smoke alarm with
    no batteries. v1.0 measured only the first half, on the construction that flattered it most.

    v1.1 THEN GRADED ITSELF WITH A COIN, and this is the defect v1.2 repairs. It estimated a ~5%
    rate from 25 seeds, took the MAXIMUM over five grid rows, and compared that maximum to a 10%
    ceiling — so FAIL required only >=3/25 in any one row. Against a null calibrated at exactly
    the nominal 5%, that fires with probability 0.493. Measured properly (300 seeds per row,
    1500 batteries) the shipped null false-fires at 4.73% pooled, worst row 6.00%, which is
    statistically indistinguishable from nominal and significantly BELOW the ceiling. The
    committed control (worst 8%) and the run that exposed this (worst 16%) are two ordinary draws
    from the same process; neither was ever evidence about the estimator.

    Two things follow, and both are implemented here rather than described:

      1. A POINT ESTIMATE MAY NOT GATE A CEILING. Each row now reports an exact (Clopper-Pearson)
         interval, and there are three outcomes, not two: FAIL only when a row's lower bound
         exceeds the ceiling, PASS only when every row's upper bound is below it, and
         INDISTINGUISHABLE when the ceiling lies inside an interval. At 25 seeds the honest
         answer is almost always the third one, and the tool now says so instead of guessing.

      2. THE VERIFIER MAY NOT WRITE ITS OWN CERTIFICATE. v1.1 wrote nulltest_grid.json on every
         run, so whichever side of the coin it landed on was published as fact — which is how a
         control that disagrees with its own code survived in the repository. This function is now
         READ-ONLY. Emission moved to --emit-grid, which refuses to write into the served
         directory and stamps provenance into the artifact.
    """
    ok = True

    r = random.Random(7)
    dirty = ([{"entity": "NCT%08d" % r.randrange(10 ** 7), "label": 0, "category": "trials"}
              for _ in range(60)]
             + [{"entity": "".join(r.choice("bcdfg") + r.choice("aeiou") for _ in range(4)),
                 "label": 1, "category": "trials"} for _ in range(60)])
    r1 = evaluate(dirty, "entity", "label", "category", n_perm=n_perm)
    print("  planted-separable battery -> %s" % r1["verdict"])
    print("      %s" % r1["headline"])
    if r1["verdict"] != "DISQUALIFIED":
        print("  FAIL: did not flag a battery separable by shape alone")
        ok = False

    print()
    print("  FALSE-FIRE GRID — batteries with no signal in them, %d seeds each" % seeds)
    print("  (rate with exact 95%% interval; ceiling %.0f%%)" % (100 * FALSE_FIRE_CEILING))
    worst = 0.0
    rows_out = []
    any_above = False
    all_below = True
    for label, mode, k in GRID:
        bad = _run_grid_row(mode, k, seeds, seed_base, n_perm, jobs)
        rate = bad / float(seeds)
        lo, hi = clopper_pearson(bad, seeds)
        worst = max(worst, rate)
        # The ceiling is a claim about the TRUE rate, so only the interval can speak to it.
        above = lo > FALSE_FIRE_CEILING          # demonstrably over the ceiling
        below = hi < FALSE_FIRE_CEILING          # demonstrably under it
        any_above = any_above or above
        all_below = all_below and below
        rows_out.append({"construction": label, "mode": mode, "strata": k,
                         "false_disqualified": bad, "seeds": seeds, "rate": rate,
                         "ci95": [lo, hi],
                         "reading": ("above ceiling" if above else
                                     "below ceiling" if below else
                                     "cannot distinguish from the ceiling at this seed count")})
        print("    %-60s %2d/%-3d  %5.1f%%  [%4.1f%%, %5.1f%%]  %s"
              % (label, bad, seeds, 100 * rate, 100 * lo, 100 * hi,
                 "ABOVE" if above else "below" if below else "indistinguishable"))

    if any_above:
        state, code = "FAIL", 1
        note = "at least one row's lower bound exceeds the ceiling — this is a real over-fire"
    elif all_below and ok:
        state, code = "PASS", 0
        note = "every row's upper bound is below the ceiling"
    else:
        state, code = ("FAIL", 1) if not ok else ("INDISTINGUISHABLE", 2)
        note = ("the ceiling lies inside at least one interval: this seed count cannot tell a "
                "calibrated tool from an over-firing one. Run --calibrate for a real certificate."
                if ok else "the planted-separable control failed, which is fatal regardless of the grid")

    print()
    print("  worst observed rate: %.1f%% — but see the intervals; a point estimate at %d seeds "
          "has ~%.0f points of resolution per seed" % (100 * worst, seeds, 100.0 / seeds))
    print("  selftest: %s" % state)
    print("      %s" % note)
    if state == "INDISTINGUISHABLE":
        print("      (v1.1 would have printed PASS or FAIL here by coin flip — at 25 seeds a "
              "perfectly calibrated null failed it 49% of the time)")

    if emit:
        _emit_grid(emit, rows_out, seeds, n_perm, seed_base, worst, state)
    return code


def _emit_grid(path, rows_out, seeds, n_perm, seed_base, worst, state):
    """Write the certificate — deliberately NOT something --selftest can do.

    A verifier that writes the file it is later checked against has no control at all; that is
    exactly how nulltest_grid.json came to disagree with the code that shipped alongside it.
    So this is a separate, explicit act, it refuses to write into the served directory, and it
    stamps enough provenance into the artifact that a stranger can tell which code produced it.
    """
    import subprocess

    here = os.path.dirname(os.path.abspath(__file__))
    dest = os.path.abspath(path)
    if os.path.dirname(dest) == here:
        print("  REFUSED to emit into the served directory (%s)." % here)
        print("  Emit elsewhere and have an independent pre-serve gate copy it in after "
              "verifying the tool hash. The verifier does not certify itself.")
        return 1

    src = open(os.path.join(here, "nulltest.py"), "rb").read()
    def _git(*a):
        try:
            return subprocess.run(("git",) + a, cwd=here, capture_output=True,
                                  text=True, timeout=10).stdout.strip() or None
        except Exception:
            return None

    with open(dest, "w") as fh:
        json.dump({
            "tool": "nulltest", "version": VERSION,
            "measures": "share of NO-SIGNAL batteries falsely returned DISQUALIFIED",
            "ceiling": FALSE_FIRE_CEILING, "state": state,
            "seeds": seeds, "n_perm": n_perm, "seed_base": seed_base,
            "worst_observed_rate": worst,
            "grid": rows_out,
            "provenance": {
                "tool_sha256": hashlib.sha256(src).hexdigest(),
                "git_commit": _git("rev-parse", "HEAD"),
                "git_dirty": bool(_git("status", "--porcelain")),
                "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
                "note": ("This artifact is evidence about the code whose sha256 is recorded here. "
                         "If tool_sha256 does not match the served nulltest.py, the certificate "
                         "does not describe the served tool and must not be trusted."),
            },
        }, fh, indent=1)
    print("  emitted %s" % dest)
    return 0


def _tool_sha256():
    with open(os.path.abspath(__file__), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def check_receipt(receipt_path, battery_path, jobs=1):
    """Replay a published report against the bytes in front of you.

    Nothing self-certifies: the receipt names the file hash, the tool hash, the keys it read and
    the permutation count it used. This re-runs under exactly those settings and says whether the
    verdict and the worst cell come out the same. Exit 0 on REPLAYS, 1 on DIVERGES, 2 on a
    receipt that cannot be replayed (different file, missing fields)."""
    need = ("verdict", "worst_cell", "keys", "n_perm", "battery_sha256")

    def _as_receipt(path):
        try:
            with open(path, encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        if not isinstance(rec, dict):
            return None
        if isinstance(rec.get("evidence"), dict) and "worst_cell" in rec["evidence"]:
            # `honest null` writes the contract's Verdict, with the receipt fields under evidence
            rec = {**rec["evidence"], "verdict": rec.get("verdict")}
        return rec if all(k in rec for k in need) else rec | {"_missing": [k for k in need if k not in rec]}

    rec = _as_receipt(receipt_path)
    if rec is None or rec.get("_missing"):
        other = _as_receipt(battery_path)
        if other is not None and not other.get("_missing"):
            print("  the arguments look swapped: %s is the receipt. Usage: nulltest.py BATTERY --check RECEIPT.json"
                  % os.path.basename(battery_path))
            return 2
        if rec is None:
            print("  %s is not a JSON receipt" % receipt_path)
            return 2
        print("  receipt lacks %s; only reports written by nulltest 1.3+ with --json (or `honest null`) can be replayed"
              % ", ".join(rec["_missing"]))
        return 2
    with open(battery_path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    print("nulltest --check — replaying %s against %s" % (os.path.basename(receipt_path),
                                                            os.path.basename(battery_path)))
    if sha != rec["battery_sha256"]:
        print("  DIFFERENT FILE: receipt sha256 %s..., this file %s..." % (rec["battery_sha256"][:16], sha[:16]))
        print("  The receipt does not describe these bytes. Nothing to replay.")
        return 2
    tool_now = _tool_sha256()
    same_tool = rec.get("tool_sha256") == tool_now
    print("  file hash matches; tool %s" % ("identical to the one that wrote the receipt" if same_tool
                                           else "DIFFERS from the one that wrote the receipt (%s... vs %s...)"
                                           % (str(rec.get("tool_sha256"))[:12], tool_now[:12])))
    keys = rec["keys"]
    raw = read_items(battery_path)
    explode = None
    ex = rec.get("explode") or {}
    if ex.get("fields"):
        explode = [(f, v) for f, v in ex["fields"].items()]
        raw = explode_items(raw, explode, split=ex.get("split"))
    tk, lk, sk = keys.get("text"), keys.get("label"), keys.get("stratum")
    items = load(battery_path, tk, lk, rec.get("positive_label"), explode=explode, split=ex.get("split"))
    tkeys = tk.split(",") if "," in tk else tk
    rep = evaluate(items, tkeys, lk, sk, n_perm=int(rec["n_perm"]), alpha=float(rec.get("alpha", 0.05)),
                   jobs=jobs)
    w0, w1 = rec["worst_cell"], rep["worst_cell"]
    same_verdict = rep["verdict"] == rec["verdict"]
    same_cell = (w0.get("null"), w0.get("stratum")) == (w1.get("null"), w1.get("stratum"))
    same_num = abs(float(w0.get("astar", -1)) - w1["astar"]) < 1e-9 and \
        abs(float(w0.get("adj_p", -1)) - w1["adj_p"]) < 1e-9
    print("  receipt: %-12s %s/%s A* %s adj p %s" % (rec["verdict"], w0.get("null"), w0.get("stratum"),
                                                     w0.get("astar"), w0.get("adj_p")))
    print("  replay : %-12s %s/%s A* %s adj p %s" % (rep["verdict"], w1["null"], w1["stratum"],
                                                     w1["astar"], w1["adj_p"]))
    if same_verdict and same_cell and same_num:
        print("  REPLAYS — the same verdict, the same worst cell, the same numbers, from the same bytes.")
        return 0
    if same_verdict and same_cell:
        print("  REPLAYS with different numbers — same verdict and worst cell; the numbers differ, which "
              "happens when the tool version changed between the receipt and now.")
        return 0
    print("  DIVERGES — this is not the result the receipt claims for these bytes.")
    return 1


def main(argv):
    ap = argparse.ArgumentParser(description="does this honesty benchmark measure honesty, or string shape?")
    ap.add_argument("battery", nargs="?")
    ap.add_argument("--text-key", default=None)
    ap.add_argument("--label-key", default=None)
    ap.add_argument("--stratum-key", default=None)
    ap.add_argument("--explode", default=None, metavar="FIELD=LABEL,...",
                    help="question-answer rows: make one item per named answer field, with that "
                         "label. e.g. right_answer=0,hallucinated_answer=1")
    ap.add_argument("--split", default=None, metavar="SEP",
                    help="with --explode: split each field on SEP first (TruthfulQA uses ';')")
    ap.add_argument("--explain", action="store_true",
                    help="after the verdict, list the features that carry each separating cell")
    ap.add_argument("--positive-label", default=None,
                    help="which label value is the fabricated/false class, when the tool cannot tell")
    ap.add_argument("--n-perm", type=int, default=600)
    ap.add_argument("--jobs", type=int, default=1,
                    help="processes for the permutations (and for --selftest/--calibrate seeds). "
                         "Changes the wall clock only; the permutations are drawn before scoring.")
    ap.add_argument("--seeds", type=int, default=25, help="selftest: seeds per grid row")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--calibrate", action="store_true",
                    help="the selftest at a seed count that can actually resolve a 5%% rate "
                         "(default 500/row). This is what produces a certificate; --selftest is "
                         "a smoke test and usually returns INDISTINGUISHABLE, which is honest.")
    ap.add_argument("--seed-base", type=int, default=9000,
                    help="first noise seed. Change it to check a result is not tuned to 9000..")
    ap.add_argument("--measure-power", action="store_true",
                    help="re-derive the measured-power (MDE) table that the POWER line quotes")
    ap.add_argument("--check", default=None, metavar="RECEIPT.json",
                    help="replay: re-score BATTERY with the receipt's own keys and permutation "
                         "count and report whether verdict, worst cell and file hash agree")
    ap.add_argument("--emit-grid", default=None, metavar="PATH",
                    help="write the certificate to PATH with provenance stamped in. Refuses to "
                         "write into the served directory — the verifier does not certify itself.")
    a = ap.parse_args(argv[1:])

    if a.measure_power:
        print("nulltest POWER — smallest planted-artifact coverage this build catches, by n:")
        return measure_power(n_perm=a.n_perm, jobs=a.jobs)
    if a.selftest or a.calibrate:
        seeds = a.seeds if not a.calibrate else max(a.seeds, 500)
        if a.calibrate:
            print("nulltest CALIBRATION — %d seeds/row, enough to resolve a 5%% rate:" % seeds)
        else:
            print("nulltest selftest — the checker must be able to fire, and able not to:")
        # --selftest is a smoke test and is capped at 200 permutations for speed. --calibrate is
        # the certificate, so it runs at the permutation count the tool actually ships with (600
        # by default): v1.2 calibrated at 200 and users ran at 600, so the certificate described a
        # setting nobody used — and Westfall-Young's small-B leak made the 200-perm grid look
        # WORSE than the shipped configuration, not better.
        n_perm = a.n_perm if a.calibrate else min(a.n_perm, 200)
        return selftest(seeds=seeds, n_perm=n_perm, seed_base=a.seed_base, emit=a.emit_grid,
                        jobs=a.jobs)
    if not a.battery:
        if a.check:
            print("--check needs the battery file too: nulltest.py BATTERY --check RECEIPT.json", file=sys.stderr)
            return 2
        ap.print_help()
        return 2
    if a.check:
        return check_receipt(a.check, a.battery, jobs=a.jobs)

    explode = None
    try:
        raw_items = read_items(a.battery)
        if a.explode:
            explode = parse_explode(a.explode)
            raw_items = explode_items(raw_items, explode, split=a.split)
            if a.text_key or a.label_key:
                print("  note: under --explode the text is each named field and the label is its "
                      "mapped value; --text-key/--label-key are ignored", file=sys.stderr)
            a.text_key, a.label_key = "text", "label"
    except LabelError as e:
        sys.exit(str(e))
    tk, lk, sk = sniff_keys(raw_items, a.text_key, a.label_key, a.stratum_key)
    if tk is None or lk is None:
        have = sorted({k for it in raw_items[:50] if isinstance(it, dict) for k in it})
        hint = (" If this CSV has no header row, add one: the first line names the fields."
                if a.battery.lower().endswith((".csv", ".tsv")) else "")
        sys.exit("could not find a %s field. The items carry: %s. Name it with %s.%s"
                 % ("text" if tk is None else "label", ", ".join(have[:20]),
                    "--text-key" if tk is None else "--label-key", hint))
    info = {}
    items = load(a.battery, tk, lk, a.positive_label, explode=explode, split=a.split, info=info)
    if sk and not any(sk in it for it in items):
        print("  note: no item carries the stratum field %r; everything is one stratum" % sk, file=sys.stderr)
    tkeys = tk.split(",") if "," in tk else tk
    progress = None
    if not a.json and len(items) >= 2000:
        # a 60k-item run takes a quarter of an hour; say so while it runs (stderr, not the report)
        def progress(done, total):
            print("\r  permutation %d of %d" % (done, total), end="", file=sys.stderr, flush=True)
    rep = evaluate(items, tkeys, lk, sk, n_perm=a.n_perm, alpha=a.alpha, jobs=a.jobs, progress=progress)
    if progress:
        print("\r" + " " * 40 + "\r", end="", file=sys.stderr, flush=True)
    rep["battery"] = os.path.basename(a.battery)
    rep["data"] = info
    # The receipt. A verdict that cannot be tied to bytes is an anecdote: these two hashes let a
    # stranger confirm WHICH file and WHICH tool produced it, and `--check` replays the whole thing.
    with open(a.battery, "rb") as fh:
        rep["battery_sha256"] = hashlib.sha256(fh.read()).hexdigest()
    rep["tool_sha256"] = _tool_sha256()
    rep["keys"] = {"text": tk, "label": lk, "stratum": sk}
    rep["positive_label"] = a.positive_label
    if explode:
        rep["explode"] = {"fields": dict(explode), "split": a.split, "rows": len(raw_items and {i.get("_row") for i in raw_items})}
    if a.explain or rep["verdict"] == "DISQUALIFIED":
        rep["explain"] = explain(items, tkeys, lk, sk, rep)

    if a.json:
        print(json.dumps(rep, indent=1))
        return 0 if rep["verdict"] == "PASS" else 1

    print("\nnulltest — %s" % rep["battery"])
    # "real / fake" is a guess about what the labels MEAN, and it is wrong for any battery whose
    # two halves are both real (a date split, a prominence split). The tool only knows label 0
    # from label 1, so that is all it says.
    print("  %d items (%d label-0 / %d label-1), keys: text=%s label=%s stratum=%s"
          % (rep["n"], rep["n_real"], rep["n_fake"], tk, lk, sk))
    # What label-1 IS, in the file's own words. Every WHY line below says "label-1"; without this
    # line the reader has to guess which class that was.
    print("  label-1 = %r, label-0 = %r (the verdict is two-sided; the mapping only sets the sign)"
          % (info.get("label1_raw_value"), info.get("label0_raw_value")))
    dq = []
    if info.get("rows_dropped_missing_field"):
        dq.append("%d rows dropped (no %s or %s field)" % (info["rows_dropped_missing_field"], tk, lk))
    if info.get("empty_texts"):
        dq.append("%d empty texts kept" % info["empty_texts"])
    if info.get("non_string_texts"):
        dq.append("%d non-string texts coerced with str()" % info["non_string_texts"])
    if dq:
        print("  data:    %s" % "; ".join(dq))
    print("  %d cells, family-wise corrected (Westfall-Young min-p), %d permutations, each a refit"
          % (rep["family_size"], rep["n_perm"]))
    print()
    shown = 0
    for name, e in rep["nulls"].items():
        for st, c in sorted(e["per_stratum"].items(), key=lambda kv: kv[1]["adj_p"]):
            if not c["separates"] and c["adj_p"] > 0.25:
                continue
            print("  %-11s %-22s n=%-4d A* %.3f  raw p %.4f  adj p %.4f%s%s"
                  % (name, st, c["n"], c["astar"], c["raw_p"], c["adj_p"],
                     "  SEPARATES" if c["separates"] else "",
                     "  [underpowered]" if c["underpowered"] else ""))
            shown += 1
    if not shown:
        print("  no cell came close to significance after correction")
    print()
    print("  %s" % rep["headline"])
    print("  %d of %d cells separate after correction at alpha=%.2f"
          % (rep["n_separating_cells"], rep["family_size"], rep["alpha"]))
    if rep["underpowered_cells"]:
        print("  underpowered cells (n < %d), read with caution: %s"
              % (rep["min_cell"], ", ".join(rep["underpowered_cells"][:6])))
    print()
    print("  VERDICT: %s" % rep["verdict"])
    # A verdict without its power is half a result. Printed here, not buried in --json, because
    # the number people quote is the one they can see.
    pw = rep.get("power") or {}
    if pw.get("reading"):
        print("  POWER:   %s" % pw["reading"])
    if rep.get("saturated"):
        print("  NOTE:    adjusted p is at the permutation floor (<= %.5f); it is a bound, not a "
              "measurement" % rep["p_floor"])
    if rep.get("borderline"):
        print("  NOTE:    BORDERLINE — %s" % rep["borderline_note"])
    if rep.get("explain"):
        print()
        print("  WHY (in-sample description of the separating cells; the verdict above is held-out):")
        for c in rep["explain"]["cells"]:
            print("  %s/%s  A* %.3f  adj p %.4f" % (c["probe"], c["stratum"], c["astar"], c["adj_p"]))
            print("      %s" % c["reading"])
            for side in ("favours_label1", "favours_label0"):
                rows = c.get(side) or []
                if rows:
                    print("      %-15s %s" % (side.replace("favours_", "") + ":",
                          "  ".join("%s %d:%d" % (_show_feature(c["probe"], r["feature"]), r["in_label1"], r["in_label0"])
                                    for r in rows[:6])))
            ex = c.get("examples")
            if ex:
                for lab in ("label1", "label0"):
                    for t in ex[lab]:
                        print("      e.g. %s: %s" % (lab, t))
    print()
    print("  " + rep["scope"].replace(". ", ".\n  "))
    return 0 if rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
