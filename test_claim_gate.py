#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Kevin Russell (Aperture / Project Forty Two)
"""claim_gate break-tests — plant a defect, run the real gate script, require it to fire.

WHY THIS EXISTS. claim_gate matched elements with a non-overlapping regex and then kept only the
"innermost" ones. When a <div> was matched first, a <b> inside it was never emitted as its own
element, so the div was dropped for having a figure-bearing child AND the child was never checked.
On the live /evidence page "17 of 18", "0.967" and "0.742" sat inside such <b> tags, and the gate
reported "0 failures" without having looked at them. Rule 2 had the same hole: a retracted claim
inside a <b> could render without its withdrawal and nothing fired.

Every test here runs the gate as a subprocess against a throwaway tree, the same way it runs on the
site, and asserts on what it prints. Each defect test has a matching annotated case, so a gate that
fires on everything fails too.

    python3 -m unittest test_claim_gate        # or: pytest test_claim_gate.py
    CLAIM_GATE_SCRIPT=/path/to/claim_gate.py   # to test a copy elsewhere
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def _gate_script():
    env = os.environ.get("CLAIM_GATE_SCRIPT")
    if env:
        return env
    for cand in (os.path.join(HERE, "claim_gate.py"),                               # honesttools
                 os.path.join(HERE, "..", "web", "static", "verifier", "claim_gate.py")):  # observatory
        if os.path.exists(cand):
            return os.path.abspath(cand)
    raise SystemExit("test_claim_gate: cannot find claim_gate.py — set CLAIM_GATE_SCRIPT")


REGISTRY = {"entries": [
    {"id": "live-claim", "status": "grounded-empirical"},
    {"id": "dead-claim", "status": "falsified-negative"},
]}

HEAD = "<!doctype html>\n<html>\n<head>\n<title>t</title>\n</head>\n<body>\n"
TAIL = "\n</body>\n</html>\n"

# One page per case. The gate refuses to run on fewer than five pages, so the set is also the
# denominator: every page below must be read, or a test fails.
PAGES = {
    # the defect as it sat on /evidence: a figure in <b> inside a <div>, unannotated
    "nested_unannotated": '<div class="bl-txt">The battery separated on <b>17 of 18 cells</b>.</div>',
    # the same shape, annotated on the element that carries the figure
    "nested_annotated": '<div class="bl-txt">The battery separated on <b data-claim="unregistered">16 of 18 cells</b>.</div>',
    # rule 2 through the same hole: a dead claim rendered without its withdrawal
    "nested_retracted": '<div class="bl-txt">Headline: <b data-claim="dead-claim">0 of 36 fabricated</b>.</div>',
    # ...and with its withdrawal shown, which must pass
    "nested_retracted_disclosed": '<div class="bl-txt">Headline: <b data-claim="dead-claim"><s>0 of 36</s> withdrawn</b>.</div>',
    # a wrapper's id must not cover a number that lives in its child (the double-count the
    # original INNERMOST rule was written to prevent)
    "wrapper": '<div class="card" data-claim="live-claim">Summary <b>AUROC 0.951</b></div>',
    # a parent's own figure must still be checked when a child also carries one
    "parent_own_figure": '<p>Rate 4.64% and <b data-claim="unregistered">116 of 2,500</b> runs.</p>',
    "parent_own_figure_annotated": '<p data-claim="live-claim">Rate 4.64% and <b data-claim="unregistered">116 of 2,500</b> runs.</p>',
    # positive control on the flat shape the old gate already handled
    "flat": '<p>A flat figure 0.967 here.</p>\n<p data-claim="live-claim">An annotated 0.912.</p>',
    # markup inside a comment is not published and must not be read as a claim
    "commented": '<!-- <p>an old draft said 0.999</p> -->\n<p>No figures here.</p>',
}

FAIL_LINE = re.compile(r"^FAIL\s+(\S+)\s+(\S+?):(\d+)\s+(.*)$")


class ClaimGateBreakTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="claim_gate_test_")
        static = os.path.join(cls.tmp, "static")
        os.makedirs(os.path.join(static, "verifier"))
        shutil.copy(_gate_script(), os.path.join(static, "verifier", "claim_gate.py"))
        cls.lines = {}
        for name, body in PAGES.items():
            src = HEAD + body + TAIL
            with open(os.path.join(static, name + ".html"), "w", encoding="utf-8") as fh:
                fh.write(src)
            cls.lines[name] = src
        reg = os.path.join(cls.tmp, "registry.json")
        with open(reg, "w") as fh:
            json.dump(REGISTRY, fh)
        env = dict(os.environ, CLAIM_GATE_REGISTRY=reg)
        out = subprocess.run([sys.executable, os.path.join(static, "verifier", "claim_gate.py"),
                              "--strict"], capture_output=True, text=True, env=env, timeout=120)
        cls.stdout = out.stdout + out.stderr
        cls.code = out.returncode
        cls.fails = [FAIL_LINE.match(l).groups() for l in out.stdout.splitlines() if FAIL_LINE.match(l)]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _fails(self, page, kind=None):
        return [f for f in self.fails if f[1] == page + ".html" and (kind is None or f[0] == kind)]

    def _line_of(self, page, needle):
        src = self.lines[page]
        return src[:src.index(needle)].count("\n") + 1

    # -- the gate ran at all ------------------------------------------------------------------

    def test_gate_ran_and_failed_overall(self):
        self.assertNotIn("refusing to run", self.stdout, self.stdout)
        self.assertEqual(self.code, 1, "planted defects must make --strict exit 1\n" + self.stdout)

    # -- the defect: a figure nested in <b> inside a <div> --------------------------------------

    def test_nested_unannotated_figure_is_reported(self):
        hits = self._fails("nested_unannotated", "UNANNOTATED")
        self.assertEqual(len(hits), 1, self.stdout)
        self.assertIn("17 of 18", hits[0][3])

    def test_nested_annotated_figure_passes(self):
        self.assertEqual(self._fails("nested_annotated"), [], self.stdout)

    def test_nested_retracted_claim_must_render_its_withdrawal(self):
        hits = self._fails("nested_retracted", "RETRACTED-NOT-DISCLOSED")
        self.assertEqual(len(hits), 1, self.stdout)
        self.assertEqual(self._fails("nested_retracted_disclosed"), [], self.stdout)

    # -- no wrapper double-count, no parent blind spot ------------------------------------------

    def test_wrapper_id_does_not_cover_child_figure(self):
        hits = self._fails("wrapper", "UNANNOTATED")
        self.assertEqual(len(hits), 1, self.stdout)
        self.assertIn("0.951", hits[0][3])

    def test_parent_own_figure_is_checked(self):
        hits = self._fails("parent_own_figure", "UNANNOTATED")
        self.assertEqual(len(hits), 1, self.stdout)
        self.assertIn("4.64%", hits[0][3])
        self.assertNotIn("116 of 2,500", hits[0][3], "the child's annotated figure is not the parent's")
        self.assertEqual(self._fails("parent_own_figure_annotated"), [], self.stdout)

    # -- controls ---------------------------------------------------------------------------------

    def test_flat_control_fires_and_annotated_flat_passes(self):
        hits = self._fails("flat", "UNANNOTATED")
        self.assertEqual(len(hits), 1, self.stdout)
        self.assertIn("0.967", hits[0][3])

    def test_commented_out_markup_is_not_a_claim(self):
        self.assertEqual(self._fails("commented"), [], self.stdout)

    def test_reported_line_is_the_source_line(self):
        hits = self._fails("nested_unannotated", "UNANNOTATED")
        self.assertEqual(len(hits), 1, self.stdout)
        self.assertEqual(int(hits[0][2]), self._line_of("nested_unannotated", "<b>17 of 18"), self.stdout)


if __name__ == "__main__":
    unittest.main()
