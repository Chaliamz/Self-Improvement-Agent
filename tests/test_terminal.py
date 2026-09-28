"""Build outputs, the terminal script, rule compliance, and schema rules."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import yaml

from tradekb import analysis
from tradekb.export import build_payload
from tradekb.risk import (SizingInput, exposure, fmt_cap, liquidation_price, margin_status,
                          max_leverage_liq_beyond_stop, size_position, split_plan)
from tradekb.store import load_kb
from tradekb.validate import validate
from tests.test_kb import REPO, KBTestCase

NODE = shutil.which("node")
TEMPLATE = REPO / "templates" / "terminal.html"


@unittest.skipUnless(NODE, "node not installed")
class InlineScriptTest(unittest.TestCase):
    def test_leverage_cap_never_rounds_up(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        line = re.search(r"^const fmtCap = .*?;", text, re.M).group(0)
        cases = [50 / (3.42 / 54.44 * 100), 50 / (0.498 / 12.98 * 100), 50 / 6.25, 50 / 3.14]
        script = "const isNum = x => typeof x === 'number' && isFinite(x);\n" + line + f"\nconsole.log(JSON.stringify({json.dumps(cases)}.map(fmtCap)));"
        out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), [fmt_cap(x) for x in cases])  # JS and Python agree
        self.assertEqual(json.loads(out.stdout), ["7.95x", "13.03x", "8.00x", "15.92x"])

    def test_inline_script_parses(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        scripts = re.findall(r"<script>(.*?)</script>", text, re.S)
        self.assertTrue(scripts)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write("\n".join(scripts))
        out = subprocess.run([NODE, "--check", fh.name], capture_output=True, text=True, timeout=30)
        Path(fh.name).unlink()
        self.assertEqual(out.returncode, 0, out.stderr)


class ExposureTest(unittest.TestCase):
    def test_t0001_decomposition(self):
        e = exposure(90.41, 87.59, risk_pct=1.0, leverage=10, margin_mode=None)
        self.assertAlmostEqual(e["stop_pct"], 2.82 / 90.41 * 100)
        self.assertAlmostEqual(e["notional_pct"], 1.0 / e["stop_pct"] * 100)
        self.assertAlmostEqual(e["margin_pct"], e["notional_pct"] / 10)
        self.assertAlmostEqual(e["liq_isolated"], 90.41 * 0.9 / 0.995)
        self.assertTrue(e["liq_mode_assumed"])
        self.assertFalse(e["liq_before_stop"])

    def test_margin_loss_rule(self):
        e = exposure(90.41, 87.59, risk_pct=1.0, leverage=20, margin_mode="isolated", max_margin_loss_pct=50)
        self.assertAlmostEqual(e["margin_loss_pct"], 2.82 / 90.41 * 100 * 20)
        self.assertTrue(e["margin_loss_breach"])
        self.assertAlmostEqual(e["max_leverage_for_rule"], 50 / (2.82 / 90.41 * 100))
        self.assertFalse(exposure(90.41, 87.59, 1.0, leverage=10, max_margin_loss_pct=50)["margin_loss_breach"])

    def test_sizing_flags_margin_rule_and_min_rr(self):
        res = size_position(SizingInput(entry=90.41, stop=87.59, risk_amount=100, leverage=20,
                                        max_margin_loss_pct=50, min_rr=5, targets=(103.30,)))
        messages = " ".join(m for _, m in res.flags)
        self.assertIn("above your 50% limit", messages)
        self.assertIn("below your 5R minimum", messages)

    def test_cap_display_is_floored_and_obeys_the_rule(self):
        # T-0006: 6.282% stop, cap 7.959x. Printing "8.0x" would invite a 50.3% margin loss.
        stop_pct = 3.42 / 54.44 * 100
        self.assertEqual(fmt_cap(50 / stop_pct), "7.95x")
        self.assertLessEqual(float(fmt_cap(50 / stop_pct)[:-1]) * stop_pct, 50)
        res = size_position(SizingInput(entry=54.44, stop=51.02, risk_amount=100, leverage=8, max_margin_loss_pct=50))
        self.assertTrue(any("use 7.95x or less" in m for _, m in res.flags))

    def test_margin_aim_50_to_60(self):
        # trader, 2026-09-28: "always aim for 50-60% at the stop". Above 60% is a breach; below 50% is not a risk problem.
        self.assertEqual(margin_status(44.0, 60, 50), "below_aim")
        self.assertEqual(margin_status(50.3, 60, 50), "within")
        self.assertEqual(margin_status(60.0, 60, 50), "within")
        self.assertEqual(margin_status(60.1, 60, 50), "breach")
        self.assertEqual(margin_status(12.3, 60), "within")               # no aim recorded: only the limit applies
        self.assertIsNone(margin_status(None, 60, 50))
        base = dict(entry=54.44, stop=51.02, risk_amount=100, max_margin_loss_pct=60, margin_loss_aim_min_pct=50)
        at8 = size_position(SizingInput(leverage=8, **base))              # T-0006 at 8x: 50.3%, inside the aim
        self.assertEqual(at8.flags, [])
        self.assertAlmostEqual(at8.min_leverage_for_aim, 50 / (3.42 / 54.44 * 100))
        self.assertEqual(fmt_cap(at8.max_leverage_for_rule), "9.55x")
        at7 = size_position(SizingInput(leverage=7, **base))              # 44.0%: a NOTE, never a warning
        self.assertEqual([lvl for lvl, _ in at7.flags], ["NOTE"])
        self.assertIn("below your 50-60% aim (7.96x reaches it)", at7.flags[0][1])
        at10 = size_position(SizingInput(leverage=10, **base))            # 62.8%
        self.assertTrue(any(lvl == "CRITICAL" and "above your 60% limit: use 9.55x or less" in m for lvl, m in at10.flags))
        e = exposure(54.44, 51.02, 1.0, leverage=7, margin_mode="isolated", max_margin_loss_pct=60, margin_loss_aim_min_pct=50)
        self.assertTrue(e["margin_loss_below_aim"]); self.assertFalse(e["margin_loss_breach"])
        self.assertAlmostEqual(e["min_leverage_for_aim"], 50 / (3.42 / 54.44 * 100))
        e8 = exposure(54.44, 51.02, 1.0, leverage=8, margin_mode="isolated", max_margin_loss_pct=60, margin_loss_aim_min_pct=50)
        self.assertFalse(e8["margin_loss_below_aim"]); self.assertFalse(e8["margin_loss_breach"])

    def test_liquidation_cap_sits_exactly_at_the_stop(self):
        for entry, stop, side in ((100, 99.4, "long"), (100, 100.6, "short"), (54.44, 51.02, "long"), (0.01298, 0.013478, "short")):
            for mmr in (0.0, 0.005, 0.01):
                cap = max_leverage_liq_beyond_stop(entry, stop, mmr)
                self.assertAlmostEqual(liquidation_price(entry, side, 1.0, leverage=cap, margin_mode="isolated", mmr_rate=mmr),
                                       stop, delta=abs(entry - stop) * 1e-9)
                over = liquidation_price(entry, side, 1.0, leverage=cap * 1.01, margin_mode="isolated", mmr_rate=mmr)
                self.assertTrue(over > stop if side == "long" else over < stop, "above the cap, liquidation comes first")
        self.assertEqual(fmt_cap(max_leverage_liq_beyond_stop(100, 99.4, 0.005)), "91.15x")

    def test_tight_stop_aim_is_capped_by_liquidation(self):
        base = dict(risk_amount=100, max_margin_loss_pct=60, margin_loss_aim_min_pct=50, mmr_rate=0.005)
        at100 = size_position(SizingInput(entry=100, stop=99.4, leverage=100, **base))   # exactly 60%, yet liquidated first
        self.assertTrue(any(lvl == "CRITICAL" and "BEFORE the stop" in m for lvl, m in at100.flags))
        self.assertEqual(fmt_cap(at100.max_leverage_liq_beyond_stop), "91.15x")
        tight = size_position(SizingInput(entry=100, stop=99.8, **base))                  # 0.2% stop: the aim needs 250x
        self.assertTrue(any(lvl == "WARN" and "the aim cannot be met" in m for lvl, m in tight.flags))
        e = exposure(100, 99.4, 1.0, margin_mode="isolated", mmr_rate=0.005, max_margin_loss_pct=60, margin_loss_aim_min_pct=50)
        self.assertTrue(e["liq_binds"])
        self.assertEqual(fmt_cap(e["max_leverage_safe"]), "91.15x")                       # not the rule's 100x
        wide = exposure(54.44, 51.02, 1.0, margin_mode="isolated", mmr_rate=0.005, max_margin_loss_pct=60)
        self.assertFalse(wide["liq_binds"]); self.assertEqual(wide["max_leverage_safe"], wide["max_leverage_for_rule"])
        self.assertNotIn("max_leverage_liq", exposure(100, 99.4, 1.0, margin_mode="cross", max_margin_loss_pct=60))

    def test_cross_mode_has_no_isolated_liquidation(self):
        self.assertNotIn("liq_isolated", exposure(100, 98, 1.0, leverage=10, margin_mode="cross"))


class BuildTest(KBTestCase):
    def test_build_outputs_and_staleness(self):
        self.write_trade("T-0001", result={"r": 2.0}, journal={"before": "</script><script>alert(1)</script>"})
        self.assertTrue(any(i.where == "terminal.html" and "not built" in i.msg for i in self.issues("INFO")))
        code, out = self.run_cli("build")
        self.assertEqual(code, 0, out)
        kb_json = json.loads((self.tmp / "exports" / "kb.json").read_text())
        self.assertEqual(kb_json["schema_version"], 1)
        self.assertEqual(kb_json["trades"][0]["derived"]["r"], 2.0)
        self.assertEqual(kb_json["stats"]["overall"]["n"], 1)
        html = (self.tmp / "terminal.html").read_text()
        self.assertIn(f'content="{kb_json["fingerprint"]}"', html)
        payload = html.split('<script id="kb-data" type="application/json">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(payload)["trades"][0]["journal"]["before"], "</script><script>alert(1)</script>")
        self.assertEqual([i for i in self.issues() if i.where in ("terminal.html", "exports/kb.json")], [])
        self.write_trade("T-0001", result={"r": -1.0})
        stale = [i for i in self.issues("WARN") if "stale" in i.msg]
        self.assertEqual({i.where for i in stale}, {"terminal.html", "exports/kb.json"})

    def test_build_is_deterministic_apart_from_timestamp(self):
        self.write_trade("T-0001", result={"r": 1.0})
        self.run_cli("build")
        first = json.loads((self.tmp / "exports" / "kb.json").read_text())
        self.run_cli("build")
        second = json.loads((self.tmp / "exports" / "kb.json").read_text())
        first.pop("build"); second.pop("build")
        self.assertEqual(first, second)


class ReadinessAndRulesTest(KBTestCase):
    def test_required_trades_formula(self):
        from tradekb.stats import required_trades
        r = required_trades(0.35, 3.5)
        self.assertAlmostEqual(r["expectancy"], 0.575)
        self.assertEqual(r["n"], 110)
        self.assertIsNone(required_trades(0.25, 3.0)["n"])  # negative edge can never be proven

    def test_readiness_gates_are_ordered(self):
        import yaml as _yaml
        (self.tmp / "playbook" / "automation.yaml").write_text(_yaml.safe_dump({"stages": [
            {"id": "a", "name": "A", "criteria": [{"label": "trades", "metric": "measured_trades", "min": 2}]},
            {"id": "b", "name": "B", "criteria": [{"label": "manual", "manual": "done", "evidence": "report.md"}]}]}))
        from tradekb.readiness import evaluate
        self.write_trade("T-0001", result={"r": 1.0})
        stages = evaluate(load_kb())["stages"]
        self.assertEqual([s["status"] for s in stages], ["active", "locked"])
        self.write_trade("T-0002", result={"r": -1.0})
        stages = evaluate(load_kb())["stages"]
        self.assertEqual([s["status"] for s in stages], ["done", "done"])

    def test_manual_done_requires_evidence_and_metric_must_exist(self):
        import yaml as _yaml
        (self.tmp / "playbook" / "automation.yaml").write_text(_yaml.safe_dump({"stages": [
            {"id": "a", "criteria": [{"label": "x", "manual": "done"}, {"label": "y", "metric": "vibes", "min": 1}]}]}))
        msgs = [i.msg for i in self.issues("ERROR")]
        self.assertTrue(any("must cite its evidence" in m for m in msgs))
        self.assertTrue(any("unknown metric 'vibes'" in m for m in msgs))

    def test_profile_rules_flag_trades(self):
        import yaml as _yaml
        prof = _yaml.safe_load((self.tmp / "profile" / "trader.yaml").read_text())
        prof["leverage"]["max_margin_loss_at_stop_pct"] = 60
        prof["leverage"]["margin_loss_aim_min_pct"] = 50
        prof["risk"]["min_rr"] = 2.5
        (self.tmp / "profile" / "trader.yaml").write_text(_yaml.safe_dump(prof))
        self.write_trade("T-0001", result={"r": 1.0}, risk={"risk_amount": 100, "leverage": 25},
                         plan={"entry": 100, "stop": 97, "targets": [104]})
        warns = [i.msg for i in self.issues("WARN")]
        self.assertTrue(any("above your 60% limit (max 20.00x for this stop)" in m for m in warns))  # 75% of margin
        self.assertTrue(any("below your 2.5R minimum" in m for m in warns))


class RuleComplianceTest(KBTestCase):
    """The trader's stated rules (live profile: 1% cap, 60% margin limit, 2.5R minimum) checked per taken trade."""

    def checks(self):
        kb = load_kb()
        return {row.trade.id: analysis.rule_checks(row, kb) for row in analysis.rows(kb, analysis.TAKEN)}

    def test_fields_decide_each_rule(self):
        # stop 3.837% x 20 = 76.7% of margin: broken. 4.07R planned: kept. 1% risk: kept.
        self.write_trade("T-0001", direction="short", plan={"entry": 0.012980, "stop": 0.013478, "targets": [0.010954]},
                         risk={"risk_pct": 1.0, "leverage": 20}, timeframes={"execution": "5m", "chain": ["4h", "5m"], "top_down": False},
                         review={"setup_validity": "invalid", "mistakes": [], "behaviors": ["respected_invalidation"]}, result={"r": -1.0})
        # stop 3.12% x 10 = 31.2%: kept. 1.5R planned: broken. 2% risk: broken. Nothing recorded: unknown.
        self.write_trade("T-0002", plan={"entry": 90.41, "stop": 87.59, "targets": [94.64]}, risk={"risk_pct": 2.0, "leverage": 10},
                         result={"r": 1.5})
        c = self.checks()
        self.assertEqual(c["T-0001"], {"top_down": False, "setup_valid": False, "risk_pct": True, "leverage": False,
                                       "min_rr": True, "stop": True})
        self.assertEqual(c["T-0002"], {"top_down": None, "setup_valid": None, "risk_pct": False, "leverage": True,
                                       "min_rr": False, "stop": None})

    def test_tagged_mistake_breaks_its_rule_without_fields(self):
        self.write_trade("T-0001", risk={"risk_amount": 100}, timeframes={"top_down": True},
                         review={"mistakes": ["excessive_leverage", "moved_stop", "oversized_position", "ignored_htf"],
                                 "behaviors": ["respected_invalidation"]}, result={"r": -1.0})
        c = self.checks()["T-0001"]
        self.assertEqual((c["leverage"], c["stop"], c["risk_pct"], c["top_down"]), (False, False, False, False))

    def test_only_taken_trades_are_checked_and_split_sums(self):
        self.write_trade("T-0001", risk={"risk_pct": 1.0}, result={"r": 2.0})
        self.write_trade("T-0002", risk={"risk_pct": 3.0}, result={"r": -1.0})
        self.write_trade("T-0003", status="missed", closed=None, result={"hypothetical_r": 3.0})
        p = build_payload(load_kb())
        by_id = {t["id"]: t for t in p["trades"]}
        self.assertIsNone(by_id["T-0003"]["derived"]["rule_checks"])
        rules = p["stats"]["rules"]
        self.assertEqual(rules["counts"]["risk_pct"], {"kept": 1, "broken": 1, "unknown": 0})
        self.assertEqual((rules["none_broken"]["n"], rules["none_broken"]["total"]), (1, 2.0))
        self.assertEqual((rules["any_broken"]["n"], rules["any_broken"]["total"]), (1, -1.0))
        self.assertEqual([d["key"] for d in rules["definitions"]], ["top_down", "setup_valid", "risk_pct", "leverage", "min_rr", "stop"])
        self.assertIn("at most 60% of margin (aim 50-60%)", rules["definitions"][3]["rule"])


