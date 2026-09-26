# Trading Playbook

Consolidated knowledge (system prompt §27). Every entry must cite the evidence behind it:
trade IDs, n, and the `./tj` output it rests on. An entry without evidence does not belong
here; it belongs in a trade record's `evidence.hypotheses`.

Status: **INITIALIZATION.** 1 measured trade (T-0001), 1 missed (T-0002). Nothing below is established.

## Strategies

| Strategy | Version | Status | Measured trades | Expectancy (95% CI) |
|---|---|---|---:|---|
| supply-demand-structure | 1.1 | unvalidated | 1 (T-0001) | n=1: not computed (no CI below n=5) |

## Established rules
_None. Requires the promotion gate in `config.yaml`._

## Developing rules
_None._

## Hypotheses
_None._

## Avoid
_None._

## High-quality setups
_None._

## Execution errors
_None recorded. Source of truth: `./tj errors`._

## Risk rules
Stated by the trader (2026-09-26). These are the trader's rules, not performance findings.
- 1% of equity at risk per trade, always.
- Leverage is chosen from the stop distance (T-0001: 3.14% -> 10x). It does not change the 1% risk.
- Hold until TP; break-even and partials are barely used. Good R:R setups are hunted.
- Unresolved: margin mode, max leverage, daily loss limit, max open risk, fees (see `profile/trader.yaml`).

## Behavioural rules
_None._

## Change log
| Date | Change | Evidence |
|---|---|---|
| 2026-09-26 | Strategy `supply-demand-structure` v1.0 recorded from the trader's own statement | T-0001 |
| 2026-09-26 | v1.1 clarification (CHG-001): close-based structure, 1% risk, leverage use, hold-to-TP, red box, 4H execution. No rule changed | trader's statement |
