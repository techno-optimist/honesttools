# The Honesty Toolbox — Mission & Charter

*Founding document. Written 2026-07-27. This is a contract with ourselves before it is a pitch to
anyone else, and like every tool in the box it is meant to be falsifiable — see the last section.*

---

## Mission

The world is deploying AI it cannot check. Every model size needs honesty tooling, and needs it
differently: small and mid open models (8B–35B) are being shipped by people who cannot fall back on
capability trust and need a **model-free gate that runs in CI with no GPU, no network, no logprobs**;
frontier models need checks whose **cost to defeat rises with the producer's capability**. Meanwhile
the checks that already exist self-certify — they report green without ever having been broken on
purpose.

Our job is to build and package the honesty toolbox: model-agnostic tools that score **bytes,
outputs, and behavior**; that each ship their own break-test and print their own false-positive
rate; that a stranger can replay offline without trusting us; and whose first public act was to
disqualify our own two flagship batteries.

**Safe *and* useful** means the tools make deployment decisions *possible*, not just publishable —
the eval you can trust, the number you can bind, the receipt you can re-derive, the abstention you
can certify.

> **One line:** Honesty tools that never take their own word for it — model-free checks for AI of
> every size, each shipped with the break-test that would catch it lying, replayable by any stranger
> offline.

---

## The spine: a contract, not a collection

The offering is not a grab-bag of scripts, not a leaderboard, and not a hosted service. It is a
**contract**, delivered as a package. Every tool in the box implements one frozen interface:

| method | what it guarantees |
|---|---|
| `run(input) -> Verdict` | a structured verdict with the numbers that back it |
| `selftest()` | the deliberately-broken input the tool **must** catch — run in CI on every commit |
| `false_positive_rate()` | a **calibrated, shipped document** — a measured rate with intervals, not a promise |
| `replay(receipt)` | re-derive the verdict offline, stdlib only, with no call back to us |

`honesttools` on PyPI is how that contract reaches a stranger in one line. The contract is the moat:
a lone script is copyable, but a contract that **forces every member to expose its own vacuity
mode** is a standard others build inside — which is how the toolbox grows without either of us in
the loop.

**The stable/experimental wall is mechanical, not editorial.** A tool that fails its own
pre-registered kill condition cannot emit a stable verdict, no matter how real the thing it almost
measures. This is the packaging-layer version of the discipline we nearly lost: it makes it
*impossible* to launder a failing tool under the credibility of a passing one.

---

## The toolbox today

Honest status. We oversell nothing in either direction — no "six-tool suite with four asterisks,"
and no eulogies for tools that have a documented way back.

### Shipped — in the contract, replayable, live
- **`null`** — model-free surface floor. Measures whether a benchmark measures honesty or string
  shape before any score on it is trusted. Apache-2.0, 8-job CI, calibrated 4.0% pooled
  false-positive rate (v1.4: 10 constructions × 500 seeds, stratified null, worst row 4.8%).
  12 of 17 audited benchmarks fail it; 5 of them are ours; two rows sit at A* 1.000 and both are
  ours. *(figures updated in place 2026-10-24, twice; the rest of this section is as written.)*
- **`gate`** — binds every published numeral to a registry id and fails closed. 0 unannotated
  numerals across 9 live pages.
- **`verify`** — re-derives a signed verdict from one stdlib+crypto file with no call back to us.
  The independence primitive: trust the math, not the lab.
- **`audit`** — scores a manifest of batteries and renders the one table; refuses to go green if any
  of our own batteries is missing. The anti-flattery invariant as executable code.

### Revive — real, partial, with a costed path back (not dead)
- **`checkerboard`** *(cheapest revival)* — checks the checker: does a verifier actually verify?
  Competence leg live-passes on the 35B (J=1.0, p=1.9e-6). Provenance leg is power-limited (zero
  discordant pairs in the latest run). Path: author same-content, tag-swapped pairs locally until
  McNemar has power. No new registry, no recalibration, no calendar wait.
- **`renew`** *(highest-value lane)* — contamination-free eval generation from dated public
  registries: the answer key is written by a third party **before** any model is asked. The PyPI
  floor already passed; held for underpower at n=80 with a clear accumulate-over-days path, plus an
  unsolved era-vocabulary leak that PRE/POST name-shape matching must close. The NVD answer key is
  dead (CVE ids encode the answer); **the key died, the recipe did not.**
- **`observertest`** — concealment/sandbagging detection from output bytes only. Fails its
  pre-registered kill condition as written (a real dressing-by-register interaction masquerades as
  concealment). Two documented revival paths. **The one tool whose defeat cost rises with producer
  capability** — a frontier-tier instrument, net-negative at the small tier. Cannot emit a stable
  verdict until it clears its own kill condition.

### Build — the next tool the world needs
- **`abstaintest`** — a fail-closed selective-prediction certificate for verbalized uncertainty, no
  logprobs: does "I don't know" actually mean I-don't-know? Certifies a claimed selective-risk bound
  per model per policy, with a shuffled-label null that catches confidence merely tracking question
  difficulty. Structurally a clone of `null`'s null + the audit certificate, pointed at confidence
  instead of surface — the lowest-risk gap to build, and the decision every abstain/escalate/route
  loop rests on.

