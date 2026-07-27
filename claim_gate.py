#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Kevin Russell (Aperture / Project Forty Two)
"""claim_gate — no numeral ships on a public page without something behind it.

WHY THIS EXISTS. On 2026-07-25 we retracted a headline and corrected it on two pages. It stayed
live on a third for two days. A census then found 58 surviving problems across eight pages, and the
cause was one thing, not fifty:

    we retract CLAIMS, but the site publishes NUMBERS, and nothing binds the two.

The same measurement travelled as "cross-provider transfer", "language-invariant off-distribution
detection", and "familiarity" — so grepping the retracted claim found nothing, and only grepping
the DIGITS found all four copies. "1.000" appeared four times on one page meaning three different
things. A fix landed on two copies of a field and missed a third, which kept rendering
"undefined real / undefined fabricated" on a live console.

Retraction was treated as an edit to prose. The unit that actually propagates is the numeral.

WHAT THIS CHECKS

  1. UNANNOTATED FIGURES.  Any element whose text carries a benchmark-shaped numeral must declare
     data-claim="<registry-id>". This rule fails CLOSED — a new unannotated number is a failure, so
     coverage cannot silently rot. It is the load-bearing rule; the rest only work on what it forces
     to be labelled.

  2. RETRACTED SOURCES.  If data-claim names a registry entry whose status is falsified-negative,
     retracted or withdrawn, the element must itself render the withdrawal — a <s> strike or the
     word "withdrawn" — so a dead number cannot appear as a live one.

  3. DISQUALIFIED BATTERIES.  If data-battery names a battery that nulltest DISQUALIFIES, the
     element must say DISQUALIFIED. A score measured on a battery that fails the floor is not
     wrong, it is uninterpretable, and the page has to say so.

  4. SELF-REPORTING ARTIFACTS.  A battery JSON's surface_floor block must match what nulltest
     computes on that same file. calibration-battery-v1.json hand-carried cells_separating: 17
     while the tool printed 16 — and our own retraction quoted the artifact. An artifact must never
     be able to assert its own verdict.

Rule 4 alone would have caught the 17-vs-16. Rule 1 would have caught all four pages.

    python3 claim_gate.py                 # check the served tree
    python3 claim_gate.py --retract <id>  # every file:line citing a registry id, plus every
                                          # distinct numeral inside those elements, then every
                                          # unannotated occurrence of those numerals tree-wide
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.dirname(HERE)
def _find_registry():
    """Walk up for results_registry/results.json, and allow CLAIM_GATE_REGISTRY to override.

    A fixed number of dirname() calls assumed one repo layout. The deploy tree has no
    results_registry at all, so the gate refused to run there — correct behaviour from the guard,
    but useless as a pre-deploy check, which is exactly where it needs to run.
    """
    env = os.environ.get("CLAIM_GATE_REGISTRY")
    if env:
        return env
    d = STATIC
    for _ in range(8):
        cand = os.path.join(d, "results_registry", "results.json")
        if os.path.exists(cand):
            return cand
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    # the deploy tree is a sibling checkout of the same repo; fall back to the canonical one
    home = os.path.expanduser("~/Desktop/cultural-soliton-observatory/results_registry/results.json")
    return home if os.path.exists(home) else cand


REGISTRY = _find_registry()
BATTERIES = os.path.join(HERE, "batteries")

# A benchmark-shaped numeral. Deliberately narrow: version strings, years, byte counts and prices
# are not claims about measurement, and sweeping them in would train people to ignore this gate.
FIGURE = re.compile(
    r"\b0\.\d{2,4}\b"                 # 0.955, 0.9997
    r"|\bAUROC\s*[\d.]+"              # AUROC 0.83
    r"|\b\d{1,3}\.\d%|\b\d{1,3}%"     # 96.7%, 18%
    r"|\b\d+\s*(?:of|/)\s*\d+\b"      # 0 of 36, 16 of 18
    r"|\bA\*\s*[\d.]+")               # A* 0.967

# a bare running counter, not a published measurement
PLACEHOLDER = re.compile(r"^\W*\d[\d,]*\s*/\s*\d[\d,]*\W*$|^\W*0\s*/\s*0\W*$")

DEAD = {"falsified-negative", "retracted", "withdrawn"}

# Three annotations, because pretending every published numeral maps to a registry entry would be
# its own dishonesty. Most do not — the registry holds results, the site holds prose about them.
#   <registry-id>      the figure traces to a registered result
#   "unregistered"     a real measurement with NO registry entry. This is DEBT, counted and printed
#                      on every run so it has to trend down. It is not a pass.
#   "not-a-measurement" file sizes, item counts, latencies, prices — nothing a floor applies to.
SPECIAL = {"unregistered", "not-a-measurement"}
DISCLOSED = re.compile(r"<s>|withdrawn|WITHDRAWN|retracted|RETRACTED|DISQUALIFIED", re.I)

PUBLIC = [f for f in os.listdir(STATIC) if f.endswith(".html")] if os.path.isdir(STATIC) else []


def _registry():
    """Load the registry, or FAIL LOUDLY.

    This returned {} on any error, which made rule 2 pass everything silently whenever the registry
    could not be found — a check reporting success without having checked, inside the gate written
    to stop exactly that. Caught by deliberately planting a retracted claim and watching nothing
    fire. An empty registry is now an error, not a quiet pass.
    """
    if not os.path.exists(REGISTRY):
        raise SystemExit("claim_gate: registry not found at %s — refusing to run, because with no "
                         "registry every retracted-claim check would pass vacuously." % REGISTRY)
    with open(REGISTRY) as fh:
        entries = json.load(fh).get("entries") or []
    if not entries:
        raise SystemExit("claim_gate: registry has no entries — refusing to run.")
    return {e["id"]: e for e in entries}


def _floor(name):
    """Ask nulltest, never the artifact."""
    p = os.path.join(BATTERIES, name if name.endswith(".json") else name + ".json")
    if not os.path.exists(p):
        return None
    try:
        out = subprocess.run([sys.executable, os.path.join(HERE, "nulltest.py"), p, "--json"],
                             capture_output=True, text=True, timeout=900)
        return json.loads(out.stdout)
    except Exception:
        return None


def _elements(html):
    """(line, inner_html, attrs, inner_text) for leaf-ish elements carrying visible text."""
    out = []
    for m in re.finditer(r"<(span|div|li|p|td|b|h[1-6])\b([^>]*)>(.*?)</\1>", html, re.S):
        inner = re.sub(r"<[^>]+>", " ", m.group(3))
        # group(3) is the inner HTML — markup WITHOUT the opening tag's attributes. Disclosure must
        # be judged on that, never on the whole element: the registry id
        # "verifydomain-147-headline-retracted" contains the word "retracted", so searching the
        # whole element matched the gate's OWN annotation and passed every retracted claim silently.
        out.append((html[:m.start()].count("\n") + 1, m.group(3), m.group(2), inner))
    # INNERMOST ONLY. The regex matches every ancestor too, so a wrapper div was being reported for
    # figures that live in its children — and annotating the wrapper would attach one claim id to
    # several unrelated numbers. Keep an element only if no nested element also carries a figure.
    keep = []
    for line, inner_html, attrs, inner in out:
        nested = re.finditer(r"<(span|div|li|p|td|b|h[1-6])\b[^>]*>(.*?)</\1>", inner_html, re.S)
        if any(FIGURE.search(re.sub(r"<[^>]+>", " ", n.group(2))) for n in nested):
            continue
        keep.append((line, inner_html, attrs, inner))
    return keep


def check(strict_unannotated=False):
    # A DENOMINATOR, mirroring the registry guard. With PUBLIC empty — a wrong cwd, a moved tree, a
    # glob that matched nothing — this walked zero pages and reported "0 failures", which reads
    # identical to a clean run. The registry arm already refused to run vacuously; the pages arm
    # did not. Same hole, one function apart, in the gate written to stop exactly this.
    if len(PUBLIC) < 5:
        raise SystemExit("claim_gate: found only %d public pages under %s — refusing to run, because "
                         "a near-empty page set reports '0 failures' and looks like a clean pass."
                         % (len(PUBLIC), STATIC))
    reg = _registry()
    fails, warns, debt, skipped = [], [], [], []
    for fn in sorted(PUBLIC):
        path = os.path.join(STATIC, fn)
        html = open(path, encoding="utf-8", errors="replace").read()
        # A page can declare itself superseded. It is still served (we do not delete history), but
        # its figures are not live coverage debt. The declaration is machine-readable so a page
        # cannot quietly opt out of the gate in prose.
        if 'name="claim-gate" content="superseded"' in html:
            skipped.append(fn)
            continue
        body = html[html.find("<body"):] or html
        # Strip style/script before matching. rgba(0,0,0,0.24) is not a claim about measurement,
        # and a gate that flags CSS teaches people to skim its output. Replaced with newlines so
        # line numbers still point at the real source.
        body = re.sub(r"<(style|script)\b.*?</\1>",
                      lambda m: "\n" * m.group(0).count("\n"), body, flags=re.S)
        for line, whole, attrs, inner in _elements(body):
            if not FIGURE.search(inner):
                continue
            # "0 / 0", "0 / 1,000" and friends are live counters rendered by JS, not measurements.
            if PLACEHOLDER.search(inner.strip()):
                continue
            cid = re.search(r'data-claim="([^"]+)"', attrs)
            bat = re.search(r'data-battery="([^"]+)"', attrs)
            if not cid:
                (fails if strict_unannotated else warns).append(
                    ("UNANNOTATED", fn, line, inner.strip()[:90]))
                continue
            key = cid.group(1)
            if key in SPECIAL:
                debt.append((key, fn, line, inner.strip()[:70]))
                continue
            entry = reg.get(key)
            if entry is None:
                fails.append(("CLAIM-ID-NOT-IN-REGISTRY", fn, line, key))
                continue
            if entry and entry.get("status") in DEAD and not DISCLOSED.search(whole):
                fails.append(("RETRACTED-NOT-DISCLOSED", fn, line, cid.group(1)))
            if bat:
                rep = _floor(bat.group(1))
                if rep and rep["verdict"] == "DISQUALIFIED" and "DISQUALIFIED" not in whole:
                    fails.append(("DISQUALIFIED-NOT-LABELLED", fn, line, bat.group(1)))

    # rule 4 — artifacts must not assert their own verdict
    for bn in sorted(os.listdir(BATTERIES)) if os.path.isdir(BATTERIES) else []:
        if not bn.endswith(".json"):
            continue
        try:
            d = json.load(open(os.path.join(BATTERIES, bn)))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue          # a bare-array battery carries no self-reported verdict to contradict
        sf = d.get("surface_floor") or {}
        claimed = sf.get("cells_separating")
        if claimed is None:
            continue
        rep = _floor(bn)
        if rep and rep.get("n_separating_cells") != claimed:
            fails.append(("ARTIFACT-SELF-REPORT", bn, 0,
                          "says %s, nulltest says %s" % (claimed, rep["n_separating_cells"])))
    return fails, warns, debt, skipped


def retract(cid):
    """Everything that must change when a claim dies."""
    reg = _registry()
    print("retracting: %s" % cid)
    if cid in reg:
        print("  registry status: %s" % reg[cid].get("status"))
    hits, numerals = [], set()
    for fn in sorted(PUBLIC):
        html = open(os.path.join(STATIC, fn), encoding="utf-8", errors="replace").read()
        for line, whole, attrs, inner in _elements(html):
            if ('data-claim="%s"' % cid) in attrs:
                hits.append((fn, line, inner.strip()[:80]))
                numerals.update(FIGURE.findall(inner))
    print("\n  elements citing it (%d):" % len(hits))
    for fn, ln, txt in hits:
        print("    %s:%d  %s" % (fn, ln, txt))
    print("\n  numerals inside them (%d): %s" % (len(numerals), ", ".join(sorted(numerals)) or "none"))
    print("\n  UNANNOTATED occurrences of those numerals elsewhere — these are what gets missed:")
    found = 0
    for num in sorted(numerals):
        for fn in sorted(PUBLIC):
            for i, ln in enumerate(open(os.path.join(STATIC, fn), encoding="utf-8",
                                        errors="replace").read().split("\n"), 1):
                if num in ln and 'data-claim="%s"' % cid not in ln:
                    print("    %s:%d  %s" % (fn, i, num)); found += 1
    if not found:
        print("    none")
    return 0


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--retract", metavar="REGISTRY_ID")
    ap.add_argument("--strict", action="store_true",
                    help="treat unannotated figures as failures (the end state; warnings until annotated)")
    a = ap.parse_args(argv[1:])
    if a.retract:
        return retract(a.retract)

    fails, warns, debt, skipped = check(strict_unannotated=a.strict)
    for kind, fn, line, detail in fails:
        print("FAIL  %-26s %s:%s  %s" % (kind, fn, line, detail))
    if warns:
        print("\n%d unannotated figures (warnings until the annotation pass lands; --strict fails on them)"
              % len(warns))
        for kind, fn, line, detail in warns[:12]:
            print("  warn  %s:%s  %s" % (fn, line, detail))
        if len(warns) > 12:
            print("  ... and %d more" % (len(warns) - 12))
    if debt:
        print("\n%d figures annotated but UNREGISTERED or not-a-measurement — standing debt, must trend down:"
              % len(debt))
        seen = {}
        for kind, fn, line, txt in debt:
            seen.setdefault((fn, kind), 0)
            seen[(fn, kind)] += 1
        for (fn, kind), n in sorted(seen.items()):
            print("  %-22s %-18s %d" % (fn, kind, n))
    if skipped:
        print("\nskipped as superseded (still served, not live claims): %s" % ", ".join(skipped))
    print("\n%d failures, %d unannotated, %d annotated-debt" % (len(fails), len(warns), len(debt)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