class MarginAimRecordsTest(KBTestCase):
    def test_validator_and_rule_check_use_the_limit(self):
        prof = yaml.safe_load((self.tmp / "profile" / "trader.yaml").read_text())
        prof["leverage"].update(max_margin_loss_at_stop_pct=60, margin_loss_aim_min_pct=50)
        (self.tmp / "profile" / "trader.yaml").write_text(yaml.safe_dump(prof))
        plan = {"entry": 54.44, "stop": 51.02, "targets": [66.10]}
        self.write_trade("T-0001", plan=plan, risk={"risk_pct": 1.0, "leverage": 7}, result={"r": 3.41})    # 44.0%: below aim
        self.write_trade("T-0002", plan=plan, risk={"risk_pct": 1.0, "leverage": 9}, result={"r": 3.41})    # 56.5%: inside
        self.write_trade("T-0003", plan=plan, risk={"risk_pct": 1.0, "leverage": 10}, result={"r": 3.41})   # 62.8%: breach
        msgs = [(i.level, i.where, i.msg) for i in self.issues() if "of the posted margin" in i.msg]
        self.assertEqual([w for _, w, _ in msgs], ["T-0003.yaml"])
        self.assertEqual(msgs[0][0], "WARN")
        self.assertIn("above your 60% limit (max 9.55x for this stop)", msgs[0][2])
        kb = load_kb()
        checks = {r.trade.id: analysis.rule_checks(r, kb)["leverage"] for r in analysis.rows(kb, analysis.TAKEN)}
        self.assertEqual(checks, {"T-0001": True, "T-0002": True, "T-0003": False})
        exp = {t["id"]: t["derived"]["exposure"] for t in build_payload(kb)["trades"]}
        self.assertEqual([exp[k]["margin_loss_below_aim"] for k in ("T-0001", "T-0002", "T-0003")], [True, False, False])


