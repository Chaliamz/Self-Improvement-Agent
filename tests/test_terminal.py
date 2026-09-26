"""Build outputs, the terminal's JavaScript risk math (parity with tradekb/risk.py), and schema rules."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from tradekb.risk import SizingInput, exposure, size_position
from tradekb.store import load_kb
from tradekb.validate import validate
from tests.test_kb import REPO, KBTestCase

NODE = shutil.which("node")
TEMPLATE = REPO / "templates" / "terminal.html"


def risk_math_js() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r"/\* RISK-MATH:BEGIN.*?\*/(.*?)/\* RISK-MATH:END \*/", text, re.S)
    assert match, "RISK-MATH block missing from the terminal template"
    return match.group(1)


CASES = [
    dict(entry=100, stop=98, risk_amount=100, equity=10_000, leverage=10, targets=(104, 106)),
    dict(entry=90.41, stop=87.59, risk_amount=100, equity=10_000, leverage=10, targets=(103.30,)),
    dict(entry=64200, stop=64850, risk_amount=250, equity=25_000, leverage=20, fee_rate=0.0005, targets=(62900,)),
    dict(entry=100, stop=97, risk_amount=100, equity=10_000, leverage=50),
    dict(entry=100, stop=99, risk_amount=100, fee_rate=0.0005, slippage_pct=0.05, qty_step=0.1),
    dict(entry=50, stop=51, risk_amount=20, equity=1_000, margin_mode="cross", mmr_rate=0.01),
    dict(entry=90.41, stop=87.59, risk_amount=100, equity=10_000, leverage=20, max_margin_loss_pct=50, min_rr=2.5,
         targets=(103.30,)),
    dict(entry=90.41, stop=87.59, risk_amount=100, equity=10_000, leverage=10, max_margin_loss_pct=50, min_rr=5,
         fee_rate=0.0006, targets=(103.30,)),
]
KEYS = {"qty": "qty", "notional": "notional", "loss_at_stop": "lossAtStop", "risk_pct": "riskPct",
        "effective_leverage": "effectiveLeverage", "margin_required": "marginRequired",
        "liquidation": "liquidation", "liq_to_stop_ratio": "liqToStop", "per_unit_loss": "perUnitLoss",
        "margin_loss_pct": "marginLossPct", "max_leverage_for_rule": "maxLeverageForRule"}


@unittest.skipUnless(NODE, "node not installed")
class JavaScriptParityTest(unittest.TestCase):
    def test_risk_math_matches_python(self):
        js_cases = [{"entry": c["entry"], "stop": c["stop"], "riskAmount": c["risk_amount"], "equity": c.get("equity"),
                     "leverage": c.get("leverage"), "marginMode": c.get("margin_mode", "isolated"),
                     "mmrRate": c.get("mmr_rate", 0.005), "feeRate": c.get("fee_rate", 0.0),
                     "slippagePct": c.get("slippage_pct", 0.0), "qtyStep": c.get("qty_step"),
                     "targets": list(c.get("targets", ())), "maxMarginLossPct": c.get("max_margin_loss_pct"),
                     "minRr": c.get("min_rr")} for c in CASES]
        script = risk_math_js() + f"\nconsole.log(JSON.stringify({json.dumps(js_cases)}.map(c => RiskMath.size(c))));"
        out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        results = json.loads(out.stdout)
        for case, js in zip(CASES, results):
            py = size_position(SizingInput(**case))
            for py_key, js_key in KEYS.items():
                a, b = getattr(py, py_key), js[js_key]
                if a is None:
                    self.assertIsNone(b, f"{py_key} for {case}")
                else:
                    self.assertAlmostEqual(a, b, places=9, msg=f"{py_key} for {case}")
            self.assertEqual(py.side, js["side"])
            self.assertEqual([lvl for lvl, _ in py.flags], [lvl for lvl, _ in js["flags"]], f"flag levels for {case}")
            for tp_py, tp_js in zip(py.targets, js["targets"]):
                self.assertAlmostEqual(tp_py.rr_gross, tp_js["rrGross"], places=9)
                self.assertAlmostEqual(tp_py.rr_net, tp_js["rrNet"], places=9)

    def test_js_rejects_what_python_rejects(self):
        script = risk_math_js() + """
const bad = [{entry: 100, stop: 100, riskAmount: 1}, {entry: 100, stop: 102, riskAmount: 1, side: "long"},
             {entry: 100, stop: 98, riskAmount: 1, targets: [99]}];
console.log(JSON.stringify(bad.map(c => { try { RiskMath.size(c); return "ok"; } catch (e) { return "error"; } })));"""
        out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(json.loads(out.stdout), ["error", "error", "error"])

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
