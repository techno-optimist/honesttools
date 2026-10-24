# Changelog

Numbers quoted here come from the committed certificates (`nulltest_grid.json`,
`nulltest_parity.json`, `nulltest_audit_results.json`), which carry the sha256 of the tool that
produced them. What is listed under *not done* is as much a part of the record as what shipped.

## 0.3.0 — 2026-10-24 — nulltest 1.4 (correction)

A statistics review of 1.3 on the day it shipped found that the permutation null was not
stratified, that the seventh probe could never score, and that Westfall–Young was biased at the
permutation floor. All three are fixed; the verdicts that changed are listed under *Evidence* and
in `audit_notes.json` as CORRECTION entries.

**Instrument**
- Stratified null: labels are shuffled within each stratum. No-signal batteries with 85/15 label
  rates false-fired 44% of the time under 1.3 (120 simulated batteries); 3.0% [1.7%, 4.9%] (15 of 500) now.
- Six probes: the `stratum` probe is removed (degenerate in every per-stratum cell by construction;
  it never produced a cell). The label rate per stratum is printed as a description.
- Westfall–Young: observed and permuted statistics are p-valued from the same pool; the
  permutation count is raised to `ceil(2(K+1)/alpha)` (hundreds) when `--n-perm` cannot resolve
  alpha for the family, and the report records `n_perm_requested` and `n_perm`.
- Worst-cell ties broken by effect `(A*−0.5)·√n`; BORDERLINE two-sided (alpha/2 ≤ adj p < 2·alpha).
- Receipts record `positive_label`; `--check` honours it and accepts `honest null` output.
- Loader: `is_true`/`truth` sniffed before `type`/`kind`; `--explode` names a field no row has;
  file-not-found, malformed JSON and empty files are sentences, not tracebacks; `--positive-label`
  is case-insensitive; `--stratum-key none` disables a sniffed stratum; the report opens with rows
  read and dropped, coerced texts and the raw value that became label-1 (`data` in the receipt).
- `--explain` shows one cell per probe before the rest (8 cells); large files print progress.
- GitHub Action: `args:` accepts quoted arguments.
- Browser engine mirrors all of the above; parity measured bit-identical on 270 cells across 14
  batteries, including astral, CJK, whitespace, quoted-CSV and small-cell fixtures (`parity/`).

**Evidence**
- Grid: 10 rows × 500 seeds (three new constructions: 85/15 label rates, 36 cells, strata of 20).
  Worst row 4.8%, pooled 4.0% (201 of 5,000); every interval under the 10% ceiling; the 85/15 row 3.0% [1.7%, 4.9%] (15 of 500).
- Audit: 17 rows re-scored; 16 verdicts unchanged. `grounding-coordinate` (ours) moves from
  BORDERLINE PASS (adj p 0.057) to BORDERLINE DISQUALIFIED (0.037), same cell, same A* 0.855.
  TruthfulQA's worst cell is now words/Law A* 0.857 (63 of 222 cells separate; tie-break by effect).
  `truth-is-universal/facts` now BORDERLINE. 12 of 17 fail, 5 of the 12 ours; two rows at A* 1.000, both ours.
- 51 unit tests.

**Not done**
- No PyPI release; no outside user; the GitHub Actions runner on this repository has not started
  a run since the workflow was added, so CI has not executed the eight gates remotely.

## 0.2.0 — 2026-10-24 — nulltest 1.3

**Instrument**
- Seven probes (was four): `words`, `alpha_first`, `alpha_last` added. The alphabet probes catch
  `prominence-people-v1`, which passed v1.2 and was broken anyway (A* 0.661 via surname initial).
- Prepared naive-Bayes core with bit-identical scores (we measured about 13× on one battery;
  no timing is committed). `--jobs N` for parallel permutations; parallel equals serial.
- Input: JSON, JSONL, CSV, TSV; `--text-key a,b`; labels never guessed (`--positive-label`).
- `--explode FIELD=LABEL,... --split SEP` for question-answer corpora.
- `--explain`: WHY section naming the features that carry each separating cell (in-sample, never
  used for the verdict). Also in the browser engine; the parity harness compares the WHY tables.
- BORDERLINE flag within 2× of alpha. `--measure-power` re-derives the MDE table.
- Every `--json` report carries `battery_sha256` and `tool_sha256`; `--check RECEIPT` replays a
  published verdict against the bytes and says REPLAYS or DIVERGES.

**Evidence**
- Calibrated at the shipped 600 permutations, 7 grid rows × 500 seeds: worst row 5.0%, pooled 4.6%.
- Audit table 17 rows (was 14): TruthfulQA reference answers, HaluEval QA and HaluEval dialogue
  added and all three DISQUALIFIED by answer alone. 11 of 17 fail, 4 of the 11 ours.
  `grounding-coordinate` moved from DISQUALIFIED to BORDERLINE PASS when the family widened.

**Toolbox**
- `honest null` takes the full flag set; `honest check` replays a receipt; `honest audit` runs the
  table from a checkout.
- GitHub Action (`uses: techno-optimist/honestytools@main`) runs the test in a benchmark author's
  own CI, writes the receipt, and puts WHY in the job summary.
- 42 stdlib tests; CI jobs: certificates, batteries, tests, parity, selftest, read-only, install,
  action.
- CONTRIBUTING, issue templates for adding a benchmark and reporting a verdict, this changelog.
- README rewritten; CHARTER amended with what the evidence supports.

**Not done**
- Not on PyPI. `pyproject.toml` is ready and `publish.yml` publishes on a GitHub Release once a
  PyPI pending publisher exists.
- No outside user has run the tool on their own benchmark.
- The wheel does not bundle the calibrated grid; `honest fpr` declines to quote a rate it cannot
  verify against the installed code.
- `pyproject.toml` Repository URL fixed (pointed at a repository that did not exist).

## 0.1.1 and earlier

Phase 0 skeleton: the tool contract, `honest null`, nulltest v1.2 with four probes, the audit
harness, the claim gate and the parity harness. See the git history.
