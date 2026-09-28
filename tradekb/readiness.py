"""Automation readiness: the gated road from a discretionary journal to a live bot.

Stages and criteria live in playbook/automation.yaml. Computed criteria are evaluated
from the journal on every build; manual criteria are marked done only with evidence.
A stage is done when all its criteria are met; the first unfinished stage is active and
everything after it stays locked. Nothing downstream can be skipped.
"""
from __future__ import annotations

from . import analysis
from .stats import required_trades
from .store import KB, dig

METRICS = {
    "measured_trades": "closed trades with a measurable R",
    "classified_losses": "losses with a loss type (A-E)",
    "longs": "measured long trades",
    "shorts": "measured short trades",
    "open_questions": "open questions in current strategy versions",
    "unresolved_profile": "unresolved profile parameters",
}
MANUAL_STATES = ("pending", "done")


def metric_values(kb: KB) -> dict[str, int]:
    from .store import unresolved
    rs = analysis.realized(kb)
    questions = 0
    for strat in kb.strategies.values():
        current = strat.versions.get(str(strat.meta.get("current_version"))) or {}
        questions += len(current.get("open_questions") or [])
    return {
        "measured_trades": len(rs),
        "classified_losses": sum(1 for r in rs if r.d.outcome == "loss" and dig(r.t, "review.loss_type")),
        "longs": sum(1 for r in rs if r.t.get("direction") == "long"),
        "shorts": sum(1 for r in rs if r.t.get("direction") == "short"),
        "open_questions": questions,
        "unresolved_profile": len(unresolved(kb.profile)),
    }


def _criterion(c: dict, values: dict[str, int]) -> dict:
    out = {"label": c.get("label"), "target": c.get("target"), "evidence": c.get("evidence")}
    if "metric" in c:
        value = values.get(c["metric"])
        lo, hi = c.get("min"), c.get("max")
        met = value is not None and (lo is None or value >= lo) and (hi is None or value <= hi)
        progress = (min(1.0, value / lo) if lo else (1.0 if met else 0.0)) if value is not None else 0.0
        out.update({"kind": "computed", "metric": c["metric"], "value": value, "min": lo, "max": hi,
                    "met": met, "progress": progress})
    else:
        state = c.get("manual", "pending")
        out.update({"kind": "manual", "state": state, "met": state == "done", "progress": 1.0 if state == "done" else 0.0})
    return out


def evaluate(kb: KB) -> dict:
    doc = kb.automation or {}
    values = metric_values(kb)
    stages, blocked = [], False
    for st in doc.get("stages") or []:
        criteria = [_criterion(c, values) for c in st.get("criteria") or []]
        done = bool(criteria) and all(c["met"] for c in criteria)
        status = "locked" if blocked else ("done" if done else "active")
        if not done:
            blocked = True
        stages.append({"id": st.get("id"), "name": st.get("name"), "goal": st.get("goal"),
                       "status": status, "criteria": criteria})
    sizing = doc.get("sample_size") or {}
    scenarios = []
    for sc in sizing.get("scenarios") or []:
        res = required_trades(sc["win_rate"], sc["avg_win"], sc.get("avg_loss", -1.0),
                              sizing.get("alpha", 0.05), sizing.get("power", 0.8))
        scenarios.append({**sc, **res})
    active = next((s for s in stages if s["status"] == "active"), None)
    return {"stages": stages, "active": active["id"] if active else None, "metrics": values,
            "sample_size": {"alpha": sizing.get("alpha", 0.05), "power": sizing.get("power", 0.8),
                            "scenarios": scenarios, "note": sizing.get("note")},
            "safety": doc.get("safety") or [], "venue": doc.get("venue") or {},
            "open_questions": [str(q) for q in doc.get("open_questions") or []],
            "malfunction_guard": doc.get("malfunction_guard") or {}}