class StrictYamlTest(KBTestCase):
    """INC-013: YAML silently keeps the last of two duplicate keys. The loader must refuse them everywhere."""

    def test_duplicate_key_is_a_load_error(self):
        text = (self.tmp / "profile" / "trader.yaml").read_text()
        (self.tmp / "profile" / "trader.yaml").write_text(text.replace("terminology:\n", "terminology:\n  POI: \"first\"\n", 1))
        errs = [i.msg for i in self.issues("ERROR")]
        self.assertTrue(any("duplicate key 'POI'" in m for m in errs), errs)

    def test_duplicate_key_in_a_trade_is_caught(self):
        self.write_trade("T-0001", result={"r": 1.0})
        path = self.tmp / "journal" / "trades" / "T-0001.yaml"
        path.write_text(path.read_text() + "direction: short\n")
        self.assertTrue(any("duplicate key 'direction'" in i.msg for i in self.issues("ERROR")))

    def test_every_repository_yaml_loads_strictly(self):
        from tradekb.store import load_yaml
        files = [p for p in REPO.rglob("*.y*ml") if ".git" not in p.parts]
        self.assertGreater(len(files), 30)
        for path in files:
            load_yaml(path)          # raises KBError on a duplicate key

    def test_merge_keys_still_work(self):
        from tradekb.store import load_yaml
        path = self.tmp / "m.yaml"
        path.write_text("base: &b {a: 1}\nuse:\n  <<: *b\n  c: 2\n")
        self.assertEqual(load_yaml(path)["use"], {"a": 1, "c": 2})


