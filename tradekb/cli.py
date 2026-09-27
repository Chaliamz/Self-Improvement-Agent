"""`tj` — the trading journal command line. Run `./tj <command> -h` for options."""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from . import analysis, report
from .model import num
from .risk import CRITICAL, SizingInput, fmt_cap, size_position
from .stats import compare
from .store import KB, KBError, create_trade, dig, load_kb
from .validate import validate


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def cmd_status(kb: KB, args) -> int:
    print(report.status(kb, validate(kb)))
    return 0


def cmd_validate(kb: KB, args) -> int:
    issues = validate(kb, allow_version_edits=args.allow_version_edits)
    shown = [i for i in issues if args.verbose or i.level != "INFO"]
    for issue in shown:
        print(issue)
    errors = sum(1 for i in issues if i.level == "ERROR")
    warns = sum(1 for i in issues if i.level == "WARN")
    infos = sum(1 for i in issues if i.level == "INFO")
    print(f"\n{errors} error(s), {warns} warning(s), {infos} info" + ("" if args.verbose else " (use -v to list)"))
    return 1 if errors or (args.strict and warns) else 0


def cmd_new(kb: KB, args) -> int:
    path = create_trade(kb, status=args.status, opened=args.date or dt.date.today(),
                        asset=args.asset, direction=args.direction, market=args.market)
    print(path.relative_to(kb.root))
    return 0


def cmd_show(kb: KB, args) -> int:
    trade = kb.trade(args.id)
    if trade is None:
        print(f"error: no trade {args.id}", file=sys.stderr)
        return 2
    row = next(r for r in analysis.rows(kb) if r.trade.id == args.id)
    print(report.show_trade(kb, row, validate(kb)))
    return 0


