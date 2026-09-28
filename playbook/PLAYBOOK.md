# Trading Playbook

Consolidated knowledge (system prompt §27). Every entry must cite the evidence behind it:
trade IDs, n, and the `./tj` output it rests on. An entry without evidence does not belong
here; it belongs in a trade record's `evidence.hypotheses`.

Status: **INITIALIZATION.** 7 measured trades (T-0001, T-0003, T-0004, T-0006, T-0007, T-0009, T-0010), 1 missed
(T-0002), 2 not taken (T-0005, T-0008; counterfactual only). Overall (`./tj stats`): +1.72R expectancy, 95% CI [-0.20,
+3.38], n=7, LOW tier: the interval now includes zero. Seven trades cannot separate skill from luck. Nothing below is
established.

## Strategies

| Strategy | Version | Status | Measured trades | Expectancy (95% CI) |
|---|---|---|---:|---|
| supply-demand-structure | 1.13 | unvalidated | 6 (T-0001, T-0004, T-0006, T-0007, T-0009, T-0010) | n=6: +1.52R, 95% CI [-0.27, +3.41] (LOW) |
| key-level-sr | 1.5 | unvalidated | 1 (T-0003) | n=1: +2.94R, no CI below n=5 (LOW). Now scoped to day trading and swings; n=0 there |

## Established rules
_None. Requires the promotion gate in `config.yaml`._

## Developing rules
_None._

## Hypotheses
- **Top-down vs lower-timeframe-only.** The trader flags LTF-only entries as risky (T-0003) and names skipping the
  15m-30m as the cause of T-0004. Evidence (`./tj stats --by top_down`): n=2 without complete top-down (T-0003
  +2.94R, T-0004 -1.00R), n=2 with it (T-0006 +3.41R, T-0009 -1.00R: top-down done, but the 4h FVG it showed was
  ignored), T-0001 and T-0007 not recorded. T-0005 had it (+3.09R) but is a counterfactual and excluded. Test: `./tj compare top_down yes no`, from n=5 per side for an interval.
  Status: observation.
- **Target the strongest opposing level.** Now the trader's stated preference (v1.5 target model: "more
  preferable to hunt strongest levels"). Whether it pays is untested: T-0006's order was 66.10 (3.41R); the
  70.70 supply would have given about 4.75R (COUNTERFACTUAL, same 4h candle). n=1. Record both levels on
  future trades. Status: hypothesis (performance), rule (preference).
- **Counter-trend trades.** The trader calls T-0007 (short at ATH, bullish bias) risky but worth it for a very
  solid setup at 4.12R; graded like any other setup, "just a bit riskier" (2026-09-27). `./tj stats --by
  trend`: with-trend n=4 (+2.48R; T-0009 -1.00R added), counter-trend n=2 (T-0004 -1.00R, T-0007 +4.12R). The trend label is derived
  from the regime tag, so T-0004 counts as counter-trend against its bullish 30m regime. Far too few to
  compare. Status: observation.
- **A break inside the impulsive candle's range is consolidation, not a CH ("NOT CH").** Now a rule (v1.6
  checklist item 3). Evidence: T-0004 taken on a 5m break inside the 30m candle range, -1.00R (false_ch); T-0008
  a break inside the 4h candle range, recognised and skipped, -1.00R COUNTERFACTUAL. n=2 (1 realized). Whether
  the filter pays is untested. Status: rule (stated); hypothesis (performance).