class SplitEntryTest(KBTestCase):
    """Trader, 2026-09-28: up to 3 limit orders; 1 = 1%, 2 = 0.5% each, 3 = 0.3% each; one stop and one target.
    The stop is beyond every order, so it is hit only once all have filled: the margin rule applies to the full position."""

    def test_three_orders_risk_0_9_pct_and_the_full_position_carries_the_margin_rule(self):
        plan = split_plan([52.9, 54.44, 53.5], 51.02, 30.0, leverage=9, max_margin_loss_pct=60, margin_loss_aim_min_pct=50,
                          targets=(66.10,), min_rr=2.5)
        self.assertEqual(plan.entries, [54.44, 53.5, 52.9])                        # fill order for a long: highest first
        self.assertAlmostEqual(plan.fills[-1].loss_at_stop, 90.0)                  # 3 x 0.3% = 0.9%
        for f in plan.fills:
            self.assertAlmostEqual(f.loss_at_stop, 30.0 * f.orders)
            self.assertAlmostEqual(f.avg_entry, f.notional / f.qty)
        full = plan.fills[-1]
        self.assertAlmostEqual(plan.max_leverage_full_fill, 60 / full.stop_distance_pct)
        self.assertAlmostEqual(plan.min_leverage_full_fill_aim, 50 / full.stop_distance_pct)
        self.assertEqual(fmt_cap(plan.max_leverage_first_order), "9.55x")          # the agreed policy: the widest stop
        self.assertLess(plan.max_leverage_first_order, plan.max_leverage_full_fill)
        self.assertEqual([f.survives_to for f in plan.fills], [53.5, 52.9, 51.02])  # next order, next order, the stop
        self.assertEqual(plan.flags, [])
        warn = split_plan([54.44, 53.5], 51.02, 50.0, leverage=10, max_margin_loss_pct=60)   # full position: 53.4%
        self.assertEqual([lvl for lvl, _ in warn.flags], ["WARN"])
        self.assertIn("above the agreed first-order cap (9.55x)", warn.flags[0][1])
        over = split_plan([54.44, 53.5], 51.02, 50.0, leverage=12, max_margin_loss_pct=60)   # full position: 64.0%
        self.assertTrue(any(lvl == "CRITICAL" and "with every order filled" in m for lvl, m in over.flags))

    def test_liquidation_is_checked_at_every_step(self):
        for entries, stop, mmr in (([54.44, 53.5, 52.9], 51.02, 0.005), ([100.0, 100.3], 100.6, 0.005), ([0.3691, 0.36], 0.3505, 0.01)):
            plan = split_plan(entries, stop, 10.0, mmr_rate=mmr)
            at = split_plan(entries, stop, 10.0, leverage=plan.max_leverage_liq * 0.999, mmr_rate=mmr)
            self.assertFalse(any(f.liq_first for f in at.fills))
            over = split_plan(entries, stop, 10.0, leverage=plan.max_leverage_liq * 1.01, mmr_rate=mmr)
            self.assertTrue(any(f.liq_first for f in over.fills))
            self.assertTrue(any(lvl == "CRITICAL" and "liquidation comes before" in m for lvl, m in over.flags))

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            split_plan([100, 102], 101, 10)                                        # entries on both sides of the stop
        with self.assertRaises(ValueError):
            split_plan([100, 100], 98, 10)
        with self.assertRaises(ValueError):
            split_plan([100, 99], 98, 10, targets=(99.5,))                         # target inside the first entry

    def test_cli_uses_the_profile_shares(self):
        code, out = self.run_cli("size", "--entry", "54.44", "--add-entry", "53.5", "--stop", "51.02", "--risk-amount", "100")
        self.assertEqual(code, 0)
        self.assertIn("0.5% of equity per order (50.00)", out)
        self.assertIn("full position, margin rule", out)
        code, out = self.run_cli("size", "--entry", "54.44", "--add-entry", "53.5", "--add-entry", "53", "--add-entry", "52.5",
                                 "--stop", "51.02", "--risk-amount", "100")
        self.assertEqual(code, 2)                                                  # 4 orders: no rule for it


