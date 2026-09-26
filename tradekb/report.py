"""Markdown rendering. Every number is printed with its sample size; nothing is shown without n."""
from __future__ import annotations

import datetime as dt
from statistics import fmean, median

from . import analysis
from .analysis import Row
from .model import OUTCOME_WORD, PROCESS_WORD
from .stats import Comparison, Summary, histogram
from .store import KB, dig, unresolved


def fr(x: float | None) -> str:
    return "—" if x is None else f"{x:+.2f}R"


def fpct(x: float | None) -> str:
    return "—" if x is None else f"{x:.0%}"


def fnum(x: float | None, digits: int = 2) -> str:
    return "—" if x is None else f"{x:,.{digits}f}"


def fci(ci: tuple[float, float] | None) -> str:
    return "—" if ci is None else f"[{ci[0]:+.2f}, {ci[1]:+.2f}]"


SUMMARY_HEAD = ("| {label} | n | W/L/BE | Win% | Avg win | Avg loss | Expectancy | 95% CI | Median | PF | "
                "Max DD | Streak W/L | Evidence |\n"
                "|---|---:|---|---:|---:|---:|---:|---|---:|---:|---:|---|---|")


def summary_row(label: str, s: Summary) -> str:
    pf = "—" if s.profit_factor is None else f"{s.profit_factor:.2f}"
    return (f"| {label} | {s.n} | {s.wins}/{s.losses}/{s.breakevens} | {fpct(s.win_rate)} | {fr(s.avg_win)} | "
            f"{fr(s.avg_loss)} | {fr(s.expectancy)} | {fci(s.ci)} | {fr(s.median)} | {pf} | "
            f"{s.max_drawdown:.2f}R | {s.max_win_streak}/{s.max_loss_streak} | {s.evidence} |")


def summary_table(label: str, groups: list[tuple[str, Summary]]) -> str:
    return "\n".join([SUMMARY_HEAD.format(label=label)] + [summary_row(g, s) for g, s in groups])


def grouped_table(kb: KB, rs: list[Row], key: str) -> str:
    groups = analysis.group(rs, key)
    if not groups:
        return "_No data._"
    table = summary_table(key, [(g, analysis.summarize_rows(members, kb)) for g, members in groups.items()])
    if key in ("setup", "regime", "mistake", "behavior"):
        table += "\n\n_Multi-valued field: a trade appears in every group it is tagged with, so groups overlap._"
    return table


def comparison(label_a: str, label_b: str, c: Comparison) -> str:
    return "\n".join([
        summary_table("arm", [(f"A: {label_a}", c.a), (f"B: {label_b}", c.b)]),
        "",
        f"Difference in expectancy (A − B): {fr(c.diff)}  ·  95% bootstrap CI: {fci(c.ci)}",
        "",
        f"**Verdict:** {c.verdict}",
    ])


def status(kb: KB, issues) -> str:
    counts = {s: 0 for s in ("closed", "open", "planned", "missed", "not_taken")}
    for trade in kb.trades:
        if trade.status in counts:
            counts[trade.status] += 1
    measured = analysis.realized(kb)
    moderate = kb.config["evidence_tiers"]["moderate_min_n"]
    errors = sum(1 for i in issues if i.level == "ERROR")
    warns = sum(1 for i in issues if i.level == "WARN")
    lines = [
        f"# Knowledge base status — {dt.date.today().isoformat()}",
        "",
        f"Trades: {counts['closed']} closed ({len(measured)} with computable R) · {counts['open']} open · "
        f"{counts['planned']} planned · {counts['missed'] + counts['not_taken']} missed/not taken",
        f"Validation: {errors} error(s), {warns} warning(s){' — run ./tj validate' if errors or warns else ''}",
    ]
    if len(measured) < moderate:
        lines.append(f"Phase: INITIALIZATION ({len(measured)}/{moderate} measured trades). Learn terminology, "
                     f"strategies and risk rules; record everything; do not propose system redesigns.")
    else:
        lines.append(f"Phase: PATTERN ANALYSIS (n={len(measured)}). Cross-trade patterns may be examined; "
                     f"every claim still carries its n and CI.")

    gaps = unresolved(kb.profile)
    lines.append(f"Unresolved profile parameters ({len(gaps)}): {', '.join(gaps) if gaps else 'none'}")

    if kb.strategies:
        lines.append("Strategies: " + ", ".join(
            f"{slug} v{s.meta.get('current_version')} [{s.meta.get('status')}]" for slug, s in kb.strategies.items()))
    else:
        lines.append("Strategies: none defined yet.")
    active = [eid for eid, e in kb.experiments.items() if e.get("status") in ("planned", "running")]
    lines.append(f"Active experiments: {', '.join(active) if active else 'none'}")

    from .readiness import evaluate
    ready = evaluate(kb)
    if ready["stages"]:
        active = next((st for st in ready["stages"] if st["status"] == "active"), None)
        if active:
            met = sum(c["met"] for c in active["criteria"])
            lines.append(f"Automation readiness: {active['name']} ({met}/{len(active['criteria'])} criteria met)")
        else:
            lines.append("Automation readiness: all stages complete")
    recurring = [e for e in analysis.error_db(kb) if e.recurring]
    lines.append("Recurring errors: " + (", ".join(
        f"{e.tag} x{e.count} (last {e.last_seen}, {e.recent} in recent window)" for e in recurring)
        if recurring else "none flagged."))

    open_rows = analysis.rows(kb, {"open"})
    if open_rows:
        lines.append("Open positions:")
        total, by_dir = 0.0, {}
        for row in open_rows:
            risk = row.d.risk
            total += risk or 0
            by_dir[row.t.get("direction")] = by_dir.get(row.t.get("direction"), 0) + 1
            lines.append(f"  - {row.trade.id} {row.t.get('asset')} {row.t.get('direction')} "
                         f"risk {fnum(risk)} ({row.d.risk_source or 'unknown'})")
        lines.append(f"  Aggregate open risk (known legs): {fnum(total)} · by direction: {by_dir}. "
                     f"Same-direction positions in correlated assets are one bet, not several.")
    return "\n".join(lines)


