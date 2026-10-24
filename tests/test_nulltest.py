#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for nulltest.py — stdlib unittest, no fixtures outside this file.

    python3 -m unittest discover -s tests -v

Each test states the defect it would catch. A test that cannot fail on a plausible regression is
decoration, so every one of these was watched failing against a deliberately broken version first.
"""
import json
import os
import random
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import nulltest as N  # noqa: E402

PERM = 120   # enough to resolve alpha=0.05 (floor 1/121) and keep the suite under a minute


def _rng(seed):
    return random.Random(seed)


def _ids(r, n):
    return ["NCT%08d" % r.randrange(10 ** 7) for _ in range(n)]


def _cvcv(r, n, syll=4):
    return ["".join(r.choice("bcdfg") + r.choice("aeiou") for _ in range(syll)) for _ in range(n)]


def battery(texts0, texts1, cat="c"):
    return ([{"entity": t, "label": 0, "category": cat} for t in texts0]
            + [{"entity": t, "label": 1, "category": cat} for t in texts1])


class Statistics(unittest.TestCase):
    def test_auroc_perfect_and_inverted(self):
        y = [0, 0, 1, 1]
        self.assertEqual(N.auroc(y, [1, 2, 3, 4]), 1.0)
        self.assertEqual(N.auroc(y, [4, 3, 2, 1]), 0.0)
        # RULE 1: an inverted classifier is as bad as a correct one
        self.assertEqual(N.astar(y, [4, 3, 2, 1]), 1.0)

    def test_auroc_ties_are_half_ranked(self):
        self.assertAlmostEqual(N.auroc([0, 1], [1, 1]), 0.5)

    def test_auroc_single_class_is_none(self):
        self.assertIsNone(N.auroc([1, 1, 1], [1, 2, 3]))

    def test_clopper_pearson_brackets_the_rate(self):
        lo, hi = N.clopper_pearson(5, 100)
        self.assertLess(lo, 0.05)
        self.assertGreater(hi, 0.05)
        self.assertAlmostEqual(lo, 0.0164, places=3)
        self.assertAlmostEqual(hi, 0.1128, places=3)

    def test_pval_never_zero(self):
        self.assertGreater(N._pval([0.5] * 100, 1.0), 0.0)


class Probes(unittest.TestCase):
    """Each probe must recover the artifact it was written for, on held-out folds."""

    def test_lexicality_catches_spelling(self):
        r = _rng(1)
        b = battery(_ids(r, 60), _cvcv(r, 60))
        y = [i["label"] for i in b]
        s = N.null_lexicality([i["entity"] for i in b], y, None)
        self.assertGreater(N.astar(y, s), 0.95)

    def test_words_catches_a_template(self):
        r = _rng(2)
        t0 = ["The city of %s is in %s." % (w, v) for w, v in zip(_cvcv(r, 60), _cvcv(r, 60))]
        t1 = ["%s is not located in %s." % (w, v) for w, v in zip(_cvcv(r, 60), _cvcv(r, 60))]
        y = [0] * 60 + [1] * 60
        s = N.null_words(t0 + t1, y, None)
        self.assertGreater(N.astar(y, s), 0.95)

    def test_alpha_last_catches_surname_initial_sampling(self):
        """The prominence-people-v1 defect: one class drawn from the top of a surname-sorted list."""
        r = _rng(3)
        first = _cvcv(r, 200, 3)
        sur0 = [r.choice("abcdefghijklmnopqrstuvwxyz") + w for w in _cvcv(r, 100, 3)]
        sur1 = [r.choice("abc") + w for w in _cvcv(r, 100, 3)]            # alphabetically-first
        t0 = ["%s %s" % (f.title(), s.title()) for f, s in zip(first[:100], sur0)]
        t1 = ["%s %s" % (f.title(), s.title()) for f, s in zip(first[100:], sur1)]
        y = [0] * 100 + [1] * 100
        self.assertGreater(N.astar(y, N.null_alpha_last(t0 + t1, y, None)), 0.80)
        self.assertLess(N.astar(y, N.null_alpha_first(t0 + t1, y, None)), 0.65)

    def test_alpha_probe_is_ascii_only_and_safe_on_empty(self):
        self.assertEqual(N._alpha_first(""), 0)
        self.assertEqual(N._alpha_first("Émile Zola"), 0)
        self.assertEqual(N._alpha_last("Émile Zola"), 26)
        self.assertEqual(N._alpha_first("  bravo  "), 2)

    def test_shape_catches_ids_versus_words(self):
        r = _rng(4)
        b = battery(_ids(r, 60), _cvcv(r, 60))
        y = [i["label"] for i in b]
        self.assertGreater(N.astar(y, N.null_shape([i["entity"] for i in b], y, None)), 0.95)

    def test_nb_is_held_out(self):
        """LOO leaked labels and scored pure noise at A* = 1.000. K-fold must stay near chance."""
        r = _rng(5)
        texts = _ids(r, 200)
        y = [r.randrange(2) for _ in texts]
        self.assertLess(N.astar(y, N.null_lexicality(texts, y, None)), 0.65)

    def test_prepared_nb_matches_one_shot(self):
        r = _rng(6)
        texts = _cvcv(r, 80)
        nb = N._NB(texts, N._ngrams)
        for _ in range(3):
            y = [r.randrange(2) for _ in texts]
            self.assertEqual(nb.score(y), N._nb_scores(texts, y, N._ngrams))


class Verdicts(unittest.TestCase):
    def test_planted_separable_is_disqualified(self):
        r = _rng(7)
        rep = N.evaluate(battery(_ids(r, 60), _cvcv(r, 60)), "entity", "label", "category", n_perm=PERM)
        self.assertEqual(rep["verdict"], "DISQUALIFIED")
        self.assertTrue(rep["saturated"])

    def test_noise_passes(self):
        rep = N.evaluate(N._noise_battery(9001, 1, "coin"), "entity", "label", "category", n_perm=PERM)
        self.assertEqual(rep["verdict"], "PASS")

    def test_parallel_equals_serial(self):
        """--jobs changes the wall clock only. The permutations are drawn before scoring."""
        b = N._noise_battery(9002, 2, "coin")
        a = N.evaluate(b, "entity", "label", "category", n_perm=PERM, jobs=1)
        c = N.evaluate(b, "entity", "label", "category", n_perm=PERM, jobs=3)
        self.assertEqual(a["nulls"], c["nulls"])
        self.assertEqual(a["headline"], c["headline"])

    def test_not_scorable_is_not_pass(self):
        """A corpus with no scorable cell used to come back PASS."""
        items = [{"entity": "same", "label": i % 2, "category": "c"} for i in range(40)]
        rep = N.evaluate(items, "entity", "label", "category", n_perm=PERM)
        self.assertEqual(rep["verdict"], "NOT_SCORABLE")

    def test_single_class_cell_is_skipped_not_crashed(self):
        r = _rng(8)
        items = battery(_ids(r, 30), _cvcv(r, 30)) + [{"entity": t, "label": 0, "category": "only0"}
                                                      for t in _ids(r, 20)]
        rep = N.evaluate(items, "entity", "label", "category", n_perm=PERM)
        self.assertNotIn("only0", rep["nulls"]["lexicality"]["per_stratum"])

    def test_worst_cell_tiebreak_prefers_largest_effect(self):
        r = _rng(9)
        rep = N.evaluate(battery(_ids(r, 60), _cvcv(r, 60)), "entity", "label", "category", n_perm=PERM)
        tied = [c["astar"] for e in rep["nulls"].values() for c in e["per_stratum"].values()
                if c["adj_p"] == rep["worst_cell"]["adj_p"]]
        self.assertEqual(rep["worst_cell"]["astar"], max(tied))

    def test_multi_field_text(self):
        r = _rng(10)
        items = [{"q": "What is %s?" % w, "a": a, "label": 0} for w, a in zip(_cvcv(r, 40), _ids(r, 40))]
        items += [{"q": "What is %s?" % w, "a": a, "label": 1} for w, a in zip(_cvcv(r, 40), _cvcv(r, 40))]
        rep = N.evaluate(items, ["q", "a"], "label", None, n_perm=PERM)
        self.assertEqual(rep["verdict"], "DISQUALIFIED")
        self.assertEqual(N.item_text(items[0], ["q", "a"]), items[0]["q"] + "\n" + items[0]["a"])

    def test_report_carries_version_and_probes(self):
        rep = N.evaluate(N._noise_battery(9003, 1, "alt"), "entity", "label", "category", n_perm=PERM)
        self.assertEqual(rep["version"], N.VERSION)
        self.assertEqual(rep["probes"], list(N.NULLS))


class Loading(unittest.TestCase):
    def _write(self, name, text):
        d = tempfile.mkdtemp()
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    def test_csv_and_tsv(self):
        p = self._write("b.csv", "statement,label\nThe sky is blue.,1\nThe sky is green.,0\n")
        items = N.read_items(p)
        self.assertEqual(items[0]["statement"], "The sky is blue.")
        tk, lk, sk = N.sniff_keys(items)
        self.assertEqual((tk, lk, sk), ("statement", "label", None))
        p = self._write("b.tsv", "entity\tlabel\tdomain\nA\t0\tx\nB\t1\tx\n")
        self.assertEqual(N.sniff_keys(N.read_items(p)), ("entity", "label", "domain"))

    def test_jsonl_and_wrapped_json(self):
        p = self._write("b.jsonl", '{"text":"a","y":0}\n{"text":"b","y":1}\n')
        self.assertEqual(len(N.read_items(p)), 2)
        p = self._write("b.json", json.dumps({"battery": [{"entity": "a", "label": 0}]}))
        self.assertEqual(N.read_items(p)[0]["entity"], "a")

    def test_labels_known_words_are_coerced(self):
        items = [{"t": "a", "k": "fabricated"}, {"t": "b", "k": "real"}]
        out, pos = N.coerce_labels(items, "k")
        self.assertEqual(pos, "fabricated")
        self.assertEqual([i["k"] for i in out], [1, 0])
        out, _ = N.coerce_labels([{"k": True}, {"k": False}], "k")
        self.assertEqual([i["k"] for i in out], [1, 0])

    def test_unknown_label_words_refuse_to_guess(self):
        """v1.2 mapped 'yes'/'no', 'A'/'B', anything, to 0 silently."""
        with self.assertRaises(N.LabelError):
            N.coerce_labels([{"k": "alpha"}, {"k": "beta"}], "k")
        out, pos = N.coerce_labels([{"k": "alpha"}, {"k": "beta"}], "k", positive="beta")
        self.assertEqual([i["k"] for i in out], [0, 1])

    def test_three_label_values_refuse(self):
        with self.assertRaises(N.LabelError):
            N.coerce_labels([{"k": 0}, {"k": 1}, {"k": 2}], "k")

    def test_positive_label_must_exist(self):
        with self.assertRaises(N.LabelError):
            N.coerce_labels([{"k": 0}, {"k": 1}], "k", positive="7")

    def test_load_splits_comma_text_keys(self):
        p = self._write("qa.json", json.dumps([{"q": "x", "a": "y", "label": 0}, {"q": "u", "a": "v", "label": 1}]))
        items = N.load(p, "q,a", "label")
        self.assertEqual(len(items), 2)


class Novelty(unittest.TestCase):
    def test_copy_of_a_real_has_zero_novelty(self):
        items = [{"entity": "alpha beta", "label": 0}, {"entity": "alpha beta", "label": 1}]
        self.assertEqual(N.novelty(items), 0.0)

    def test_disjoint_alphabet_is_fully_novel(self):
        items = [{"entity": "aaaa", "label": 0}, {"entity": "zzzz", "label": 1}]
        self.assertEqual(N.novelty(items), 1.0)


if __name__ == "__main__":
    unittest.main()