class SplitTradeRTest(KBTestCase):
    """R of a split trade is counted on the full 1R: 1 of 3 orders filled at 3R = +0.9R (trader, 2026-09-28)."""
    PLAN = {"entry": 54.44, "stop": 51.02, "targets": [64.70], "split_entries": [53.5, 52.9], "split_share": 0.3}

    def r(self, tid):
        from tradekb.model import r_multiple
        return r_multiple(load_kb().trade(tid).data)

    def test_one_of_three_filled_at_3r_is_0_9r(self):
        self.write_trade("T-0001", plan=self.PLAN, fills={"exits": [{"price": 64.70}], "orders_filled": 1})
        r, src = self.r("T-0001")
        self.assertAlmostEqual(r, 0.3 * (64.70 - 54.44) / 3.42)            # 3.0R on the first order x 0.3 = 0.9R
        self.assertAlmostEqual(r, 0.9)
        self.assertFalse([i for i in self.issues("ERROR")])

    def test_full_stop_is_0_9r_and_the_audit_agrees(self):
        self.write_trade("T-0001", plan=self.PLAN, fills={"exits": [{"price": 51.02}], "orders_filled": 3})
        self.assertAlmostEqual(self.r("T-0001")[0], -0.9)
        from tradekb import audit
        self.assertEqual(audit.run(load_kb(), check_outputs=False).failures, [])

    def test_split_records_are_checked(self):
        self.write_trade("T-0001", plan=self.PLAN, fills={"exits": [{"price": 51.02}], "orders_filled": 1})
        self.assertTrue(any("price reaches the stop only through every order" in i.msg for i in self.issues("WARN")))
        self.write_trade("T-0001", plan={**self.PLAN, "split_share": None}, fills={"exits": [{"price": 64.70}], "orders_filled": 1})
        self.assertTrue(any("plan.split_share is required" in i.msg for i in self.issues("ERROR")))
        self.assertIsNone(self.r("T-0001")[0])                              # no silent single-entry R
        self.write_trade("T-0001", plan={**self.PLAN, "split_entries": [53.5, 52.9, 52.0]}, fills={"exits": [{"price": 64.70}], "orders_filled": 1})
        self.assertTrue(any("allows up to 3" in i.msg for i in self.issues("ERROR")))
        self.write_trade("T-0001", plan={**self.PLAN, "split_entries": [50.0]}, fills={"exits": [{"price": 64.70}], "orders_filled": 1})
        self.assertTrue(any("at or beyond the stop" in i.msg for i in self.issues("ERROR")))


