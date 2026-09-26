# Trading Playbook

Consolidated knowledge (system prompt §27). Every entry must cite the evidence behind it:
trade IDs, n, and the `./tj` output it rests on. An entry without evidence does not belong
here; it belongs in a trade record's `evidence.hypotheses`.

Status: **INITIALIZATION.** 2 measured trades (T-0001, T-0003), 1 missed (T-0002). Nothing below is established.

## Strategies

| Strategy | Version | Status | Measured trades | Expectancy (95% CI) |
|---|---|---|---:|---|
| supply-demand-structure | 1.2 | unvalidated | 1 (T-0001) | n=1: not computed (no CI below n=5) |
| key-level-sr | 1.0 | unvalidated | 1 (T-0003) | n=1: not computed (no CI below n=5) |

## Established rules
_None. Requires the promotion gate in `config.yaml`._

## Developing rules
_None._

## Hypotheses
- **Top-down vs lower-timeframe-only.** The trader flags LTF-only entries as risky (T-0003). Evidence: n=1 without
  top-down, n=0 with. Test: `./tj compare top_down yes no`, from n=5 per side for an interval. Status: observation.
- **Fees on tight-stop scalps.** T-0003's stop was 0.239%. With HYPOTHETICAL fees of 0.02-0.05% per side, 2.94R
  gross becomes 2.38-1.78R net, below the 2.5R minimum, and fee-free sizing would really risk 1.17-1.42%.
  The trader's actual fees are unknown. Status: open question (key-level-sr v1.0, question 4).

## Avoid
_None._

## High-quality setups
_None._

## Execution errors
_None recurring. Source of truth: `./tj errors` (skipped_top_down x1, T-0003)._

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
| 2026-09-26 | Strategy `supply-demand-structure` v1.0 recorded from the trader's own statement | T-0001 |
| 2026-09-26 | New strategy `key-level-sr` v1.0 (unvalidated): key S/R, reclaim-retest-accept / deviation-retest | T-0003 |
| 2026-09-26 | Top Down Analysis recorded as the trader's analysis method (profile `process.top_down`) | trader's statement |
| 2026-09-26 | v1.2 clarification (CHG-002): stop placement, red-box definition, 50% margin-loss leverage rule, min R:R 2.5, shorts mirror longs. No rule changed | trader's statement |
| 2026-09-26 | v1.1 clarification (CHG-001): close-based structure, 1% risk, leverage use, hold-to-TP, red box, 4H execution. No rule changed | trader's statement |