def show_trade(kb: KB, row: Row, issues) -> str:
    t, d = row.t, row.d
    sid = dig(t, "strategy.id")
    strategy = f"{sid} v{dig(t, 'strategy.version', '?')}" if sid else "—"
    lines = [
        f"# {row.trade.id} — {t.get('asset')} {t.get('direction')} [{t.get('status')}]",
        "",
        f"Setups: {', '.join(t.get('setups') or []) or '—'} · Regime: {', '.join(t.get('regime') or []) or '—'} · "
        f"Strategy: {strategy}",
        f"Initial risk (1R): {fnum(d.risk)} ({d.risk_source or 'not computable'})",
    ]
    if d.counterfactual_r is not None:
        lines.append(f"COUNTERFACTUAL R: {fr(d.counterfactual_r)} — hypothetical, excluded from all statistics")
    elif t.get("status") == "closed":
        lines.append(f"Result: {fr(d.r)} ({d.r_source or 'not computable: needs ' + ', '.join(d.missing)}) · "
                     f"PnL {fnum(d.pnl)} · Outcome: {d.outcome or '—'}")
        lines.append(f"Process: {d.grade or 'unscored'}"
                     + (f" (mean {d.process_mean:.2f}/5)" if d.process_mean is not None else "")
                     + (f" → **{d.label}**" if d.label else ""))
    mine = [i for i in issues if i.where == row.trade.path.name]
    if mine:
        lines += ["", "Validation:"] + [f"  - {i.level} {i.msg}" for i in mine]
    return "\n".join(lines)


def errors_section(kb: KB) -> str:
    errs = analysis.error_db(kb)
    lines = [f"Recurring threshold: {kb.config['recurring_error_min']} occurrences · recent window: last "
             f"{kb.config['recent_window']} recorded trades", ""]
    if not errs:
        lines.append("_No mistakes recorded._")
    else:
        lines += ["| Mistake | Count | Recent | Recurring | R cost (n measured) | Mean R | Last seen |",
                  "|---|---:|---:|---|---:|---:|---|"]
        for e in errs:
            lines.append(f"| {e.tag} | {e.count} | {e.recent} | {'**YES**' if e.recurring else 'no'} | "
                         f"{fr(e.total_r)} ({e.n_measured}) | {fr(e.mean_r)} | {e.last_seen} |")
    behaviors = analysis.behavior_db(kb)
    lines += ["", "**Behaviours** — mean R with vs without (correlational, not causal):", ""]
    if not behaviors:
        lines.append("_No behaviours recorded._")
    else:
        lines += ["| Behaviour | n with | Mean R with | n without | Mean R without |", "|---|---:|---:|---:|---:|"]
        for b in behaviors:
            lines.append(f"| {b.tag} | {b.n_with} | {fr(b.mean_with)} | {b.n_without} | {fr(b.mean_without)} |")
    return "\n".join(lines)