class DetailTimeframeTest(KBTestCase):
    def test_detail_timeframes_sit_below_execution(self):
        tf = {"htf": "4h", "execution": "4h", "chain": ["4h"], "detail": ["1h"], "top_down": True}
        self.write_trade("T-0001", result={"r": 3.41}, timeframes=tf)
        self.assertFalse([i for i in self.issues() if "timeframes" in i.msg or "top_down" in i.msg])
        self.write_trade("T-0001", result={"r": 3.41}, timeframes={**tf, "detail": ["1D"]})
        self.assertTrue(any("is not below the execution timeframe" in i.msg for i in self.issues("ERROR")))


class VersionNumberTest(KBTestCase):
    def test_unquoted_version_is_refused(self):
        self.write_trade("T-0001", result={"r": 1.0}, strategy={"id": None, "version": 1.10})
        self.assertTrue(any("is a number: quote it" in i.msg for i in self.issues("ERROR")))
        self.write_trade("T-0001", result={"r": 1.0}, strategy={"id": None, "version": "1.10"})
        self.assertFalse(any("is a number" in i.msg for i in self.issues("ERROR")))


INCIDENT = {"id": "INC-001", "date": "2026-09-28", "area": "data", "severity": "medium", "title": "t", "detail": "d",
            "found_by": "agent", "status": "fixed", "fix": "f"}


class IncidentLogTest(KBTestCase):
    def write_incidents(self, items):
        (self.tmp / "playbook" / "incidents.yaml").write_text(yaml.safe_dump({"incidents": items}))

    def test_valid_log_exports_with_counts(self):
        self.write_incidents([INCIDENT, {**INCIDENT, "id": "INC-002", "status": "open", "severity": "high", "fix": None}])
        self.assertTrue(any("open high-severity incident" in i.msg for i in self.issues("WARN")))
        self.assertFalse([i for i in self.issues("ERROR")])
        p = build_payload(load_kb())
        self.assertEqual([x["id"] for x in p["incidents"]], ["INC-001", "INC-002"])
        self.assertEqual(p["health"]["by_status"]["open"], 1)
        self.assertEqual(p["health"]["open_by_severity"], {"high": 1, "medium": 0, "low": 0})
        from tradekb import audit
        self.assertEqual(audit.run(load_kb(), check_outputs=False).failures, [])

    def test_schema_errors(self):
        self.write_incidents([{**INCIDENT, "id": "INC-002"}, {**INCIDENT, "id": "INC-002", "area": "vibes", "fix": ""}])
        errs = [i.msg for i in self.issues("ERROR")]
        self.assertTrue(any("expected INC-001" in m for m in errs))
        self.assertTrue(any("area must be one of" in m for m in errs))
        self.assertTrue(any("needs `fix`" in m for m in errs))

    def test_append_only_against_the_last_commit(self):
        git = ["git", "-C", str(self.tmp), "-c", "user.email=t@t", "-c", "user.name=t"]
        self.write_incidents([INCIDENT, {**INCIDENT, "id": "INC-002", "title": "second"}])
        subprocess.run(git + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "playbook/incidents.yaml"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "log"], check=True)
        self.write_incidents([{**INCIDENT, "status": "guarded"}, {**INCIDENT, "id": "INC-002", "title": "second"},
                              {**INCIDENT, "id": "INC-003"}])
        self.assertFalse([i for i in self.issues("ERROR") if "incidents" in i.where])     # status change + append: fine
        self.write_incidents([INCIDENT])                                                  # INC-002 deleted
        self.assertTrue(any("INC-002 was committed and is gone" in i.msg for i in self.issues("ERROR")))
        self.write_incidents([INCIDENT, {**INCIDENT, "id": "INC-002", "title": "rewritten"}])
        self.assertTrue(any("may not be rewritten" in i.msg for i in self.issues("ERROR")))

    def test_guard_spec_is_validated_and_exported(self):
        (self.tmp / "playbook" / "automation.yaml").write_text(yaml.safe_dump({"stages": [], "malfunction_guard": {
            "status": "specified", "on_trip": "halt", "checks": [{"id": "G1", "name": "n", "trigger": "t", "action": "a"},
                                                                 {"id": "G1", "name": "", "trigger": "t", "action": "a"}]}}))
        errs = [i.msg for i in self.issues("ERROR")]
        self.assertTrue(any("duplicate id G1" in m for m in errs))
        self.assertTrue(any("name must be a non-empty text" in m for m in errs))
        self.assertEqual(build_payload(load_kb())["readiness"]["malfunction_guard"]["checks"][0]["id"], "G1")


