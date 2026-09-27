"""Integrity audit: recompute everything the build publishes and compare.

`validate` checks that each record is well-formed. `audit` checks that what is PUBLISHED is right:
derived numbers are recomputed here with independent code (not by calling the model functions
that produced them), aggregates are re-summed, and the files on disk (kb.json, terminal.html,
charts) are compared byte-for-byte in meaning with a fresh build. Any mismatch means a bug,
a stale build, or corruption. All three block a commit.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
from pathlib import Path

from .export import IMAGE_TYPES, build_payload, fingerprint
from .store import KB, trade_number

TOL = 1e-9
SINGLE_VALUED = ("direction", "asset", "timeframe", "top_down", "strategy", "version", "entry_model",
                 "leverage", "risk", "grade", "trader_grade", "trend", "month", "session")
MAGIC = {".png": b"\x89PNG", ".jpg": b"\xff\xd8", ".jpeg": b"\xff\xd8", ".gif": b"GIF8"}
KB_DATA_RE = re.compile(r'<script id="kb-data" type="application/json">(.*?)</script>', re.S)
CHARTS_RE = re.compile(r'<script id="kb-charts" type="application/json">(.*?)</script>', re.S)


class Audit:
    def __init__(self) -> None:
        self.results: list[tuple[bool, str]] = []

    def check(self, ok: bool, message: str) -> None:
        self.results.append((bool(ok), message))

    @property
    def failures(self) -> list[str]:
        return [m for ok, m in self.results if not ok]


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _independent_r(t: dict) -> float | None:
    """R from the raw record, written separately from model.r_multiple on purpose."""
    res = t.get("result") or {}
    if _num(res.get("r")) is not None:
        return _num(res["r"])
    if _num(res.get("pnl")) is not None:
        return None  # money-based R depends on risk inputs; covered by the unit tests
    plan, fills = t.get("plan") or {}, t.get("fills") or {}
    entry = _num(fills.get("entry_avg")) if _num(fills.get("entry_avg")) is not None else _num(plan.get("entry"))
    stop = _num(plan.get("stop"))
    sign = {"long": 1, "short": -1}.get(t.get("direction"))
    exits = fills.get("exits") or []
    if None in (entry, stop, sign) or entry == stop or not exits:
        return None
    if len(exits) == 1:
        px = _num(exits[0].get("price"))
        return None if px is None else sign * (px - entry) / abs(entry - stop)
    weights = [(_num(e.get("price")), _num(e.get("qty")) or _num(e.get("fraction"))) for e in exits]
    if any(p is None or w is None for p, w in weights):
        return None
    total = sum(w for _, w in weights)
    return sign * (sum(p * w for p, w in weights) / total - entry) / abs(entry - stop)


def _sort_key(t: dict):
    when = t.get("closed") or t.get("opened")
    return (str(when) if when else "9999", trade_number(t["id"]) or 0)


def run(kb: KB, check_outputs: bool = True) -> Audit:
    a = Audit()
    p = build_payload(kb)
    band = kb.config["breakeven_band_r"]
    trades = p["trades"]
    realized = [t for t in trades if t["status"] == "closed" and _num(t["derived"]["r"]) is not None]
    o = p["stats"]["overall"]

    # per-trade derivations, recomputed independently
    for t in trades:
        ind = _independent_r(t)
        if t["status"] == "closed" and ind is not None:
            a.check(abs(ind - t["derived"]["r"]) < TOL, f"{t['id']}: R {t['derived']['r']} equals independent recompute {ind}")
        plan = t.get("plan") or {}
        entry, stop = _num(plan.get("entry")), _num(plan.get("stop"))
        sign = {"long": 1, "short": -1}.get(t.get("direction"))
        for tp, rr in zip(plan.get("targets") or [], t["derived"]["planned_rr"]):
            if None not in (entry, stop, sign, _num(tp)) and entry != stop:
                a.check(abs(sign * (tp - entry) / abs(entry - stop) - rr) < TOL, f"{t['id']}: planned R:R {rr:.4f} for target {tp}")
        exp = t["derived"].get("exposure")
        if exp and entry and stop:
            a.check(abs(exp["stop_pct"] - abs(entry - stop) / entry * 100) < TOL, f"{t['id']}: stop distance %")
            lev = _num((t.get("risk") or {}).get("leverage"))
            if lev and "margin_loss_pct" in exp:
                a.check(abs(exp["margin_loss_pct"] - exp["stop_pct"] * lev) < TOL, f"{t['id']}: margin loss at stop")

    # rule compliance: the numeric rules recomputed from raw fields, and the counts re-tallied
    prof = kb.profile or {}
    limit = _num((prof.get("leverage") or {}).get("max_margin_loss_at_stop_pct"))
    tol = _num((prof.get("leverage") or {}).get("margin_loss_tolerance_pct"))
    ceiling = tol if tol is not None else limit     # independent restatement: a breach is beyond the tolerance
    cap = _num((prof.get("risk") or {}).get("max_risk_per_trade_pct"))
    taken = [t for t in trades if t["status"] in ("closed", "open")]
    for t in trades:
        rc = t["derived"].get("rule_checks")
        a.check((rc is not None) == (t in taken), f"{t['id']}: rule checks present exactly on taken trades")
        if rc is None:
            continue
        tags = set((t.get("review") or {}).get("mistakes") or [])
        entry = _num((t.get("fills") or {}).get("entry_avg"))
        entry = entry if entry is not None else _num((t.get("plan") or {}).get("entry"))
        stop, lev = _num((t.get("plan") or {}).get("stop")), _num((t.get("risk") or {}).get("leverage"))
        if "excessive_leverage" in tags:
            want = False
        elif None in (entry, stop, lev, limit) or not entry or entry == stop:
            want = None
        else:
            want = abs(entry - stop) / entry * 100 * lev <= ceiling + 1e-9
        a.check(rc["leverage"] == want, f"{t['id']}: leverage rule {rc['leverage']} equals recompute {want}")
        rp = _num((t.get("risk") or {}).get("risk_pct"))
        want = False if "oversized_position" in tags else None if None in (rp, cap) else rp <= cap + 1e-9
        a.check(rc["risk_pct"] == want, f"{t['id']}: risk rule {rc['risk_pct']} equals recompute {want}")
    rules = p["stats"]["rules"]
    for d in rules["definitions"]:
        c = rules["counts"][d["key"]]
        tally = {k: sum(1 for t in taken if t["derived"]["rule_checks"][d["key"]] is v) for k, v in (("kept", True), ("broken", False), ("unknown", None))}
        a.check(c == tally, f"rule '{d['key']}': kept/broken/unknown re-tally {tally}")
    split = [t for t in realized if False in t["derived"]["rule_checks"].values()]
    a.check(rules["any_broken"]["n"] == len(split) and rules["none_broken"]["n"] == len(realized) - len(split),
            "rule split: none-broken + any-broken cover every measured trade")
    a.check(abs((rules["any_broken"]["total"] or 0) + (rules["none_broken"]["total"] or 0) - o["total"]) < TOL,
            "rule split: the two totals sum to overall R")

    # aggregates
    rs = [t["derived"]["r"] for t in realized]
    a.check(o["n"] == len(rs), f"overall n = {o['n']} measured trades")
    a.check(abs(o["total"] - sum(rs)) < TOL, f"overall total R = {o['total']:.6f} equals the sum of trade R")
    if rs:
        a.check(abs(o["expectancy"] - sum(rs) / len(rs)) < TOL, "expectancy equals total / n")
    wins = sum(1 for r in rs if r > band); losses = sum(1 for r in rs if r < -band)
    a.check((o["wins"], o["losses"], o["breakevens"]) == (wins, losses, len(rs) - wins - losses),
            f"W/L/BE = {o['wins']}/{o['losses']}/{o['breakevens']}")
    a.check(sum(b["count"] for b in p["stats"]["histogram"]) == len(rs), "R distribution counts sum to n")

    chrono = sorted(realized, key=_sort_key)
    curve = p["stats"]["equity_curve"]
    a.check([c["id"] for c in curve] == [t["id"] for t in chrono], "equity curve is in chronological (close-date) order")
    cum = 0.0
    ok = True
    for c, t in zip(curve, chrono):
        cum += t["derived"]["r"]
        ok &= abs(c["cum_r"] - cum) < TOL
    a.check(ok and (not curve or abs(curve[-1]["cum_r"] - o["total"]) < TOL), "cumulative R path re-sums correctly")

    for key, groups in p["stats"]["by"].items():
        total_n = sum(g["summary"]["n"] for g in groups)
        if key in SINGLE_VALUED:
            a.check(total_n == len(rs), f"breakdown '{key}': groups sum to n ({total_n})")
        else:
            a.check(total_n >= len(rs), f"breakdown '{key}': multi-valued groups cover n ({total_n} >= {len(rs)})")

    m = p["readiness"]["metrics"]
    a.check(m["measured_trades"] == len(rs), "readiness: measured trades")
    a.check(m["longs"] == sum(1 for t in realized if t.get("direction") == "long"), "readiness: long count")
    a.check(m["shorts"] == sum(1 for t in realized if t.get("direction") == "short"), "readiness: short count")

    # chart files exist and carry the right signature
    for t in trades:
        for rel in (t.get("evidence") or {}).get("charts") or []:
            path = kb.root / rel
            ext = path.suffix.lower()
            if not path.is_file():
                a.check(False, f"{t['id']}: chart {rel} is missing")
                continue
            head = path.read_bytes()[:12]
            sig_ok = (head[:4] == b"RIFF" and head[8:12] == b"WEBP") if ext == ".webp" else head.startswith(MAGIC.get(ext, b""))
            a.check(ext in IMAGE_TYPES and sig_ok, f"{t['id']}: chart {rel} is a valid {ext} image")

    if not check_outputs:
        return a

    # published files vs a fresh build
    fp = fingerprint(kb.root)
    fresh = json.loads(json.dumps(p, ensure_ascii=False))
    kb_path = kb.root / "exports" / "kb.json"
    try:
        disk = json.loads(kb_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        a.check(False, f"exports/kb.json unreadable: {exc}")
        return a
    a.check(disk.get("fingerprint") == fp, "exports/kb.json fingerprint matches the current inputs")
    body = {k: v for k, v in disk.items() if k not in ("fingerprint", "build")}
    a.check(body == fresh, "exports/kb.json content equals a fresh build")

    html_path = kb.root / "terminal.html"
    try:
        html = html_path.read_text(encoding="utf-8")
    except OSError as exc:
        a.check(False, f"terminal.html unreadable: {exc}")
        return a
    a.check(f'<meta name="kb-fingerprint" content="{fp}">' in html, "terminal.html fingerprint matches the current inputs")
    match = KB_DATA_RE.search(html)
    embedded = json.loads(match.group(1).replace("<\\/", "</")) if match else None
    a.check(embedded == disk, "terminal.html embeds exactly exports/kb.json")
    cm = CHARTS_RE.search(html)
    charts = json.loads(cm.group(1).replace("<\\/", "</")) if cm else {}
    for t in trades:
        for rel in (t.get("evidence") or {}).get("charts") or []:
            path = kb.root / rel
            uri = charts.get(rel, "")
            ok = uri.startswith(f"data:{IMAGE_TYPES.get(path.suffix.lower(), '?')};base64,") and path.is_file() \
                and base64.b64decode(uri.split(",", 1)[1]) == path.read_bytes()
            a.check(ok, f"terminal.html embeds chart {rel} intact")
    return a
