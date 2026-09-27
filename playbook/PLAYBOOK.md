# Trading Playbook

Consolidated knowledge (system prompt §27). Every entry must cite the evidence behind it:
trade IDs, n, and the `./tj` output it rests on. An entry without evidence does not belong
here; it belongs in a trade record's `evidence.hypotheses`.

Status: **INITIALIZATION.** 5 measured trades (T-0001, T-0003, T-0004, T-0006, T-0007), 1 missed (T-0002), 1 not
taken (T-0005, counterfactual only). Overall (`./tj stats`): +2.81R expectancy, 95% CI [+0.81, +4.16], n=5, LOW
tier. Five trades cannot separate skill from luck. Nothing below is established.

## Strategies

| Strategy | Version | Status | Measured trades | Expectancy (95% CI) |
|---|---|---|---:|---|
| supply-demand-structure | 1.5 | unvalidated | 4 (T-0001, T-0004, T-0006, T-0007) | n=4: +2.77R point estimate, no CI below n=5 (LOW) |
| key-level-sr | 1.2 | unvalidated | 1 (T-0003) | n=1: +2.94R, no CI below n=5 (LOW) |

## Established rules
_None. Requires the promotion gate in `config.yaml`._

## Developing rules
_None._

## Hypotheses
- **Top-down vs lower-timeframe-only.** The trader flags LTF-only entries as risky (T-0003) and names skipping the
  15m-30m as the cause of T-0004. Evidence (`./tj stats --by top_down`): n=2 without complete top-down (T-0003
  +2.94R, T-0004 -1.00R), n=1 with it (T-0006 +3.41R), T-0001 not recorded. T-0005 had it (+3.09R) but is a
  counterfactual and excluded. Test: `./tj compare top_down yes no`, from n=5 per side for an interval.
  Status: observation.
- **Target the strongest opposing level.** Now the trader's stated preference (v1.5 target model: "more
  preferable to hunt strongest levels"). Whether it pays is untested: T-0006's order was 66.10 (3.41R); the
  70.70 supply would have given about 4.75R (COUNTERFACTUAL, same 4h candle). n=1. Record both levels on
  future trades. Status: hypothesis (performance), rule (preference).
- **Counter-trend trades.** The trader calls T-0007 (short at ATH, bullish bias) risky but worth it for a very
  solid setup at 4.12R. `./tj stats --by trend`: with-trend n=3 (+3.64R), counter-trend n=2 (T-0004 -1.00R,
  T-0007 +4.12R). The trend label is derived from the regime tag, so T-0004 counts as counter-trend against
  its bullish 30m regime. Far too few to compare. Status: observation.
- **A 5m CHoCH the 30m has not confirmed is consolidation, not a reversal.** Trader's diagnosis of T-0004; the
  chart agrees (the 22:30 fill sat inside the bullish 22:00 30m candle). n=1. Now a rule in v1.3 (clarification,
  trader-stated), so later trades test it. Status: hypothesis.
- **Stops just beyond an obvious swing get swept before the move.** T-0004: stop 0.013478 above the 0.013447 spike
  high, swept to about 0.013813, then the valid short formed there (T-0005). n=1. Status: hypothesis.
- **Fees on tight-stop scalps.** T-0003's stop was 0.239%. With HYPOTHETICAL fees of 0.02-0.05% per side, 2.94R
  gross becomes 2.38-1.78R net, below the 2.5R minimum, and fee-free sizing would really risk 1.17-1.42%.
  Answered (trader, 2026-09-27): fees are inside the 1% risk and will be counted separately by the bot.
  Status: parked until the bot stage (fee rates stay unresolved in the profile).

## Avoid
Rules the trader stated after T-0004 (2026-09-26). These are the trader's rules, not performance findings (n=1).
- Entering on a lower-timeframe CHoCH that the 15m-30m has not confirmed (strategy v1.3 checklist item 3).
- A stop just beyond the obvious swing where the liquidity rests: the valid entry forms there (item 5).
- Margin loss at the stop beyond the tolerance: target 50%, fine up to about 55%, margin call at 80% (trader,
  2026-09-27). T-0004: 20x on a 3.84% stop = 76.7% of margin (13.03x for the target, 14.33x at most);
  isolated liquidation about 0.013561 sat only 1.17x the stop distance away (`./tj show T-0004`).
