"""Position sizing and exposure decomposition for LINEAR (quote-margined) contracts and spot.

Units
  prices, money ........ quote currency
  quantity ............. base units
  *_pct arguments ...... PERCENT      (1.0 = 1%)
  *_rate arguments ..... DECIMAL      (0.0005 = 5 bps)

Inverse (coin-margined) contracts are NOT supported: their PnL is non-linear in
price and every formula below would be wrong for them.

Liquidation prices are single-tier approximations that ignore fees, funding and
tiered maintenance margin. The exchange's displayed liquidation price is
authoritative; these exist to catch the structural error of a stop sitting
beyond liquidation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal

CRITICAL, WARN, NOTE = "CRITICAL", "WARN", "NOTE"


def margin_status(margin_loss_pct: float | None, limit: float | None, aim_min: float | None = None) -> str | None:
    """The trader's isolated-margin rule: "always aim for 50-60% at the stop" (2026-09-28). Above `limit`%
    of the posted margin lost at the stop is a breach. Below `aim_min`% is not a risk problem (the loss is
    still the 1% risk; more margin is posted and liquidation sits further away), only short of the aim.
    Returns breach | within | below_aim, or None when the loss or the rule is unknown."""
    if margin_loss_pct is None or limit is None:
        return None
    if margin_loss_pct > limit + 1e-9:
        return "breach"
    return "below_aim" if aim_min is not None and margin_loss_pct < aim_min - 1e-9 else "within"


def max_leverage_liq_beyond_stop(entry: float, stop: float, mmr_rate: float, buffer: float = 1.0) -> float:
    """Highest isolated leverage whose liquidation sits at least `buffer` x the stop distance from entry.

    From liquidation_price(): the liquidation distance as a fraction of entry is (1/L - mmr) / (1 - mmr) for a
    long and (1/L - mmr) / (1 + mmr) for a short. Setting it >= buffer x stop fraction gives
    L <= 1 / (mmr + buffer x stop fraction x (1 -/+ mmr)). The margin rule alone does not guarantee this: at
    a 0.6% stop, 100x is exactly 60% of margin, yet a 0.5% maintenance rate liquidates first (at ~91x)."""
    _require_positive("entry", entry)
    _require_positive("stop", stop)
    side = infer_side(entry, stop)
    frac = abs(entry - stop) / entry
    return 1 / (mmr_rate + buffer * frac * ((1 - mmr_rate) if side == "long" else (1 + mmr_rate)))


def default_leverage(caps: list[float | None]) -> int | None:
    """The bot's default leverage: the highest whole number under every cap (the 60% margin rule, liquidation kept
    1.5x the stop distance away). Lower is always allowed (trader, 2026-09-28: "we don't have to reach it to -60% at
    all costs"; "Ceiling should be 60% so we should avoid margin calls (80%)")."""
    live = [c for c in caps if c is not None]
    if not live:
        return None
    return max(1, math.floor(min(live) + 1e-9))


def fmt_cap(leverage: float) -> str:
    """A leverage ceiling for display, floored to 0.01x: rounding up would print a value that breaks the rule."""
    return f"{math.floor(leverage * 100 + 1e-9) / 100:.2f}x"


@dataclass(frozen=True)
class SizingInput:
    entry: float
    stop: float
    risk_amount: float
    side: str | None = None
    equity: float | None = None
    leverage: float | None = None
    margin_mode: str = "isolated"
    mmr_rate: float = 0.005
    fee_rate: float = 0.0
    slippage_pct: float = 0.0
    qty_step: float | None = None
    targets: tuple[float, ...] = ()
    max_risk_pct: float | None = None
    max_leverage: float | None = None
    max_margin_loss_pct: float | None = None   # isolated: max loss on posted margin at the stop, percent (breach above)
    margin_loss_aim_min_pct: float | None = None    # lower edge of the leverage aim (trader: "aim for 50-60% at the stop")
    min_rr: float | None = None                # minimum reward:risk (gross) for the best target
    fee_share_warn: float = 0.20
    liq_buffer_warn: float = 1.5


@dataclass
class TargetRR:
    price: float
    rr_gross: float
    rr_net: float


@dataclass
class SizingResult:
    side: str
    qty: float
    qty_unrounded: float
    notional: float
    stop_fill: float
    stop_distance_pct: float
    per_unit_loss: float
    fee_per_unit: float
    loss_at_stop: float
    risk_pct: float | None
    effective_leverage: float | None
    margin_required: float | None
    liquidation: float | None
    liq_to_stop_ratio: float | None
    margin_loss_pct: float | None               # loss at stop as % of posted margin (= stop % x leverage, fees incl.)
    max_leverage_for_rule: float | None         # highest leverage that keeps margin loss within the limit
    targets: list[TargetRR]
    flags: list[tuple[str, str]] = field(default_factory=list)
    min_leverage_for_aim: float | None = None        # lowest leverage that reaches the aim's lower edge
    max_leverage_liq_beyond_stop: float | None = None  # isolated: highest leverage whose liquidation stays beyond the stop
    default_leverage: int | None = None              # the bot's choice: highest whole number within the rule and the buffer


def infer_side(entry: float, stop: float) -> str:
    if stop < entry:
        return "long"
    if stop > entry:
        return "short"
    raise ValueError("entry equals stop: stop distance is zero, position size is undefined")


def floor_to_step(qty: float, step: float) -> float:
    """Round DOWN to the exchange step. Down, never nearest: rounding up would exceed the risk budget."""
    steps = (Decimal(repr(qty)) / Decimal(repr(step))).to_integral_value(rounding=ROUND_FLOOR)
    return float(steps * Decimal(repr(step)))


def liquidation_price(entry: float, side: str, qty: float, *, leverage: float | None,
                      margin_mode: str, mmr_rate: float, equity: float | None = None) -> float | None:
    """Approximate liquidation price, or None if not computable / not reachable.

    isolated: margin = qty*entry/L;  liquidate when margin + PnL = mmr * qty * price
    cross:    whole equity backs this single position (assumes no other positions)
    """
    if margin_mode == "isolated":
        if not leverage:
            return None
        if side == "long":
            price = entry * (1 - 1 / leverage) / (1 - mmr_rate)
        else:
            price = entry * (1 + 1 / leverage) / (1 + mmr_rate)
    elif margin_mode == "cross":
        if not equity or qty <= 0:
            return None
        if side == "long":
            price = (entry - equity / qty) / (1 - mmr_rate)
        else:
            price = (entry + equity / qty) / (1 + mmr_rate)
    else:
        raise ValueError("margin_mode must be isolated or cross")
    return price if price > 0 else None


def _require_positive(name: str, value: float | None, optional: bool = False) -> None:
    if value is None and optional:
        return
    if value is None or value <= 0:
        raise ValueError(f"{name} must be > 0 (got {value})")


def size_position(inp: SizingInput) -> SizingResult:
    _require_positive("entry", inp.entry)
    _require_positive("stop", inp.stop)
    _require_positive("risk_amount", inp.risk_amount)
    _require_positive("equity", inp.equity, optional=True)
    _require_positive("leverage", inp.leverage, optional=True)
    _require_positive("qty_step", inp.qty_step, optional=True)
    if not 0 <= inp.mmr_rate < 1:
        raise ValueError("mmr_rate is a decimal in [0, 1), e.g. 0.005 for 0.5%")
    if inp.fee_rate < 0 or inp.slippage_pct < 0:
        raise ValueError("fee_rate and slippage_pct cannot be negative")
    if inp.margin_mode not in ("isolated", "cross"):
        raise ValueError("margin_mode must be isolated or cross")

    side = infer_side(inp.entry, inp.stop)
    if inp.side and inp.side != side:
        where = "below" if inp.side == "long" else "above"
        raise ValueError(f"stop {inp.stop} is on the wrong side of entry {inp.entry}: "
                         f"a {inp.side} stop must be {where} entry")

    flags: list[tuple[str, str]] = []
    if inp.fee_rate > 0.01:
        flags.append((WARN, f"fee_rate {inp.fee_rate} is above 1% per side: fee_rate is a DECIMAL "
                            f"(0.0005 = 5 bps), not a percent"))

    slip = inp.slippage_pct / 100.0
    stop_fill = inp.stop * (1 - slip) if side == "long" else inp.stop * (1 + slip)
    fee_per_unit = inp.fee_rate * (inp.entry + stop_fill)
    per_unit_loss = abs(inp.entry - stop_fill) + fee_per_unit

    qty_raw = inp.risk_amount / per_unit_loss
    qty = floor_to_step(qty_raw, inp.qty_step) if inp.qty_step else qty_raw
    if qty <= 0:
        flags.append((CRITICAL, f"risk budget {inp.risk_amount:,.2f} is smaller than one quantity step "
                                f"({inp.qty_step}) at this stop distance: the trade cannot be sized within risk"))

    loss_at_stop = qty * per_unit_loss
    notional = qty * inp.entry
    stop_distance_pct = abs(inp.entry - inp.stop) / inp.entry * 100

    fee_share = fee_per_unit / per_unit_loss
    if fee_share > inp.fee_share_warn:
        flags.append((WARN, f"fees are {fee_share:.0%} of the loss at stop: the stop is tight relative to "
                            f"round-trip cost, so net R:R is materially below gross"))

    risk_pct = effective_leverage = None
    if inp.equity:
        risk_pct = loss_at_stop / inp.equity * 100
        effective_leverage = notional / inp.equity
        if inp.max_risk_pct is not None and risk_pct > inp.max_risk_pct + 1e-9:
            flags.append((CRITICAL, f"loss at stop is {risk_pct:.2f}% of equity, above your max "
                                    f"{inp.max_risk_pct}% per trade"))

    loss_pct_of_notional = per_unit_loss / inp.entry * 100
    max_leverage_for_rule = (inp.max_margin_loss_pct / loss_pct_of_notional
                             if inp.max_margin_loss_pct is not None else None)
    aim = inp.margin_loss_aim_min_pct
    min_leverage_for_aim = aim / loss_pct_of_notional if aim is not None and inp.max_margin_loss_pct is not None else None
    max_leverage_liq = (max_leverage_liq_beyond_stop(inp.entry, stop_fill, inp.mmr_rate)
                        if inp.margin_mode == "isolated" else None)
    margin_loss_pct = loss_pct_of_notional * inp.leverage if inp.leverage else None
    status = margin_status(margin_loss_pct, inp.max_margin_loss_pct, aim)
    if status == "breach":
        flags.append((CRITICAL, f"loss at stop is {margin_loss_pct:.1f}% of the posted margin, above your "
                                f"{inp.max_margin_loss_pct:g}% limit: use {fmt_cap(max_leverage_for_rule)} or less"))
    elif status == "below_aim":
        flags.append((NOTE, f"loss at stop is {margin_loss_pct:.1f}% of the posted margin, below your {aim:g}-"
                            f"{inp.max_margin_loss_pct:g}% aim, which is not required (trader: 'we don't have to reach it "
                            f"to -60% at all costs'). The loss at the stop is the same; more margin is posted"))
    if (max_leverage_liq is not None and min_leverage_for_aim is not None
            and max_leverage_liq < min_leverage_for_aim):
        flags.append((NOTE, f"the {aim:g}-{inp.max_margin_loss_pct:g}% aim needs {min_leverage_for_aim:.2f}x, but "
                            f"liquidation reaches the stop above {fmt_cap(max_leverage_liq)} (maintenance rate "
                            f"{inp.mmr_rate}): stay at or below {fmt_cap(max_leverage_liq)}. The aim is not required "
                            f"(trader: 'we don't have to reach it to -60% at all costs')"))

    margin_required = None
    if inp.leverage:
        margin_required = notional / inp.leverage
        if inp.equity and margin_required > inp.equity:
            flags.append((CRITICAL, f"margin required {margin_required:,.2f} exceeds equity "
                                    f"{inp.equity:,.2f}: the order would be rejected or is larger than intended"))
        if inp.max_leverage is not None and inp.leverage > inp.max_leverage:
            flags.append((WARN, f"leverage setting {inp.leverage:g}x is above your max {inp.max_leverage:g}x"))
        if inp.margin_mode == "isolated" and inp.mmr_rate >= 1 / inp.leverage:
            flags.append((CRITICAL, f"{inp.leverage:g}x isolated with maintenance rate {inp.mmr_rate} "
                                    f"liquidates at or before entry"))

    liq = None
    liq_ratio = None
    if qty > 0 and (inp.leverage or inp.margin_mode == "cross"):
        liq = liquidation_price(inp.entry, side, qty, leverage=inp.leverage, margin_mode=inp.margin_mode,
                                mmr_rate=inp.mmr_rate, equity=inp.equity)
    if liq is not None:
        stop_dist = abs(inp.entry - stop_fill)
        liq_ratio = abs(inp.entry - liq) / stop_dist
        beyond_stop = liq >= stop_fill if side == "long" else liq <= stop_fill
        if beyond_stop:
            flags.append((CRITICAL, f"liquidation (~{liq:,.6g}) is reached BEFORE the stop ({stop_fill:,.6g}): "
                                    f"the stop cannot protect this position. Lower leverage or add margin."))
        elif liq_ratio < inp.liq_buffer_warn:
            flags.append((WARN, f"liquidation is only {liq_ratio:.2f}x the stop distance from entry: "
                                f"a wick, gap or fee drag can liquidate before the stop fills"))

    targets = []
    for tp in inp.targets:
        _require_positive("target", tp)
        if (side == "long" and tp <= inp.entry) or (side == "short" and tp >= inp.entry):
            raise ValueError(f"target {tp} is not on the profit side of entry {inp.entry} for a {side}")
        gross = abs(tp - inp.entry) / abs(inp.entry - inp.stop)
        net = (abs(tp - inp.entry) - inp.fee_rate * (inp.entry + tp)) / per_unit_loss
        targets.append(TargetRR(tp, gross, net))
    if inp.min_rr is not None and targets and max(t.rr_gross for t in targets) < inp.min_rr:
        flags.append((WARN, f"best target gives {max(t.rr_gross for t in targets):.2f}R, below your "
                            f"{inp.min_rr:g}R minimum"))

    return SizingResult(side, qty, qty_raw, notional, stop_fill, stop_distance_pct, per_unit_loss,
                        fee_per_unit, loss_at_stop, risk_pct, effective_leverage, margin_required,
                        liq, liq_ratio, margin_loss_pct, max_leverage_for_rule, targets, flags,
                        min_leverage_for_aim=min_leverage_for_aim, max_leverage_liq_beyond_stop=max_leverage_liq,
                        default_leverage=default_leverage([max_leverage_for_rule, max_leverage_liq_beyond_stop(
                            inp.entry, stop_fill, inp.mmr_rate, inp.liq_buffer_warn) if inp.margin_mode == "isolated" else None]))


@dataclass
class SplitFill:
    orders: int                  # how many limit orders have filled (in fill order)
    avg_entry: float
    qty: float
    notional: float
    loss_at_stop: float          # incl. fees, like size_position
    stop_distance_pct: float     # from the average entry
    margin_loss_pct: float | None
    liquidation: float | None    # isolated, at the given leverage
    survives_to: float           # the next order's price, or the stop once every order has filled
    liq_first: bool | None       # liquidation comes before `survives_to`
    rr: list[float]              # gross R:R per target, from the average entry


@dataclass
class SplitPlan:
    side: str
    entries: list[float]         # in fill order: the first order price reaches comes first
    order_risk: float            # money at risk per order
    order_qty: list[float]
    fills: list[SplitFill]
    max_leverage_first_order: float | None     # THE RULE: the first order's stop x leverage within the limit
    min_leverage_first_order_aim: float | None # the aim's lower edge on the first order (a preference, not required)
    max_leverage_full_fill: float | None       # margin limit on the full position (implied by the first-order rule)
    max_leverage_liq: float                    # liquidation behind every next order and the stop
    flags: list[tuple[str, str]] = field(default_factory=list)
    default_leverage: int | None = None        # the bot's choice: first-order rule and a 1.5x liquidation buffer at every step


def split_plan(entries: list[float], stop: float, order_risk: float, *, leverage: float | None = None,
               mmr_rate: float = 0.005, fee_rate: float = 0.0, max_margin_loss_pct: float | None = None,
               margin_loss_aim_min_pct: float | None = None, targets: tuple[float, ...] = (),
               min_rr: float | None = None, liq_buffer: float = 1.5) -> SplitPlan:
    """Split limit entries sharing one stop and one target (trader, 2026-09-28: up to 3 orders; 1 = 1%, 2 = 0.5% each,
    3 = 0.3% each). Each order is sized from its own risk share, and fills merge into ONE isolated position with ONE
    leverage setting.

    Leverage rule (trader, 2026-09-28): "our first limit order must not exceed 60%. if invalidation is 6% we can get
    10X leverage. since we used 10X leverage on first order, we are going to use the same leverage on the rest." The
    first order's stop is the widest, so the full position stays inside the limit too. The stop sits beyond every
    order, so price reaches it only after every order has filled ("it's impossible to hit SL when only 1 of 3 orders
    filled"). Liquidation is checked at every step: a partly filled position must survive until price reaches the
    next order, and the full position until the stop."""
    if not entries:
        raise ValueError("split_plan needs at least one entry")
    _require_positive("stop", stop)
    _require_positive("order_risk", order_risk)
    for e in entries:
        _require_positive("entry", e)
    sides = {infer_side(e, stop) for e in entries}
    if len(sides) > 1:
        raise ValueError("split entries sit on both sides of the stop: one stop cannot serve them all")
    side = sides.pop()
    order = sorted(entries, reverse=(side == "long"))
    if len(set(order)) != len(order):
        raise ValueError("two split orders at the same price: merge them into one")
    for t in targets:
        if (side == "long" and t <= order[0]) or (side == "short" and t >= order[0]):
            raise ValueError(f"target {t} is not on the profit side of the first entry {order[0]} for a {side}")
    per_unit = [abs(e - stop) + fee_rate * (e + stop) for e in order]
    qtys = [order_risk / u for u in per_unit]
    fills: list[SplitFill] = []
    caps: list[float] = []
    buffered: list[float] = []
    for n in range(1, len(order) + 1):
        q = sum(qtys[:n]); notional = sum(qq * e for qq, e in zip(qtys[:n], order[:n]))
        avg = notional / q
        loss = sum(qq * u for qq, u in zip(qtys[:n], per_unit[:n]))
        nxt = order[n] if n < len(order) else stop
        caps.append(max_leverage_liq_beyond_stop(avg, nxt, mmr_rate))
        buffered.append(max_leverage_liq_beyond_stop(avg, nxt, mmr_rate, liq_buffer))
        mloss = loss * leverage / notional * 100 if leverage else None
        liq = liquidation_price(avg, side, q, leverage=leverage, margin_mode="isolated", mmr_rate=mmr_rate) if leverage else None
        first = None if liq is None else (liq >= nxt if side == "long" else liq <= nxt)
        rr = [abs(t - avg) / abs(avg - stop) for t in targets]
        fills.append(SplitFill(n, avg, q, notional, loss, abs(avg - stop) / avg * 100, mloss, liq, nxt, first, rr))
    full = fills[-1]
    full_loss_pct = full.loss_at_stop / full.notional * 100          # loss at the stop as % of notional, fees included
    first_loss_pct = per_unit[0] / order[0] * 100
    full_cap = max_margin_loss_pct / full_loss_pct if max_margin_loss_pct is not None else None
    first_cap = max_margin_loss_pct / first_loss_pct if max_margin_loss_pct is not None else None
    first_aim = (margin_loss_aim_min_pct / first_loss_pct
                 if margin_loss_aim_min_pct is not None and first_cap is not None else None)
    liq_cap = min(caps)
    flags: list[tuple[str, str]] = []
    if leverage:
        first_loss = first_loss_pct * leverage
        if max_margin_loss_pct is not None and first_loss > max_margin_loss_pct + 1e-9:
            flags.append((CRITICAL, f"the first order's stop x {leverage:g}x = {first_loss:.1f}% of the margin, above your "
                                    f"{max_margin_loss_pct:g}% limit for the first order: use {fmt_cap(first_cap)} or less "
                                    f"for every order"))
        bad = [f.orders for f in fills if f.liq_first]
        if bad:
            flags.append((CRITICAL, f"liquidation comes before the next order or the stop with {', '.join(map(str, bad))} order(s) "
                                    f"filled: use {fmt_cap(liq_cap)} or less"))
    if min_rr is not None and targets and max(fills[0].rr) < min_rr - 1e-9:
        flags.append((WARN, f"if only the first order fills, the best target gives {max(fills[0].rr):.2f}R, below your {min_rr:g}R minimum"))
    return SplitPlan(side, order, order_risk, qtys, fills, first_cap, first_aim, full_cap, liq_cap, flags,
                     default_leverage([first_cap, *buffered]))


def exposure(entry: float, stop: float, risk_pct: float | None, leverage: float | None = None,
             margin_mode: str | None = None, mmr_rate: float = 0.005,
             max_margin_loss_pct: float | None = None, margin_loss_aim_min_pct: float | None = None) -> dict:
    """Equity-free exposure decomposition for a trade that risks a fixed % of equity.

    Everything is a percentage of equity, so it works without knowing the account size:
      notional % = risk % / stop % x 100      effective leverage = notional % / 100
      margin %   = notional % / leverage       (fees ignored: unknown for recorded trades)
    Liquidation is computed for isolated margin only (cross needs equity and other positions);
    when margin_mode is unknown the isolated figure is returned and flagged as an assumption.
    """
    side = infer_side(entry, stop)
    stop_pct = abs(entry - stop) / entry * 100
    out: dict = {"side": side, "stop_pct": stop_pct}
    if max_margin_loss_pct is not None:
        out["max_leverage_for_rule"] = max_margin_loss_pct / stop_pct
        if margin_loss_aim_min_pct is not None:
            out["min_leverage_for_aim"] = margin_loss_aim_min_pct / stop_pct
        if margin_mode in (None, "isolated"):
            liq_cap = max_leverage_liq_beyond_stop(entry, stop, mmr_rate)
            out["max_leverage_liq"] = liq_cap                            # above this, liquidation comes before the stop
            out["max_leverage_safe"] = min(out["max_leverage_for_rule"], liq_cap)
            out["liq_binds"] = liq_cap < out["max_leverage_for_rule"]
    notional_pct = None
    if risk_pct:
        notional_pct = risk_pct / stop_pct * 100
        out["notional_pct"] = notional_pct
        out["effective_leverage"] = notional_pct / 100
    if leverage:
        out["margin_loss_pct"] = stop_pct * leverage          # the trader's own calc: fee-free
        if max_margin_loss_pct is not None:
            status = margin_status(out["margin_loss_pct"], max_margin_loss_pct, margin_loss_aim_min_pct)
            out["margin_loss_breach"] = status == "breach"           # above the limit (60%)
            out["margin_loss_below_aim"] = status == "below_aim"     # under the aim's lower edge: not a risk breach
        if notional_pct is not None:
            out["margin_pct"] = notional_pct / leverage
        if margin_mode in (None, "isolated"):
            liq = liquidation_price(entry, side, 1.0, leverage=leverage, margin_mode="isolated", mmr_rate=mmr_rate)
            out["liq_mode_assumed"] = margin_mode is None
            out["liq_isolated"] = liq
            if liq is not None:
                out["liq_distance_pct"] = abs(entry - liq) / entry * 100
                out["liq_to_stop"] = abs(entry - liq) / abs(entry - stop)
                out["liq_before_stop"] = liq >= stop if side == "long" else liq <= stop
    return out