def cmd_size(kb: KB, args) -> int:
    p = kb.profile
    rc = kb.config["risk_checks"]
    sources: list[tuple[str, str, str]] = []

    def pick(name, arg_value, profile_path, default=None, default_note="default (assumption)"):
        if arg_value is not None:
            sources.append((name, str(arg_value), "argument"))
            return arg_value
        prof = num(dig(p, profile_path)) if profile_path else None
        if prof is not None:
            sources.append((name, str(prof), f"profile {profile_path}"))
            return prof
        if default is not None:
            sources.append((name, str(default), default_note))
        return default

    equity = pick("equity", args.equity, "account.equity")
    if args.risk_amount is not None:
        risk_amount = args.risk_amount
        sources.append(("risk amount", f"{risk_amount:,.2f}", "argument"))
    else:
        risk_pct = pick("risk %", args.risk_pct, "risk.risk_per_trade_pct")
        if risk_pct is None:
            print("error: risk per trade is UNRESOLVED. Pass --risk-amount, or --risk-pct with --equity, "
                  "or record it in profile/trader.yaml once the trader states it.", file=sys.stderr)
            return 2
        if equity is None:
            print("error: --risk-pct needs account equity (--equity or profile account.equity).", file=sys.stderr)
            return 2
        risk_amount = equity * risk_pct / 100
    fee_rate = pick("fee rate (per side, decimal)", args.fee_rate, "fees.taker_rate", 0.0, "0 — FEES EXCLUDED")
    mmr = pick("maintenance margin rate", args.mmr_rate, "leverage.maintenance_margin_rate",
               rc["default_mmr_rate"])
    margin_mode = args.margin_mode or dig(p, "leverage.margin_mode")
    if args.leverage and margin_mode is None:
        margin_mode = "isolated"
        sources.append(("margin mode", "isolated", "ASSUMED — pass --margin-mode"))
    elif margin_mode:
        sources.append(("margin mode", margin_mode, "argument" if args.margin_mode else "profile"))
    if args.leverage:
        sources.append(("leverage setting", f"{args.leverage:g}x", "argument"))
    if args.slippage_pct:
        sources.append(("stop slippage", f"{args.slippage_pct}%", "argument"))

    inp = SizingInput(
        entry=args.entry, stop=args.stop, risk_amount=risk_amount, side=args.side, equity=equity,
        leverage=args.leverage, margin_mode=margin_mode or "isolated", mmr_rate=mmr, fee_rate=fee_rate,
        slippage_pct=args.slippage_pct, qty_step=args.qty_step, targets=tuple(args.target or ()),
        max_risk_pct=num(dig(p, "risk.max_risk_per_trade_pct")),
        max_leverage=num(dig(p, "leverage.max_leverage")),
        max_margin_loss_pct=num(dig(p, "leverage.max_margin_loss_at_stop_pct")),
        margin_loss_tolerance_pct=num(dig(p, "leverage.margin_loss_tolerance_pct")),
        min_rr=num(dig(p, "risk.min_rr")),
        fee_share_warn=rc["fee_share_warn"], liq_buffer_warn=rc["liq_buffer_warn"],
    )
    res = size_position(inp)

    print(f"## Position size — {res.side.upper()}\n")
    print("| Input | Value | Source |\n|---|---|---|")
    print(f"| entry / stop | {args.entry:g} / {args.stop:g} | argument |")
    for name, value, src in sources:
        print(f"| {name} | {value} | {src} |")
    print("\n| Output | Value |\n|---|---|")
    qty = f"{res.qty:.8g}" + (f" (unrounded {res.qty_unrounded:.8g})" if args.qty_step else "")
    print(f"| Quantity (base units) | {qty} |")
    print(f"| Notional | {res.notional:,.2f} |")
    print(f"| Stop distance | {res.stop_distance_pct:.3f}% |")
    risk_line = f"{res.loss_at_stop:,.2f}" + (f" = {res.risk_pct:.2f}% of equity" if res.risk_pct is not None else "")
    print(f"| Loss at stop (incl. fees & slippage) | {risk_line} |")
    if res.effective_leverage is not None:
        print(f"| Effective leverage (notional / equity) | {res.effective_leverage:.2f}x |")
    if res.margin_required is not None:
        print(f"| Margin posted at {args.leverage:g}x | {res.margin_required:,.2f} |")
    if res.margin_loss_pct is not None:
        print(f"| Loss on margin at stop (isolated) | {res.margin_loss_pct:.1f}% |")
    if res.max_leverage_for_rule is not None:
        print(f"| Max leverage for your {inp.max_margin_loss_pct:g}% margin-loss target | {fmt_cap(res.max_leverage_for_rule)} |")
    if res.max_leverage_for_tolerance is not None:
        print(f"| Max leverage within your {inp.margin_loss_tolerance_pct:g}% tolerance | {fmt_cap(res.max_leverage_for_tolerance)} |")
    if res.liquidation is not None:
        print(f"| Liquidation, {margin_mode} (approx.) | {res.liquidation:,.6g} "
              f"({res.liq_to_stop_ratio:.2f}x stop distance) |")
    elif args.leverage or margin_mode == "cross":
        print("| Liquidation | not reachable / not computable with these inputs |")
    if res.targets:
        print("\n| Target | R:R gross | R:R net of fees |\n|---|---:|---:|")
        for tgt in res.targets:
            print(f"| {tgt.price:g} | {tgt.rr_gross:.2f} | {tgt.rr_net:.2f} |")
    if res.flags:
        print("\nFlags:")
        for level, msg in res.flags:
            print(f"- **{level}** {msg}")
    if args.leverage:
        print("\nLeverage changes margin posted and liquidation distance only. Loss at stop is fixed by "
              "size × stop distance.")
    print("\nLiquidation is a single-tier approximation (no fees, funding, or tiered MMR); the exchange figure "
          "is authoritative. Linear contracts / spot only.")
    return 1 if any(level == CRITICAL for level, _ in res.flags) else 0


def _scoped(kb: KB, args) -> list:
    return analysis.apply_filters(analysis.realized(kb), analysis.parse_where(args.where), args.since)


def cmd_stats(kb: KB, args) -> int:
    rs = _scoped(kb, args)
    if args.by:
        print(report.grouped_table(kb, rs, args.by))
    else:
        print(report.summary_table("scope", [("all", analysis.summarize_rows(rs, kb))]))
    print(f"\nn = {len(rs)} closed trades with computable R in scope.")
    return 0


def cmd_errors(kb: KB, args) -> int:
    print(report.errors_section(kb))
    return 0


def cmd_compare(kb: KB, args) -> int:
    rs = _scoped(kb, args)
    arm_a = [row for row in rs if args.a in analysis.labels(row, args.field)]
    arm_b = [row for row in rs if args.b in analysis.labels(row, args.field)]
    overlap = {r.trade.id for r in arm_a} & {r.trade.id for r in arm_b}
    if overlap:
        print(f"note: {len(overlap)} trade(s) are in both arms ({', '.join(sorted(overlap))}); "
              f"the arms are not independent.\n")
    result = compare([r.d.r for r in arm_a], [r.d.r for r in arm_b], kb.config,
                     analysis.conditions(arm_a, kb.config, kb), analysis.conditions(arm_b, kb.config, kb))
    print(report.comparison(f"{args.field}={args.a}", f"{args.field}={args.b}", result))
    return 0