### Dead — cited as the cost of honesty, not revived
- **`nondisclosure`** — falsified 233/233 by pure text addition, and needs our private transcripts.
- **`numeral-beacon`** — defeated by paraphrase and rounding, the default output of real summarizers.

---

## Principles (the non-negotiables)

1. **Break the check before trusting it.** No tool enters `stable` until its selftest catches a
   deliberately broken input. Every defect in our ~17-item failure taxonomy was found this way —
   none by running the check normally.
2. **Nothing self-certifies.** Every verdict is offline-replayable by a stranger with stdlib and no
   call back to us. A verdict only we can reproduce is not a verdict.
3. **Fail closed.** A missing input, an unbound numeral, an absent battery is a red. The audit table
   refuses to go green without our own worst artifacts at the top of it.
4. **Print your own false-positive rate.** Every tool ships a calibrated FPR as a merge gate and
   states its limits in its own output.
5. **Score bytes, not internals.** No logprobs, no weights, no producer cooperation. The tools must
   survive the reachability collapse and must never require trusting the model they score.
6. **Symmetric honesty.** We neither oversell deaths as terminal nor revivals as done. The
   stable/experimental wall enforces this in code, not in prose.

---

## Who it's for

1. **Small/mid open-model deployers** shipping an 8B–35B in a real pipeline — the tier that cannot
   fall back on capability trust and needs `pip install honesttools; honest null battery.json` to
   run in CI with no GPU, no network, no logprobs, scoring *their* artifact and asking nothing of
   their model.
2. **Benchmark and eval authors**, including honesty/hallucination-leaderboard maintainers, who have
   no 30-second way today to check their own battery isn't surface-separable before publishing.
3. **Auditors, red-teams, and advisors** who must put a name on a verdict and therefore need the
   offline replay — endorse the math you re-derived, not the lab that emitted it.
4. **Frontier evaluators** (as the revival lane matures) who need concealment checks whose cost to
   defeat rises with capability.

---

## Roadmap

| phase | ships | proves |
|---|---|---|
| **0 — Contract** (wk 1–2) | the one-page tool contract + `null` wrapped in it as `honest null`, pyproject skeleton, stable/experimental wall as code | the contract fits the strongest tool without distorting it; the unifying interface is designed against the hardest case first, reversibly |
| **1 — v0.1** (wk 3–6) | PyPI release with exactly the four shipped tools, CI running every selftest on every commit, per-tool FPR docs, fork-clean repo under the honesty.tools brand | a stranger goes from install to verdict on their own benchmark in one command, and the audit refuses green when experimental tools are invoked as stable |
| **2 — Revival, cheapest first** (wk 3–10, parallel) | checkerboard provenance pairs; renew/PyPI accumulation + name-shape matcher; observertest many-dressings collection | each oversold death gets an honest verdict — clear your own kill condition and graduate, or fail again and join the dead list. Either is a result |
| **3 — abstaintest** (Q2) | the selective-prediction certificate, built inside the contract from day one | the contract *generates* new tools, not only wraps old ones — the toolbox grows without the founder as bottleneck |
| **4 — external co-signature** (Q2) | the first verdict re-derived and signed by someone who is not us | independence is real; today every verdict is still signed by us, and the thesis requires that to end |

---

## What we stop

- Shipping loose single-machine scripts with incompatible interfaces and no receipts — new work
  lands inside the contract or it doesn't land.
- Reviving the genuinely dead (`nondisclosure`, `numeral-beacon`).
- Building new detection tools before the packaging layer exists.
- Building anything that reads logprobs, weights, or internals — a depreciating class as reachability
  collapses.
- Overselling in either direction.
- Routing every field-tracking and review decision through the founder — the contract plus the
  `renew` eval-factory is how the system stays at the front of the wave without him reading every
  paper.

---

## Why this stays at the front of the wave

Three compounding reasons a two-person lab can hold this:

1. **The reachability collapse is our tailwind.** Only 1 of 5 model families still exposes logprobs,
   so every internals-reading honesty method is depreciating on a clock — while byte/output/behavior
   scorers, which is our entire stable set, are the durable survivors. We are positioned where the
   field is being forced to move.
2. **Freshness becomes mechanical, not heroic.** The renewal recipe generates exams whose answer
   keys predate the model. As models memorize every static benchmark, our eval supply regenerates on
   a **cron schedule, not a reading list.**
3. **The moat is the discipline, compiled into a contract.** Break-before-trust, the calibration
   loop, the anti-flattery invariant — turned into a plugin interface every member must satisfy. CI
   runs every selftest; the audit refuses vacuous green; the FPR doc is a merge gate. The contract
   does the reviewing, so neither of us is the bottleneck. Capability growth makes confident-sounding
   error subtler, which raises the value of every tool in the box — **the demand curve bends toward
   us as the models get better.**

---

## For advisors

