#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Kevin Russell (Aperture / Project Forty Two)
"""nulltest_audit.py — point the null test at published honesty benchmarks, reproducibly.

    python3 nulltest_audit.py                 # run every target in the manifest
    python3 nulltest_audit.py --only NAME     # one target
    python3 nulltest_audit.py --list          # what is in the manifest and why

WHAT THIS IS. A benchmark that labels items REAL/FABRICATED (or TRUE/FALSE) reports how well a
model tells them apart. If a classifier that never sees a model can recover those labels from the
SURFACE FORM of the item text, part of that score was spelling. This runs our null test over other
people's released corpora and publishes which ones survive their own surface floor.

WHAT A "DISQUALIFIED" VERDICT IS NOT. It is not a finding of error, misconduct, or bad faith by
the authors, and it is not a claim that the paper's conclusion is wrong. It says one specific
thing: on this corpus, a model-free classifier recovers the labels above what label-shuffling
produces, so a model-based score on it needs a surface control to be interpretable. Several of
these papers predate the practice. ALL NINE OF OUR OWN BATTERIES ARE IN THIS TABLE AND FOUR ARE
DISQUALIFIED, INCLUDING THE TWO WORST ROWS ON IT.

(That sentence used to read "our own two batteries, and both are disqualified". It was true when
written and quietly stopped being true as the manifest grew — while four of ours, including the
worst artifact we have produced, were missing from the served table entirely. render_audit.py
--check now compares batteries/ against the table and fails if any of ours is absent, so the
claim is enforced rather than remembered.)

WHY EVERY ROW CARRIES A HASH. The point is that a stranger can re-derive the verdict without
trusting us: the URL we fetched, the sha256 of the exact bytes we scored, the field mapping, and
the one command that reproduces the number. A row we cannot source is not published — it is
reported as unretrievable, which is itself a finding about the field.

A NOTE ON WHAT THE SURFACE HIT MEANS, which differs by corpus type:
  real_vs_fabricated_entity — the item is an entity string. A surface hit means the invented
      entities are spelled differently from the real ones. This is the case the instrument was
      built for.
  true_vs_false_statement  — the item is a whole sentence. A surface hit may reflect TEMPLATING
      (how the false statements were generated) rather than anything about the entities. That is
      still a real confound for a probe trained on those sentences, but it is a different claim
      and the table says which kind each row is.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "audit_cache")
MANIFEST = os.path.join(HERE, "nulltest_audit_manifest.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def _nt():
    spec = importlib.util.spec_from_file_location("nt", os.path.join(HERE, "nulltest.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fetch(url, dest, timeout=90):
    """Fetch once and cache. Returns (bytes, sha256) or raises.

    Tries three transports in order, because a stranger's Python may have no CA bundle and this
    tool is worthless if it only runs on our laptop: (1) urllib with the default context,
    (2) urllib with certifi's bundle if installed, (3) curl, which uses the system trust store.

    WE NEVER DISABLE CERTIFICATE VERIFICATION. An audit tool whose whole subject is whether you
    can trust a number does not get to fetch that number over an unverified channel, and a
    silent ssl._create_unverified_context() here would be the single most embarrassing line in
    this repository.
    """
    if os.path.exists(dest):
        b = open(dest, "rb").read()
        return b, hashlib.sha256(b).hexdigest()

    errs = []
    b = None
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
    except Exception as e:
        errs.append("urllib: %s" % str(e)[:70])
        try:
            import ssl
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                b = r.read()
        except Exception as e2:
            errs.append("certifi: %s" % str(e2)[:70])
            import subprocess
            try:
                p = subprocess.run(["curl", "-sSL", "--fail", "-m", str(timeout), "-A", UA, url],
                                   capture_output=True, timeout=timeout + 15)
                if p.returncode == 0 and p.stdout:
                    b = p.stdout
                else:
                    errs.append("curl: rc=%d %s" % (p.returncode, p.stderr.decode()[:60]))
            except Exception as e3:
                errs.append("curl: %s" % str(e3)[:60])
    if b is None:
        raise RuntimeError("; ".join(errs))

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(b)
    return b, hashlib.sha256(b).hexdigest()


def parse_items(raw_bytes, spec):
    """Turn the fetched bytes into a list of dicts, per the manifest's `format`."""
    fmt = spec.get("format", "json")
    text = raw_bytes.decode("utf-8", "replace")
    if fmt == "jsonl":
        return [json.loads(l) for l in text.splitlines() if l.strip()]
    if fmt == "csv":
        import csv
        return list(csv.DictReader(io.StringIO(text)))
    obj = json.loads(text)
    if isinstance(obj, list):
        return obj
    for k in (spec.get("root"), "items", "data", "rows", "battery", "examples"):
        if k and isinstance(obj.get(k), list):
            return obj[k]
    raise ValueError("could not find a list of items in the JSON")


def normalise(items, spec):
    """Map a corpus onto nulltest's keys. Explicit and auditable — no sniffing."""
    tk, lk, sk = spec["text_field"], spec["label_field"], spec.get("stratum_field")
    pos = set(str(v).lower() for v in spec.get("label_positive", [1, "1", True, "true"]))
    invert = bool(spec.get("invert_label"))
    out = []
    for it in items:
        if tk not in it or lk not in it:
            continue
        v = str(it[lk]).lower()
        y = 1 if v in pos else 0
        if invert:
            y = 1 - y
        row = {"entity": str(it[tk]), "label": y}
        if sk and it.get(sk) is not None:
            row["category"] = str(it[sk])
        out.append(row)
    return out


