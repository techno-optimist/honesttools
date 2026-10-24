# Changelog

Numbers quoted here come from the committed certificates (`nulltest_grid.json`,
`nulltest_parity.json`, `nulltest_audit_results.json`), which carry the sha256 of the tool that
produced them. What is listed under *not done* is as much a part of the record as what shipped.

## 0.2.0 — 2026-10-24 — nulltest 1.3

**Instrument**
- Seven probes (was four): `words`, `alpha_first`, `alpha_last` added. The alphabet probes catch
  `prominence-people-v1`, which passed v1.2 and was broken anyway (A* 0.661 via surname initial).
- Prepared naive-Bayes core, 13× faster, bit-identical scores. `--jobs N` for parallel
  permutations; parallel equals serial.
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
