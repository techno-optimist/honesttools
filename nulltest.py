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
    python3 nulltest.py battery.json --text-key entity --label-key label --stratum-key category
    python3 nulltest.py battery.json --json          # machine-readable
    python3 nulltest.py --selftest                   # planted-failure control

WHAT IT MEASURES  (four surface nulls, each a classifier with no model access)
    lexicality   character 3-5grams of the item text        (does the string LOOK fake?)
    length       character and word count                   (are fakes shorter/longer?)
    shape        digit/punct/case/token-pattern signature    (are reals ID-shaped and fakes word-shaped?)
    stratum      the stratum label alone, one-hot            (does the category leak the answer?)

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
these four probes. A benchmark can still be circular (labels drawn from the same store the system
retrieves from), contaminated, or mislabeled, and pass cleanly. Circularity in particular is
invisible here — it is a provenance property, not a surface one.
"""
from __future__ import annotations

import argparse
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
# the four surface nulls — each maps item text to ONE score, using no model
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


def _nb_scores(texts, y, featfn, k=5, seed=20260724):
    """K-fold naive-Bayes log-odds over binary features.

    NOT leave-one-out. A LOO variant that subtracts an item's own counts from the class totals
    leaks its label: the subtraction itself leaves a systematic per-class offset, and this tool's
    own selftest caught that scoring a pure-noise battery at A* = 1.000. Counts are now built on
    the training folds ONLY, so a test item never contributes to the statistics that score it.
    """
    feats = [featfn(t) for t in texts]
    n = len(feats)
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    folds = [idx[i::k] for i in range(k)]
    scores = [0.0] * n

    for f_te in folds:
        te = set(f_te)
        tr = [i for i in idx if i not in te]
        if not tr or not f_te:
            continue
        pos, neg = {}, {}
        npos = nneg = 0
        for i in tr:
            d = pos if y[i] == 1 else neg
            if y[i] == 1:
                npos += 1
            else:
                nneg += 1
            for g in feats[i]:
                d[g] = d.get(g, 0) + 1
        if npos == 0 or nneg == 0:
            continue
        seen = {}
        for i in tr:
            for g in feats[i]:
                seen[g] = seen.get(g, 0) + 1
        vocab = {g for g, c in seen.items() if c >= 2}      # drop hapax: pure memorisation
        for i in f_te:
            sc = 0.0
            for g in feats[i]:
                if g not in vocab:
                    continue
                sc += (math.log((pos.get(g, 0) + 0.5) / (npos + 1.0))
                       - math.log((neg.get(g, 0) + 0.5) / (nneg + 1.0)))
            # QUANTIZE before ranking. The score is a sum of ~200 log terms, and CPython's
            # libm log and V8's Math.log may differ by 1 ulp — enough that two items which tie
            # exactly in one language differ by 1e-16 in the other, which changes a tie group
            # and moves the AUROC by half a rank. Caught in browser/CLI parity on
            # lexicality/firms (0.795 vs 0.800). 1e-9 is far above the noise and far below any
            # difference that could matter to a log-odds. floor(x*1e9+0.5) is exactly what
            # JavaScript's Math.round does, including for negatives.
            scores[i] = math.floor(sc * 1e9 + 0.5) / 1e9
    return scores


def null_lexicality(texts, y, strata):
    return _nb_scores(texts, y, lambda t: _ngrams(t))


def null_length(texts, y, strata):
    return [len(t) + 0.001 * len(t.split()) for t in texts]


_SHAPE = re.compile(r"[A-Z]{2,}|\d+|[^\w\s]")
def null_shape(texts, y, strata):
    """Token-shape signature: digit runs, ALLCAPS runs, punctuation. This is the null that catches
    'reals are ID-shaped (NGC 6315, NCT02921971) and fakes are pronounceable words'."""
    def sig(t):
        return sorted({"S:" + ("D" if x.isdigit() else "U" if x.isupper() else "P") + str(min(len(x), 4))
                       for x in _SHAPE.findall(t)} | {"len%d" % min(len(t) // 4, 12)})
    return _nb_scores(texts, y, sig)


def null_stratum(texts, y, strata):
    """Does the stratum label alone predict truth? If yes the benchmark is unbalanced by design."""
    if not strata:
        return None
    rate, cnt = {}, {}
    for st, yy in zip(strata, y):
        rate[st] = rate.get(st, 0) + yy
        cnt[st] = cnt.get(st, 0) + 1
    # K-fold, not leave-one-out: LOO on a rate leaks the held-out label (see _nb_scores).
    idx = list(range(len(y)))
    random.Random(20260724).shuffle(idx)
    folds = [idx[i::5] for i in range(5)]
    out = [0.5] * len(y)
    for f_te in folds:
        te = set(f_te)
        r, c = {}, {}
        for i in idx:
            if i in te:
                continue
            r[strata[i]] = r.get(strata[i], 0) + y[i]
            c[strata[i]] = c.get(strata[i], 0) + 1
        for i in f_te:
            st = strata[i]
            out[i] = (r.get(st, 0) / c[st]) if c.get(st) else 0.5
    return out


NULLS = {
    "lexicality": null_lexicality,
    "length": null_length,
    "shape": null_shape,
    "stratum": null_stratum,
}


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
    "by four model-free probes, two-sided, refit inside every permutation and family-wise "
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


def _score_all_cells(texts, y, strata, cells, folds=None):
    """Fit all four nulls on THESE labels and return A* for every (null, stratum) cell.

    Called once for the observation and once per permutation. The refit is the point: it is
    what makes the null aware of the scorer's own capacity to overfit.
    """
    out = {}
    if folds is None:
        folds = _fold_of(len(y))
    for name, fn in NULLS.items():
        s = fn(texts, y, strata)
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


def _pval(sorted_col, t):
    """P(A* >= t) under this cell's own null. +1 in numerator and denominator: a permutation
    p-value must never be 0, or an adjusted p of 0 would claim infinite evidence from B draws."""
    import bisect
    b = len(sorted_col)
    if b == 0 or t is None:
        return 1.0
    return (b - bisect.bisect_left(sorted_col, t) + 1.0) / (b + 1.0)


def evaluate(items, text_key, label_key, stratum_key, n_perm=600, seed=20260724,
             min_cell=12, alpha=0.05, progress=None):
    import bisect

    texts = [str(it[text_key]) for it in items]
    y = [int(it[label_key]) for it in items]
    strata = [str(it.get(stratum_key, "_all")) for it in items] if stratum_key else ["_all"] * len(items)

    cells = _cell_defs(strata)
    rng = random.Random(seed)
    obs = _score_all_cells(texts, y, strata, cells)
    keys = sorted([k for k, v in obs.items() if v is not None])

    report = {"n": len(items), "n_fake": sum(y), "n_real": len(y) - sum(y),
              "strata": sorted(set(strata)), "min_cell": min_cell, "n_perm": n_perm,
              "alpha": alpha, "family_size": len(keys), "correction": "westfall_young_min_p",
              "nulls": {}, "underpowered_cells": []}

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
    draws = {k: [] for k in keys}
    ys = list(y)
    for b in range(n_perm):
        rng.shuffle(ys)
        sc = _score_all_cells(texts, ys, strata, cells)
        for k in keys:
            v = sc.get(k)
            if v is not None:
                draws[k].append(v)
        if progress and (b % 25 == 0):
            progress(b, n_perm)

    cols = {k: sorted(v) for k, v in draws.items()}

    # ---- Westfall-Young min-p ---------------------------------------------------------
    raw = {k: _pval(cols[k], obs[k]) for k in keys}
    q = []
    for b in range(n_perm):
        best = 1.0
        for k in keys:
            col = draws[k]
            if b < len(col):
                p = _pval(cols[k], col[b])
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
    worst = {"astar": 0.0, "adj_p": 1.0, "_adj_p_exact": 2.0,
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
            if (adj[k] < worst["_adj_p_exact"]) or (adj[k] == worst["_adj_p_exact"]
                                                    and obs[k] > worst["astar"]):
                worst = {"astar": round(obs[k], 3), "adj_p": round(adj[k], 4),
                         "_adj_p_exact": adj[k],
                         "raw_p": round(raw[k], 4), "null": name, "stratum": st,
                         "n": len(idx), "threshold": cell["threshold"],
                         "underpowered": cell["underpowered"]}
        if entry["per_stratum"]:
            report["nulls"][name] = entry

    worst.pop("_adj_p_exact", None)      # comparison scratch, never part of the published report
    report["worst_cell"] = worst
    report["n_separating_cells"] = sum(1 for k in keys if adj[k] < alpha)
    report["verdict"] = "DISQUALIFIED" if worst["adj_p"] < alpha else "PASS"
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
# MEASURED POWER — what this tool can and cannot see at a given n.
#
# Measured 2026-07-25 on a clean synthetic base (surface-matched nonsense, random labels, no
# artifact by construction) by planting a +1-character marker on a fraction of the label-1 half
# and finding the smallest fraction that produced DISQUALIFIED in >=3 of 4 seeds. Grid was coarse
# — 15%, 30%, 60%, 100% — so a threshold of 60% means "caught at 60%, missed at 30%".
#
#     n = 156   60%      n = 702    60%
#     n = 324   60%      n = 1496   30%
#
# Corroborated on real data: geometry-of-truth/cities is DISQUALIFIED at A* 0.765 with n=1496 and
# PASSES 5 of 5 random subsamples at n=354. A* is NOT a stable effect size — the lexicality null is
# a fitted classifier, so with less data it learns an artifact less well and measured separability
# falls. Two corpora of different n are therefore NOT comparable to one another.
_MDE = ((1496, 0.30), (702, 0.60), (324, 0.60), (156, 0.60))


def _power_note(n, verdict):
    mde = next((f for lo, f in _MDE if n >= lo), None)
    out = {"n": n, "measured_mde": mde,
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
def load(path, text_key, label_key):
    raw = open(path, "r", encoding="utf-8").read().strip()
    items = ([json.loads(l) for l in raw.splitlines() if l.strip()]
             if path.endswith(".jsonl") else json.loads(raw))
    if isinstance(items, dict):
        for k in ("items", "battery", "data", "rows"):
            if isinstance(items.get(k), list):
                items = items[k]
                break
    if not isinstance(items, list):
        sys.exit("could not find a list of items in %s" % path)
    out = []
    for it in items:
        if text_key not in it or label_key not in it:
            continue
        v = it[label_key]
        if isinstance(v, str):
            v = 1 if v.lower() in ("fake", "fabrication", "fabricated", "false", "1", "coined") else 0
        out.append({**it, label_key: int(v)})
    if not out:
        sys.exit("no items had both --text-key %r and --label-key %r" % (text_key, label_key))
    return out


def _noise_battery(seed, strata, mode, n=120):
    """A battery with NO signal in it: identical surface forms, labels assigned by noise.

    `mode` is the whole point of the grid. "alt" alternates labels by position; "coin" flips a
    coin. v1.0's selftest ran ONLY ("alt", 1 stratum) — the single construction it passed — and
    printed "selftest: PASS". The construction IS the finding, so we publish a grid, not a number.
    """
    r = random.Random(seed)
    out = []
    for i in range(n):
        y = (i % 2) if mode == "alt" else r.randrange(2)
        out.append({"entity": "NCT%08d" % r.randrange(10 ** 7), "label": y,
                    "category": "s%d" % (i % strata)})
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
        ("coin-flip, 6 strata", "coin", 6))

VERSION = "1.2"
FALSE_FIRE_CEILING = 0.10


def selftest(seeds=25, n_perm=200, seed_base=9000, emit=None):
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
        bad = 0
        for s in range(seeds):
            rep = evaluate(_noise_battery(seed_base + s, k, mode), "entity", "label", "category",
                           n_perm=n_perm)
            if rep["verdict"] == "DISQUALIFIED":
                bad += 1
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
        print("    %-48s %2d/%-3d  %5.1f%%  [%4.1f%%, %5.1f%%]  %s"
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
    import hashlib
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


def main(argv):
    ap = argparse.ArgumentParser(description="does this honesty benchmark measure honesty, or string shape?")
    ap.add_argument("battery", nargs="?")
    ap.add_argument("--text-key", default=None)
    ap.add_argument("--label-key", default=None)
    ap.add_argument("--stratum-key", default=None)
    ap.add_argument("--n-perm", type=int, default=600)
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
    ap.add_argument("--emit-grid", default=None, metavar="PATH",
                    help="write the certificate to PATH with provenance stamped in. Refuses to "
                         "write into the served directory — the verifier does not certify itself.")
    a = ap.parse_args(argv[1:])

    if a.selftest or a.calibrate:
        seeds = a.seeds if not a.calibrate else max(a.seeds, 500)
        if a.calibrate:
            print("nulltest CALIBRATION — %d seeds/row, enough to resolve a 5%% rate:" % seeds)
        else:
            print("nulltest selftest — the checker must be able to fire, and able not to:")
        return selftest(seeds=seeds, n_perm=min(a.n_perm, 200),
                        seed_base=a.seed_base, emit=a.emit_grid)
    if not a.battery:
        ap.print_help()
        return 2

    probe = open(a.battery, encoding="utf-8").read(4000)
    tk = a.text_key or next((k for k in ("entity", "text", "claim", "question", "name", "prompt")
                             if '"%s"' % k in probe), "entity")
    lk = a.label_key or next((k for k in ("label", "y", "is_fake", "type") if '"%s"' % k in probe), "label")
    sk = a.stratum_key or next((k for k in ("category", "domain", "stratum", "cell") if '"%s"' % k in probe), None)

    items = load(a.battery, tk, lk)
    rep = evaluate(items, tk, lk, sk, n_perm=a.n_perm, alpha=a.alpha)
    rep["battery"] = os.path.basename(a.battery)
    rep["keys"] = {"text": tk, "label": lk, "stratum": sk}

    if a.json:
        print(json.dumps(rep, indent=1))
        return 0 if rep["verdict"] == "PASS" else 1

    print("\nnulltest — %s" % rep["battery"])
    # "real / fake" is a guess about what the labels MEAN, and it is wrong for any battery whose
    # two halves are both real (a date split, a prominence split). The tool only knows label 0
    # from label 1, so that is all it says.
    print("  %d items (%d label-0 / %d label-1), keys: text=%s label=%s stratum=%s"
          % (rep["n"], rep["n_real"], rep["n_fake"], tk, lk, sk))
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
    print()
    print("  " + rep["scope"].replace(". ", ".\n  "))
    return 0 if rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
