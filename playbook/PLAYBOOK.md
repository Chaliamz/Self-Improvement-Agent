# Trading Playbook

Consolidated knowledge (system prompt §27). Every entry must cite the evidence behind it:
trade IDs, n, and the `./tj` output it rests on. An entry without evidence does not belong
here; it belongs in a trade record's `evidence.hypotheses`.

Status: **INITIALIZATION.** 10 measured trades (T-0001, T-0003, T-0004, T-0006, T-0007, T-0009, T-0010, T-0012, T-0013,
T-0014), 3 missed (T-0002; T-0015 and T-0016, the BERA examples), 3 not taken (T-0005, T-0008, T-0011; counterfactual only). Overall (`./tj stats`): +2.08R
expectancy, 95% CI [+0.41, +3.74], profit factor 6.21, n=10, LOW tier. The interval sat at [-0.20, +3.38] at n=7: a few
trades move it a lot. Ten trades cannot separate skill from luck. Nothing below is established.

## Strategies

| Strategy | Version | Status | Measured trades | Expectancy (95% CI) |
|---|---|---|---:|---|
| supply-demand-structure | 1.24 | unvalidated | 9 (T-0001, T-0004, T-0006, T-0007, T-0009, T-0010, T-0012, T-0013, T-0014) | n=9: +1.99R, 95% CI [+0.14, +3.85] (LOW) |
| key-level-sr | 1.6 | unvalidated | 1 (T-0003) | n=1: +2.94R, no CI below n=5 (LOW). Now scoped to day trading and swings; n=0 there |

## Established rules
_None. Requires the promotion gate in `config.yaml`._

## Developing rules
_None._