class BotSpecTest(KBTestCase):
    def test_venue_and_questions_reach_the_export(self):
        import yaml as _yaml
        (self.tmp / "playbook" / "automation.yaml").write_text(_yaml.safe_dump({
            "venue": {"exchange": "MEXC"}, "open_questions": ["1. Scan list?"],
            "stages": [{"id": "a", "criteria": [{"label": "trades", "metric": "measured_trades", "min": 1}]}]}))
        rd = build_payload(load_kb())["readiness"]
        self.assertEqual(rd["venue"], {"exchange": "MEXC"})
        self.assertEqual(rd["open_questions"], ["1. Scan list?"])

    def test_alerts_spec_is_validated_and_exported(self):
        import yaml as _yaml
        spec = {"channel": None, "events": ["entry filled", "exit at stop loss"], "content": ["risk in USDT"]}
        (self.tmp / "playbook" / "automation.yaml").write_text(_yaml.safe_dump({"stages": [], "alerts": spec}))
        self.assertEqual(build_payload(load_kb())["readiness"]["alerts"], spec)
        (self.tmp / "playbook" / "automation.yaml").write_text(_yaml.safe_dump({"stages": [], "alerts": {**spec, "events": []}}))
        self.assertTrue(any("events must be a non-empty list" in i.msg for i in self.issues("ERROR")))

    def test_bot_questions_must_be_text(self):
        import yaml as _yaml
        (self.tmp / "playbook" / "automation.yaml").write_text(_yaml.safe_dump({"open_questions": [{"q": 1}], "stages": []}))
        self.assertTrue(any("open_questions must be a list" in i.msg for i in self.issues("ERROR")))

    def test_explicit_none_is_resolved_not_a_gap(self):
        from tradekb.store import unresolved
        self.assertEqual(unresolved({"risk": {"max_daily_loss_r": "none", "max_open_risk_pct": None}}), ["risk.max_open_risk_pct"])


class GradeAndTrendTest(KBTestCase):
    def test_trader_grade_is_text_and_groups(self):
        self.write_trade("T-0001", result={"r": 4.12}, review={"mistakes": [], "behaviors": [], "trader_grade": "S"})
        self.write_trade("T-0002", result={"r": -1.0}, review={"mistakes": [], "behaviors": [], "trader_grade": 5})
        self.assertTrue(any("trader_grade must be" in i.msg for i in self.issues("ERROR")))
        self.write_trade("T-0002", result={"r": -1.0})
        groups = analysis.group(analysis.realized(load_kb()), "trader_grade")
        self.assertEqual({k: len(v) for k, v in groups.items()}, {"S": 1, "(unknown)": 1})

    def test_trend_alignment_from_regime_and_direction(self):
        self.write_trade("T-0001", direction="short", plan={"entry": 100, "stop": 101, "targets": []}, regime=["bullish"], result={"r": 4.0})
        self.write_trade("T-0002", direction="long", regime=["range", "bullish"], result={"r": 1.0})
        self.write_trade("T-0003", direction="long", regime=["neutral"], result={"r": 1.0})
        groups = analysis.group(analysis.realized(load_kb()), "trend")
        self.assertEqual({k: [r.trade.id for r in v] for k, v in groups.items()},
                         {"counter_trend": ["T-0001"], "with_trend": ["T-0002"], "(unknown)": ["T-0003"]})


