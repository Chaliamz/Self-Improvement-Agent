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
| `playbook/automation.yaml` | gated road from journal to bot (stages, criteria, safety, bot questions, malfunction guard G1-G9) | computed gates update on build; a manual gate goes `done` only with `evidence:` |
| `playbook/incidents.yaml` | incident log: bugs, data corruption, trader-corrected readings, near misses | **append-only** (the validator checks it against the last commit); shown in the terminal's Health tab |
| `config.yaml` | thresholds (evidence tiers, promotion gates) | assumptions; change only with a stated reason |
| `terminal.html` | the trader's single-file terminal (journal, stats, rule compliance, strategy + checklist, risk, bot readiness, data gaps, health) | **generated** by `./tj build`; never edit by hand |
| `exports/kb.json` | schema-versioned machine export: the contract for the future trading bot | **generated** by `./tj build`; never edit by hand |
| `templates/terminal.html` | terminal source; displays only what `./tj build` computed (no math of its own) | `tests/test_render.py` walks every tab and background in headless Chromium |

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
   Record the trader's own grade in `review.trader_grade` when they give one (scale S, A, B, C, D).
   Record `fills.worst_price` and `fills.best_price` from the chart (furthest against / in favour between entry
   and exit; the TP price when the target filled): `./tj` turns them into MAE / MFE in R.
   Record `timeframes.chain` (highest first, ending at the execution timeframe), `timeframes.detail` (lower
   timeframes viewed only for detail, e.g. unmitigated levels/FVGs) and `timeframes.top_down` (true/false); record
   `fills.duration_minutes` when the trader states a duration (dates alone cannot time a scalp).
   Timeframe notation is TradingView's: m minutes, h hours, D days, W weeks, M months. The trader
   may write "1M" for one minute; check the chart interval and record `1m`.
4. `./tj show T-####` → use its R, outcome and GOOD/BAD OUTCOME × PROCESS label.
   `./tj validate` must report 0 errors.
5. Reply in the §44 TRADE REVIEW format. If `./tj status` flags a recurring error,
   say so (§15) as a system-design problem, without shaming.
6. `./tj build` (regenerates `terminal.html` and `exports/kb.json`), `./tj audit` (must pass), then commit:
   `journal: T-#### ASSET long|short +1.8R (setup)`.

### B. The trader presents a setup BEFORE entry
1. `./tj new --status planned ...`; write the thesis, confirmation and invalidation into
   `journal.before`. **Commit it before the outcome is known**: the commit timestamp is
   the proof that the thesis was not written with hindsight (§33, §37).
2. `./tj size --entry E --stop S [--leverage L --margin-mode M --target T]` for the risk
   decomposition; for split limit entries add `--add-entry E2 [--add-entry E3]` (per-order risk from profile
   `risk.split_entries`; one leverage for the position, set by the widest-stop order). Surface every CRITICAL/WARN
   flag and every "ASSUMED"/"default" input.
3. Run the strategy version's `checklist` item by item and report each as pass / fail / unknown with
   the evidence. T-0004 is the reference failure: a 5m CHoCH the 30m had not confirmed (item 3), entry
   below the zone (item 4), stop just beyond the obvious swing (item 5), 20x on a 3.84% stop (item 6).
   Check the news filter (profile `news_filter`): no new entry within 1 hour before a red (high-impact) USD event on
   ForexFactory. If today's calendar is unknown, say so and ask the trader.
4. Reply in the §18 structure. Do not tell the trader whether to take it.
5. Later: update the same record to `open`, then `closed` (workflow A from step 2).

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

### I. A bug, corrupted data or a corrected reading
The trader asked to be told about every potential bug, in the terminal. The moment one is found:
1. Append an entry to `playbook/incidents.yaml` (next `INC-###`; area, severity, found_by, status, fix).
   A reading the trader corrects is a `data` incident found by `trader`.
2. Fix it, and add a test that fails without the fix. Never commit around a failing test.
3. Set `status: fixed` (or `guarded` when a check now blocks an external cause) and name the commit in `fix`.
   Never delete or reword a committed entry: status and fix may change, history may not.
4. Say so in the reply, plainly, with the incident ID.

## Hard rules

- `null` over a guess. Always. A plausible number is worse than a missing one.
- Charts shared in chat are not saved automatically. Record what you see in
  `evidence.observed`; ask the trader to commit the image if they want it kept.
- Canonical tags only (the validator rejects aliases and unknown tags).
- `./tj validate` must show 0 errors before every commit, and no `stale` warning: run `./tj build`
  after any knowledge-base change and commit `terminal.html` + `exports/kb.json` with it.
- `./tj audit` must pass before every commit. It recomputes every published number independently
  and checks kb.json, the terminal's embedded copy and every chart file. Never commit around it.
- When the trader states a rule that applies to trades already recorded, update those records too
  (a strategy clarification that leaves old trades contradicting it is corrupted data).
- Verify chart reads before recording them: calibrate on axis ticks (never on stacked label boxes),
  measure wicks with a tolerant detector, and record reads as "about" with the stated accuracy.
- Contradictions between the trader's rules and their own trades go into the strategy version's
  `open_questions` (INITIALIZATION step 11). Ask; never resolve them by assumption.
- Never promote, generalise or declare a winner beyond what `./tj` output supports.
  "Insufficient evidence" is a complete answer.
- Units: `*_pct` = percent (1.0 = 1%), `*_rate` = decimal (0.0005 = 5 bps).
- Never accept, store, or echo exchange API keys. If the trader offers them, decline and point to the
  `safety` list in `playbook/automation.yaml`: keys live only on the bot's server, trade-only, no withdrawals.
- No automation stage is skipped: the bot is built only after stage 1 of `./tj status` readiness is complete.
- Test before anything ships: run the full suite (`python3 -m unittest discover -s tests -t .`, which includes the
  headless-browser render of every tab) before every commit that touches `tradekb/`, `templates/` or `tests/`.
- Every bug found goes into `playbook/incidents.yaml` (workflow I). YAML duplicate keys are load errors.
- Leverage from `./tj size` must keep liquidation beyond the stop, not only inside the 50-60% margin aim.
- Commit every knowledge-base change and push to the session's working branch.
