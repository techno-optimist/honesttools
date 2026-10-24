# nulltest — does this benchmark measure what it says, or just how the text looks?

A truthfulness, hallucination or honesty benchmark labels its items (real vs. invented, true vs.
false, grounded vs. hallucinated) and reports how well a model tells them apart. If a small
classifier that **never sees a model**, only the surface form of the item text, can recover those
labels, then part of every score on that benchmark was spelling, length, template or sampling
order, not the ability the benchmark claims to measure.

`nulltest` measures how much of a benchmark's label signal is recoverable from surface form alone,
and says PASS, DISQUALIFIED or NOT_SCORABLE. It scores no model. It needs no GPU, no network and no
API key, and nothing from whoever built the benchmark. One Python file, standard library only, and
a JavaScript port that computes the same bits in a browser.

```bash
git clone https://github.com/techno-optimist/honestytools && cd honestytools
python3 nulltest.py your_benchmark.json
python3 nulltest.py your_benchmark.csv --text-key statement --label-key label --positive-label 0
python3 nulltest.py your_benchmark.json --json              # machine-readable
python3 nulltest.py your_benchmark.json --jobs 8            # permutations in parallel
python3 nulltest.py your_benchmark.json --explain           # which strings carry the label
python3 nulltest.py qa_data.json --explode right_answer=0,hallucinated_answer=1   # QA rows
python3 -m unittest discover -s tests                        # 40 tests, a few seconds
```

(`pip install honesttools` is the plan, and `pyproject.toml` is ready for it, but the package is
**not on PyPI yet**. Until it is, clone.)

## Who this is for

- **Authors of benchmarks** with a two-class label over text, before they publish. Thirty seconds
  tells you whether a regex could score your benchmark.
- **Reviewers and leaderboard maintainers** checking a benchmark they did not build. Every verdict
  carries the sha256 of the file it scored, so a reader can re-derive it.
- **Anyone reading a hallucination number** who wants to know how much of it the text alone
  explains.

It is **not** a model evaluator, and a team shipping a model has little use for it unless they also
build their own test sets. An earlier version of this page pitched it to that audience; the audit
table below, which is the only usage record we have, contains only benchmarks.

## Input

JSON (a list, or an object holding a list under `items`, `battery`, `data`, `rows`, `examples` or
`instances`), JSONL, CSV or TSV. The tool picks the text, label and stratum fields from the item
keys and prints which ones it chose; override them with `--text-key`, `--label-key`,
`--stratum-key`. Several text fields can be scored together: `--text-key question,answer`.

Labels may be `0/1`, booleans, or a recognised word pair (`real/fake`, `true/false`,
`faithful/hallucinated`, `correct/incorrect` and a few others). Any other pair stops the run and
asks for `--positive-label VALUE`. The tool does not guess, because a guess that happened to be
backwards would still print a confident verdict.

### Question-answer benchmarks: `--explode`

The test needs one text and one two-class label per item. Most QA benchmarks store a question
with a right answer and a wrong one on the same row. `--explode FIELD=LABEL,...` turns each named
field into its own item carrying that label; `--split ";"` separates several answers in one cell;
the row's other fields are kept, so the question's category can be the stratum. The question that
this asks of such data is: can the answer be told right from wrong **without the question**?

```bash
# HaluEval QA: {"question", "right_answer", "hallucinated_answer"} per line
python3 nulltest.py qa_data.json --explode right_answer=0,hallucinated_answer=1

# TruthfulQA: several ';'-separated answers per cell, one category per question
python3 nulltest.py TruthfulQA.csv --explode "Correct Answers=0,Incorrect Answers=1" --split ";" --stratum-key Category
```

Both are in the audit table below. A benchmark with more than two classes has to be filtered to
two first; the tool refuses to pick.

### `--explain`: which strings carry the label