def full_report(kb: KB, rs: list[Row], scope: str) -> str:
    cfg = kb.config
    out = [f"# Quantitative review — {dt.date.today().isoformat()}", "", f"Scope: {scope}", ""]
    if not rs:
        out.append("No closed trades with computable R in scope. Nothing to analyse: do not infer patterns.")
        return "\n".join(out + ["", "## Data gaps", "", _gaps(kb)])

    t = cfg["evidence_tiers"]
    out += [f"Evidence tiers: LOW < {t['moderate_min_n']} ≤ MODERATE < {t['higher_min_n']} (+ ≥ "
            f"{t['higher_min_conditions']} distinct '{t['condition_group']}' regimes) ≤ HIGHER. "
            f"Tiers describe sample adequacy, not whether an edge exists — read the CI for that.", ""]

    overall = analysis.summarize_rows(rs, kb)
    out += ["## 1. Overall", "", summary_table("scope", [("all", overall)]), ""]
    held = analysis.holding_days(rs)
    if held:
        out.append(f"Holding time (days, n={len(held)}): mean {fmean(held):.1f}, median {median(held):.1f}")
    rs_values = [row.d.r for row in rs]
    out += ["", "R distribution:", ""] + [f"- {label}: {count}" for label, count in
                                           histogram(rs_values, cfg["breakeven_band_r"])]

    sections = [("2. By setup", "setup"), ("3. By entry model", "entry_model"), ("4. By market regime", "regime"),
                ("5. By strategy version", "version"), ("6. By session", "session"), ("7. By asset", "asset"),
                ("8. By direction", "direction"), ("9. By execution timeframe", "timeframe"),
                ("10. By leverage setting", "leverage"), ("11. By risk per trade", "risk")]
    for title, key in sections:
        out += ["", f"## {title}", "", grouped_table(kb, rs, key)]

    out += ["", "## 12. Process vs outcome", ""]
    matrix = analysis.process_outcome_matrix(rs)
    out += ["| Process \\ Outcome | win | loss | breakeven |", "|---|---:|---:|---:|"]
    for grade in ("good", "mixed", "poor", "unscored"):
        out.append(f"| {grade} | " + " | ".join(str(matrix.get((grade, o), 0)) for o in OUTCOME_WORD) + " |")
    lucky = matrix.get(("poor", "win"), 0)
    if lucky:
        out.append(f"\n{lucky} trade(s) are {OUTCOME_WORD['win']} / {PROCESS_WORD['poor']}: "
                   f"wins that should not reinforce the behaviour that produced them.")

    out += ["", "## 13. Loss classification (A–E)", ""]
    breakdown = analysis.loss_type_breakdown(rs)
    if breakdown:
        labels = kb.taxonomies["loss_types"].tags
        out += ["| Type | n | Total R | Meaning |", "|---|---:|---:|---|"]
        for lt, members in breakdown.items():
            out.append(f"| {lt} | {len(members)} | {fr(sum(m.d.r for m in members))} | "
                       f"{(labels.get(lt) or {}).get('label', '')} |")
    else:
        out.append("_No losses in scope._")

    out += ["", "## 14. Errors and behaviours", "", errors_section(kb)]

    clean = [row for row in rs if not dig(row.t, "review.mistakes")]
    dirty = [row for row in rs if dig(row.t, "review.mistakes")]
    out += ["", "## 15. Trades without vs with tagged mistakes", "",
            summary_table("subset", [("no mistakes", analysis.summarize_rows(clean, kb)),
                                     ("≥1 mistake", analysis.summarize_rows(dirty, kb))]),
            "", "_The gap estimates the cost of execution errors, confounded by whatever else differs between "
                "the subsets. Untagged is not the same as mistake-free if reviews are incomplete._"]

    cf = [row for row in analysis.counterfactuals(kb) if row.d.counterfactual_r is not None]
    out += ["", "## 16. COUNTERFACTUAL — missed / not taken (hypothetical, excluded above)", ""]
    if cf:
        vals = [row.d.counterfactual_r for row in cf]
        out.append(f"n={len(cf)} · sum {fr(sum(vals))} · mean {fr(fmean(vals))} · "
                   f"ids: {', '.join(row.trade.id for row in cf)}")
    else:
        out.append("_None recorded._")

    out += ["", "## 17. Data gaps", "", _gaps(kb)]
    return "\n".join(out)


def _gaps(kb: KB) -> str:
    lines = []
    missing = analysis.unmeasurable(kb)
    if missing:
        lines.append(f"- {len(missing)} closed trade(s) excluded (R not computable): "
                     + ", ".join(f"{row.trade.id} (needs {', '.join(row.d.missing)})" for row in missing))
    unreviewed = [row.trade.id for row in analysis.rows(kb, {"closed"}) if row.d.grade is None]
    if unreviewed:
        lines.append(f"- {len(unreviewed)} closed trade(s) without process scores: {', '.join(unreviewed)}")
    gaps = unresolved(kb.profile)
    if gaps:
        lines.append(f"- Unresolved profile parameters: {', '.join(gaps)}")
    return "\n".join(lines) or "_None._"
