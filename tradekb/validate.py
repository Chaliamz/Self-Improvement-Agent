"""Integrity checks for the knowledge base.

ERROR  the record is wrong or would corrupt statistics; fix before committing
WARN   internally inconsistent or a risk finding worth surfacing (prefixed RISK:)
INFO   missing information or review debt; never blocks
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from . import model
from .model import COUNTERFACTUAL, REALIZED, derive, num
from .risk import fmt_cap, liquidation_price
from .store import KB, STATUSES, TRADE_ID_RE, Trade, as_date, dig, unresolved

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"

ENUMS = {
    "review.setup_validity": ("valid", "invalid", "uncertain"),
    "review.strategy_change": ("yes", "no", "insufficient_evidence"),
    "review.evidence_strength": ("low", "moderate", "high"),
    "risk.margin_mode": ("isolated", "cross"),
}
NUMERIC = ("plan.entry", "plan.stop", "risk.account_equity", "risk.risk_amount", "risk.risk_pct",
           "risk.leverage", "risk.size", "risk.notional", "fills.entry_avg", "fills.fees",
           "fills.duration_minutes", "result.pnl", "result.r", "result.hypothetical_r")
TAG_FIELDS = (("setups", "setups"), ("regime", "regimes"), ("review.mistakes", "mistakes"),
              ("review.behaviors", "behaviors"))
STRATEGY_STATUSES = ("unvalidated", "developing", "established", "retired")
CHANGE_STATUSES = ("observation", "hypothesis", "testing", "provisional", "established", "rejected")
CHANGE_KINDS = ("rule_change", "clarification")
EXPERIMENT_STATUSES = ("planned", "running", "concluded", "abandoned")
CHANGE_ID_RE = re.compile(r"^CHG-\d{3,}$")
EXPERIMENT_ID_RE = re.compile(r"^EXP-\d{3,}$")
VERSION_FILE_RE = re.compile(r"^playbook/strategies/[^/]+/v[^/]+\.yaml$")
# TradingView notation: m minutes, h hours, D days, W weeks, M months. "1M" is a month, never a minute.
TIMEFRAME_RE = re.compile(r"^\d+(m|h|D|W|M)$")


@dataclass
class Issue:
    level: str
    where: str
    msg: str

    def __str__(self) -> str:
        return f"{self.level:5} {self.where}: {self.msg}"


class _Sink:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def __call__(self, level: str, where: str, msg: str) -> None:
        self.issues.append(Issue(level, where, msg))


def _check_taxonomies(kb: KB, add: _Sink) -> None:
    for name, tax in kb.taxonomies.items():
        seen: dict[str, str] = {}
        for tag, meta in tax.tags.items():
            if not re.fullmatch(r"[A-Za-z0-9_]+", tag):
                add(ERROR, f"taxonomy/{name}", f"tag '{tag}' must be letters, digits, underscore")
            for alias in (meta or {}).get("aliases") or []:
                if alias in tax.tags:
                    add(ERROR, f"taxonomy/{name}", f"alias '{alias}' of '{tag}' is itself a canonical tag")
                elif alias in seen and seen[alias] != tag:
                    add(ERROR, f"taxonomy/{name}", f"alias '{alias}' maps to both '{seen[alias]}' and '{tag}'")
                seen[alias] = tag
            group = (meta or {}).get("group")
            if tax.groups and group is not None and group not in tax.groups:
                add(ERROR, f"taxonomy/{name}", f"tag '{tag}' references undefined group '{group}'")


def _check_tags(t: dict, kb: KB, where: str, add: _Sink) -> None:
    for path, tax_name in TAG_FIELDS:
        values = dig(t, path, [])
        if not isinstance(values, list):
            add(ERROR, where, f"{path} must be a list")
            continue
        tax = kb.taxonomies[tax_name]
        for tag in values:
            canonical, alias_of = tax.resolve(str(tag))
            if alias_of:
                add(ERROR, where, f"{path}: '{tag}' is an alias; use the canonical tag '{alias_of}'")
            elif canonical is None:
                add(ERROR, where, f"{path}: unknown tag '{tag}'. If this is a term the trader introduced, "
                                  f"add it to taxonomy/{tax_name}.yaml with introduced_in: {t.get('id')}")
    regime_tax = kb.taxonomies["regimes"]
    by_group: dict[str, list[str]] = {}
    for tag in t.get("regime") or []:
        grp = (regime_tax.tags.get(str(tag)) or {}).get("group")
        if grp and (regime_tax.groups.get(grp) or {}).get("exclusive"):
            by_group.setdefault(grp, []).append(str(tag))
    for grp, tags in by_group.items():
        if len(tags) > 1:
            add(ERROR, where, f"regime: {', '.join(tags)} are mutually exclusive ({grp})")


def _check_numbers(t: dict, where: str, add: _Sink) -> None:
    for path in NUMERIC:
        value = dig(t, path)
        if value is not None and num(value) is None:
            add(ERROR, where, f"{path} must be a plain number (no units, %, or thousands separators), "
                              f"got {value!r}")
    for path in ("plan.entry", "plan.stop", "fills.entry_avg", "risk.account_equity", "risk.leverage",
                 "risk.size", "risk.notional", "risk.risk_amount", "fills.duration_minutes"):
        value = num(dig(t, path))
        if value is not None and value <= 0:
            add(ERROR, where, f"{path} must be > 0")
    targets = dig(t, "plan.targets", [])
    if not isinstance(targets, list) or any(num(x) is None or num(x) <= 0 for x in targets):
        add(ERROR, where, "plan.targets must be a list of positive numbers")
    exits = dig(t, "fills.exits", [])
    if not isinstance(exits, list):
        add(ERROR, where, "fills.exits must be a list")
    else:
        for i, ex in enumerate(exits):
            if not isinstance(ex, dict):
                add(ERROR, where, f"fills.exits[{i}] must be a mapping with price and qty/fraction")
                continue
            for key in ("price", "qty", "fraction"):
                if ex.get(key) is not None and num(ex.get(key)) is None:
                    add(ERROR, where, f"fills.exits[{i}].{key} must be a number")
            fraction = num(ex.get("fraction"))
            if fraction is not None and not 0 < fraction <= 1:
                add(ERROR, where, f"fills.exits[{i}].fraction must be in (0, 1]")


def _check_timeframes(t: dict, where: str, add: _Sink, opened, closed) -> None:
    for path in ("timeframes.htf", "timeframes.execution"):
        value = dig(t, path)
        if value is not None and not TIMEFRAME_RE.match(str(value)):
            add(ERROR, where, f"{path} '{value}' is not a timeframe: use m/h/D/W/M, e.g. 1m, 15m, 4h, 1D "
                              f"(1M means one month)")
    chain = dig(t, "timeframes.chain", [])
    if not isinstance(chain, list):
        add(ERROR, where, "timeframes.chain must be a list, highest timeframe first")
        chain = []
    for value in chain:
        if not TIMEFRAME_RE.match(str(value)):
            add(ERROR, where, f"timeframes.chain entry '{value}' is not a timeframe (m/h/D/W/M)")
    top_down = dig(t, "timeframes.top_down")
    if top_down is not None and not isinstance(top_down, bool):
        add(ERROR, where, "timeframes.top_down must be true, false or null")
    elif top_down is True and len(chain) < 2:
        add(WARN, where, "top_down is true but timeframes.chain lists fewer than two timeframes")
    execution = dig(t, "timeframes.execution")
    if execution is not None and str(execution).endswith("M"):
        add(WARN, where, f"timeframes.execution '{execution}' means {str(execution)[:-1]} month(s). For minutes write "
                         f"'{str(execution)[:-1]}m'")
    if chain and execution is not None and str(chain[-1]) != str(execution):
        add(WARN, where, f"timeframes.chain should end at the execution timeframe ({execution})")
    minutes = num(dig(t, "fills.duration_minutes"))
    if minutes is not None and opened and closed:
        days = (closed - opened).days
        if minutes > (days + 1) * 1440 or minutes < max(0, days - 1) * 1440:
            add(WARN, where, f"fills.duration_minutes = {minutes:g} does not fit the dates "
                             f"({opened} to {closed}, {days} day(s))")


def _check_geometry(t: dict, where: str, add: _Sink) -> None:
    direction, entry, stop = t.get("direction"), model.entry_price(t), num(dig(t, "plan.stop"))
    if direction not in ("long", "short") or entry is None:
        return
    if stop is not None:
        if stop == entry:
            add(ERROR, where, "plan.stop equals entry: zero risk distance")
        elif (direction == "long") != (stop < entry):
            side = "below" if direction == "long" else "above"
            add(ERROR, where, f"{direction} stop {stop} must be {side} entry {entry}")
    for tp in dig(t, "plan.targets", []) or []:
        tp = num(tp)
        if tp is not None and (direction == "long") != (tp > entry):
            add(ERROR, where, f"target {tp} is on the loss side of entry {entry} for a {direction}")


def _check_risk(t: dict, kb: KB, where: str, add: _Sink) -> None:
    rc = kb.config["risk_checks"]
    stated, computed = num(dig(t, "risk.risk_amount")), model.computed_risk(t)
    if stated and computed:
        drift = computed / stated - 1
        if abs(drift) > rc["stated_vs_computed_tolerance"]:
            add(WARN, where, f"RISK: stated 1R = {stated:,.2f} but size x stop distance = {computed:,.2f} "
                             f"({drift:+.0%}). Oversized, or the recorded stop is not the initial stop?")
    equity, pct = num(dig(t, "risk.account_equity")), num(dig(t, "risk.risk_pct"))
    if pct is not None and pct > 10:
        add(WARN, where, f"risk.risk_pct = {pct}: this field is in PERCENT (1.0 = 1%). {pct} means {pct}% of equity")
    if equity and pct is not None and stated:
        implied = stated / equity * 100
        if abs(implied - pct) > max(0.05, pct * rc["stated_vs_computed_tolerance"]):
            add(WARN, where, f"risk_pct {pct}% disagrees with risk_amount/equity = {implied:.2f}%")
    max_pct = num(dig(kb.profile, "risk.max_risk_per_trade_pct"))
    actual_pct = pct if pct is not None else (stated / equity * 100 if stated and equity else None)
    mistakes = set(dig(t, "review.mistakes", []) or [])
    def breach(tag: str, msg: str) -> None:
        """A breach already tagged as a mistake is acknowledged: keep it visible, stop it nagging."""
        if tag in mistakes:
            add(INFO, where, f"{msg} (acknowledged: tagged {tag})")
        else:
            add(WARN, where, msg)
    if max_pct is not None and actual_pct is not None and actual_pct > max_pct + 1e-9:
        breach("oversized_position", f"RISK: {actual_pct:.2f}% of equity at risk exceeds your max {max_pct}% per trade")

    leverage, direction = num(dig(t, "risk.leverage")), t.get("direction")
    entry, stop, size = model.entry_price(t), num(dig(t, "plan.stop")), model.position_size(t)
    if leverage and direction in ("long", "short") and entry and stop:
        mode = dig(t, "risk.margin_mode")
        if mode is None:
            add(INFO, where, "risk.margin_mode unknown: liquidation vs stop not checked")
        else:
            mmr = num(dig(kb.profile, "leverage.maintenance_margin_rate")) or rc["default_mmr_rate"]
            liq = liquidation_price(entry, direction, size or 0, leverage=leverage, margin_mode=mode,
                                    mmr_rate=mmr, equity=equity)
            if liq is not None and ((direction == "long" and liq >= stop) or (direction == "short" and liq <= stop)):
                add(WARN, where, f"RISK: approx. liquidation {liq:,.6g} ({mode}, mmr {mmr}) is reached before "
                                 f"the stop {stop}: the stop could not protect this position")

    max_margin_loss = num(dig(kb.profile, "leverage.max_margin_loss_at_stop_pct"))
    if leverage and entry and stop and entry != stop and max_margin_loss is not None:
        margin_loss = abs(entry - stop) / entry * 100 * leverage
        if margin_loss > max_margin_loss + 1e-9:
            breach("excessive_leverage", f"RISK: stop distance x leverage = {margin_loss:.1f}% of the posted margin, above your "
                                         f"{max_margin_loss:g}% limit (max {fmt_cap(max_margin_loss / (abs(entry - stop) / entry * 100))} "
                                         f"for this stop)")
    min_rr = num(dig(kb.profile, "risk.min_rr"))
    rrs = [x for x in model.planned_rr(t) if x is not None]
    if min_rr is not None and rrs and max(rrs) < min_rr - 1e-9 and t.get("status") in ("planned", "open", "closed"):
        add(WARN, where, f"planned R:R {max(rrs):.2f} is below your {min_rr:g}R minimum")

    exits = model.resolved_exits(t)
    if size and exits and all(q is not None for _, q in exits) and t.get("status") == REALIZED:
        closed_qty = sum(q for _, q in exits)
        if abs(closed_qty / size - 1) > 0.01:
            add(WARN, where, f"exit quantities sum to {closed_qty:g} but position size is {size:g}")


def _check_review(t: dict, kb: KB, where: str, add: _Sink, outcome: str | None) -> None:
    for path, allowed in ENUMS.items():
        value = dig(t, path)
        if isinstance(value, bool):
            add(ERROR, where, f"{path}: YAML read a bare yes/no as {value}; quote it (\"yes\" / \"no\")")
        elif value is not None and value not in allowed:
            add(ERROR, where, f"{path} must be one of {', '.join(allowed)} (got {value!r})")
    for dim in model.DIMENSIONS:
        value = dig(t, f"review.scores.{dim}")
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5):
            add(ERROR, where, f"review.scores.{dim} must be an integer 1-5 or null")
    followed = dig(t, "review.followed_plan")
    if followed is not None and not isinstance(followed, bool):
        add(ERROR, where, "review.followed_plan must be true, false or null")

    loss_type = dig(t, "review.loss_type")
    mistakes = dig(t, "review.mistakes", []) or []
    if loss_type is not None:
        if str(loss_type) not in kb.taxonomies["loss_types"].tags:
            add(ERROR, where, f"review.loss_type must be one of {', '.join(kb.taxonomies['loss_types'].tags)}")
        elif outcome != "loss":
            add(WARN, where, f"review.loss_type {loss_type} set but outcome is {outcome}")
        elif loss_type == "A" and (mistakes or followed is False):
            add(WARN, where, "loss type A (good loss) contradicts recorded mistakes / plan deviation")
        elif loss_type == "C" and not mistakes:
            add(WARN, where, "loss type C (execution error) but no review.mistakes tagged")
        elif loss_type == "D" and dig(t, "review.setup_validity") != "invalid":
            add(WARN, where, "loss type D (invalid setup) but review.setup_validity is not 'invalid'")
    elif outcome == "loss" and dig(t, "review.lesson"):
        add(INFO, where, "reviewed loss without review.loss_type (A-E)")


def _check_trade(trade: Trade, kb: KB, add: _Sink) -> None:
    t, where = trade.data, trade.path.name
    tid = t.get("id")
    if not isinstance(tid, str) or not TRADE_ID_RE.match(tid):
        add(ERROR, where, "id must look like T-0001")
    elif trade.path.stem != tid:
        add(ERROR, where, f"filename must equal id ({tid}.yaml)")
    status = t.get("status")
    if status not in STATUSES:
        add(ERROR, where, f"status must be one of {', '.join(STATUSES)}")
    if t.get("direction") not in (None, "long", "short"):
        add(ERROR, where, "direction must be long, short or null")

    try:
        opened = as_date(t.get("opened"))
        if opened is None:
            add(ERROR, where, "opened date is required (YYYY-MM-DD)")
    except ValueError:
        opened = None
        add(ERROR, where, f"opened is not a YYYY-MM-DD date: {t.get('opened')!r}")
    try:
        closed = as_date(t.get("closed"))
    except ValueError:
        closed = None
        add(ERROR, where, f"closed is not a YYYY-MM-DD date: {t.get('closed')!r}")
    if opened and closed and closed < opened:
        add(ERROR, where, "closed date is before opened date")
    if status == REALIZED and closed is None:
        add(WARN, where, "closed trade has no closed date")

    _check_numbers(t, where, add)
    _check_timeframes(t, where, add, opened, closed)
    _check_tags(t, kb, where, add)
    _check_geometry(t, where, add)
    _check_risk(t, kb, where, add)

    d = derive(t, kb.config)
    _check_review(t, kb, where, add, d.outcome)

    has_result = num(dig(t, "result.pnl")) is not None or num(dig(t, "result.r")) is not None
    if status == REALIZED:
        if num(dig(t, "result.hypothetical_r")) is not None:
            add(ERROR, where, "result.hypothetical_r is for missed/not_taken trades only: it would mix "
                              "counterfactual and realized results")
        if d.r is None:
            add(WARN, where, f"R not computable, excluded from statistics. Needs: {', '.join(d.missing)}")
        if not str(dig(t, "journal.before", "")).strip():
            add(INFO, where, "no pre-trade thesis in journal.before: review is exposed to hindsight bias")
        if d.grade is None:
            add(INFO, where, "not yet reviewed: fewer than 3 process dimensions scored")
    elif status in COUNTERFACTUAL and has_result:
        add(ERROR, where, f"{status} trade carries result.pnl/result.r: use result.hypothetical_r")
    elif status == "planned" and has_result:
        add(ERROR, where, "planned trade carries a realized result")

    sid, version = dig(t, "strategy.id"), dig(t, "strategy.version")
    if sid is not None:
        strat = kb.strategies.get(str(sid))
        if strat is None:
            add(ERROR, where, f"strategy.id '{sid}' not found in playbook/strategies/")
        elif version is not None and str(version) not in strat.versions:
            add(ERROR, where, f"strategy '{sid}' has no version {version} "
                              f"(have: {', '.join(strat.versions) or 'none'})")
        elif version is None:
            add(WARN, where, f"strategy '{sid}' set without strategy.version: A/B by version impossible")
        else:
            stated_tf = ((strat.versions[str(version)] or {}).get("timeframes") or {}).get("execution")
            allowed_tf = [str(x) for x in stated_tf] if isinstance(stated_tf, list) else ([str(stated_tf)] if stated_tf else [])
            trade_tf = dig(t, "timeframes.execution")
            if allowed_tf and trade_tf and str(trade_tf) not in allowed_tf:
                add(WARN, where, f"execution timeframe {trade_tf} is not one of {sid} v{version}'s ({', '.join(allowed_tf)})")
            elif allowed_tf and not trade_tf:
                add(INFO, where, f"timeframes.execution is empty; {sid} v{version} uses {', '.join(allowed_tf)}")
            models = (strat.versions[str(version)] or {}).get("entry_models") or {}
            entry_model = dig(t, "plan.entry_model")
            if entry_model is not None and models and str(entry_model) not in models:
                add(ERROR, where, f"plan.entry_model '{entry_model}' is not an entry model of {sid} v{version} "
                                  f"(have: {', '.join(models)})")
    exp_id, variant = dig(t, "strategy.experiment"), dig(t, "strategy.variant")
    if exp_id is not None:
        exp = kb.experiments.get(str(exp_id))
        if exp is None:
            add(ERROR, where, f"strategy.experiment '{exp_id}' not found in playbook/experiments/")
        elif variant is None or str(variant) not in (exp.get("variants") or {}):
            add(ERROR, where, f"strategy.variant must name a variant of {exp_id}")

    for chart in dig(t, "evidence.charts", []) or []:
        if not (kb.root / str(chart)).exists():
            add(WARN, where, f"chart not found: {chart}")


def _check_strategies(kb: KB, add: _Sink) -> None:
    promo = kb.config["promotion"]
    realized_by_strategy: dict[str, int] = {}
    for trade in kb.trades:
        sid = dig(trade.data, "strategy.id")
        if sid and trade.status == REALIZED and derive(trade.data, kb.config).r is not None:
            realized_by_strategy[str(sid)] = realized_by_strategy.get(str(sid), 0) + 1
    trade_ids = {t.id for t in kb.trades}

    for slug, strat in kb.strategies.items():
        where, meta = f"strategies/{slug}", strat.meta
        if meta.get("id") != slug:
            add(ERROR, where, f"strategy.yaml id must equal directory name '{slug}'")
        status = meta.get("status")
        if status not in STRATEGY_STATUSES:
            add(ERROR, where, f"status must be one of {', '.join(STRATEGY_STATUSES)}")
        needed = (promo["strategy_min_trades"] or {}).get(status)
        have = realized_by_strategy.get(slug, 0)
        if needed and have < needed:
            add(ERROR, where, f"status '{status}' requires >= {needed} measured trades; have {have}. "
                              f"Promotion without evidence is exactly what this system forbids")
        current = str(meta.get("current_version"))
        if current not in strat.versions:
            add(ERROR, where, f"current_version {current} has no file v{current}.yaml")
        for key, doc in strat.versions.items():
            if str((doc or {}).get("version")) != key:
                add(ERROR, where, f"v{key}.yaml must contain version: \"{key}\"")

        seen = set()
        for i, ch in enumerate(strat.changes):
            cw = f"{where}/changes[{i}]"
            if not isinstance(ch, dict):
                add(ERROR, cw, "each change must be a mapping")
                continue
            cid = ch.get("id")
            if not isinstance(cid, str) or not CHANGE_ID_RE.match(cid):
                add(ERROR, cw, "id must look like CHG-001")
            elif cid in seen:
                add(ERROR, cw, f"duplicate change id {cid}")
            seen.add(cid)
            kind = ch.get("kind", "rule_change")
            cstatus = ch.get("status")
            if kind not in CHANGE_KINDS:
                add(ERROR, cw, f"kind must be one of {', '.join(CHANGE_KINDS)}")
                continue
            if kind == "clarification":
                # The trader stating rules that were already in force: no performance claim, no evidence gate.
                if cstatus != "adopted":
                    add(ERROR, cw, "a clarification has status 'adopted'")
                if not ch.get("statement"):
                    add(ERROR, cw, "a clarification must quote the trader's statement")
                if ch.get("rule_changed"):
                    add(ERROR, cw, "a clarification cannot change a rule: record a rule_change instead")
                resulting = ch.get("resulting_version")
                if resulting is None or str(resulting) not in strat.versions:
                    add(ERROR, cw, f"resulting_version {resulting} has no version file")
                continue
            if cstatus not in CHANGE_STATUSES or cstatus == "adopted":
                add(ERROR, cw, f"status must be one of {', '.join(CHANGE_STATUSES)}")
            evidence = ch.get("evidence") or []
            for ref in evidence:
                if ref not in trade_ids:
                    add(ERROR, cw, f"evidence references unknown trade {ref}")
            needed = (promo["change_min_evidence"] or {}).get(cstatus)
            if needed and len(evidence) < needed:
                add(ERROR, cw, f"status '{cstatus}' requires >= {needed} evidence trades; has {len(evidence)}")
            for field_name in ("current_rule", "observation", "hypothesis", "proposed_change",
                               "expected_effect", "overfitting_risk"):
                if not ch.get(field_name):
                    add(WARN, cw, f"missing {field_name} (required by the strategy-evolution protocol)")
            resulting = ch.get("resulting_version")
            if resulting is not None and str(resulting) not in strat.versions:
                add(ERROR, cw, f"resulting_version {resulting} has no version file")


def _check_experiments(kb: KB, add: _Sink) -> None:
    counts: dict[tuple[str, str], int] = {}
    for trade in kb.trades:
        exp, var = dig(trade.data, "strategy.experiment"), dig(trade.data, "strategy.variant")
        if exp and var and trade.status == REALIZED and derive(trade.data, kb.config).r is not None:
            counts[(str(exp), str(var))] = counts.get((str(exp), str(var)), 0) + 1
    for eid, exp in kb.experiments.items():
        where = f"experiments/{exp['_file']}"
        if not EXPERIMENT_ID_RE.match(eid):
            add(ERROR, where, "id must look like EXP-001")
        elif exp["_file"] != eid:
            add(ERROR, where, f"filename must equal id ({eid}.yaml)")
        if exp.get("status") not in EXPERIMENT_STATUSES:
            add(ERROR, where, f"status must be one of {', '.join(EXPERIMENT_STATUSES)}")
        variants = exp.get("variants")
        if not isinstance(variants, dict) or len(variants) < 2:
            add(ERROR, where, "variants must define at least two arms (A, B)")
            continue
        min_n = exp.get("min_n_per_variant") or kb.config["evidence_tiers"]["moderate_min_n"]
        if exp.get("status") == "concluded":
            short = {v: counts.get((eid, str(v)), 0) for v in variants if counts.get((eid, str(v)), 0) < min_n}
            if short:
                add(WARN, where, f"concluded below min_n_per_variant={min_n}: "
                                 + ", ".join(f"{v}={n}" for v, n in short.items()))


def _check_automation(kb: KB, add: _Sink) -> None:
    from .readiness import MANUAL_STATES, METRICS
    doc, where = kb.automation, "playbook/automation.yaml"
    if not doc:
        return
    for i, st in enumerate(doc.get("stages") or []):
        for j, c in enumerate((st or {}).get("criteria") or []):
            cw = f"{where}: stages[{i}].criteria[{j}]"
            if "metric" in c:
                if c["metric"] not in METRICS:
                    add(ERROR, cw, f"unknown metric '{c['metric']}' (have: {', '.join(METRICS)})")
                if c.get("min") is None and c.get("max") is None:
                    add(ERROR, cw, "a computed criterion needs min or max")
            else:
                state = c.get("manual", "pending")
                if state not in MANUAL_STATES:
                    add(ERROR, cw, f"manual must be one of {', '.join(MANUAL_STATES)}")
                elif state == "done" and not c.get("evidence"):
                    add(ERROR, cw, "a manual criterion marked done must cite its evidence")


def version_edits(kb: KB) -> list[str] | None:
    """Committed strategy version files modified/deleted in the working tree. None if git is unavailable."""
    try:
        out = subprocess.run(["git", "-C", str(kb.root), "diff", "--name-status", "HEAD", "--",
                              "playbook/strategies"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    edits = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0][:1] in "MDR" and VERSION_FILE_RE.match(parts[1]):
            edits.append(f"{parts[0][:1]} {parts[1]}")
    return edits


def _check_build(kb: KB, add: _Sink) -> None:
    from .export import OUTPUTS, embedded_fingerprint, fingerprint
    current = fingerprint(kb.root)
    for rel in OUTPUTS:
        path = kb.root / rel
        if not path.exists():
            add(INFO, rel, "not built yet: run ./tj build")
        elif embedded_fingerprint(path) != current:
            add(WARN, rel, "stale: the knowledge base changed since the last build. Run ./tj build")


def validate(kb: KB, allow_version_edits: bool = False, check_build: bool = True) -> list[Issue]:
    add = _Sink()
    for err in kb.load_errors:
        add(ERROR, "load", err)
    _check_taxonomies(kb, add)

    ids: dict[str, str] = {}
    for trade in kb.trades:
        if trade.id in ids:
            add(ERROR, trade.path.name, f"duplicate id {trade.id} (also in {ids[trade.id]})")
        ids[trade.id] = trade.path.name
        _check_trade(trade, kb, add)

    _check_strategies(kb, add)
    _check_experiments(kb, add)
    _check_automation(kb, add)

    edits = version_edits(kb)
    for edit in edits or []:
        add(WARN if allow_version_edits else ERROR, "playbook",
            f"strategy version files are immutable once committed ({edit}). "
            f"Create a new version file and record the change in changes.yaml instead")

    if check_build:
        _check_build(kb, add)

    gaps = unresolved(kb.profile)
    if gaps:
        add(INFO, "profile/trader.yaml", f"{len(gaps)} unresolved parameter(s): learn them from the trader, "
                                         f"never assume: {', '.join(gaps)}")
    order = {ERROR: 0, WARN: 1, INFO: 2}
    return sorted(add.issues, key=lambda i: order[i.level])
