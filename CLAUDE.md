# Self-Improving Trading Agent — operating protocol

This repository IS the agent's memory. Nothing learned in a conversation survives
unless it is written here and committed. The trader's master directive is imported
below and governs all analysis; this file governs how that analysis is persisted.

@docs/SYSTEM_PROMPT.md

---

## Division of labour

- **You judge; `./tj` computes.** Classification, chart reading, thesis critique,
  loss typing and process scoring are yours. R multiples, position size, liquidation,
  expectancy, confidence intervals and recurrence counts come from `./tj`. Never do
  that arithmetic in your head when the tool can, and never quote a statistic the
  tool did not print.
- **One source of truth.** The error database, behaviour database and all performance
  statistics are derived from `journal/trades/*.yaml`. Do not maintain counts by hand
  anywhere else.

## Session start

A SessionStart hook runs `./tj status` (unresolved parameters, phase, recurring errors,
open positions). If it did not run, run it yourself. Respect the **phase** it reports:
in INITIALIZATION, learn and record; do not propose system redesigns.

## Repository map

| Path | Holds | Rule |
|---|---|---|
| `journal/trades/T-####.yaml` | one record per trade/idea | created with `./tj new`; unknown = `null` |
| `journal/charts/` | screenshots the trader commits | reference from `evidence.charts` |
| `profile/trader.yaml` | risk limits, fees, sessions, terminology | fill only from the trader's own statements; cite in `sources` |
| `taxonomy/*.yaml` | canonical tags (setups, regimes, mistakes, behaviours, loss types) | add the trader's new terms here in their words |
| `playbook/strategies/<slug>/` | `strategy.yaml`, immutable `v*.yaml`, append-only `changes.yaml` | from `templates/strategy/` |
| `playbook/experiments/EXP-###.yaml` | A/B tests | from `templates/experiment.yaml` |
| `playbook/PLAYBOOK.md` | consolidated knowledge (§27) | every entry cites trade IDs and n |
| `playbook/automation.yaml` | gated road from journal to bot (stages, criteria, safety) | computed gates update on build; a manual gate goes `done` only with `evidence:` |
| `config.yaml` | thresholds (evidence tiers, promotion gates) | assumptions; change only with a stated reason |
| `terminal.html` | the trader's single-file terminal (journal, stats, strategy, risk, calculator) | **generated** by `./tj build`; never edit by hand |
| `exports/kb.json` | schema-versioned machine export: the contract for the future trading bot | **generated** by `./tj build`; never edit by hand |
| `templates/terminal.html` | terminal source; its RISK-MATH block mirrors `tradekb/risk.py` | change both together; `tests/test_terminal.py` enforces parity |

## Workflows

### A. The trader sends a completed trade
1. `./tj new --asset X --direction long|short` → fill the record. Facts the trader gave or
   the chart shows go in fields and `evidence.observed`; your readings go in
   `evidence.interpreted`; untested ideas in `evidence.hypotheses`. Missing = `null`.
2. `plan.stop` is the **initial** stop. If the stop was moved, record that in
   `journal.during` and tag `moved_stop`/`widened_stop`, never overwrite `plan.stop`.
3. Score the five dimensions (§42), set `setup_validity`, `followed_plan`, `loss_type`
   (losses), `mistakes`, `behaviors`, `lesson`, `strategy_change`. Set `plan.entry_model` to one
   of the strategy version's `entry_models`, and record the trader's confluences/confirmations.
4. `./tj show T-####` → use its R, outcome and GOOD/BAD OUTCOME × PROCESS label.
   `./tj validate` must report 0 errors.
5. Reply in the §44 TRADE REVIEW format. If `./tj status` flags a recurring error,
   say so (§15) as a system-design problem, without shaming.
6. `./tj build` (regenerates `terminal.html` and `exports/kb.json`), then commit:
   `journal: T-#### ASSET long|short +1.8R (setup)`.

