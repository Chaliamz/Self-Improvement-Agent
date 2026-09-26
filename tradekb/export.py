"""Build outputs: exports/kb.json (machine contract) and terminal.html (human view).

kb.json is the interface for downstream consumers such as the planned trading bot:
schema-versioned, fully derived from the YAML sources, never edited by hand.
terminal.html embeds the same payload plus chart images in one self-contained file.

Both carry a fingerprint of every input file (records, rules, config, code, template).
`tj validate` recomputes it and flags the outputs as stale when they no longer match.
"""
from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import hashlib
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from . import __version__, analysis, model, readiness
from .model import num
from .risk import exposure
from .stats import histogram
from .store import KB, TAXONOMIES, dig, unresolved

SCHEMA_VERSION = 1
OUTPUTS = ("exports/kb.json", "terminal.html")
TEMPLATE = "templates/terminal.html"
INPUT_GLOBS = ("config.yaml", "profile/*.yaml", "taxonomy/*.yaml", "journal/trades/*.yaml", "journal/charts/*",
               "playbook/*.yaml", "playbook/strategies/**/*.yaml", "playbook/experiments/*.yaml", "tradekb/*.py", TEMPLATE)
BREAKDOWNS = ("setup", "entry_model", "version", "direction", "asset", "regime", "session", "timeframe",
              "leverage", "risk", "month")
FINGERPRINT_RE = re.compile(r'"fingerprint":\s*"([0-9a-f]+)"|<meta name="kb-fingerprint" content="([0-9a-f]+)"')


def fingerprint(root: Path) -> str:
    """Hash of every input. Identical inputs -> identical outputs (the build is deterministic)."""
    digest = hashlib.sha256()
    for pattern in INPUT_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and "__pycache__" not in path.parts:
                digest.update(path.relative_to(root).as_posix().encode())
                digest.update(b"\0")
                digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def embedded_fingerprint(path: Path) -> str | None:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return None
    match = FINGERPRINT_RE.search(head)
    return (match.group(1) or match.group(2)) if match else None


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if dataclasses.is_dataclass(value):
        return jsonable(dataclasses.asdict(value))
    return value


def _trade(row: analysis.Row, kb: KB) -> dict:
    t = row.t
    entry, stop = model.entry_price(t), num(dig(t, "plan.stop"))
    exp = None
    if entry and stop and entry != stop:
        mmr = num(dig(kb.profile, "leverage.maintenance_margin_rate")) or kb.config["risk_checks"]["default_mmr_rate"]
        exp = exposure(entry, stop, num(dig(t, "risk.risk_pct")), num(dig(t, "risk.leverage")),
                       dig(t, "risk.margin_mode"), mmr, num(dig(kb.profile, "leverage.max_margin_loss_at_stop_pct")))
    held = analysis.holding_days([row])
    derived = jsonable(row.d)
    derived.update({"exposure": exp, "planned_rr": model.planned_rr(t), "holding_days": held[0] if held else None,
                    "sort_date": row.when.isoformat() if row.when else None})
    return {**jsonable(t), "derived": derived}


def _summary(rs: list, kb: KB) -> dict:
    return jsonable(analysis.summarize_rows(rs, kb))


