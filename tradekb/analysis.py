"""Cross-trade aggregation: grouping, filtering, and the error / behaviour databases.

The error and behaviour "databases" are DERIVED from trade records, never
maintained by hand. One source of truth means counts cannot drift from the
journal, and a tag typo is caught by validation instead of silently splitting
a recurring error into two rare ones.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import fmean
from typing import Callable

from .model import COUNTERFACTUAL, REALIZED, Derived, derive, num
from .stats import Summary, summarize
from .store import KB, Trade, as_date, dig, trade_number


@dataclass
class Row:
    trade: Trade
    d: Derived
    when: dt.date | None

    @property
    def t(self) -> dict:
        return self.trade.data


def _when(t: dict) -> dt.date | None:
    for key in ("closed", "opened"):
        try:
            value = as_date(t.get(key))
        except ValueError:
            value = None
        if value:
            return value
    return None


def rows(kb: KB, statuses: frozenset[str] | set[str] | None = None) -> list[Row]:
    out = []
    for trade in kb.trades:
        if statuses is None or trade.status in statuses:
            out.append(Row(trade, derive(trade.data, kb.config), _when(trade.data)))
    out.sort(key=lambda row: (row.when or dt.date.max, trade_number(row.trade.id) or 0, row.trade.id))
    return out


def realized(kb: KB) -> list[Row]:
    """Closed trades with a computable R, chronological. The ONLY input to performance stats."""
    return [row for row in rows(kb, {REALIZED}) if row.d.r is not None]


def unmeasurable(kb: KB) -> list[Row]:
    return [row for row in rows(kb, {REALIZED}) if row.d.r is None]


def counterfactuals(kb: KB) -> list[Row]:
    return rows(kb, set(COUNTERFACTUAL))


def leverage_bucket(t: dict) -> str:
    lev = num(dig(t, "risk.leverage"))
    if lev is None:
        return "(unknown)"
    for limit, label in ((1, "<=1x"), (3, "1-3x"), (5, "3-5x"), (10, "5-10x"), (20, "10-20x")):
        if lev <= limit:
            return label
    return ">20x"


def risk_bucket(t: dict) -> str:
    pct = num(dig(t, "risk.risk_pct"))
    if pct is None:
        equity, amount = num(dig(t, "risk.account_equity")), num(dig(t, "risk.risk_amount"))
        pct = amount / equity * 100 if equity and amount else None
    if pct is None:
        return "(unknown)"
    for limit, label in ((0.25, "<=0.25%"), (0.5, "0.25-0.5%"), (1, "0.5-1%"), (2, "1-2%")):
        if pct <= limit:
            return label
    return ">2%"


def _one(value) -> list[str]:
    return [str(value)] if value not in (None, "") else ["(unknown)"]


def _many(values) -> list[str]:
    return [str(v) for v in values] if isinstance(values, list) and values else ["(none)"]


GROUPERS: dict[str, Callable[[Row], list[str]]] = {
    "setup": lambda r: _many(r.t.get("setups")),
    "regime": lambda r: _many(r.t.get("regime")),
    "strategy": lambda r: _one(dig(r.t, "strategy.id")),
    "version": lambda r: _one(f"{dig(r.t, 'strategy.id')}@v{dig(r.t, 'strategy.version')}"
                              if dig(r.t, "strategy.id") else None),
    "experiment": lambda r: _one(dig(r.t, "strategy.experiment")),
    "variant": lambda r: _one(dig(r.t, "strategy.variant")),
    "session": lambda r: _one(r.t.get("session")),
    "asset": lambda r: _one(r.t.get("asset")),
    "market": lambda r: _one(r.t.get("market")),
    "direction": lambda r: _one(r.t.get("direction")),
    "timeframe": lambda r: _one(dig(r.t, "timeframes.execution")),
    "htf": lambda r: _one(dig(r.t, "timeframes.htf")),
    "leverage": lambda r: [leverage_bucket(r.t)],
    "risk": lambda r: [risk_bucket(r.t)],
    "loss_type": lambda r: _one(dig(r.t, "review.loss_type")),
    "mistake": lambda r: _many(dig(r.t, "review.mistakes")),
    "behavior": lambda r: _many(dig(r.t, "review.behaviors")),
    "validity": lambda r: _one(dig(r.t, "review.setup_validity")),
    "grade": lambda r: _one(r.d.grade),
    "outcome": lambda r: _one(r.d.outcome),
    "month": lambda r: _one(r.when.strftime("%Y-%m") if r.when else None),
}


def labels(row: Row, key: str) -> list[str]:
    if key not in GROUPERS:
        raise ValueError(f"unknown field '{key}'. Choose from: {', '.join(sorted(GROUPERS))}")
    return GROUPERS[key](row)


def parse_where(pairs: list[str] | None) -> dict[str, str]:
    where = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"--where expects field=value, got '{pair}'")
        key, value = pair.split("=", 1)
        if key not in GROUPERS:
            raise ValueError(f"unknown field '{key}'. Choose from: {', '.join(sorted(GROUPERS))}")
        where[key] = value
    return where


def apply_filters(rs: list[Row], where: dict[str, str], since: dt.date | None = None) -> list[Row]:
    out = []
    for row in rs:
        if since and (row.when is None or row.when < since):
            continue
        if all(value in labels(row, key) for key, value in where.items()):
            out.append(row)
    return out


def group(rs: list[Row], key: str) -> dict[str, list[Row]]:
    """Multi-valued fields (setup, regime, mistake, behaviour) put a trade in several groups: groups overlap."""
    groups: dict[str, list[Row]] = defaultdict(list)
    for row in rs:
        for label in labels(row, key):
            groups[label].append(row)
    return dict(sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])))


def conditions(rs: list[Row], cfg: dict, kb: KB) -> int:
    """Distinct market conditions covered: regime tags from the configured exclusive group."""
    group_name = cfg["evidence_tiers"]["condition_group"]
    tax = kb.taxonomies["regimes"].tags
    seen = set()
    for row in rs:
        for tag in row.t.get("regime") or []:
            if (tax.get(tag) or {}).get("group") == group_name:
                seen.add(tag)
    return len(seen)


def summarize_rows(rs: list[Row], kb: KB) -> Summary:
    return summarize([row.d.r for row in rs], kb.config, conditions(rs, kb.config, kb))


@dataclass
class ErrorStat:
    tag: str
    count: int
    recent: int
    trades: list[str]
    n_measured: int
    total_r: float | None
    mean_r: float | None
    last_seen: str
    recurring: bool


def error_db(kb: KB) -> list[ErrorStat]:
    """Every mistake occurrence in any non-planned record; R cost from measurable closed trades only."""
    cfg = kb.config
    recorded = [row for row in rows(kb) if row.trade.status != "planned"]
    recent_ids = {row.trade.id for row in recorded[-cfg["recent_window"]:]}
    by_tag: dict[str, list[Row]] = defaultdict(list)
    for row in recorded:
        for tag in dig(row.t, "review.mistakes", []) or []:
            by_tag[str(tag)].append(row)
    out = []
    for tag, hits in by_tag.items():
        measured = [row.d.r for row in hits if row.d.r is not None]
        out.append(ErrorStat(
            tag=tag, count=len(hits), recent=sum(1 for row in hits if row.trade.id in recent_ids),
            trades=[row.trade.id for row in hits], n_measured=len(measured),
            total_r=sum(measured) if measured else None, mean_r=fmean(measured) if measured else None,
            last_seen=hits[-1].trade.id, recurring=len(hits) >= cfg["recurring_error_min"],
        ))
    out.sort(key=lambda e: (not e.recurring, -e.count, e.total_r if e.total_r is not None else 0))
    return out


@dataclass
class BehaviorStat:
    tag: str
    n_with: int
    mean_with: float | None
    n_without: int
    mean_without: float | None


def behavior_db(kb: KB) -> list[BehaviorStat]:
    """Mean R with vs without each behaviour. Correlational only: behaviours are not randomly assigned."""
    rs = realized(kb)
    tags = sorted({str(tag) for row in rs for tag in (dig(row.t, "review.behaviors", []) or [])})
    out = []
    for tag in tags:
        with_ = [row.d.r for row in rs if tag in (dig(row.t, "review.behaviors", []) or [])]
        without = [row.d.r for row in rs if tag not in (dig(row.t, "review.behaviors", []) or [])]
        out.append(BehaviorStat(tag, len(with_), fmean(with_) if with_ else None,
                                len(without), fmean(without) if without else None))
    out.sort(key=lambda b: -b.n_with)
    return out


def process_outcome_matrix(rs: list[Row]) -> Counter:
    return Counter((row.d.grade or "unscored", row.d.outcome) for row in rs)


def loss_type_breakdown(rs: list[Row]) -> dict[str, list[Row]]:
    losses = [row for row in rs if row.d.outcome == "loss"]
    out: dict[str, list[Row]] = defaultdict(list)
    for row in losses:
        out[str(dig(row.t, "review.loss_type", "(unclassified)"))].append(row)
    return dict(sorted(out.items()))


def holding_days(rs: list[Row]) -> list[int]:
    out = []
    for row in rs:
        try:
            opened, closed = as_date(row.t.get("opened")), as_date(row.t.get("closed"))
        except ValueError:
            continue
        if opened and closed:
            out.append((closed - opened).days)
    return out
