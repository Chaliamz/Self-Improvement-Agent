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
import math
import random
import re
from pathlib import Path

from .export import IMAGE_TYPES, build_payload, fingerprint
from .store import KB, trade_number

TOL = 1e-9
SINGLE_VALUED = ("weekday", "direction", "asset", "timeframe", "top_down", "strategy", "version", "entry_model",
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
    if plan.get("split_entries"):
        # split entry: filled orders are the ones nearest the first entry; each adds share x its own R
        prices = [_num(plan.get("entry"))] + [_num(x) for x in plan["split_entries"]]
        share, n = _num(plan.get("split_share")), fills.get("orders_filled")
        pxs = {_num(e.get("price")) for e in exits}
        if None in prices or None in (stop, sign, share) or not isinstance(n, int) or len(pxs) != 1 or None in pxs:
            return None
        px = pxs.pop()
        near_first = sorted(prices, key=lambda e: -sign * e)[:n]
        return sum(share * sign * (px - e) / abs(e - stop) for e in near_first) if n >= 1 and stop not in prices else None
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


def _rank(values: list, q: float):
    """Nearest rank, restated: the value at position round-half-up(q x (count - 1)) of the sorted list."""
    s = sorted(values)
    return s[math.floor(q * (len(s) - 1) + 0.5)]


def _audit_more(a: Audit, p: dict, realized: list, kb: KB) -> None:
    mo = p["stats"]["more"]
    rs = [t["derived"]["r"] for t in realized]
    n = len(rs)
    a.check(mo["n"] == n, "more stats: n")
    if n >= 2:
        mean = sum(rs) / n
        sd = math.sqrt(sum((r - mean) ** 2 for r in rs) / (n - 1))
        a.check(mo["sd"] is not None and abs(mo["sd"] - sd) < 1e-9, "more stats: standard deviation of R re-derived")
        want_sqn = math.sqrt(min(n, 100)) * mean / sd if n >= kb.config["min_n_for_ratios"] and sd else None
        a.check((mo["sqn"] is None and want_sqn is None) or (want_sqn is not None and abs(mo["sqn"] - want_sqn) < 1e-9), "more stats: SQN re-derived")
    if rs:
        a.check(abs(mo["best"]["r"] - max(rs)) < TOL and abs(mo["worst"]["r"] - min(rs)) < TOL, "more stats: best and worst R")
    hits = []
    for t in realized:
        targets = [_num(x) for x in (t.get("plan") or {}).get("targets") or [] if _num(x) is not None]
        exits = [_num(e.get("price")) for e in (t.get("fills") or {}).get("exits") or [] if _num(e.get("price")) is not None]
        if any(abs(e - x) <= 1e-9 * max(abs(x), 1.0) for e in exits for x in targets):
            hits.append(t["id"])
    a.check(sorted(mo["target_hit_ids"]) == sorted(hits) and mo["target_hits"] == len(hits), "more stats: target hits recounted")
    best_rr = [max(x for x in t["derived"]["planned_rr"] if x is not None) for t in realized
               if any(x is not None for x in t["derived"]["planned_rr"])]
    if best_rr:
        mean_rr = sum(best_rr) / len(best_rr)
        a.check(abs(mo["planned_rr_mean"] - mean_rr) < 1e-9 and abs(mo["breakeven_win_rate"] - 1 / (1 + mean_rr)) < 1e-9,
                "more stats: planned R:R and break-even win rate")


def _audit_outlook(a: Audit, p: dict, realized: list, kb: KB) -> None:
    """Replay the Monte Carlo protocol with separately written aggregation."""
    out, cfg = p["stats"]["outlook"], kb.config
    rs = [t["derived"]["r"] for t in realized]
    if len(rs) < cfg["min_n_for_ci"]:
        a.check(out is None, "outlook: absent below the minimum sample")
        return
    horizon, paths, band, seed = cfg["outlook"]["trades"], cfg["outlook"]["paths"], cfg["breakeven_band_r"], cfg["bootstrap"]["seed"]
    wins, losses = [r for r in rs if r > band], [r for r in rs if r < -band]

    def replay(next_r):
        steps, finals, dds, streaks = [[] for _ in range(horizon)], [], [], []
        for _ in range(paths):
            path = [next_r() for _ in range(horizon)]
            cum = 0.0
            running = []
            for r in path:
                cum += r
                running.append(cum)
            for i, v in enumerate(running):
                steps[i].append(v)
            highs = [max([0.0] + running[:i + 1]) for i in range(horizon)]
            dds.append(max(h - v for h, v in zip(highs, running)) if running else 0.0)
            best = cur = 0
            for r in path:
                cur = cur + 1 if r < -band else 0
                best = best if best > cur else cur
            streaks.append(best); finals.append(running[-1])
        return steps, finals, dds, streaks

    sc = {s["key"]: s for s in out["scenarios"]}
    g = random.Random(seed)
    cases = [("as_sampled", lambda: rs[g.randrange(len(rs))])]
    if wins and losses:
        k, n, z = len(wins), len(rs), 1.96
        ph = k / n
        w = (ph + z * z / (2 * n) - z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))) / (1 + z * z / n)
        aw, al = sum(wins) / len(wins), sum(losses) / len(losses)
        g2 = random.Random(seed + 1)
        cases.append(("low_win_rate", lambda: aw if g2.random() < w else al))
        a.check("low_win_rate" in sc and abs(sc["low_win_rate"]["win_rate"] - w) < 1e-12, "outlook: low win rate is the Wilson lower bound")
    a.check(len(sc) == len(cases), "outlook: scenario count")
    for key, draw in cases:
        steps, finals, dds, streaks = replay(draw)
        s = sc.get(key) or {}
        ok = all(abs(s["bands"][name][i + 1] - _rank(steps[i], q)) < 1e-9 for name, q in
                 (("p5", .05), ("p25", .25), ("p50", .5), ("p75", .75), ("p95", .95)) for i in range(horizon))
        a.check(ok and all(s["bands"][b][0] == 0.0 for b in s["bands"]), f"outlook {key}: percentile bands replayed")
        a.check(abs(s["final"]["p50"] - _rank(finals, .5)) < 1e-9 and abs(s["p_negative"] - sum(f < 0 for f in finals) / paths) < 1e-12,
                f"outlook {key}: final R and the chance of ending negative replayed")
        a.check(abs(s["max_drawdown"]["p95"] - _rank(dds, .95)) < 1e-9 and s["losing_streak"]["p95"] == _rank(streaks, .95),
                f"outlook {key}: drawdown and losing streak replayed")


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
            if "max_leverage_liq" in exp:
                mmr = _num((kb.profile.get("leverage") or {}).get("maintenance_margin_rate"))
                mmr = mmr if mmr is not None else kb.config["risk_checks"]["default_mmr_rate"]
                cap = exp["max_leverage_liq"]
                liq = entry * (1 - 1 / cap) / (1 - mmr) if stop < entry else entry * (1 + 1 / cap) / (1 + mmr)
                a.check(abs(liq - stop) <= abs(entry - stop) * 1e-9, f"{t['id']}: at the liquidation cap {cap:.4f}x, liquidation sits on the stop")
                a.check(exp["max_leverage_safe"] == min(cap, exp["max_leverage_for_rule"])
                        and exp["liq_binds"] == (cap < exp["max_leverage_for_rule"]), f"{t['id']}: safe leverage is the lower cap")
            lev = _num((t.get("risk") or {}).get("leverage"))
            if lev and "margin_loss_pct" in exp:
                a.check(abs(exp["margin_loss_pct"] - exp["stop_pct"] * lev) < TOL, f"{t['id']}: margin loss at stop")

    # excursions (MAE / MFE), recomputed from the raw prices
    for t in realized:
        fl, plan = t.get("fills") or {}, t.get("plan") or {}
        entry = _num(fl.get("entry_avg")); entry = entry if entry is not None else _num(plan.get("entry"))
        stop, sign = _num(plan.get("stop")), {"long": 1, "short": -1}.get(t.get("direction"))
        for key, field_name, fav in (("mae_r", "worst_price", -1), ("mfe_r", "best_price", 1)):
            px_, got = _num(fl.get(field_name)), t["derived"].get(key)
            if None in (entry, stop, sign, px_) or entry == stop:
                a.check(got is None, f"{t['id']}: {key} absent without {field_name}")
            else:
                want = max(0.0, fav * sign * (px_ - entry)) / abs(entry - stop)
                a.check(got is not None and abs(got - want) < TOL, f"{t['id']}: {key} {got} equals independent recompute {want:.6f}")

    ex = p["stats"]["excursions"]
    wm = sorted(t["derived"]["mae_r"] for t in realized if t["derived"].get("outcome") == "win" and t["derived"].get("mae_r") is not None)
    lm = sorted(t["derived"]["mfe_r"] for t in realized if t["derived"].get("outcome") == "loss" and t["derived"].get("mfe_r") is not None)
    mid = lambda v: None if not v else (v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2)
    a.check(ex["winners"] == len(wm) and ex["losers"] == len(lm), "excursions: winner/loser counts")
    for key, want in (("winner_mae_median", mid(wm)), ("loser_mfe_median", mid(lm)), ("winner_mae_max", wm[-1] if wm else None),
                      ("loser_mfe_max", lm[-1] if lm else None)):
        a.check((ex[key] is None and want is None) or (want is not None and ex[key] is not None and abs(ex[key] - want) < TOL),
                f"excursions: {key} re-derived")

    # rule compliance: the numeric rules recomputed from raw fields, and the counts re-tallied
    prof = kb.profile or {}
    limit = _num((prof.get("leverage") or {}).get("max_margin_loss_at_stop_pct"))
    ceiling = limit                                 # independent restatement: a breach is above the limit (the aim's top)
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

    _audit_more(a, p, realized, kb)
    _audit_outlook(a, p, realized, kb)

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

    # incident log: exported unchanged, counts re-tallied
    raw = [i for i in kb.incidents if isinstance(i, dict)]
    a.check(p["incidents"] == json.loads(json.dumps(p["incidents"])) and len(p["incidents"]) == len(kb.incidents),
            "incidents: exported one for one")
    hl = p["health"]
    a.check(hl["incidents"] == len(raw), "health: incident total re-tallied")
    for key, field_ in (("by_status", "status"), ("by_severity", "severity")):
        tally: dict = {}
        for i in raw:
            tally[i.get(field_)] = tally.get(i.get(field_), 0) + 1
        a.check(all(hl[key].get(k, 0) == v for k, v in tally.items()) and sum(hl[key].values()) == len(raw),
                f"health: incidents {key} re-tallied")
    opens: dict = {}
    for i in raw:
        if i.get("status") == "open":
            opens[i.get("severity")] = opens.get(i.get("severity"), 0) + 1
    a.check(all(hl["open_by_severity"].get(k, 0) == v for k, v in opens.items())
            and sum(hl["open_by_severity"].values()) == sum(opens.values()), "health: open incidents re-tallied")

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