- Entering at an inducement: "AVOID Inducements at all costs" (trader, 2026-09-27). Equal highs/lows are
  liquidity to be swept into the zone (T-0001), never the entry (strategy v1.4 checklist item 7).

## Zone quality (trader-stated, 2026-09-27; not performance findings)
- A supply/demand level is drawn where price created a CH, and is stronger with an FVG ("FVG + CH").
- Fresh beats mitigated: "high probability when it's not retested"; "the more a supply/demand level
  mitigates the weaker it becomes". The reverse of S/R levels and trendlines, where at least 3 reactions
  are preferred.
- Open: does a zone traded through, reclaimed and retested (T-0006) count as fresh? (v1.4 question 9)

## High-quality setups
_None._

## Execution errors
_None recurring (threshold 3). Source of truth: `./tj errors`: ignored_htf, stop_in_liquidity and excessive_leverage
x1 each (T-0004), skipped_top_down x1 (T-0003)._ The top-down rule was broken in both trades where it was recorded
(T-0003, T-0004; terminal Rule compliance). Watch item, not yet a pattern.

## Risk rules
Stated by the trader (2026-09-26). These are the trader's rules, not performance findings.
- 1% of equity at risk per trade, always.
- Isolated margin. Leverage is capped so the loss on margin at the stop stays within 50%:
  leverage <= 50 / stop %. T-0001: 3.14% x 10x = 31.4%. Leverage does not change the 1% risk.
- Minimum R:R 2.5 for the best target; 3.0 preferred.
- Hold until TP; break-even and partials are barely used. Good R:R setups are hunted.
- Fees are inside the 1% risk; the bot will count them separately (trader, 2026-09-27).
- Isolated margin: aim for 50% of margin lost at the stop, up to about 55% is fine, margin call at 80% (trader,
  2026-09-27). `./tj` flags a breach only beyond 55%. Leverage caps are always shown rounded down.
- Unresolved: max leverage, daily loss limit, max open risk, fee rates (see `profile/trader.yaml`).

## Behavioural rules
_None._

## Change log
| Date | Change | Evidence |
|---|---|---|
| 2026-09-27 | supply-demand-structure v1.5 clarification (CHG-005): 30m potential CH (close beyond the previous opposite candle), strongest-level target preferred, divergence on wicks, no fixed tolerance for equal highs/lows, margin rule 50% target / 55% tolerance, entry models supply_level / demand_level, counter-trend context. No rule changed | trader's answers; T-0006, T-0007 |
| 2026-09-27 | key-level-sr v1.2 clarification (CHG-002): what counts as a reaction (rejection, break-retest-continue, or deviation) | trader's answer |
| 2026-09-27 | T-0006 corrected: the order was 66.10 (not 62.64); risk rescored 4 -> 5 under the clarified margin rule | trader's correction |
| 2026-09-27 | supply-demand-structure v1.4 clarification (CHG-004): zones drawn from CH + FVG, fresh beats mitigated, inducements avoided (checklist item 7), divergence types, 4h zone with 1h execution. No rule changed | trader's answers; T-0006 |
| 2026-09-27 | key-level-sr v1.1 clarification (CHG-001): at least 3 reactions for S/R and trendlines; scalp top-down 30m-1h, 15m, 1m-5m; LTF point-of-interest target; fees inside the 1%. T-0003 duration corrected to 24 min | trader's answers; T-0003 |
| 2026-09-26 | v1.3 clarification (CHG-003): 15m-30m confirms a lower-timeframe CHoCH; stop beyond the zone, not the obvious swing; pre-entry checklist; new supply from a liquidity sweep as a short entry. No performance claim | T-0004 (trader's review), T-0005 (counterfactual) |
| 2026-09-26 | Strategy `supply-demand-structure` v1.0 recorded from the trader's own statement | T-0001 |
| 2026-09-26 | New strategy `key-level-sr` v1.0 (unvalidated): key S/R, reclaim-retest-accept / deviation-retest | T-0003 |
| 2026-09-26 | Top Down Analysis recorded as the trader's analysis method (profile `process.top_down`) | trader's statement |
| 2026-09-26 | v1.2 clarification (CHG-002): stop placement, red-box definition, 50% margin-loss leverage rule, min R:R 2.5, shorts mirror longs. No rule changed | trader's statement |
| 2026-09-26 | v1.1 clarification (CHG-001): close-based structure, 1% risk, leverage use, hold-to-TP, red box, 4H execution. No rule changed | trader's statement |
