#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Kevin Russell (Aperture / Project Forty Two)
"""honest — the toolbox entry point. One command, many tools, one contract.

    honest list                     what is in the box, and at which tier
    honest null <battery.json>      run the model-free surface floor
    honest selftest [tool]          run a tool's break-test (all tools if omitted)
    honest fpr <tool>               print a tool's calibrated false-positive rate

Phase 0 of the charter: the contract is proven on the STRONGEST tool first (`null`), reversibly,
before the weaker three are wrapped. `observertest` is registered `experimental` on purpose — to
demonstrate that the stable/experimental wall actually refuses to let it emit a stable verdict, not
to run it here. See CHARTER.md.
"""
from __future__ import annotations

import importlib.util
import os
import sys

import contract
from contract import (EXPERIMENTAL, PASS, STABLE, Tool, Verdict)

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(mod, path):
    spec = importlib.util.spec_from_file_location(mod, os.path.join(HERE, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── null: wrap the shipped surface floor in the contract ──────────────────────────────────
class NullTool(Tool):
    name = "null"
    summary = "model-free surface floor — does a benchmark measure honesty, or string shape?"

    def _nt(self):
        return _load("nulltest", "nulltest.py")

    def run(self, battery_path, n_perm=600) -> Verdict:
        nt = self._nt()
        probe = open(battery_path, encoding="utf-8").read(4000)
        tk = next((k for k in ("entity", "text", "claim", "question", "name", "prompt")
                   if '"%s"' % k in probe), "entity")
        lk = next((k for k in ("label", "y", "is_fake", "type") if '"%s"' % k in probe), "label")
        sk = next((k for k in ("category", "domain", "stratum", "cell") if '"%s"' % k in probe), None)
        items = nt.load(battery_path, tk, lk)
        rep = nt.evaluate(items, tk, lk, sk, n_perm=n_perm)
        w = rep.get("worst_cell") or {}
        return Verdict(
            tool=self.name, tier=STABLE, verdict=rep["verdict"], headline=rep["headline"],
            evidence={"worst_cell": w, "n": rep.get("n"), "family_size": rep.get("family_size"),
                      "battery": os.path.basename(battery_path)},
            fpr=self.false_positive_rate(), replayable=True)

    def selftest(self) -> bool:
        """null's break-test: a battery separable by string shape ALONE must come back DISQUALIFIED,
        and pure noise must NOT. This is the discipline that caught every defect in the taxonomy."""
        nt = self._nt()
        import random
        r = random.Random(7)
        dirty = ([{"entity": "NCT%08d" % r.randrange(10 ** 7), "label": 0, "category": "t"}
                  for _ in range(60)]
                 + [{"entity": "".join(r.choice("bcdfg") + r.choice("aeiou") for _ in range(4)),
                     "label": 1, "category": "t"} for _ in range(60)])
        must_fire = nt.evaluate(dirty, "entity", "label", "category", n_perm=200)["verdict"]
        clean = nt.evaluate(nt._noise_battery(9001, 1, "coin"), "entity", "label", "category",
                            n_perm=200)["verdict"]
        ok = (must_fire == "DISQUALIFIED" and clean != "DISQUALIFIED")
        print("  null.selftest: planted-separable -> %s (want DISQUALIFIED), "
              "pure-noise -> %s (want not-DISQUALIFIED): %s"
              % (must_fire, clean, "PASS" if ok else "FAIL"))
        return ok

    def false_positive_rate(self) -> dict | None:
        """The calibrated grid, if a certificate that matches THIS code is present. A certificate
        that describes different code is not this tool's FPR, so it is not reported as one."""
        import hashlib
        import json
        p = os.path.join(HERE, "nulltest_grid.json")
        if not os.path.exists(p):
            return None
        try:
            d = json.load(open(p))
        except Exception:
            return None
        stamped = (d.get("provenance") or {}).get("tool_sha256") or d.get("tool_sha256")
        actual = hashlib.sha256(open(os.path.join(HERE, "nulltest.py"), "rb").read()).hexdigest()
        if stamped != actual:
            return None      # the certificate is not about this code; refuse to quote it
        return {"worst_rate": d.get("worst_observed_rate") or d.get("worst_rate"),
                "ceiling": d.get("ceiling"), "seeds": d.get("seeds"), "state": d.get("state"),
                "source": "nulltest_grid.json (provenance matches this tool)"}

    def replay(self, receipt) -> Verdict:
        """null needs no signed receipt: the battery IS the receipt. Re-running run() on the same
        bytes reproduces the verdict, offline, with stdlib — which is what replay means here."""
        return self.run(receipt)


# ── observertest: registered experimental ON PURPOSE, to exercise the wall ─────────────────
class ObservertestStub(Tool):
    name = "observertest"
    summary = "concealment/sandbagging detection (EXPERIMENTAL — fails its own kill condition today)"

    def run(self, *a, **k) -> Verdict:
        # It would return a real finding when run against a served endpoint. Here it demonstrates
        # that the wall forces even a PASS-looking result to a non-stable verdict.
        return Verdict(self.name, EXPERIMENTAL, PASS,
                       "would report register-exchangeability + domain-selectivity from output bytes",
                       evidence={"note": "fails its pre-registered kill condition (Stage B 4/5); "
                                         "see Aperture/research/tools_deep/obs/FALSE_POSITIVE_RATE.md"})

    def selftest(self) -> bool:
        print("  observertest.selftest: fails its kill condition (Stage B fired 4/5 vs <=1/5) — "
              "correctly cannot enter stable")
        return False

    def false_positive_rate(self) -> dict | None:
        return {"measured": "4 of 5 fresh-dressing runs false-fired Stage B (kill condition <=1/5)",
                "verdict": "FAILS — not shippable as written", "paths": ["many dressings", "empirical null"]}

    def replay(self, receipt) -> Verdict:
        return self.run()


contract.register(NullTool(), STABLE)
contract.register(ObservertestStub(), EXPERIMENTAL)


# ── CLI ───────────────────────────────────────────────────────────────────────────────────
def _cmd_list():
    print("honesttools — the honesty toolbox\n")
    for name, tier, summary in contract.registered():
        tag = "  " if tier == STABLE else "* "
        print("  %s%-14s [%s]  %s" % (tag, name, tier, summary))
    print("\n  * experimental: real finding, but the wall forbids it a stable-green verdict.")
    return 0


def _cmd_selftest(which):
    names = [which] if which else [n for n, _, _ in contract.registered()]
    all_ok = True
    for n in names:
        tier = contract.tier_of(n)
        _, tool = contract._REGISTRY[n]
        ok = tool.selftest()
        # An experimental tool is ALLOWED to fail its selftest — that is why it is experimental.
        # A stable tool that fails its selftest is a release-blocking failure.
        if tier == STABLE and not ok:
            all_ok = False
        elif tier == EXPERIMENTAL and not ok:
            print("      (experimental: a failing selftest is expected and keeps it out of stable)")
    return 0 if all_ok else 1


def _cmd_fpr(name):
    _, tool = contract._REGISTRY[name]
    fpr = tool.false_positive_rate()
    if fpr is None:
        # On-ethos: refuse to quote a rate we cannot verify against the running code. When the
        # calibrated grid is not installed beside the tool (a pip wheel does not bundle it yet),
        # point to the published measurement and to how a stranger reproduces it, rather than
        # printing a number that might not describe this build.
        print("  %s: no calibrated grid is installed beside this build, so there is no rate this" % name)
        print("  tool can verify against the code you are running — and it will not quote one it")
        print("  cannot verify. The calibrated false-positive rate for the published version is at")
        print("  https://www.honesty.tools/audit ; reproduce it yourself with:")
        print("      python3 -m nulltest --calibrate --emit-grid ./grid.json   (~a few minutes)")
        return 1
    import json
    print(json.dumps(fpr, indent=1))
    return 0


def main(argv=None):
    # argv=None is the console-script entry point (`honest ...`); the list form is used by tests
    # and by `python3 honest.py ...`.
    if argv is None:
        argv = sys.argv
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = argv[1]
    if cmd == "list":
        return _cmd_list()
    if cmd == "selftest":
        return _cmd_selftest(argv[2] if len(argv) > 2 else None)
    if cmd == "fpr":
        if len(argv) < 3:
            print("usage: honest fpr <tool>")
            return 2
        return _cmd_fpr(argv[2])
    if cmd in contract._REGISTRY:
        if len(argv) < 3:
            print("usage: honest %s <battery.json>" % cmd)
            return 2
        v = contract.run(cmd, argv[2])
        print(v.to_json())
        # exit 0 only on a verdict a downstream pipeline may actually rely on
        return 0 if v.is_stable_green() or v.verdict == "DISQUALIFIED" else 1
    print("unknown command %r — try: honest list" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