def strength(astar):
    """A verdict is binary; the effect is not. Without this, a corpus at A* 0.565 and one at
    A* 1.000 both print DISQUALIFIED and a reader takes them as equivalent. They are not: one
    is a slight surface tilt that a large n makes detectable, the other is a corpus a regular
    expression could score. Our own tool was overstating until this was added."""
    if astar >= 0.90:
        return "severe"
    if astar >= 0.75:
        return "substantial"
    if astar >= 0.60:
        return "moderate"
    return "slight"


def run_one(spec, n_perm=600, verbose=True):
    name = spec["name"]
    row = {"name": name, "paper": spec.get("paper", ""), "label_kind": spec.get("label_kind", "unknown"),
           "url": spec.get("url", ""), "status": None}
    if not spec.get("url"):
        row["status"] = "not_released"
        row["note"] = spec.get("note", "no item-level corpus located")
        return row
    dest = os.path.join(CACHE, spec.get("cache_as", name.replace("/", "_")))
    try:
        raw, sha = fetch(spec["url"], dest)
    except Exception as e:
        row["status"] = "unretrievable"
        row["note"] = "fetch failed on this date: %s" % str(e)[:110]
        return row
    row["sha256"] = sha
    row["bytes"] = len(raw)
    try:
        items = normalise(parse_items(raw, spec), spec)
    except Exception as e:
        row["status"] = "unparseable"
        row["note"] = str(e)[:140]
        return row

    ys = set(i["label"] for i in items)
    if len(items) < 30 or len(ys) < 2:
        row["status"] = "unscorable"
        row["note"] = "%d items, %d distinct labels — too small or single-class" % (len(items), len(ys))
        return row

    nt = _nt()
    has_stratum = any("category" in i for i in items)
    rep = nt.evaluate(items, "entity", "label", "category" if has_stratum else None, n_perm=n_perm)
    row.update({
        "status": "scored", "n": rep["n"], "n_fake": rep["n_fake"], "n_real": rep["n_real"],
        "cells": rep["family_size"], "verdict": rep["verdict"],
        "worst_cell": rep["worst_cell"], "headline": rep["headline"],
        "separating_cells": rep.get("n_separating_cells", 0),
        "astar": rep["worst_cell"]["astar"],
        "strength": strength(rep["worst_cell"]["astar"]) if rep["verdict"] == "DISQUALIFIED" else "—",
    })
    if verbose:
        w = rep["worst_cell"]
        print("  %-32s %-13s %-12s A* %-6s adj p %-7s %s/%s"
              % (name[:32], rep["verdict"], row["strength"], w["astar"], w["adj_p"],
                 w["null"], w["stratum"]), flush=True)
    return row


def main(argv):
    ap = argparse.ArgumentParser(description="run the null test over published honesty benchmarks")
    ap.add_argument("--only")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--n-perm", type=int, default=600)
    a = ap.parse_args(argv[1:])

    if not os.path.exists(MANIFEST):
        print("no manifest at %s" % MANIFEST)
        return 2
    man = json.load(open(MANIFEST))
    all_targets = man["targets"]          # the full manifest, for merging and for the missing-row check
    targets = all_targets
    if a.only:
        targets = [t for t in targets if t["name"] == a.only]
        if not targets:
            print("no target named %r" % a.only)
            return 2

    if a.list:
        for t in targets:
            print("  %-34s %-26s %s" % (t["name"][:34], t.get("label_kind", "?"),
                                        t.get("url") or "(no released corpus)"))
        return 0

    print("nulltest audit — %d targets, %d permutations each" % (len(targets), a.n_perm))
    print()
    rows = [run_one(t, n_perm=a.n_perm) for t in targets]
    dest = os.path.join(HERE, "nulltest_audit_results.json")

    # --only USED TO REPLACE THE WHOLE FILE. Re-scoring one target rewrote the results with a
    # single row, so one flag silently emptied the public accountability table while /audit went
    # on claiming to show every benchmark we have scored. Merge by name instead, keep the
    # manifest's order, and say plainly which rows are left over from an earlier run.
    prior = {}
    if a.only and os.path.exists(dest):
        try:
            for r in (json.load(open(dest)).get("rows") or []):
                prior[r["name"]] = r
        except Exception:
            prior = {}
    fresh = {r["name"]: r for r in rows}
    merged, carried = [], 0
    for t in all_targets:
        r = fresh.get(t["name"]) or prior.get(t["name"])
        if r is None:
            continue
        if t["name"] not in fresh:
            carried += 1
        merged.append(r)

    out = {"tool": "nulltest", "version": "1.1", "n_perm": a.n_perm,
           "generated_from": os.path.basename(MANIFEST), "rows": merged}
    if carried:
        out["partial_run"] = ("%d of %d rows were carried over from an earlier run, not scored "
                              "now (--only %s)" % (carried, len(merged), a.only))
    with open(dest, "w") as fh:
        json.dump(out, fh, indent=1)
    if carried:
        print("  carried %d unscored row(s) from the previous results file" % carried)
    missing = [t["name"] for t in all_targets if t["name"] not in fresh and t["name"] not in prior]
    if missing:
        print("  NOT IN THE TABLE (never scored): %s" % ", ".join(missing))

    scored = [r for r in rows if r["status"] == "scored"]
    dq = [r for r in scored if r["verdict"] == "DISQUALIFIED"]
    print()
    print("  scored %d of %d; %d DISQUALIFIED, %d PASS; %d not released / unretrievable"
          % (len(scored), len(rows), len(dq), len(scored) - len(dq),
             len([r for r in rows if r["status"] in ("not_released", "unretrievable")])))
    print("  wrote nulltest_audit_results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