def cmd_report(kb: KB, args) -> int:
    rs = _scoped(kb, args)
    scope = f"closed trades with computable R (n={len(rs)})"
    if args.where or args.since:
        scope += f", filters: {' '.join(args.where or [])}{' since ' + args.since.isoformat() if args.since else ''}"
    print(report.full_report(kb, rs, scope))
    return 0


def cmd_build(kb: KB, args) -> int:
    from .export import build
    result = build(kb)
    print(f"built terminal.html ({result['bytes'] / 1024:,.0f} KiB) and exports/kb.json · "
          f"{result['trades']} trade record(s) · fingerprint {result['fingerprint']}")
    if result["errors"]:
        print(f"warning: built with {result['errors']} validation error(s); run ./tj validate", file=sys.stderr)
        return 1
    return 0


def cmd_audit(kb: KB, args) -> int:
    from .audit import run
    result = run(kb, check_outputs=not args.no_outputs)
    for ok, message in result.results:
        if args.verbose or not ok:
            print(("PASS  " if ok else "FAIL  ") + message)
    failed = len(result.failures)
    print(f"\naudit: {len(result.results) - failed} passed, {failed} failed")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tj", description="Trading journal and knowledge base.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="session briefing: counts, phase, unresolved parameters, recurring errors")

    v = sub.add_parser("validate", help="integrity checks; exit 1 on errors")
    v.add_argument("--strict", action="store_true", help="also fail on warnings")
    v.add_argument("-v", "--verbose", action="store_true", help="also list INFO items")
    v.add_argument("--allow-version-edits", action="store_true",
                   help="downgrade edits to committed strategy version files to warnings (typo fixes only)")

    n = sub.add_parser("new", help="create the next trade record from the template")
    n.add_argument("--status", default="closed", choices=("planned", "open", "closed", "missed", "not_taken"))
    n.add_argument("--asset")
    n.add_argument("--direction", choices=("long", "short"))
    n.add_argument("--market")
    n.add_argument("--date", type=_date, help="opened date, default today")

    s = sub.add_parser("show", help="derived metrics and validation for one trade")
    s.add_argument("id")

    z = sub.add_parser("size", help="position size, exposure and liquidation decomposition")
    z.add_argument("--entry", type=float, required=True)
    z.add_argument("--stop", type=float, required=True)
    z.add_argument("--side", choices=("long", "short"), help="asserted side; errors if the stop contradicts it")
    z.add_argument("--risk-amount", type=float, help="money lost at stop (1R)")
    z.add_argument("--risk-pct", type=float, help="percent of equity, 1.0 = 1%%")
    z.add_argument("--equity", type=float)
    z.add_argument("--leverage", type=float)
    z.add_argument("--margin-mode", choices=("isolated", "cross"))
    z.add_argument("--mmr-rate", type=float, help="maintenance margin rate, decimal (0.005 = 0.5%%)")
    z.add_argument("--fee-rate", type=float, help="fee per side, decimal (0.0005 = 5 bps)")
    z.add_argument("--slippage-pct", type=float, default=0.0, help="adverse stop slippage, percent")
    z.add_argument("--qty-step", type=float, help="exchange quantity step; size is floored to it")
    z.add_argument("--target", type=float, action="append", help="repeatable")

    for name, helptext in (("stats", "performance summary, optionally grouped"),
                           ("report", "full quantitative review (input to the periodic review)")):
        p = sub.add_parser(name, help=helptext)
        if name == "stats":
            p.add_argument("--by", choices=sorted(analysis.GROUPERS))
        p.add_argument("--where", action="append", metavar="FIELD=VALUE")
        p.add_argument("--since", type=_date)

    sub.add_parser("errors", help="recurring-error and behaviour databases")
    sub.add_parser("build", help="rebuild terminal.html and exports/kb.json from the knowledge base")
    au = sub.add_parser("audit", help="recompute every published number and check outputs on disk")
    au.add_argument("-v", "--verbose", action="store_true", help="list passing checks too")
    au.add_argument("--no-outputs", action="store_true", help="skip kb.json / terminal.html comparison")

    c = sub.add_parser("compare", help="A/B comparison with a bootstrap CI on the expectancy difference")
    c.add_argument("field", choices=sorted(analysis.GROUPERS))
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--where", action="append", metavar="FIELD=VALUE")
    c.add_argument("--since", type=_date)
    return parser


COMMANDS = {"status": cmd_status, "validate": cmd_validate, "new": cmd_new, "show": cmd_show,
            "size": cmd_size, "stats": cmd_stats, "errors": cmd_errors, "compare": cmd_compare,
            "report": cmd_report, "build": cmd_build, "audit": cmd_audit}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        kb = load_kb()
        return COMMANDS[args.cmd](kb, args)
    except (KBError, ValueError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
