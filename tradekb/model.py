"""Per-trade derivations: R multiple, outcome, process grade. Pure functions.

R precedence (first available wins, and the source is always reported):
  1. result.r                         -- stated by the trader
  2. PnL / initial risk               -- net, account-level (captures fees and sizing errors)
  3. price-based from exits           -- size-free, GROSS of fees

Initial risk precedence:
  1. risk.risk_amount                 -- the trader's defined 1R
  2. |entry - initial stop| x size
  3. risk.risk_pct x account_equity / 100

Using the stated 1R means an oversized trade that loses shows as worse than -1R.
That is intended: it makes the sizing error visible in the numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean
from typing import Any

from .store import dig

REALIZED = "closed"
COUNTERFACTUAL = frozenset({"missed", "not_taken"})
DIMENSIONS = ("setup", "context", "execution", "risk", "management")

OUTCOME_WORD = {"win": "GOOD OUTCOME", "loss": "BAD OUTCOME", "breakeven": "NEUTRAL OUTCOME"}
PROCESS_WORD = {"good": "GOOD PROCESS", "mixed": "MIXED PROCESS", "poor": "POOR PROCESS"}


def num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def side_sign(t: dict) -> int | None:
    return {"long": 1, "short": -1}.get(t.get("direction"))


def entry_price(t: dict) -> float | None:
    avg = num(dig(t, "fills.entry_avg"))
    return avg if avg is not None else num(dig(t, "plan.entry"))


def position_size(t: dict) -> float | None:
    size = num(dig(t, "risk.size"))
    if size is not None:
        return size
    notional, entry = num(dig(t, "risk.notional")), entry_price(t)
    if notional is not None and entry:
        return notional / entry
    return None


def resolved_exits(t: dict) -> list[tuple[float, float | None]] | None:
    """-> [(price, qty_or_None)], or None if any exit lacks a price."""
    raw = dig(t, "fills.exits", [])
    if not isinstance(raw, list) or not raw:
        return None
    size = position_size(t)
    out = []
    for ex in raw:
        if not isinstance(ex, dict) or num(ex.get("price")) is None:
            return None
        qty = num(ex.get("qty"))
        if qty is None and num(ex.get("fraction")) is not None and size is not None:
            qty = num(ex.get("fraction")) * size
        out.append((num(ex["price"]), qty))
    return out


def initial_risk(t: dict) -> tuple[float | None, str | None]:
    stated = num(dig(t, "risk.risk_amount"))
    if stated is not None and stated > 0:
        return stated, "stated risk_amount"
    entry, stop, size = entry_price(t), num(dig(t, "plan.stop")), position_size(t)
    if entry is not None and stop is not None and size and entry != stop:
        return abs(entry - stop) * size, "size x stop distance"
    equity, pct = num(dig(t, "risk.account_equity")), num(dig(t, "risk.risk_pct"))
    if equity and pct:
        return equity * pct / 100.0, "risk_pct x equity"
    return None, None


def computed_risk(t: dict) -> float | None:
    """|entry - stop| x size, ignoring any stated figure. Used to audit stated risk."""
    entry, stop, size = entry_price(t), num(dig(t, "plan.stop")), position_size(t)
    if entry is None or stop is None or not size:
        return None
    return abs(entry - stop) * size


def realized_pnl(t: dict) -> tuple[float | None, str | None]:
    stated = num(dig(t, "result.pnl"))
    if stated is not None:
        return stated, "stated pnl"
    sign, entry, exits = side_sign(t), entry_price(t), resolved_exits(t)
    if sign is None or entry is None or not exits or any(q is None for _, q in exits):
        return None, None
    gross = sum(sign * (price - entry) * qty for price, qty in exits)
    fees = num(dig(t, "fills.fees")) or 0.0
    return gross - fees, "from exits net of fills.fees"


def price_r(t: dict) -> float | None:
    sign, entry, stop, exits = side_sign(t), entry_price(t), num(dig(t, "plan.stop")), resolved_exits(t)
    if sign is None or entry is None or stop is None or entry == stop or not exits:
        return None
    if len(exits) == 1:
        avg_exit = exits[0][0]
    elif all(q is not None and q > 0 for _, q in exits):
        total = sum(q for _, q in exits)
        avg_exit = sum(p * q for p, q in exits) / total
    else:
        return None
    return sign * (avg_exit - entry) / abs(entry - stop)


def r_multiple(t: dict) -> tuple[float | None, str | None]:
    stated = num(dig(t, "result.r"))
    if stated is not None:
        return stated, "stated"
    pnl, _ = realized_pnl(t)
    risk, risk_src = initial_risk(t)
    if pnl is not None and risk:
        return pnl / risk, f"pnl / {risk_src}"
    pr = price_r(t)
    if pr is not None:
        return pr, "price-based from exits (gross of fees)"
    return None, None


def missing_for_r(t: dict) -> list[str]:
    need = []
    if side_sign(t) is None:
        need.append("direction")
    if entry_price(t) is None:
        need.append("plan.entry or fills.entry_avg")
    if num(dig(t, "plan.stop")) is None:
        need.append("plan.stop")
    if resolved_exits(t) is None and num(dig(t, "result.pnl")) is None:
        need.append("fills.exits[].price or result.pnl")
    if num(dig(t, "result.pnl")) is not None and initial_risk(t)[0] is None:
        need.append("risk.risk_amount (or size + stop)")
    return need or ["result.r"]


def outcome(r: float | None, pnl: float | None, band: float) -> str | None:
    if r is not None:
        return "win" if r > band else "loss" if r < -band else "breakeven"
    if pnl is not None:
        return "win" if pnl > 0 else "loss" if pnl < 0 else "breakeven"
    return None


def process_grade(t: dict, cfg: dict) -> tuple[str | None, float | None]:
    pc = cfg["process"]
    scores = [num(dig(t, f"review.scores.{d}")) for d in DIMENSIONS]
    scored = [s for s in scores if s is not None]
    if len(scored) < pc["min_scored_dimensions"]:
        return None, None
    mean = fmean(scored)
    grade = "good" if mean >= pc["good_min"] else "poor" if mean <= pc["poor_max"] else "mixed"
    return grade, mean


def outcome_process_label(grade: str | None, out: str | None) -> str | None:
    if grade is None or out is None:
        return None
    return f"{OUTCOME_WORD[out]} / {PROCESS_WORD[grade]}"


@dataclass
class Derived:
    r: float | None
    r_source: str | None
    risk: float | None
    risk_source: str | None
    pnl: float | None
    outcome: str | None
    grade: str | None
    process_mean: float | None
    label: str | None
    counterfactual_r: float | None
    missing: list[str] = field(default_factory=list)
    mae_r: float | None = None                  # heat: furthest move against the entry before the exit, in R
    mfe_r: float | None = None                  # run: furthest move in favour before the exit, in R


def excursions(t: dict) -> tuple[float | None, float | None]:
    """MAE / MFE in R from the chart-measured fills.worst_price and fills.best_price (between entry and exit).
    A price on the wrong side of the entry counts as 0 here; the validator reports it as an error."""
    entry, stop, sign = entry_price(t), num(dig(t, "plan.stop")), side_sign(t)
    if None in (entry, stop, sign) or entry == stop:
        return None, None
    risk = abs(entry - stop)
    worst, best = num(dig(t, "fills.worst_price")), num(dig(t, "fills.best_price"))
    mae = max(0.0, sign * (entry - worst)) / risk if worst is not None else None
    mfe = max(0.0, sign * (best - entry)) / risk if best is not None else None
    return mae, mfe


def derive(t: dict, cfg: dict) -> Derived:
    status = t.get("status")
    risk, risk_src = initial_risk(t)
    if status in COUNTERFACTUAL:
        return Derived(None, None, risk, risk_src, None, None, None, None, None,
                       num(dig(t, "result.hypothetical_r")))
    r, r_src = r_multiple(t) if status == REALIZED else (None, None)
    pnl, _ = realized_pnl(t) if status == REALIZED else (None, None)
    out = outcome(r, pnl, cfg["breakeven_band_r"]) if status == REALIZED else None
    grade, mean = process_grade(t, cfg)
    missing = missing_for_r(t) if status == REALIZED and r is None else []
    mae, mfe = excursions(t) if status == REALIZED else (None, None)
    return Derived(r, r_src, risk, risk_src, pnl, out, grade, mean,
                   outcome_process_label(grade, out), None, missing, mae, mfe)


def planned_rr(t: dict) -> list[float | None]:
    """Gross reward:risk per planned target, from the initial stop."""
    entry, stop, sign = entry_price(t), num(dig(t, "plan.stop")), side_sign(t)
    out = []
    for tp in dig(t, "plan.targets", []) or []:
        tp = num(tp)
        if None in (entry, stop, tp, sign) or entry == stop:
            out.append(None)
        else:
            out.append(sign * (tp - entry) / abs(entry - stop))
    return out
