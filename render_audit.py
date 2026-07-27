#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Kevin Russell (Aperture / Project Forty Two)
"""render_audit.py — build the /audit table FROM the results file, instead of by hand.

WHY THIS EXISTS. audit.html carried the line "regenerated from nulltest_audit_results.json" above
a table of eight hand-typed <tr> rows, and nothing regenerated anything. The claim was a
description of an intention. So when the manifest grew from 7 targets to 11, the page kept showing
7 — four of OUR OWN batteries missing, including our worst artifact — under a headline that said
"including every one of our own". The page was not lying about a number; it was lying about a
mechanism, which is harder to notice and lasts longer.

The rule this enforces: a page may not claim to be generated unless a program generates it.

WHAT IS MECHANICAL AND WHAT IS EDITORIAL. Every number in the table comes from
nulltest_audit_results.json and cannot be typed. Every prose note — the two 2026-07-26 tie-break
corrections, the power caveat on sp_en_trans — lives in audit_notes.json keyed by benchmark, and
is merged in. That split is the point: regenerating can never silently drop a correction, and
editing prose can never silently change a number.

MARGINALITY. A verdict a hair from its threshold is not the same as one that is nowhere near it,
and a flat table implies they are. Rows within 3x of alpha are flagged, in BOTH directions: a
DISQUALIFIED at adjusted p 0.03 and a PASS at 0.0982 are each a coin-toss away from the other
verdict, and the reader is told so.

    python3 render_audit.py            # rewrite audit.html's <tbody>
    python3 render_audit.py --check    # exit 1 if the page is stale (for a pre-serve gate)
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "nulltest_audit_results.json")
NOTES = os.path.join(HERE, "audit_notes.json")
PAGE = os.path.abspath(os.path.join(HERE, "..", "audit.html"))
ALPHA = 0.05
MARGIN_FACTOR = 3.0

SAT = ('<span class="ad-sat" title="at the permutation floor — a bound, not a measurement">'
       '≤</span>')


def marginal(verdict, adj_p):
    """Within 3x of alpha, in whichever direction the verdict went."""
    if adj_p is None:
        return False
    if verdict == "DISQUALIFIED":
        return adj_p > ALPHA / MARGIN_FACTOR
    if verdict == "PASS":
        return adj_p < ALPHA * MARGIN_FACTOR
    return False


def order_key(row):
    """Ours first, worst first — which is what the headline promises."""
    ours = row["name"].startswith("aperture/")
    dq = (row.get("verdict") == "DISQUALIFIED")
    w = row.get("worst_cell") or {}
    return (0 if ours else 1, 0 if dq else 1, w.get("adj_p") if w.get("adj_p") is not None else 9)


def render_rows(rows, notes):
    out = []
    for r in sorted(rows, key=order_key):
        name = r["name"]
        w = r.get("worst_cell") or {}
        adj = w.get("adj_p")
        verdict = r.get("verdict") or r.get("status", "—")
        ours = name.startswith("aperture/")
        sat = SAT if r.get("saturated") or (adj is not None and adj <= 0.0017) else ""
        vcls = ("ad-dq" if verdict == "DISQUALIFIED" else
                "ad-pass" if verdict == "PASS" else "ad-na")

        note = "n=%s; detected at this size, but not comparable to rows of different n" % r.get("n")
        if verdict == "PASS":
            note = ("n=%s; a PASS is the absence of a detected surface artifact at this size, "
                    "not proof there is none" % r.get("n"))
        if marginal(verdict, adj):
            note += ('<br><span class="ad-marg"><b>MARGINAL</b> — adjusted p %.4g sits within 3&times; '
                     'of alpha (%.2f). This verdict is close to its threshold and should not be read '
                     'as firmly as rows far from it.</span>' % (adj, ALPHA))
        extra = notes.get(name)
        if extra:
            note += '<br><span class="ad-corr">%s</span>' % extra

        out.append(
            '<tr class="%s"><td><b>%s</b>%s</td><td class="num">%s</td><td class="num">%s</td>'
            '<td class="num">%s%s</td><td class="%s">%s</td><td class="ad-note">%s</td></tr>'
            % ("ad-ours" if ours else "",
               html.escape(name),
               ' <span class="ad-tag">ours</span>' if ours else "",
               r.get("n", "—"),
               w.get("astar", "—"),
               ("%.4g" % adj) if adj is not None else "—", (" " + sat) if sat else "",
               vcls, html.escape(verdict), note))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if audit.html does not match the results file")
    a = ap.parse_args(argv[1:])

    rows = json.load(open(RESULTS))["rows"]
    notes = json.load(open(NOTES)) if os.path.exists(NOTES) else {}

    # A note for a benchmark that is no longer in the table is a correction that has silently
    # stopped being displayed. Say so rather than dropping it.
    names = {r["name"] for r in rows}
    orphan = [k for k in notes if not k.startswith("_") and k not in names]

    body = "<tbody>" + "\n      ".join(render_rows(rows, notes)) + "</tbody>"
    page = open(PAGE, encoding="utf-8").read()
    new = re.sub(r"<tbody>.*?</tbody>", lambda _: body, page, count=1, flags=re.S)
    # the eyebrow must name the run it actually came from
    new = re.sub(r"the null-floor audit &middot; nulltest [^&]*&middot; regenerated from [^<]*",
                 "the null-floor audit &middot; nulltest 1.2 &middot; %d rows generated from "
                 "nulltest_audit_results.json by render_audit.py" % len(rows), new, count=1)

    # THE HEADLINE IS A CHECKABLE CLAIM, so check it. The page says the table includes "every one
    # of our own". That was false for weeks because a battery could be written, served and cited
    # without anyone adding it to the manifest — and nothing anywhere compared the two lists.
    # Being unpublished must not be a way to stay unaudited.
    bat = os.path.join(HERE, "batteries")
    on_disk = {os.path.splitext(f)[0] for f in os.listdir(bat)
               if f.endswith(".json")} if os.path.isdir(bat) else set()
    in_table = {r["name"].split("/", 1)[1] for r in rows if r["name"].startswith("aperture/")}
    unaudited = sorted(on_disk - in_table)

    if a.check:
        stale = (new != page)
        print("audit.html is %s (%d rows in results)"
              % ("STALE — run render_audit.py" if stale else "current", len(rows)))
        for k in orphan:
            print("  orphan note, no longer displayed: %s" % k)
        for b in unaudited:
            print("  OUR BATTERY NOT IN THE TABLE: %s — the page claims to include every one of "
                  "ours, so this makes the page false" % b)
        return 1 if (stale or unaudited) else 0

    open(PAGE, "w", encoding="utf-8").write(new)
    print("wrote %s — %d rows (%d ours, %d third-party)"
          % (PAGE, len(rows),
             sum(1 for r in rows if r["name"].startswith("aperture/")),
             sum(1 for r in rows if not r["name"].startswith("aperture/"))))
    flagged = [r["name"] for r in rows
               if marginal(r.get("verdict"), (r.get("worst_cell") or {}).get("adj_p"))]
    if flagged:
        print("  flagged MARGINAL: %s" % ", ".join(flagged))
    for k in orphan:
        print("  ORPHAN NOTE (a correction that would silently vanish): %s" % k)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
