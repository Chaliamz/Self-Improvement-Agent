"""Build outputs, the terminal script, rule compliance, and schema rules."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from tradekb import analysis
from tradekb.export import build_payload
from tradekb.risk import SizingInput, exposure, fmt_cap, size_position
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
        prof["leverage"]["max_margin_loss_at_stop_pct"] = 50
        prof["risk"]["min_rr"] = 2.5
        (self.tmp / "profile" / "trader.yaml").write_text(_yaml.safe_dump(prof))
        self.write_trade("T-0001", result={"r": 1.0}, risk={"risk_amount": 100, "leverage": 25},
                         plan={"entry": 100, "stop": 97, "targets": [104]})
        warns = [i.msg for i in self.issues("WARN")]
        self.assertTrue(any("above your 50% limit" in m for m in warns))
        self.assertTrue(any("below your 2.5R minimum" in m for m in warns))


class RuleComplianceTest(KBTestCase):
    """The trader's stated rules (live profile: 1% cap, 50% margin rule, 2.5R minimum) checked per taken trade."""

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
        self.assertIn("50% of margin", rules["definitions"][3]["rule"])


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
