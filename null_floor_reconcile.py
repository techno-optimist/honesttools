#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Kevin Russell (Aperture / Project Forty Two)
"""null_floor_reconcile.py — reconcile two of our own instruments that disagreed.

    python3 null_floor_reconcile.py            # needs numpy + scikit-learn, and nulltest.py beside it

THE DEFECT THIS CLOSES. On 2026-07-24 we shipped two instruments that reported different
worst-cell surface separability for the SAME battery file (sha256 3e1dcce2...), with no note:

    the certificate   0.837  in lexicality_charngram / drugs_compounds
    nulltest          0.878  in lexicality / eponymous_theorems

A page whose premise is "check it yourself" cannot invite that comparison and leave it
hanging. So: they are not in conflict. They are two ESTIMATORS of the same quantity —
"how much of the REAL/FABRICATED label is recoverable from surface form alone" — and they
disagree because they are different classifiers:

    A (certificate) : TF-IDF char_wb 3-5grams -> logistic regression, StratifiedKFold(5)
    B (nulltest)    : char 3-5gram set -> naive-Bayes log-odds, 5-fold, hapax dropped

WHICH ONE GOVERNS -- AND THE ANSWER CHANGED TWICE. This script first published max(A, B) =
0.878, reasoning that an adversary picks whichever estimator works best, which gave a margin
of 0.045 for our 0.923 figure. A review killed that too, and it was right:

    the two estimators disagree by 0.154 ON THE SAME CELL -- lexicality/eponymous_theorems,
    0.724 against 0.878 -- at n=28, where the noise-only 95th percentile is 0.709.

When two implementations of one measurement disagree by more than the margin being claimed,
taking the maximum is not conservatism. It is SELECTION ON NOISE. NO DEFENSIBLE MARGIN EXISTS
at this n, and the 0.923 figure is withdrawn until there is a battery that is not
surface-separable to measure it on. Certificate v3 records the withdrawal.

NOTE ON WHAT THIS IS NOT. These are point estimates of separability, not hypothesis tests.
`nulltest.py` answers the different question "does any cell separate beyond chance, after
correcting for the whole family of cells it searched" and returns a verdict. A point estimate
and a corrected test do not have to agree, and quoting one where the other belongs is how
the 0.086 got published in the first place.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BATTERY = os.path.join(HERE, "batteries", "grounding-coordinate.json")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def estimator_a(items):
    """The certificate's estimator. Transcribed from the published replay verifier."""
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold
    from sklearn.pipeline import make_pipeline

    SEED = 20260606
    ents = np.asarray([it["entity"] for it in items], dtype=object)
    y = np.array([int(it["label"]) for it in items])
    cats = np.asarray([it["category"] for it in items])

    s = np.zeros(len(y))
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=SEED).split(np.zeros(len(y)), y):
        s[te] = (make_pipeline(TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)),
                               LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced"))
                 .fit(list(ents[tr]), y[tr]).predict_proba(list(ents[te]))[:, 1])

    best, where = 0.0, None
    for c in sorted(set(cats)):
        m = cats == c
        if m.sum() >= 4 and len(set(y[m])) == 2:
            a = float(roc_auc_score(y[m], s[m]))
            a = max(a, 1.0 - a)                     # two-sided; an attacker inverts for free
            if a > best:
                best, where = a, c
    return round(best, 3), "lexicality_charngram/%s" % where


def estimator_b(items):
    """The tool's estimator, as a POINT ESTIMATE (no family-wise correction — see the note)."""
    nt = _load(os.path.join(HERE, "nulltest.py"), "nt")
    texts = [it["entity"] for it in items]
    y = [int(it["label"]) for it in items]
    strata = [it["category"] for it in items]
    obs = nt._score_all_cells(texts, y, strata, nt._cell_defs(strata))
    best, where = 0.0, None
    for (nm, st), v in obs.items():
        if v is not None and v > best:
            best, where = v, "%s/%s" % (nm, st)
    return round(best, 3), where


def main():
    raw = json.load(open(BATTERY, encoding="utf-8"))
    items = raw["battery"] if isinstance(raw, dict) else raw

    a, wa = estimator_a(items)
    b, wb = estimator_b(items)
    floor = max(a, b)
    claim = 0.923

    out = {
        "battery": "grounding-coordinate.json",
        "n": len(items),
        "estimators": [
            {"name": "certificate", "method": "TF-IDF char_wb 3-5gram + logistic regression, StratifiedKFold(5)",
             "worst_cell": a, "where": wa},
            {"name": "nulltest", "method": "char 3-5gram set + naive-Bayes log-odds, 5-fold, hapax dropped",
             "worst_cell": b, "where": wb},
        ],
        "rule": "RETIRED — max-over-estimators is selection on noise when the estimators disagree on the same cell by more than the margin claimed",
        "verdict": "no defensible margin at this n; the 0.923 figure is withdrawn (cert v3)",
        "reconciled_floor": floor,
        "published_claim_within_category": claim,
        "margin_over_reconciled_floor": round(claim - floor, 3),
        "margin_we_previously_published": round(claim - 0.837, 3),
        "note": ("point estimates of separability, not hypothesis tests; nulltest.py answers the "
                 "different question of whether any cell separates beyond chance after family-wise "
                 "correction, and returns a verdict rather than a floor"),
    }
    with open(os.path.join(HERE, "null_floor_reconciled.json"), "w") as fh:
        json.dump(out, fh, indent=1)

    print("null floor reconciliation — %s (%d items)" % (out["battery"], out["n"]))
    print()
    for e in out["estimators"]:
        print("  %-13s worst cell %.3f   %s" % (e["name"], e["worst_cell"], e["where"]))
    print()
    print("  same-cell disagreement                : 0.154  (lexicality/eponymous_theorems, n=28)")
    print("  noise-only 95th percentile at n=28    : 0.709")
    print()
    print("  VERDICT: no defensible margin at this n. max-over-estimators (%.3f) is RETIRED —" % floor)
    print("           selecting the larger of two estimators that disagree by more than the")
    print("           margin claimed is selection on noise. The 0.923 figure is WITHDRAWN.")
    print()
    print("  wrote null_floor_reconciled.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