def build_payload(kb: KB) -> dict:
    cfg = kb.config
    rs = analysis.realized(kb)
    moderate = cfg["evidence_tiers"]["moderate_min_n"]

    curve, cum = [], 0.0
    for row in rs:
        cum += row.d.r
        curve.append({"id": row.trade.id, "date": row.when.isoformat() if row.when else None,
                      "r": row.d.r, "cum_r": cum})

    by = {}
    for key in BREAKDOWNS:
        by[key] = [{"label": label, "ids": [m.trade.id for m in members], "summary": _summary(members, kb)}
                   for label, members in analysis.group(rs, key).items()]

    loss_labels = kb.taxonomies["loss_types"].tags
    loss_types = {lt: {"n": len(m), "total_r": sum(x.d.r for x in m), "ids": [x.trade.id for x in m],
                       "label": (loss_labels.get(lt) or {}).get("label")}
                  for lt, m in analysis.loss_type_breakdown(rs).items()}
    matrix = analysis.process_outcome_matrix(rs)
    clean = [row for row in rs if not dig(row.t, "review.mistakes")]
    dirty = [row for row in rs if dig(row.t, "review.mistakes")]

    strategies = []
    for slug, strat in kb.strategies.items():
        measured = [row.trade.id for row in rs if dig(row.t, "strategy.id") == slug]
        strategies.append({"slug": slug, "meta": jsonable(strat.meta), "versions": jsonable(strat.versions),
                           "changes": jsonable(strat.changes), "measured_trades": measured,
                           "promotion": cfg["promotion"]["strategy_min_trades"]})

    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": __version__,
        "phase": {"name": "INITIALIZATION" if len(rs) < moderate else "PATTERN ANALYSIS",
                  "measured": len(rs), "target": moderate},
        "profile": jsonable(kb.profile),
        "unresolved": unresolved(kb.profile),
        "config": jsonable({k: cfg[k] for k in ("breakeven_band_r", "evidence_tiers", "min_n_for_ratios",
                                                "min_n_for_ci", "recurring_error_min", "promotion")}),
        "taxonomy": {name: jsonable(kb.taxonomies[name].tags) for name in TAXONOMIES},
        "strategies": strategies,
        "experiments": [jsonable(e) for e in kb.experiments.values()],
        "trades": [_trade(row, kb) for row in analysis.rows(kb)],
        "stats": {
            "overall": _summary(rs, kb),
            "histogram": [{"label": label, "count": n} for label, n in
                          histogram([row.d.r for row in rs], cfg["breakeven_band_r"])],
            "equity_curve": curve,
            "by": by,
            "errors": jsonable(analysis.error_db(kb)),
            "behaviors": jsonable(analysis.behavior_db(kb)),
            "process_outcome": [{"grade": g, "outcome": o, "n": n} for (g, o), n in sorted(
                matrix.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))],
            "loss_types": loss_types,
            "mistake_free": _summary(clean, kb),
            "with_mistakes": _summary(dirty, kb),
            "counterfactual": [{"id": row.trade.id, "hypothetical_r": row.d.counterfactual_r}
                               for row in analysis.counterfactuals(kb)],
        },
        "readiness": readiness.evaluate(kb),
        "gaps": {
            "unmeasurable": [{"id": row.trade.id, "needs": row.d.missing} for row in analysis.unmeasurable(kb)],
            "unreviewed": [row.trade.id for row in analysis.rows(kb, {"closed"}) if row.d.grade is None],
        },
    }


def _charts(kb: KB, payload: dict) -> dict[str, str]:
    """Chart images referenced by trades, as data URIs, so terminal.html stays a single file."""
    out = {}
    for trade in payload["trades"]:
        for rel in dig(trade, "evidence.charts", []) or []:
            path = kb.root / str(rel)
            if rel in out or not path.is_file():
                continue
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if mime.startswith("image/"):
                out[rel] = f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
    return out


def _script_safe(obj: Any) -> str:
    """JSON that cannot terminate the <script> element it is embedded in."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def build(kb: KB) -> dict:
    from .validate import validate

    fp = fingerprint(kb.root)
    payload = build_payload(kb)
    issues = validate(kb, check_build=False)
    meta = {
        "fingerprint": fp,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "validation": [{"level": i.level, "where": i.where, "msg": i.msg} for i in issues],
    }
    document = {"fingerprint": fp, **payload, "build": meta}

    kb_json = kb.root / "exports" / "kb.json"
    kb_json.parent.mkdir(parents=True, exist_ok=True)
    kb_json.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    template = (kb.root / TEMPLATE).read_text(encoding="utf-8")
    html = (template
            .replace("__FINGERPRINT__", fp)
            .replace("/*__KB_JSON__*/null", _script_safe(document))
            .replace("/*__CHARTS_JSON__*/null", _script_safe(_charts(kb, payload))))
    (kb.root / "terminal.html").write_text(html, encoding="utf-8")
    return {"fingerprint": fp, "trades": len(payload["trades"]), "errors": sum(i.level == "ERROR" for i in issues),
            "warnings": sum(i.level == "WARN" for i in issues), "bytes": len(html.encode())}
