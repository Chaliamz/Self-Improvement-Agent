# Trading Playbook

Consolidated knowledge (system prompt §27). Every entry must cite the evidence behind it:
trade IDs, n, and the `./tj` output it rests on. An entry without evidence does not belong
here; it belongs in a trade record's `evidence.hypotheses`.

Status: **INITIALIZATION.** 3 measured trades (T-0001, T-0003, T-0004), 1 missed (T-0002), 1 not taken
(T-0005, counterfactual only). Nothing below is established.

## Strategies

| Strategy | Version | Status | Measured trades | Expectancy (95% CI) |
|---|---|---|---:|---|
| supply-demand-structure | 1.3 | unvalidated | 2 (T-0001, T-0004) | n=2: +1.79R point estimate, no CI below n=5 |
| key-level-sr | 1.0 | unvalidated | 1 (T-0003) | n=1: not computed (no CI below n=5) |

## Established rules
_None. Requires the promotion gate in `config.yaml`._

## Developing rules
_None._

## Hypotheses
- **Top-down vs lower-timeframe-only.** The trader flags LTF-only entries as risky (T-0003) and names skipping the
  15m-30m as the cause of T-0004. Evidence (`./tj stats --by top_down`): n=2 without complete top-down (T-0003
  +2.94R, T-0004 -1.00R), n=0 measured with it (T-0001 not recorded). T-0005 had it (+3.09R) but is a
  counterfactual and excluded. Test: `./tj compare top_down yes no`, from n=5 per side for an interval.
  Status: observation.
- **A 5m CHoCH the 30m has not confirmed is consolidation, not a reversal.** Trader's diagnosis of T-0004; the
  chart agrees (the 22:30 fill sat inside the bullish 22:00 30m candle). n=1. Now a rule in v1.3 (clarification,
  trader-stated), so later trades test it. Status: hypothesis.
- **Stops just beyond an obvious swing get swept before the move.** T-0004: stop 0.013478 above the 0.013447 spike
  high, swept to about 0.013813, then the valid short formed there (T-0005). n=1. Status: hypothesis.
- **Fees on tight-stop scalps.** T-0003's stop was 0.239%. With HYPOTHETICAL fees of 0.02-0.05% per side, 2.94R
  gross becomes 2.38-1.78R net, below the 2.5R minimum, and fee-free sizing would really risk 1.17-1.42%.
  The trader's actual fees are unknown. Status: open question (key-level-sr v1.0, question 4).

## Avoid
Rules the trader stated after T-0004 (2026-09-26). These are the trader's rules, not performance findings (n=1).
- Entering on a lower-timeframe CHoCH that the 15m-30m has not confirmed (strategy v1.3 checklist item 3).
- A stop just beyond the obvious swing where the liquidity rests: the valid entry forms there (item 5).
- Leverage above 50 / stop %. T-0004: 20x on a 3.84% stop = 76.7% of margin (max 13.0x); isolated liquidation
  about 0.013561 sat only 1.17x the stop distance away (`./tj show T-0004`).

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
- Unresolved: max leverage, daily loss limit, max open risk, fees (see `profile/trader.yaml`).

## Behavioural rules
_None._

## Change log
| Date | Change | Evidence |
|---|---|---|
| 2026-09-26 | v1.3 clarification (CHG-003): 15m-30m confirms a lower-timeframe CHoCH; stop beyond the zone, not the obvious swing; pre-entry checklist; new supply from a liquidity sweep as a short entry. No performance claim | T-0004 (trader's review), T-0005 (counterfactual) |
| 2026-09-26 | Strategy `supply-demand-structure` v1.0 recorded from the trader's own statement | T-0001 |
| 2026-09-26 | New strategy `key-level-sr` v1.0 (unvalidated): key S/R, reclaim-retest-accept / deviation-retest | T-0003 |
| 2026-09-26 | Top Down Analysis recorded as the trader's analysis method (profile `process.top_down`) | trader's statement |
| 2026-09-26 | v1.2 clarification (CHG-002): stop placement, red-box definition, 50% margin-loss leverage rule, min R:R 2.5, shorts mirror longs. No rule changed | trader's statement |
| 2026-09-26 | v1.1 clarification (CHG-001): close-based structure, 1% risk, leverage use, hold-to-TP, red box, 4H execution. No rule changed | trader's statement |