> You would be endorsing an honesty toolkit whose first public act was to disqualify its
> authors' own two flagship benchmarks, and whose every verdict you can re-derive yourself, offline,
> with one standard-library file and no trust in us. Your name goes on a **frozen contract** — a
> calibrated false-positive rate, a break-test that runs on every commit, and a hard wall that keeps
> any tool that fails its own kill condition from ever showing green — not on a folder of scripts or
> a press release.

---

## What would falsify this charter

Two observations, either fatal. We hold ourselves to the rule we hold our tools to.

1. **Adoption.** If two quarters after a genuine one-line install exists, no external party has run
   `honest null` on their own battery or re-derived a single receipt — despite the install costing
   one line and asking nothing of their model — then the world does not lack a trustworthy honesty
   check, it lacks the *desire* for one, and packaging discipline was never the bottleneck.
2. **Discrimination.** If a benchmark or model behavior that passes every stable floor is later shown
   to be gamed or memorized in a way byte-level scoring could not in principle have caught — the
   honest signal has moved somewhere bytes cannot reach — then the reachability-collapse bet inverts:
   model-free was the blind position, not the durable one, and the toolbox is calibrated theater.

If either lands, we say so in the registry and change course. A mission statement that cannot be
falsified is exactly the vacuous green this lab exists to refuse.

---

## Amendment, 2026-10-24 — what the evidence supports today

The charter above is kept as written on 2026-07-27, except the figures in the `null` bullet of
*Shipped*, which are updated in place and marked. Three months on, some of it describes work
that has not happened, and this document holds itself to the same rule as the tools: say what is
measured, not what is hoped.

**Who has actually used it.** No one outside this project has run `null` on their own battery or
re-derived a receipt. The adoption clause in *What would falsify this charter* starts its clock on
the day a one-line install exists; that day has not come, because `honesttools` is not on PyPI
yet. Until it is, the install is `git clone`, and the clock is not running.

**Who it is for, in order of evidence.** The audit table is the only usage data we have, and every
row in it is a *benchmark*, scored by its authors or by us. So the audience the tool has
demonstrably served is benchmark and eval authors and the reviewers who check them. The 8B–35B
model deployer listed first above has not appeared: a team shipping a model rarely builds its own
real/fake battery, and `null` scores batteries, not models. That tier is a hope, not a user, and
is listed last now. The advisor pitch above should be read with this paragraph next to it.

**What the tool is.** The core idea is the hypothesis-only / partial-input baseline of the NLP
artifact literature (Gururangan et al. 2018; Poliak et al. 2018; AFLite). The contribution is the
discipline around it, not the idea: two-sided scoring, worst-cell reporting, refit-inside-permutation
calibration, family-wise correction, a measured false-positive rate, bit-identical browser and CLI
engines. Cite it as a packaging of a known test, done carefully.

**What changed in v1.3.** Seven probes instead of four. The two alphabet-position probes were added
because `prominence-people-v1` passed the four and was broken anyway; it is now caught. Widening
the family cost one of our own detections: `grounding-coordinate` moved from DISQUALIFIED
(adjusted p 0.030, 18 cells) to PASS (0.057, 35 cells) with its worst cell unchanged. The report
now marks such results BORDERLINE instead of letting a binary verdict hide them. The table's
"4 of 9 ours disqualified" is still true, but it is a different four.

**The roadmap.** Phase 0 shipped. Phase 1 (PyPI, every selftest in CI) is partly done: CI runs
the gates on every commit; the PyPI release has not been made. Phases 2–4 have not started. The
`checkerboard`, `renew`, `observertest` and `abstaintest` tools described above exist as research
notes and partial code elsewhere, not in this repository, and nothing here should be read as
claiming they ship.

**Later the same day.** The audit table has 17 rows: TruthfulQA's reference answers and both
HaluEval sets were added and all three fail by answer alone, so the figure in *The toolbox today*
("8 of 14 audited benchmarks fail it") is now 11 of 17, still 4 of them ours. The `gate`, `verify`
and `audit` entries under *Shipped* describe `claim_gate.py`, `verify_widget.js` and
`nulltest_audit.py`: real and in this repository, but only `null` is wrapped in the contract that
section says they all share; `honest audit` runs the harness and `honest check` replays a receipt,
and neither is a contract tool. CI runs eight jobs, not five. A GitHub Action now lets a benchmark
author run the test on every commit of their own repository, which is the install path the
adoption clause was waiting for; the clock starts when someone outside this project uses it.

**Correction, the same evening (v1.4).** A statistics review of v1.3 found that its permutation
null shuffled labels across strata, so a benchmark whose categories had different label rates
false-fired 44% of the time on noise; that its seventh probe could never score; and that the
family-wise correction was biased at the permutation floor. v1.4 fixes all three: the null is
stratified, there are six probes, and the permutation count is raised to match the family. The
grid now carries the constructions v1.3 was never tested on. Re-scored, 16 of 17 audit verdicts stand; our own `grounding-coordinate` goes from borderline PASS to borderline DISQUALIFIED, so the table reads 12 of 17, 5 of them ours. The figures in *The toolbox today* were updated in place a second time; the certificate is
`nulltest_grid.json`. This paragraph exists because the charter says claims match evidence, and
for part of one day they did not.