## Hypotheses
- **Top-down vs lower-timeframe-only.** The trader flags LTF-only entries as risky (T-0003) and names skipping the
  15m-30m as the cause of T-0004. Evidence (`./tj stats --by top_down`): n=2 without complete top-down (T-0003
  +2.94R, T-0004 -1.00R: +0.97R), n=5 with it (+2.24R, 95% CI [-0.18, +4.66]: T-0006 +3.41R, T-0009 -1.00R with the 4h
  FVG it showed ignored, T-0010 -1.00R, T-0012 +6.68R, T-0013 +3.11R, the trader's worked example from the weekly),
  T-0001 and T-0007 not recorded. T-0005 had it (+3.09R) but is a counterfactual and excluded. Test: `./tj compare top_down yes no`, from n=5 per side for an interval.
  Status: observation.
- **Target the strongest opposing level.** Now the trader's stated preference (v1.5 target model: "more
  preferable to hunt strongest levels"). Whether it pays is untested: T-0006's order was 66.10 (3.41R); the
  70.70 supply would have given about 4.75R (COUNTERFACTUAL, same 4h candle). T-0012's order was the first opposing
  supply (6.68R); the 0.0561 high above it filled two days later after a dip that stayed 4.6R in profit (about 9.34R,
  COUNTERFACTUAL), and the trader's 4h supply/FVG at 0.06471 on Aug 22 (17.03R, COUNTERFACTUAL). n=2, single paths.
  Inside the opposing zone: "its ideal the tp to go at the far edge, it depends also the RR" (2026-10-13, v1.17);
  T-0013's TP sat at the near edge (3.11R; the far edge 3.32R). Status: hypothesis (performance), rule (preference).
- **Partial profit with a break-even runner (NOT adopted).** The trader's idea on T-0012: 50% at the TP, the stop to
  break-even, the rest to the next level ("speculation for now, so we don't change any plans ... remind me in case we
  moved in that way until I give you the green", 2026-10-13). Evidence is collected per winner: did the next level fill
  before price returned to entry? T-0012: yes (about 11.85R instead of 6.68R, COUNTERFACTUAL). T-0013: undecided at the
  screenshot (price back to about 82,900, not to entry; the 84,315 resistance not reached). n=1 decided. Remind the
  trader as it grows; the trader decides. Status: hypothesis.
- **Counter-trend trades.** The trader calls T-0007 (short at ATH, bullish bias) risky but worth it for a very
  solid setup at 4.12R; graded like any other setup, "just a bit riskier" (2026-09-27). `./tj stats --by
  trend`: with-trend n=7 (+2.67R, 95% CI [+0.74, +4.54]), counter-trend n=3 (+0.71R: T-0004 -1.00R, T-0007 +4.12R,
  T-0014 -1.00R, "we went against the trend so it had potential risk"). The trend label is derived from the regime tag,
  so T-0004 counts as counter-trend against its bullish 30m regime. Three trades cannot be compared with seven.
  A 4h CH needs no 1D confirmation ("It's not necessary but you can definitely have a look on 1D as well"); aligned
  multi-timeframe CHs are "a valid one" (2026-10-17). Against the daily the zone decides the grade: T-0015 (BERA, fresh
  demand with extra data) is A, T-0014 (a retested zone that failed mid-range) was B ("we had extra data + demand didnt
  get tested", 2026-10-19). Status: observation.
- **A break inside the impulsive candle's range is consolidation, not a CH ("NOT CH", "fake CH").** Now a rule
  (checklist item 3). Evidence: T-0004 taken on a 5m break inside the 30m candle range, -1.00R (false_ch); T-0008 a
  break inside the 4h candle range, skipped, -1.00R COUNTERFACTUAL; T-0011 a 30m CH inside the 1h range (about
  82,579-85,220), skipped, -1.00R COUNTERFACTUAL. n=3 (1 realized). Counterfactuals are excluded from statistics, so
  whether the filter pays is untested. Status: rule (stated); hypothesis (performance).
- **Avoiding inducement: the limit at the origin demand, beyond the equal lows.** T-0012 (graded S, +6.68R): a 4H
  CH, then the untested 1H demand that created it; the 1H equal lows above it (about 0.0463-0.0465) were swept on the
  way down and the buy limit sat below them, at the demand. The trader's S criteria: "CH+DEMAND+ Avoiding inducement +
  Very good RR". T-0001 (AAVE, +4.57R) also had equal lows as the inducement, and T-0013 avoided the $$ liquidity lines.
  T-0015 (BERA long, missed, graded A): the equal lows of Sep 21-24 above an unmitigated demand, swept on Sep 29 into
  it; the limit at 0.2101 reached the 0.2453 target within a day (+5.87R COUNTERFACTUAL).
  `./tj stats --by setup`: inducement n=2, both winners. Far too few; the rule itself ("AVOID Inducements at all costs")
  is the trader's. Status: rule (stated); hypothesis (performance).
- **Liquidity forming before a CH points to the retest.** T-0016 (BERA short, missed, graded S): equal highs about
  0.2402/0.2407 formed under the 1H supply before and after the Oct 8 bearish CH, were swept into the supply on Oct
  14-15, and the short from 0.2482 reached the 0.1734 key level by Oct 17 (+3.92R COUNTERFACTUAL). The trader: "These
  data are extremely important so keep them in mind." With T-0012 mirrored, n=2 (1 measured). Status: rule (stated);
  hypothesis (performance).
- **Targets at key levels built by many retests; the next liquidity as the swing target.** T-0016's target was the
  0.1735 level retested from both sides through Aug 22-Sep 16 (plus a deviation); the $$ lows beneath it (about
  0.162-0.171) the swing target. Target clarity is why the trader grades it S over the higher-R long (A). Status: rule
  (stated); hypothesis (performance).
- **Pullback after a CH.** Now a rule (v1.17 market_structure): the move back into the zone that created the CH is the
  pullback, not a counter CH, while the low that formed the demand and the reversal holds; the stop goes below that
  low (trader, 2026-10-13, on T-0012). n=1 example. Status: rule (stated).
- **Entry at a fresh lower-timeframe zone without a lower-timeframe CH.** After the HTF CH: T-0012 (a limit at the 1H
  demand, +6.68R) and T-0013 (a 30M breaker block + FVG at the reclaimed 4h support, +3.11R). A lower-timeframe CH
  used as the trigger still needs the 15m-30m (T-0004). n=2, both winners. The breaker block, in the trader's words
  (2026-10-14): "the mini pullback which created inside the zone, went lower and then reversed higher forming an FVG";
  T-0013's chart shows exactly that (the Oct 8 19:00 30m up-candle, the 20:00 low, the 21:00 reversal and its FVG).
  Status: rule (stated); hypothesis (performance).
- **Front-run cancel.** T-0011: price ran about 3.4R toward the target without retesting the 30m supply, and the
  trader cancelled the limit. Under the older cancel-at-TP rule it would have filled in the Sep 30 15:30 spike and
  been stopped within about 10 minutes (-1.00R COUNTERFACTUAL). The 15:30 release (PCE, GDP) was red (trader,
  2026-10-13), so the news rule alone would also have cancelled it at 14:30. The trigger (2026-10-13): "the bot should
  trigger the cancel when we identify a CH but price doesn't make the retest to continue its trend"; on the previous low
  (2026-10-14): the bot cancels only when price makes a new low beyond the previous low before the retest ("The ideal
  option would be b when price makes new low so it's likely for price to get invalidated"; a new low by the close
  rule). On T-0011 no 30m candle closed below the 82,882 CH low, so under that rule the limit stays and the news rule
  is what cancels it at 14:30. n=1.
- **Stop beyond the swing that created the confirmed CH.** Now a rule (v1.6 checklist item 5; trader: "yes
  exactly"). T-0006, T-0007 and T-0009 kept it; T-0004's stop sat beyond a high whose CH was never confirmed and was
  swept. How close: "just very close to that swing point or demand/supply level" (2026-09-28): 0.01-0.18% of price
  so far (T-0007, T-0009, T-0006). T-0009 shows its limit: a correct stop does not rescue a wrong location.
  T-0014: the stop sat about 0.5 above the swing before the breakdown, which were also the circled equal highs; a spike
  to about 165.7 took them and the stop, and price fell to about 153.47, below the entry, the next day (+1.09R
  COUNTERFACTUAL had the stop survived). The trader: those retest highs were not equal highs ("we couldnt do anything");
  with real equal highs above a short, "be careful of a potential liquidity sweep/deviation or placing our SL above swing
  highs" (2026-10-17). The default (2026-10-19): with equal highs/lows at the trade, "wait for sweep, deviating price
  and we enter on the retest". The tolerance for "equal" is a bot parameter calibrated from the trader's $$ marks (0.2%
  apart counted, BERA; 0.56% did not, AAVE). Status: rule (stated).
- **A sweep is not a signal; the reversal after it is.** "Just because a level gets swept doesn't mean anything. For
  example when equal lows get swept and price fails to reverse (has no power) it can be a continuation to the downside
  so setup gets invalidated and any levels close to them are getting failed" (2026-10-20). The examples reversed from
  the zone after the sweep: T-0012 (measured, +6.68R), T-0015 and T-0016 (missed, COUNTERFACTUAL). No recorded trade
  shows the no-power case yet (n=0). Open: whether resting limits beyond equal highs/lows stay, since they fill before a
  reversal can show, and how the bot measures the reversal (v1.24 open questions). Status: rule (stated).
- **After a zone fails, trade the extremes.** "My main entries after our loss at T-0014 would be either our supply level
  above or last demand below" (2026-10-17): on AAVE the red supply about 179.6-182.8 (stop above the about 187.1 equal
  highs, 4.52R to 140.69) or the demand about 135.2-140.4, not the failed 157.36-160.26 zone. n=1 (T-0014). Status: rule
  (stated).
- **Entry precision (heat on winners).** `./tj build` excursions: median MAE on winners 0.24R, worst 0.38R (n=6: T-0001
  0.18R, T-0003 0.08R, T-0006 0.33R, T-0007 0.03R, T-0012 0.38R, T-0013 0.31R); the losers ran +0.28R (T-0004), +0.63R
  (T-0009), +1.65R (T-0010) and +0.46R (T-0014) before their stops (median 0.54R). This measures the trader's "sniper
  entries" (S criterion). No winner has gone 0.4R against yet. Descriptive only, n=10. Status: observation.
- **Drawdown planning (outlook).** `./tj build` Monte Carlo, 100 trades x 2,000 paths from the 10 measured trades. As
  sampled: median worst drawdown 4.0R (95%: 7.0R), losing streak 4 (95%: 7). At the low win rate the sample still
  allows (31%, 95% Wilson bound; +0.61R per trade with the +4.14R average win): drawdown 10.0R (95%: 18.7R, about 19% of
  equity at 1% risk, not compounded), losing streak 10 (95%: 16), and 0.5% of runs end below zero. The average win rests
  on 6 winners, one of them +6.68R: a smaller real average win pulls the low scenario toward zero. Plan for the second
  scenario, not the first. Status: risk planning figure (n=10), not a forecast.
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
- S also (2026-10-10): "CH+DEMAND+ Avoiding inducement + Very good RR" (T-0012, 6.68R).
- A also (2026-10-13): "our data was good enough to execute with confirmations and our reward was 3,11" (T-0013).
- B also (2026-10-16): "even though we had solid confirmations and good RR we went against the trend" (T-0014, -1R).
- `./tj stats --by trader_grade`: S n=2 (+5.40R: T-0007, T-0012), A n=4 (+2.52R; T-0010 lost), B n=2 (-1.00R each: T-0009,
  T-0014; the skipped B, T-0011, would also have lost 1R, COUNTERFACTUAL), C n=1 (+2.94R), D n=1 (-1.00R). Every B so far
  has lost, which matches the trader's own definition ("it could be a risky execution"), but n=2 measured says nothing
  yet. Status: observation.

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
  Leverage does not change the 1% risk. Ceiling 20x (trader_rule, 2026-10-13): "we should stick to the maximum of 20X
  leverage for safety reasons, that's obviously for tight stops with low % of invalidation". Before it the only ceiling
  was the 60% rule, which allowed 85x on T-0011's 0.447% stop with liquidation inside the Sep 30 spike. The bot's
  default: the highest whole number within 60%, at most 20x and with liquidation at least 1.5x the stop distance away
  (6% stop -> 10x; 0.6% stop -> 20x); lower is always allowed (`./tj size` prints it; guard G3 refuses above 20x).
- Minimum R:R 2.5 for the best target; 3.0 preferred.
- Hold until TP; break-even and partials are barely used. Good R:R setups are hunted.
- Fees are inside the 1% risk; the bot will count them separately (trader, 2026-09-27).
- The margin rule evolved: 50% (2026-09-26), 50% with 55% tolerated (2026-09-27), aim 50-60% (2026-09-28). `./tj`
  flags a breach only above 60%. Leverage caps are always shown rounded down.
- No daily stop, no pause after losses, no cap on open trades: "there's no stopping we stick to the plan. only
  1% risk we ignore frequency. there's no pause" (trader, 2026-09-27). No correlation cap: "we take every valid
  setup, bad days will happen either way" (2026-09-28). Leverage follows the stop distance, never above 20x.
- News: no new entries and no resting orders from 1 hour before to 1 hour after a red (high-impact) USD event on
  ForexFactory; open trades are kept (2026-09-27/28). Otherwise 24/7: "we trade 24/7 regardless".
- Entries after a CH: the limit goes at the zone on the longest timeframe possible (T-0007: the 4h); candle size is
  not a criterion ("Ignore small and weak candles"). An unfilled limit is cancelled when price reaches the TP first.
- Split entries (2026-09-28): up to 3 limits, 1% / 0.5% each / 0.3% each, one stop and one target. The stop is
  reached only after every order fills, so a full stop costs 0.9% (-0.9R); 1 of 3 filled at 3R = +0.9R (R on the full
  1%). Results count in USDT as well as R. Leverage: the first order's stop x leverage must not exceed 60%, and the
  same leverage goes on every order (6% stop -> 10x). `./tj size --add-entry` computes it all.
- Timeframes for swing and day trading: 1D-4h bias, 1h-30m levels and confirmations, 4h execution only for great
  setups (T-0006, T-0007). Top Down Analysis from the weekly (T-0013): 1W trend and CH, 1D levels, 4H support range
  and demand, 1H/30M confirmation and execution. Premium and discount on the weekly swing's Fib ("yes exactly",
  2026-10-14): above 0.5, day trades (swings only with extra confirmations, "its risky"); 0.618 / 0.786 / 0.886, swings
  ("61.8-78.6-88.6 we can focus on swings as well"). The Fib sits on the weekly swing points (wick low to wick high):
  BTC 57,733.48 to 87,318.63, so 0.5 = 72,526.06, 0.618 = 69,035.01, 0.786 = 64,064.70, 0.886 = 61,106.19.
- Support/resistance is a range, not a single price: "it's a range depending on how much price reacts" (2026-10-13).
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
| 2026-10-20 | supply-demand-structure v1.24 (CHG-025, clarification): a sweep of equal highs/lows is not a signal on its own, a reversal must follow; a sweep with no reversal ("has no power") is continuation, the setup is invalidated and nearby levels fail; entries follow the trader's examples (T-0012, T-0015, T-0016). Open: whether resting limits beyond equal highs/lows stay, and how the bot measures the reversal | trader's statement |
| 2026-10-19 | supply-demand-structure v1.23 (CHG-024, clarification): with equal highs/lows at the trade, wait for the sweep and the deviation and enter on the retest; against the daily, a fresh zone with extra data can grade A (T-0015) where a retested, failed zone grades B (T-0014). The equal-highs tolerance becomes a bot parameter to calibrate. No strategy question open | trader's answers |
| 2026-10-18 | T-0015 BERAUSDT long (missed, A, +5.87R COUNTERFACTUAL) and T-0016 BERAUSDT short (missed, S, +3.92R COUNTERFACTUAL), the trader's teaching examples drawn after the outcome. supply-demand-structure v1.22 (CHG-023, clarification): inducement avoidance, liquidity before a CH as the sign of a retest, key-level and swing targets, target clarity as an S criterion. Open: the equal-highs tolerance (about 0.2%?) and how much going against the daily costs in the grade | T-0015/T-0016 charts; trader's notes |
| 2026-10-17 | supply-demand-structure v1.21 (CHG-022, clarification): a 4h CH needs no 1D confirmation; equal highs/lows near the stop; after a zone fails, the entries are the supply above or the demand below; an S/R line is a zone, not a price. T-0014: entry 158.67 confirmed, loss type A confirmed, supply-level confluence added; price fell to about 153.47 after the stop. Open: how the bot recognises equal highs | trader's answers; Oct 17 chart |
| 2026-10-16 | T-0014 AAVEUSD short -1.00R (a failed 4h demand retested from below, counter-trend, grade B, loss type A on the trader's assessment). supply-demand-structure v1.20 (CHG-021, clarification): T-0014 as a B and counter-trend example; two open questions (the fake-CH scope for a 4h CH against the HTF bias; a stop just beyond equal highs). Entry price asked (158.67 tool vs 159.89 cyan line) | T-0014 charts; trader's review |
| 2026-10-14 | supply-demand-structure v1.19 (CHG-020, clarification): the bot's front-run cancel is a new low beyond the previous low (close rule); the premium/discount Fib sits on the weekly swing points (BTC 57,733.48 to 87,318.63). No strategy question open; stage 1 criterion "open strategy questions" met | trader's answers; weekly chart |
| 2026-10-14 | supply-demand-structure v1.18 (CHG-019, clarification): the breaker block defined (mini pullback inside the zone, a move below it, a reversal through it leaving an FVG; matches T-0013's chart), premium/discount on the weekly Fib with swings at 0.618 / 0.786 / 0.886, the trader's front-run answer. T-0012: the exit at 10:30 confirmed. T-0013: the other position tools were testing samples. Two strategy questions open (the front-run reading, the Fib anchors) | trader's answers; T-0013 chart |
| 2026-10-13 | T-0013 BTCUSD long +3.11R (30M breaker block + FVG at the reclaimed 4h support after the 1D/1W CH, grade A; the worked Top Down Analysis). supply-demand-structure v1.17: CHG-017 (clarifications: front-run trigger, pullback after a CH, TP at the far edge, top-down from the weekly, premium -> day trading, S/R as a range, the breaker-block entry, the pending limit; T-0013 as an A) and CHG-018 (trader_rule: a 20x leverage ceiling); key-level-sr v1.6 (CHG-006, the same ceiling). T-0011: the Sep 30 release was red. T-0012: filled at 13:00 (MAE 0.38R), 20x, Aug 14 not red; exit time asked. Partial/break-even runner recorded as a hypothesis, not adopted. New change kind trader_rule; the leverage ceiling enforced by tj size, the bot default, the validator, the audit and the terminal. INC-021 caught | trader's answers; T-0013 charts; tests |
| 2026-10-10 | T-0012 OPNUSDT long +6.68R (demand_level, 4H CH, 1H demand below an equal-lows inducement, grade S). supply-demand-structure v1.16 (CHG-016): checklist item 1 names the 1h-30m zone after the HTF CH; T-0012 is the S and inducement example; open questions 2 (pullback or bearish CH) and 3 (TP inside the opposing zone). New tag avoided_inducement. Trade records can carry open questions, shown in Data gaps and `./tj status` | T-0012 charts; trader's review; tests |
| 2026-09-30 | T-0011 BTCUSD short not taken (fake CH on the 30m; front run cancelled), -1.00R COUNTERFACTUAL. supply-demand-structure v1.15 (CHG-015): HTF (4H-1D) CH first, fake CH, front-run cancel, leverage from the invalidation %. New tags: cancelled_front_run; fake_ch as an alias of false_ch. Bot question on leverage for tight stops | T-0011 charts; trader's review |
| 2026-09-28 | supply-demand-structure v1.14 (CHG-014): macro release results are the trader's call, not a bot input; the 60% margin rule is the only leverage ceiling. Bot default leverage recorded. T-0010: the CPI printed at 15:30 UTC+3, about 2 hours after the fill. Terminal: more statistics, a two-scenario 100-trade outlook, weekday breakdown, five new backgrounds | trader's answers; tests |
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