class ExcursionTest(KBTestCase):
    def test_mae_mfe_in_r_for_both_sides(self):
        # long 100 -> stop 98 (1R = 2): worst 99 = 0.5R heat, best 106 = 3R run
        self.write_trade("T-0001", plan={"entry": 100, "stop": 98, "targets": [106]}, fills={"exits": [{"price": 106}], "worst_price": 99, "best_price": 106})
        # short 50 -> stop 51 (1R = 1): stopped out, worst = stop = 1R, best 49.7 = 0.3R
        self.write_trade("T-0002", direction="short", plan={"entry": 50, "stop": 51, "targets": [47]},
                         fills={"exits": [{"price": 51}], "worst_price": 51, "best_price": 49.7})
        rows = {r.trade.id: r.d for r in analysis.realized(load_kb())}
        self.assertAlmostEqual(rows["T-0001"].mae_r, 0.5); self.assertAlmostEqual(rows["T-0001"].mfe_r, 3.0)
        self.assertAlmostEqual(rows["T-0002"].mae_r, 1.0); self.assertAlmostEqual(rows["T-0002"].mfe_r, 0.3)
        ex = build_payload(load_kb())["stats"]["excursions"]
        self.assertEqual((ex["winners"], ex["losers"]), (1, 1))
        self.assertAlmostEqual(ex["winner_mae_median"], 0.5); self.assertAlmostEqual(ex["loser_mfe_max"], 0.3)

    def test_validator_catches_impossible_excursions(self):
        self.write_trade("T-0001", plan={"entry": 100, "stop": 98, "targets": [106]}, fills={"exits": [{"price": 106}], "worst_price": 101, "best_price": 106})
        self.write_trade("T-0002", plan={"entry": 100, "stop": 98, "targets": [106]}, fills={"exits": [{"price": 106}], "worst_price": 97, "best_price": 106})
        self.write_trade("T-0003", plan={"entry": 100, "stop": 98, "targets": [106]}, fills={"exits": [{"price": 106}], "worst_price": 99.5, "best_price": 104})
        errors = [(i.where, i.msg) for i in self.issues("ERROR")]
        warns = [(i.where, i.msg) for i in self.issues("WARN")]
        self.assertTrue(any(w == "T-0001.yaml" and "profitable side" in m for w, m in errors))
        self.assertTrue(any(w == "T-0002.yaml" and "was the stop moved" in m for w, m in warns))
        self.assertTrue(any(w == "T-0003.yaml" and "short of the exit" in m for w, m in warns))

    def test_audit_recomputes_excursions(self):
        from tradekb import model
        from tradekb.audit import run as audit
        self.write_trade("T-0001", plan={"entry": 100, "stop": 98, "targets": [106]}, fills={"exits": [{"price": 106}], "worst_price": 99, "best_price": 106})
        real = model.excursions
        with mock.patch.object(model, "excursions", lambda t: tuple(None if v is None else v + 0.01 for v in real(t))):
            failures = audit(load_kb(), check_outputs=False).failures
        self.assertTrue(any("mae_r" in f for f in failures))


class AcknowledgedBreachTest(KBTestCase):
    def test_tagged_breach_is_info_untagged_is_warn(self):
        trade = dict(plan={"entry": 100, "stop": 96, "targets": [112]}, risk={"risk_pct": 1.0, "leverage": 20}, result={"r": -1.0})
        self.write_trade("T-0001", **trade)
        self.write_trade("T-0002", **trade, review={"mistakes": ["excessive_leverage"], "behaviors": []})
        lev = [(i.level, i.where) for i in self.issues() if "of the posted margin" in i.msg]
        self.assertIn(("WARN", "T-0001.yaml"), lev)
        self.assertIn(("INFO", "T-0002.yaml"), lev)
        self.assertTrue(any("acknowledged: tagged excessive_leverage" in i.msg for i in self.issues("INFO")))


class SchemaRulesTest(KBTestCase):
    def _strategy(self, changes, entry_models=None):
        dest = self.tmp / "playbook" / "strategies" / "sd"
        shutil.copytree(REPO / "templates" / "strategy", dest)
        (dest / "strategy.yaml").write_text((dest / "strategy.yaml").read_text().replace("__SLUG__", "sd"))
        if entry_models is not None:
            v = yaml.safe_load((dest / "v1.0.yaml").read_text())
            v["entry_models"] = entry_models
            (dest / "v1.0.yaml").write_text(yaml.safe_dump(v))
        (dest / "changes.yaml").write_text(yaml.safe_dump({"changes": changes}))

    def test_clarification_needs_no_evidence(self):
        self._strategy([{"id": "CHG-001", "kind": "clarification", "status": "adopted", "rule_changed": False,
                         "statement": "1% risk per trade", "resulting_version": "1.0"}])
        self.assertEqual(self.issues("ERROR"), [])

    def test_clarification_cannot_change_rules_or_skip_statement(self):
        self._strategy([{"id": "CHG-001", "kind": "clarification", "status": "established", "rule_changed": True,
                         "resulting_version": "1.0"}])
        msgs = [i.msg for i in self.issues("ERROR")]
        self.assertTrue(any("status 'adopted'" in m for m in msgs))
        self.assertTrue(any("quote the trader's statement" in m for m in msgs))
        self.assertTrue(any("cannot change a rule" in m for m in msgs))

    def test_rule_change_cannot_use_adopted(self):
        self._strategy([{"id": "CHG-001", "status": "adopted"}])
        self.assertTrue(any("status must be one of" in i.msg for i in self.issues("ERROR")))

    def test_entry_model_must_exist_in_strategy_version(self):
        self._strategy([], entry_models={"reclaim": "x", "extreme_demand": "y"})
        self.write_trade("T-0001", result={"r": 1.0}, strategy={"id": "sd", "version": "1.0"},
                         plan={"entry": 100, "stop": 98, "targets": [], "entry_model": "breakout"})
        self.assertTrue(any("not an entry model" in i.msg for i in self.issues("ERROR")))


if __name__ == "__main__":
    unittest.main()