A DISQUALIFIED verdict is only useful if the author can find the artifact. The report therefore
ends with a WHY section (always on a DISQUALIFIED, `--explain` to force it) that describes each
separating cell in-sample: for the fitted probes, the features most over-represented in each class
with their counts; for the score probes, the class medians in plain words ("label-1 items are
longer: median 9 vs 8 characters", "last-word initials: label-1 median 'g' vs label-0 median 'l'").
These tables are a description for finding the artifact, not the evidence for the verdict; the
verdict is held-out and permutation-calibrated, the tables are not.

## The seven surface probes

| probe | what it asks |
|---|---|
| `lexicality` | character 3–5-grams, naive Bayes: does the string *look* like one class? |
| `words` | word unigrams and bigrams, naive Bayes: does the wording or the template leak the label? |
| `length` | character and word count: is one class shorter or longer? |
| `shape` | digit / ALL-CAPS / punctuation signature: are reals ID-shaped and fakes word-shaped? |
| `alpha_first` | alphabet position of the first word's initial: was one class taken from the top of a sorted list? |
| `alpha_last` | same for the last word's initial: lists sorted by surname |
| `stratum` | the category label alone: does the stratum leak the answer? |

The fitted probes are scored on held-out folds, so an item never contributes to the statistics
that score it. Each probe is **two-sided** (`A* = max(AUROC, 1−AUROC)`, because an inverted
classifier is still a classifier), scored **per stratum with the worst cell reported** rather than
the mean, **calibrated against label shuffles of the same data with the probes refit inside every
shuffle**, and **corrected across every cell tested** (Westfall–Young min-p). The PASS/DISQUALIFIED
line is drawn at a family-adjusted p of 0.05; a PASS whose worst cell lands within a factor of two
of that line is marked **BORDERLINE** in the report, because the number of cells in the family can
move such a result on its own.

The `words`, `alpha_first` and `alpha_last` probes are new in v1.3. The alphabet probes exist
because our own `prominence-people-v1` battery passed the four probes of v1.2 and was broken
anyway: its builder took the alphabetically-first 200 members of each Wikipedia category, and
biography categories sort by surname. The surname initial alone recovers its labels at A* 0.661.
Alphabetical sampling is a common way to build a list, so the probe is general. It now catches
that battery.

## Where the idea comes from

This is the hypothesis-only / partial-input baseline of the NLP artifact literature (Gururangan et
al. 2018, Poliak et al. 2018) and the artifact filtering of AFLite (Le Bras et al. 2020), applied to
two-class text benchmarks. The idea is not new. What this tool adds is the discipline around it:
two-sided scoring, worst cell not mean, refit inside every permutation, family-wise correction, a
measured false-positive rate, a reproducible power table, and a browser engine proven
bit-identical to the command line. Cite it as a careful packaging of a known test.

## What the tool says about itself

**Measured false-positive rate**, v1.3, 500 seeds per grid row at 600 permutations, exact 95%
intervals. Reproduce with `python3 nulltest.py --calibrate --jobs 4` (about 17 minutes on 4 cores):

| construction | rate | 95% CI |
|---|---|---|
| planted-clean as shipped (alternating, 1 stratum) | 4.8% | [3.1%, 7.1%] |
| coin-flip labels, 1 stratum | 3.8% | [2.3%, 5.9%] |
| coin-flip, 2 strata | 4.6% | [2.9%, 6.8%] |
| coin-flip, 4 strata | 5.0% | [3.3%, 7.3%] |
| coin-flip, 6 strata | 4.0% | [2.5%, 6.1%] |
| coin-flip, word-shaped text (all 7 probes live), 1 stratum | 4.8% | [3.1%, 7.1%] |
| coin-flip, word-shaped text (all 7 probes live), 4 strata | 5.0% | [3.3%, 7.3%] |

Every upper bound is below the 10% ceiling; the pooled rate is 4.6% over 3500 no-signal batteries. The same grid run at 200 permutations put the widest family (24 cells) at 8.4% [6.1%, 11.2%], which is the Westfall–Young small-B leak noted below; the certificate is therefore measured at the 600 permutations the tool actually runs with.

**Measured power**, v1.3. A single character appended to a fraction of the label-1 half of a clean
synthetic battery; the smallest fraction caught in at least 3 of 4 seeds. Reproduce with
`python3 nulltest.py --measure-power --jobs 4`:

| n | smallest planted coverage caught |
|---|---|
| 156 | 60% |
| 324 | 60% |
| 702 | 30% |
| 1496 | 15% |

A PASS at n=156 therefore says only that no artifact covering 60% or more of one class was found.
The POWER line in every report quotes this table for the battery's n.

**`--selftest` is a smoke test, not a certificate.** At 25 seeds it usually returns
INDISTINGUISHABLE, which is the honest answer: a 25-seed point estimate of a 5% rate compared
against a 10% ceiling fails a perfectly calibrated tool about half the time. `--selftest` is
read-only. `--calibrate --emit-grid PATH` writes the certificate, refuses to write into the tool's
own directory, and stamps the tool's sha256 into it so a reader can tell whether a certificate
describes the code in front of them. CI checks that stamp on every commit.

## Known limits — read these before quoting a verdict

- **A PASS is not a certificate of quality.** It says these seven probes did not recover the labels
  at this n. A weaker or a differently shaped artifact can be present and missed; the power table
  says how weak.
- **Circularity, contamination and mislabelling are invisible here.** They are provenance
  properties, not surface ones.
- **A wider family costs power.** Going from four probes to seven moved our own
  `grounding-coordinate` battery from DISQUALIFIED (adjusted p 0.030 over 18 cells) to PASS (0.057
  over 35 cells) with the same worst cell at the same A*. That is why BORDERLINE exists. If you
  only care about one probe, the per-cell `raw_p` is in the JSON.
- **Westfall–Young leaks at large families and few permutations.** With 24 cells the false-fire
  rate measured 8.4% at 200 permutations and 5.0% at 600 (v1.3, 500 seeds each), a discreteness
  effect at the permutation floor. Do not lower `--n-perm` below the default 600 on a battery with
  many strata; raise it for very wide families.
- **`A*` is not a stable effect size.** It is a fitted classifier's output and depends on n. Rows of
  different n are not comparable.
- **No external co-signer, and no outside user yet.** Every number here is our own measurement of
  our own tool, and no one outside this project has run it on their own benchmark. The charter
  names that as the test the project must pass.

## What's in here

| file | role |
|---|---|
| `nulltest.py` | the instrument. `--selftest`, `--calibrate`, `--measure-power`, `--emit-grid` |
| `nulltest.js` | the same instrument for a browser; `nulltest_parity.sh` proves the two agree cell by cell. The browser engine scores flat two-class files; `--explode` and `--explain` are command-line only |
| `tests/` | unit tests: every probe catches the artifact it was written for, the loader refuses to guess, parallel equals serial |
| `nulltest_audit.py` | scores a manifest of published benchmarks and writes the table behind [honesty.tools/audit](https://www.honesty.tools/audit) |
| `nulltest_audit_manifest.json` | the targets: URL, exact field mapping, label polarity, and what kind of label each is |
| `nulltest_audit_results.json` | the table. Every row carries the sha256 of the bytes scored |
| `nulltest_grid.json` | the false-positive certificate, sha256-stamped to the tool that produced it |
| `batteries/` | our own nine batteries, all of them in the table |
| `honest.py`, `contract.py` | the toolbox entry point (`honest null battery.json`) and the four-method tool contract; see `CHARTER.md` |
| `render_audit.py`, `claim_gate.py`, `null_floor_reconcile.py`, `demo.sh` | the harness we run against our own site; they expect the site tree beside them and do nothing useful in a bare checkout |

`audit_cache/` is gitignored on purpose: the audit records a URL and a sha256 for each third-party
corpus, never a copy.

## Run it against us, and against the benchmarks the field uses

The audit table at [honesty.tools/audit](https://www.honesty.tools/audit) has 17 rows: our own nine
batteries, five third-party honesty corpora, and, new in v1.3, three rows from the two benchmarks
most often quoted in hallucination papers, scored by answer alone with `--explode`:

| benchmark | items | worst cell | A* | verdict |
|---|---|---|---|---|
| TruthfulQA, reference answers (`Correct Answers` vs `Incorrect Answers`, per category) | 6028 | 77 of 222 cells separate | 1.000 | DISQUALIFIED |
| HaluEval QA (`right_answer` vs `hallucinated_answer`) | 20000 | 5 of 6 cells separate | 0.979 | DISQUALIFIED |
| HaluEval dialogue (`right_response` vs `hallucinated_response`) | 20000 | 6 of 6 cells separate | 0.849 | DISQUALIFIED |

`--explain` says why. In TruthfulQA the correct column is full of "I have no comment" and "do
not" hedges and the incorrect column of "believe that" and "that the" assertions; a model that
learned to hedge scores without knowing anything. In HaluEval the hallucinated answers were
written by ChatGPT and the right answers are HotpotQA's short reference strings: median 58
characters against 12, and in the dialogue set 104 against 69. None of this is a claim that the benchmarks are useless. It is a measurement of
how much of a score on them is available to a reader who never sees the question.

Eleven of the seventeen rows are DISQUALIFIED and four of the eleven are ours. Under v1.2 our four were
`verifydomain-claims-147`, `calibration-battery-v1`, `photon-entities` and `grounding-coordinate`;
under v1.3 `grounding-coordinate` is a BORDERLINE PASS and `prominence-people-v1`, which v1.2
missed, is caught. The two worst rows on the table are still ours. A DISQUALIFIED verdict is a
measurement about a corpus, not a finding of error or misconduct by its authors. Re-score the
whole table with `python3 nulltest_audit.py --jobs 4` (about 17 minutes on 4 cores, most of it
the two 20000-item HaluEval rows; the corpora are fetched from their own repositories and
recorded as a URL and a sha256).

## Licence

Apache-2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE). It covers this repository: the null test,
the audit harness, the claim gate and the batteries. It does not cover the third-party corpora
scored in the audit table, which are fetched from their own repositories under their own terms and
recorded here as a URL and a sha256, not a copy.