### B. The trader presents a setup BEFORE entry
1. `./tj new --status planned ...`; write the thesis, confirmation and invalidation into
   `journal.before`. **Commit it before the outcome is known**: the commit timestamp is
   the proof that the thesis was not written with hindsight (§33, §37).
2. `./tj size --entry E --stop S [--leverage L --margin-mode M --target T]` for the risk
   decomposition. Surface every CRITICAL/WARN flag and every "ASSUMED"/"default" input.
3. Reply in the §18 structure. Do not tell the trader whether to take it.
4. Later: update the same record to `open`, then `closed` (workflow A from step 2).

### C. Missed or not-taken trades
`--status missed|not_taken`. Any outcome goes in `result.hypothetical_r` only, labelled
COUNTERFACTUAL. The validator rejects realized results on these records and stats exclude them.

### D. New term or new setup
If the trader uses a term not in `taxonomy/`, add it as a new tag **in their words** with
`introduced_in: T-####` and their definition; mirror it in `profile/trader.yaml`
`terminology`. Use `aliases` only for true synonyms. Never force their term into a generic tag.

### E. New strategy (§40)
Copy `templates/strategy/` to `playbook/strategies/<slug>/`, record only rules the trader
stated, `status: unvalidated`, version `1.0`. Tag subsequent trades with `strategy.id` and
`strategy.version`.

### F. Strategy change (§20, §21, §41)
Never edit a committed `v*.yaml` (the validator fails). Two kinds of change record:
- **clarification**: the trader states rules that were already in force (filling `null`s, defining
  terms). New version file, `kind: clarification`, `status: adopted`, `rule_changed: false`, the trader's
  statement quoted. No evidence gate, because no performance claim is made. Retag the trades taken
  under those rules to the new version so per-version statistics are not split by documentation.
- **rule_change** (default): evidence-driven, as below.

For a rule change, append a change record to
`changes.yaml` with every §20 field and its evidence trade IDs. If the trader adopts it,
create the next version file and set `resulting_version`. The validator enforces the
evidence minimums in `config.yaml` for `provisional`/`established` changes and for
`developing`/`established` strategies. Do not work around the gate by lowering the
thresholds.

### G. Experiments (§22, §46)
Create `playbook/experiments/EXP-###.yaml`, fix `min_n_per_variant` **before** results
exist, tag trades with `strategy.experiment` and `strategy.variant`, evaluate with
`./tj compare variant A B --where experiment=EXP-###`. Report the tool's verdict verbatim.

### H. "Review everything we've learned" (§45)
1. `./tj validate`, then `./tj report` (and `./tj compare` for any claimed difference).
2. Write the §45 TRADING SYSTEM REVIEW from that output plus `playbook/`. Every
   performance claim carries n, the CI, and the evidence tier.
3. Update `playbook/PLAYBOOK.md` only where evidence justifies it, citing trade IDs.
4. `./tj build`, then commit: `review: YYYY-MM-DD system review`.

## Hard rules

- `null` over a guess. Always. A plausible number is worse than a missing one.
- Charts shared in chat are not saved automatically. Record what you see in
  `evidence.observed`; ask the trader to commit the image if they want it kept.
- Canonical tags only (the validator rejects aliases and unknown tags).
- `./tj validate` must show 0 errors before every commit, and no `stale` warning: run `./tj build`
  after any knowledge-base change and commit `terminal.html` + `exports/kb.json` with it.
- Contradictions between the trader's rules and their own trades go into the strategy version's
  `open_questions` (INITIALIZATION step 11). Ask; never resolve them by assumption.
- Never promote, generalise or declare a winner beyond what `./tj` output supports.
  "Insufficient evidence" is a complete answer.
- Units: `*_pct` = percent (1.0 = 1%), `*_rate` = decimal (0.0005 = 5 bps).
- Never accept, store, or echo exchange API keys. If the trader offers them, decline and point to the
  `safety` list in `playbook/automation.yaml`: keys live only on the bot's server, trade-only, no withdrawals.
- No automation stage is skipped: the bot is built only after stage 1 of `./tj status` readiness is complete.
- Commit every knowledge-base change and push to the session's working branch.
