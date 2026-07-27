#!/usr/bin/env bash
# nulltest_parity.sh — prove the browser null test and the CLI null test are one instrument.
#
#   bash nulltest_parity.sh
#
# The evidence page runs nulltest.js in the reader's browser and prints a verdict. The CLI
# runs nulltest.py. If those two ever disagree, a reader is being shown a number that no
# command can reproduce — which is the exact failure this product exists to catch. So the
# claim "same instrument" is TESTED here, cell by cell, and this script exits non-zero if
# it stops being true.
#
# Requires node (to run the browser engine outside a browser) and python3.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE" || exit 1
FAILED=0

command -v node >/dev/null || { echo "node not found — cannot run the browser engine headless"; exit 2; }

BATTERIES="batteries/grounding-coordinate.json batteries/photon-entities.json"

node nulltest_parity.js $BATTERIES > /tmp/nt_js.json || { echo "JS engine failed"; exit 1; }
for b in $BATTERIES; do
  python3 nulltest.py "$b" --json --n-perm 600 > "/tmp/nt_py_$(basename "$b")" 2>&1
done

python3 - "$BATTERIES" <<'PY'
import hashlib, json, sys, os, random
sys.path.insert(0, os.getcwd())
import nulltest as N
js = json.load(open('/tmp/nt_js.json'))
def canon(o):
    # 1.0 (python float) and 1 (js int) are the same number; compare VALUES, not encodings
    if isinstance(o, bool): return o
    if isinstance(o, (int, float)): return round(float(o), 3)
    if isinstance(o, dict): return {k: canon(v) for k, v in o.items()}
    if isinstance(o, list): return [canon(v) for v in o]
    return o

ok, total = True, 0
out = {"pairs": []}
for b in sys.argv[1].split():
    name = os.path.basename(b)
    py = json.load(open('/tmp/nt_py_%s' % name))
    j = js[name]
    a = canon({"verdict": py["verdict"], "headline": py["headline"],
               "worst_cell": py["worst_cell"], "nulls": py["nulls"]})
    c = canon({"verdict": j["verdict"], "headline": j["headline"],
               "worst_cell": j["worst_cell"], "nulls": j["nulls"]})
    cells = sum(1 + len(v["per_stratum"]) for v in py["nulls"].values())
    total += cells
    same = json.dumps(a, sort_keys=True) == json.dumps(c, sort_keys=True)
    ok &= same
    print("  %-34s %s  (%d cells: A*, threshold and separates each compared)"
          % (name, "IDENTICAL" if same else "DIVERGES", cells))
    print("     %s | %s" % (py["verdict"], py["headline"]))
    if not same:
        for nm in a["nulls"]:
            if a["nulls"][nm] != c["nulls"].get(nm):
                print("     DIFF in null %r:" % nm)
                print("       py", json.dumps(a["nulls"][nm], sort_keys=True)[:400])
                print("       js", json.dumps(c["nulls"].get(nm), sort_keys=True)[:400])
    out["pairs"].append({"battery": name, "identical": same, "cells": cells,
                         "verdict": py["verdict"], "headline": py["headline"]})

# ── the two planted controls the page offers as buttons ───────────────────────
# Generated in JS from a reimplementation of random.Random(7). They must come out as the
# SAME ITEMS and the SAME VERDICTS as nulltest.py --selftest, or the page's "must fire /
# must not fire" demonstration proves nothing about the CLI anyone can download.
rng = random.Random(7)
py_sep = ([{"entity": "NCT%08d" % rng.randrange(10**7), "label": 0, "category": "trials"} for _ in range(60)]
          + [{"entity": "".join(rng.choice("bcdfg") + rng.choice("aeiou") for _ in range(4)),
              "label": 1, "category": "trials"} for _ in range(60)])
py_clean = [{"entity": t, "label": i % 2, "category": "trials"}
            for i, t in enumerate(["NCT%08d" % rng.randrange(10**7) for _ in range(120)])]

for name, py_items, must in (("planted-separable", py_sep, "DISQUALIFIED"),
                             ("planted-clean", py_clean, "PASS")):
    j = js[name]
    same_items = py_items == j["items"]
    rep = N.evaluate(py_items, "entity", "label", "category", n_perm=600)
    same_verdict = (canon({"v": rep["verdict"], "h": rep["headline"], "w": rep["worst_cell"]})
                    == canon({"v": j["verdict"], "h": j["headline"], "w": j["worst_cell"]}))
    right = rep["verdict"] == must
    good = same_items and same_verdict and right
    ok &= good
    print("  %-34s %s  (items identical: %s; verdict identical: %s; must be %s: %s)"
          % (name, "IDENTICAL" if good else "DIVERGES", same_items, same_verdict, must, right))
    print("     %s | %s" % (rep["verdict"], rep["headline"]))
    out["pairs"].append({"battery": name, "identical": good, "cells": 0,
                         "verdict": rep["verdict"], "headline": rep["headline"],
                         "items_identical": same_items, "required_verdict": must, "met": right})

out["cells_compared"] = total
out["parity"] = "PASS" if ok else "FAIL"

# THIS SCRIPT USED TO WRITE nulltest_parity.json ON EVERY RUN — so the evidence that the browser
# and the CLI agree was produced by the same act that checked it, and whatever it last happened to
# print became the committed proof. That is how the committed certificate came to record
# "shape/trials" while the code says "lexicality/trials": it was emitted before the 2026-07-25
# tie-break fix, kept claiming to describe the tool, and nothing compared the two.
#
# Emission is now explicit, and it refuses the served directory, exactly as nulltest --emit-grid
# does. Run the check freely; producing a certificate is a separate, deliberate act.
_emit = os.environ.get("PARITY_EMIT")
if _emit:
    _dest = os.path.abspath(_emit)
    _here = os.path.dirname(os.path.abspath(__file__ if "__file__" in dir() else sys.argv[0]))
    if os.path.dirname(_dest) == _here:
        print("  REFUSED to emit into the served directory — the verifier does not certify itself.")
    else:
        out["tool_sha256"] = hashlib.sha256(open(os.path.join(_here, "nulltest.py"), "rb").read()).hexdigest()
        json.dump(out, open(_dest, "w"), indent=1)
        print("  emitted %s" % _dest)
print()
print("  %d cells compared across %d batteries" % (total, len(out["pairs"])))
print("  PARITY: %s" % out["parity"])
sys.exit(0 if ok else 1)
PY
FAILED=$?

echo
if [ "$FAILED" -eq 0 ]; then
  printf "\033[32m%s\033[0m\n" "PASS — the browser and the CLI compute the same verdict on the same bytes"
else
  printf "\033[31m%s\033[0m\n" "FAIL — the page and the CLI disagree. Do not ship until they don't."
fi
exit "$FAILED"