- **Stop beyond the swing that created the confirmed CH.** Now a rule (v1.6 checklist item 5; trader: "yes
  exactly"). T-0006, T-0007 and T-0009 kept it; T-0004's stop sat beyond a high whose CH was never confirmed and was
  swept. How close: "just very close to that swing point or demand/supply level" (2026-09-28): 0.01-0.18% of price
  so far (T-0007, T-0009, T-0006). T-0009 shows its limit: a correct stop does not rescue a wrong location.
  Status: rule (stated).
- **Entry precision (heat on winners).** `./tj build` excursions: median MAE on winners 0.13R (worst 0.33R, n=4:
  T-0001 0.18R, T-0003 0.08R, T-0006 0.33R, T-0007 0.03R); the losers ran +0.28R (T-0004), +0.63R (T-0009) and +1.65R
  (T-0010) before their stops (median 0.63R). This measures the trader's "sniper entries" (S criterion). The trader's
  management is hold to TP; no break-even rule is proposed from n=3 losers. Descriptive only, n=7. Status: observation.
- **Valid setups still lose.** T-0010 (NEAR short, graded A, process 4.20/5) lost -1.00R to NEAR-specific bullish news
  after the entry, having run +1.65R first: loss type E, BAD OUTCOME / GOOD PROCESS. Keep the process. Status:
  observation (n=1).
- **Location before confirmation.** Both losses were "executed early" by the trader's own review: T-0004 before the
  30m confirmed, T-0009 before price reached a 4h zone ("price was in the middle of nowhere"). T-0009 had a real
  CH by close on the 1h and 4h, a structural stop and 2.99R, and still failed as a deviation above unmitigated 4h
  FVGs. `./tj errors`: early_execution x2 (-2.00R), below the recurring threshold of 3. Checklist items 1 and 4
  already encode it. Status: observation (n=2).
- **Fees on tight-stop scalps.** T-0003's stop was 0.239%. With HYPOTHETICAL fees of 0.02-0.05% per side, 2.94R
  gross becomes 2.38-1.78R net, below the 2.5R minimum, and fee-free sizing would really risk 1.17-1.42%.
  Answered (trader, 2026-09-27): fees are inside the 1% risk and will be counted separately by the bot.
  Status: parked until the bot stage (fee rates stay unresolved in the profile).

## Avoid
Rules the trader stated after T-0004 (2026-09-26). These are the trader's rules, not performance findings (n=1).
- Entering on a lower-timeframe CHoCH that the 15m-30m has not confirmed (strategy v1.3 checklist item 3).
- A stop beyond a swing whose CH is unconfirmed: that swing is liquidity (item 5; T-0004).
- Price in the middle of nowhere: no demand/supply level or key level at the entry, whatever the confluences
  ("it's more preferable not to execute", 2026-09-28; T-0009, -1.00R).
- A "CH" that breaks only an internal level of a candle range: NOT CH (item 3). T-0008 was skipped for this,
  and the drawn short would have lost 1R (COUNTERFACTUAL).
- Margin loss at the stop above 60%: the aim is 50-60%, margin call at 80% (trader, 2026-09-28). T-0004: 20x on a
  3.84% stop = 76.7% of margin (the aim was 13.03x to 15.63x); isolated liquidation about 0.013561 sat only 1.17x the
  stop distance away (`./tj show T-0004`).
- Leverage whose liquidation comes before the stop, even inside the 50-60% aim. On tight stops the maintenance
  margin decides: a 0.6% stop at 100x is exactly 60%, yet liquidates first above about 91x at a 0.5% maintenance
  rate (`./tj size --entry 100 --stop 99.4`). A tool finding, not a trade (INC-015); `./tj size` prints the cap.
- Entering at an inducement: "AVOID Inducements at all costs" (trader, 2026-09-27). Equal highs/lows are
  liquidity to be swept into the zone (T-0001), never the entry (strategy v1.4 checklist item 7).

## Zone quality (trader-stated, 2026-09-27; not performance findings)
- A supply/demand level is drawn where price created a CH, and is stronger with an FVG ("FVG + CH").
- Fresh beats mitigated: "high probability when it's not retested"; "the more a supply/demand level
  mitigates the weaker it becomes". The reverse of S/R levels and trendlines, where at least 3 reactions
  are preferred.
- A zone traded through and reclaimed with a CH is a reclaim level, not a mitigated zone (T-0006); T-0007's
  supply is the mitigation example (trader, 2026-09-27).
- The zone is the level that created the reversal/CH, not a sweep candle (T-0005, T-0007).

## Grading (trader-stated, 2026-09-27)
- Scale S, A, B, C, D. S, A and B are tradeable, C maybe, D avoided.
- S: proper confluences, clear confirmations, a sniper entry that runs to TP, and about 3.5R or more (a rough
  guide; slightly less is fine). T-0007 is S.
- A: a good setup executed well, one step short of S (T-0001: missed the extreme demand, took the reclaim;
  T-0006: TP short of the strongest level). C: taken without the full process, whatever the result (T-0003,
  1m only). D: "a poor trade + mistake"; a good setup executed early is a D (T-0004, 2026-09-28).
- B: "anything with decent RR but few confluences, which means it could be a risky execution" (2026-09-28). T-0009:
  "Setup B because of FVG ignorance but decent confirmations" (-1.00R).
- D vs B (2026-09-28): T-0004 is a D because it was executed on a 5m CH when the 30m showed no CH ("Poorly
  executed"); T-0009's CH was real, so the early execution made it a risky B, not a D.
- `./tj stats --by trader_grade`: S n=1 (+4.12R), A n=3 (+2.33R; T-0010 lost), B n=1 (-1.00R), C n=1 (+2.94R), D n=1
  (-1.00R). Far too few to say whether the grade predicts the result. Status: observation.

## High-quality setups
_None._

## Execution errors
_None recurring (threshold 3). Source of truth: `./tj errors`: early_execution x2 (T-0004, T-0009; -2.00R), ignored_htf,
stop_in_liquidity, excessive_leverage and false_ch x1 each (T-0004), ignored_fvg x1 (T-0009), skipped_top_down x1
(T-0003)._ Both losses are type C (execution errors) in the trader's own words. early_execution is one occurrence
from the recurring flag. The top-down rule was broken in both trades where it was recorded
(T-0003, T-0004; terminal Rule compliance). Watch item, not yet a pattern.

## Risk rules
Stated by the trader (2026-09-26). These are the trader's rules, not performance findings.
- 1% of equity at risk per trade, always.
- Isolated margin. Leverage is set from the stop distance: never above 60% of the margin lost at the stop, and never
  so high that liquidation comes before the stop. 50-60% is the aim, a preference: "the bot can use 20X leverage if
  invalidation is 0,6% ... we don't have to reach it to -60% at all costs" (2026-09-28). T-0006: 6.28% x 8x = 50.3%.
  Leverage does not change the 1% risk. The bot's exact choice (a 20x ceiling?) is the one open bot question.
- Minimum R:R 2.5 for the best target; 3.0 preferred.
- Hold until TP; break-even and partials are barely used. Good R:R setups are hunted.
- Fees are inside the 1% risk; the bot will count them separately (trader, 2026-09-27).
- The margin rule evolved: 50% (2026-09-26), 50% with 55% tolerated (2026-09-27), aim 50-60% (2026-09-28). `./tj`
  flags a breach only above 60%. Leverage caps are always shown rounded down.
- No daily stop, no pause after losses, no cap on open trades: "there's no stopping we stick to the plan. only
  1% risk we ignore frequency. there's no pause" (trader, 2026-09-27). No correlation cap: "we take every valid
  setup, bad days will happen either way" (2026-09-28). No fixed leverage cap: leverage follows the stop distance.
- News: no new entries and no resting orders from 1 hour before to 1 hour after a red (high-impact) USD event on
  ForexFactory; open trades are kept (2026-09-27/28). Otherwise 24/7: "we trade 24/7 regardless".
- Entries after a CH: the limit goes at the zone on the longest timeframe possible (T-0007: the 4h); candle size is
  not a criterion ("Ignore small and weak candles"). An unfilled limit is cancelled when price reaches the TP first.
- Split entries (2026-09-28): up to 3 limits, 1% / 0.5% each / 0.3% each, one stop and one target. The stop is
  reached only after every order fills, so a full stop costs 0.9% (-0.9R); 1 of 3 filled at 3R = +0.9R (R on the full
  1%). Results count in USDT as well as R. Leverage: the first order's stop x leverage must not exceed 60%, and the
  same leverage goes on every order (6% stop -> 10x). `./tj size --add-entry` computes it all.
- Timeframes for swing and day trading: 1D-4h bias, 1h-30m levels and confirmations, 4h execution only for great
  setups (T-0006, T-0007).
- Bot: MEXC USDT-margined perpetuals BTC_USDT, ETH_USDT, HYPE_USDT for now; day trading and swings, no scalps for
  now. The malfunction guard is mandatory (G1-G9 in `playbook/automation.yaml`, shown in the Health tab) and never
  halts the bot: it blocks or repairs the faulty action, and every issue is reported as an error with an explanation so
  a fix can be found. Every entry and exit sends a trade alert by Telegram and email (execution analysis, prices, risk in
  USDT, leverage, setup type). Key-level setups on day/swing timeframes target at least 2.5R, further when possible.
- Unresolved: fee rates, maintenance-margin rate, account equity (see `profile/trader.yaml`). Base currency: USDT.

## Behavioural rules
_None._

## Change log
| Date | Change | Evidence |
|---|---|---|
| 2026-09-28 | T-0010 NEARUSD short -1.00R (supply_level, 1h, grade A, loss type E: NEAR news). supply-demand-structure v1.13 (CHG-013): macro news in the trade's direction as a confluence; T-0010 is an A that lost. Bot question on reading release results | T-0010 chart; trader's review |
| 2026-09-28 | supply-demand-structure v1.12 (CHG-012): the 50-60% aim is a preference; split entries take the first order's leverage (at most 60% on its stop) for every order. key-level-sr v1.5 (CHG-005): day/swing target at least 2.5R, further when possible. Bot: alerts by Telegram and email, errors reported with an explanation, no halts. No strategy questions open | trader's answers |
| 2026-09-28 | supply-demand-structure v1.11 (CHG-011): why T-0004 is D; no trade in the middle of nowhere; split fills, R unit (+0.9R for 1 of 3 at 3R) and leverage policy. key-level-sr v1.4 (CHG-004): scoped to day trading and swings (no scalps for now); one open question on its targets there | trader's answers |
| 2026-09-28 | Bot spec: USDT perpetuals on MEXC, trade alerts on entry and exit, no halts (the guard blocks or repairs the faulty action). Split-entry sizing corrected: the margin rule applies to the full position (INC-019); journal R for split trades in the trader's unit | trader's answers; tests |
| 2026-09-28 | supply-demand-structure v1.10 clarification (CHG-010): candle size is not an entry criterion ("Ignore small and weak candles"); split entries of up to 3 limits (1% / 0.5% each / 0.3% each, one stop and target; `tj size --add-entry`); the 1h as a detail timeframe; stops "just very close" to the swing or level; T-0009 is the B example. No rule changed | trader's answers; T-0009 |
| 2026-09-28 | T-0009 TIAUSDT long -1.00R (reclaim, 1h, grade B, loss type C: early execution, FVG ignored). T-0006 execution re-recorded 4h with the 1h as detail (INC-017). T-0004's entered_before_confirmation replaced by the trader's own term early_execution | T-0009 charts; trader's answers |
| 2026-09-28 | supply-demand-structure v1.9 clarification (CHG-009): grade B; T-0004 is the D example; 1D-4h bias and 1h-30m levels for swing/day trading; candles after a CH read on the longest timeframe; optional split limit entries; margin aim 50-60%; news window 1h before to 1h after with resting orders cancelled. No rule changed | trader's answers |
| 2026-09-28 | key-level-sr v1.3 clarification (CHG-003): the account-wide 50-60% margin aim and news window restated; T-0003's 0.239% stop cannot reach the aim before liquidation (209.6x needed, liquidation first above 135.2x) | trader's answers; `./tj build` exposure |
| 2026-09-28 | T-0004 corrected: grade D, setup valid, loss type D -> C, entered_before_confirmation added, rescored (setup 2 -> 4, execution 2 -> 1) | trader's correction (INC-014) |
| 2026-09-28 | Bot specification: pairs BTC/ETH/HYPE, 24/7, no correlation cap, mandatory malfunction guard G1-G9; incident log and Health tab; YAML loader refuses duplicate keys (INC-013) | trader's answers; tool fixes |
| 2026-09-27 | supply-demand-structure v1.8 clarification (CHG-008): grades A, C, D with the trader's examples; entry timing after a CH and the limit-cancel rule; no daily stop / pause / open-trade cap; news filter (checklist item 8). No rule changed | trader's answers; T-0001, T-0003, T-0006 graded |
| 2026-09-27 | Automation plan: venue MEXC; the safety list no longer assumes a daily kill switch (the trader has none); a malfunction guard is proposed as open question 5 | trader's answers |
| 2026-09-27 | supply-demand-structure v1.7 clarification (CHG-007): grading scale S-D (3.5R S guide is rough; D avoided, C maybe); the candle range is read on the HTF (a 1h pullback inside a 4h candle range is not a 4h pullback). No rule changed | trader's answers; T-0008 |
| 2026-09-27 | MAE / MFE recorded for every closed trade (fills.worst_price / best_price); the terminal shows heat and run per trade | T-0001, T-0003, T-0004, T-0006, T-0007 |
| 2026-09-27 | supply-demand-structure v1.6 clarification (CHG-006): 4H candle range / NOT CH rule (item 3), stop beyond the swing that created the confirmed CH (item 5), S grading (3.5R+), counter-trend graded normally, reclaim is not mitigation, zones are reversal/CH origins, bearish continuation close rule. No rule changed | T-0008 (avoided); trader's answers |
| 2026-09-27 | Records corrected: T-0004 stop/leverage confirmed and false_ch added; T-0006 not mitigated (setup 4 -> 5); T-0005 zone origin; T-0007 item 5 passes | trader's answers |
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
