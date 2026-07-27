# nulltest — does this honesty benchmark measure honesty, or string shape?

An honesty or hallucination benchmark labels items REAL vs FABRICATED and reports how well a model
tells them apart. If a classifier that **never sees a model** — only the surface form of the item
text — recovers those labels, part of that score was spelling.

`nulltest` measures how much of a benchmark's label signal is recoverable from surface alone.
It scores no model. No GPU, no network, no API key, no cooperation from whoever built the
benchmark. Stdlib Python, one file.

```bash
python3 nulltest.py battery.json
python3 nulltest.py battery.json --json
python3 nulltest.py --selftest      # planted-failure control
python3 nulltest.py --calibrate     # measure the tool's own false-positive rate
```

A battery is a JSON list of `{"entity": "...", "label": 0|1, "category": "..."}`. Field names are
sniffed, or set them with `--text-key/--label-key/--stratum-key`.

## The four surface nulls

| null | what it asks |
|---|---|
| `lexicality` | character 3–5grams — does the string *look* fake? |
| `length` | character and word count — are fakes shorter or longer? |
| `shape` | digit/punct/case signature — are reals ID-shaped and fakes word-shaped? |
| `stratum` | the category label alone — does the stratum leak the answer? |

Two-sided (`A* = max(AUROC, 1−AUROC)`, because an attacker inverts a classifier for free), scored
per stratum with the **worst** cell reported rather than the mean, calibrated against label
shuffles of the same data, and family-wise corrected (Westfall–Young min-p) across every cell
tested. The classifier is refit inside every permutation.

## What the tool says about itself

**Measured false-positive rate**, 500 seeds per grid row, exact 95% intervals:

| construction | rate | 95% CI |
|---|---|---|
| planted-clean (alternating, 1 stratum) | 5.2% | [3.4%, 7.5%] |
| coin-flip labels, 1 stratum | 3.8% | [2.3%, 5.9%] |
| coin-flip, 2 strata | 4.6% | [2.9%, 6.8%] |
| coin-flip, 4 strata | 5.6% | [3.8%, 8.0%] |
| coin-flip, 6 strata | 4.0% | [2.5%, 6.1%] |

Every upper bound is below the 10% ceiling. Reproduce it with `--calibrate`; it takes a while.

**`--selftest` is a smoke test, not a certificate.** At 25 seeds it usually returns
`INDISTINGUISHABLE`, and that is the honest answer: a 25-seed point estimate of a 5% rate compared
against a 10% ceiling fails a *perfectly calibrated* tool about half the time. An earlier version
did exactly that, and wrote whichever side of the coin it landed on into this directory as its own
certificate. `--selftest` is now read-only; `--emit-grid` writes certificates, refuses to write
into the served directory, and stamps the tool's sha256 into the artifact so you can tell whether a
certificate describes the code you are holding.

## Known limits — read these before quoting a verdict

- **A PASS is not a certificate of quality.** It says these four probes did not recover the labels
  at this n. Below n≈700 the measured MDE is ~60% coverage of the label-1 half: a weaker artifact
  can be present and missed. `prominence-people-v1` PASSES and is *still broken* — a fifth probe we
  had not written recovers its labels at A\* 0.661. It is published for that reason.
- **Circularity is invisible here.** It is a provenance property, not a surface one.
- **Westfall–Young leaks at large families.** FWER measured at 11.2% (nominal 5%) with K=24 cells
  at B=200 permutations — a discreteness effect as the family-min saturates at the permutation
  floor. Calibrated at K≤12. Raise `--n-perm` for wide families.
- **`A*` is not a stable effect size.** It is a fitted classifier's output, so it depends on n.
  Rows of different n are **not** comparable to each other.
- **No external co-signer.** Every number above is our own measurement of our own tool.

## Licence

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). The patent grant in §3 is the reason for
Apache rather than MIT: the intended users are labs whose counsel reads the licence first.

The licence covers this directory — the null test, the audit harness, the claim gate, and the
batteries under `batteries/`. It does not extend to the rest of the repository, and it does not
cover the third-party corpora scored in the audit table, which are fetched from their own
repositories under their own terms and recorded here as a URL and a sha256, not a copy.

## What's in here

`nulltest.py` / `nulltest.js` are the instrument, and the parity script proves they compute the
same verdict on the same bytes. `nulltest_audit.py` scores a manifest of benchmarks.
`nulltest_parity.sh`, `render_audit.py` and `claim_gate.py` are the harness we run against our own
site — the last two expect the site's page tree beside them and will not do anything useful in a
bare checkout. They are here because they are the part that keeps us honest, and publishing the
instrument without them would be publishing the easy half.

`audit_cache/` is deliberately absent and gitignored: the audit records a URL and a sha256 for
each third-party corpus, never a copy.

## Run it against us

`nulltest_audit.py` scores a manifest of published benchmarks and writes the table behind
[honesty.tools/audit](https://www.honesty.tools/audit). All nine of our own batteries are in it and
four are DISQUALIFIED, including the two worst rows on the table. A DISQUALIFIED verdict is a
measurement about a corpus, not a finding of error or misconduct by its authors.
