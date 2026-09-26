"""Integration tests against a throwaway copy of the knowledge base (never the live journal)."""
import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from tradekb import cli
from tradekb.analysis import error_db, realized
from tradekb.store import load_kb
from tradekb.validate import validate

REPO = Path(__file__).resolve().parent.parent


class KBTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for name in ("taxonomy", "templates", "profile"):
            shutil.copytree(REPO / name, self.tmp / name)
        shutil.copy(REPO / "config.yaml", self.tmp / "config.yaml")
        for sub in ("journal/trades", "journal/charts", "playbook/strategies", "playbook/experiments"):
            (self.tmp / sub).mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {"TJ_ROOT": str(self.tmp)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp)

    def write_trade(self, tid, **fields):
        data = {"id": tid, "status": "closed", "opened": "2026-09-01", "closed": "2026-09-01",
                "direction": "long", "setups": [], "regime": [],
                "plan": {"entry": 100, "stop": 98, "targets": []},
                "risk": {"risk_amount": 100}, "fills": {"exits": []}, "result": {},
                "journal": {"before": "thesis"}, "review": {"mistakes": [], "behaviors": []}}
        for key, value in fields.items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key] = {**data[key], **value}
            else:
                data[key] = value
        (self.tmp / "journal" / "trades" / f"{tid}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")

    def issues(self, level=None):
        found = validate(load_kb())
        return [i for i in found if level is None or i.level == level]

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(list(argv))
        return code, out.getvalue()


class TemplateTest(KBTestCase):
    def test_new_trade_from_template_validates_clean(self):
        code, out = self.run_cli("new", "--asset", "BTCUSDT", "--direction", "short", "--status", "planned")
        self.assertEqual(code, 0)
        self.assertIn("T-0001.yaml", out)
        self.assertEqual(self.issues("ERROR"), [])
        code, out = self.run_cli("new")
        self.assertIn("T-0002.yaml", out)

    def test_strategy_template_validates_clean(self):
        dest = self.tmp / "playbook" / "strategies" / "sweep"
        shutil.copytree(REPO / "templates" / "strategy", dest)
        meta = dest / "strategy.yaml"
        meta.write_text(meta.read_text().replace("__SLUG__", "sweep"))
        self.assertEqual(self.issues("ERROR"), [])


class ValidationTest(KBTestCase):
    def test_wrong_side_stop(self):
        self.write_trade("T-0001", plan={"entry": 100, "stop": 102})
        self.assertTrue(any("must be below entry" in i.msg for i in self.issues("ERROR")))

    def test_unknown_tag_and_alias(self):
        self.write_trade("T-0001", setups=["silver_bullet"], review={"mistakes": ["oversizing"], "behaviors": []})
        msgs = [i.msg for i in self.issues("ERROR")]
        self.assertTrue(any("unknown tag 'silver_bullet'" in m for m in msgs))
        self.assertTrue(any("canonical tag 'oversized_position'" in m for m in msgs))

    def test_exclusive_regimes(self):
        self.write_trade("T-0001", regime=["strong_trend", "range", "news_driven"])
        self.assertTrue(any("mutually exclusive" in i.msg for i in self.issues("ERROR")))

    def test_counterfactual_contamination(self):
        self.write_trade("T-0001", result={"r": 1.0, "hypothetical_r": 2.0})
        self.write_trade("T-0002", status="missed", result={"pnl": 50})
        msgs = [i.msg for i in self.issues("ERROR")]
        self.assertTrue(any("hypothetical_r is for missed" in m for m in msgs))
        self.assertTrue(any("use result.hypothetical_r" in m for m in msgs))

    def test_non_numeric_price(self):
        self.write_trade("T-0001", plan={"entry": "100 USDT", "stop": 98})
        self.assertTrue(any("plain number" in i.msg for i in self.issues("ERROR")))

    def test_loss_type_consistency(self):
        self.write_trade("T-0001", result={"r": -1.0}, review={"loss_type": "C", "mistakes": [], "behaviors": []})
        self.write_trade("T-0002", result={"r": 2.0}, review={"loss_type": "A", "mistakes": [], "behaviors": []})
        warns = [i.msg for i in self.issues("WARN")]
        self.assertTrue(any("no review.mistakes tagged" in m for m in warns))
        self.assertTrue(any("outcome is win" in m for m in warns))

    def test_stated_vs_computed_risk(self):
        self.write_trade("T-0001", risk={"risk_amount": 100, "size": 100}, result={"r": -2.0})
        self.assertTrue(any("Oversized" in i.msg for i in self.issues("WARN")))

    def test_liquidation_before_stop(self):
        self.write_trade("T-0001", risk={"risk_amount": 100, "size": 33, "leverage": 50, "margin_mode": "isolated"},
                         plan={"entry": 100, "stop": 97}, result={"r": -1.0})
        self.assertTrue(any("reached before the stop" in i.msg for i in self.issues("WARN")))

    def test_unmeasurable_trade_is_warned_and_excluded(self):
        self.write_trade("T-0001", plan={"entry": 100})
        self.assertTrue(any("R not computable" in i.msg for i in self.issues("WARN")))
        self.assertEqual(realized(load_kb()), [])

    def test_strategy_promotion_gate(self):
        dest = self.tmp / "playbook" / "strategies" / "sweep"
        shutil.copytree(REPO / "templates" / "strategy", dest)
        (dest / "strategy.yaml").write_text(
            (dest / "strategy.yaml").read_text().replace("__SLUG__", "sweep").replace(
                "status: unvalidated", "status: established"))
        self.assertTrue(any("requires >= 30 measured trades" in i.msg for i in self.issues("ERROR")))

    def test_change_promotion_gate(self):
        dest = self.tmp / "playbook" / "strategies" / "sweep"
        shutil.copytree(REPO / "templates" / "strategy", dest)
        (dest / "strategy.yaml").write_text((dest / "strategy.yaml").read_text().replace("__SLUG__", "sweep"))
        self.write_trade("T-0001", result={"r": -1.0})
        (dest / "changes.yaml").write_text(yaml.safe_dump({"changes": [{
            "id": "CHG-001", "status": "established", "evidence": ["T-0001"], "current_rule": "x",
            "observation": "x", "hypothesis": "x", "proposed_change": "x", "expected_effect": "x",
            "overfitting_risk": "x"}]}))
        self.assertTrue(any("requires >= 30 evidence trades" in i.msg for i in self.issues("ERROR")))

    def test_committed_version_files_are_immutable(self):
        import subprocess
        dest = self.tmp / "playbook" / "strategies" / "sweep"
        shutil.copytree(REPO / "templates" / "strategy", dest)
        (dest / "strategy.yaml").write_text((dest / "strategy.yaml").read_text().replace("__SLUG__", "sweep"))
        git = ["git", "-C", str(self.tmp), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        subprocess.run(git[:3] + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "init"], check=True)
        self.assertEqual(self.issues("ERROR"), [])
        v1 = dest / "v1.0.yaml"
        v1.write_text(v1.read_text().replace("entry_model: null", "entry_model: rewritten"))
        self.assertTrue(any("immutable" in i.msg for i in self.issues("ERROR")))
        edited = validate(load_kb(), allow_version_edits=True)
        self.assertFalse(any(i.level == "ERROR" for i in edited))

    def test_string_taxonomy_entry_and_bad_config_do_not_crash(self):
        with open(self.tmp / "taxonomy" / "setups.yaml", "a") as fh:
            fh.write("  my_term: My own term\n")
        (self.tmp / "config.yaml").write_text("- not a mapping\n")
        self.write_trade("T-0001", setups=["my_term"], result={"r": 1.0})
        errors = self.issues("ERROR")
        self.assertTrue(any("config.yaml" in i.msg for i in errors))
        self.assertFalse(any("my_term" in i.msg for i in errors))

    def test_unknown_strategy_reference(self):
        self.write_trade("T-0001", strategy={"id": "ghost", "version": "1.0"}, result={"r": 1.0})
        self.assertTrue(any("not found in playbook" in i.msg for i in self.issues("ERROR")))


class AnalysisTest(KBTestCase):
    def test_recurring_error_flag_and_cost(self):
        for n, r in enumerate([-1.0, -1.5, 2.0], start=1):
            self.write_trade(f"T-{n:04d}", result={"r": r}, review={"mistakes": ["fomo"], "behaviors": []})
        self.write_trade("T-0004", result={"r": 1.0}, review={"mistakes": ["late_entry"], "behaviors": []})
        errs = {e.tag: e for e in error_db(load_kb())}
        self.assertTrue(errs["fomo"].recurring)
        self.assertAlmostEqual(errs["fomo"].total_r, -0.5)
        self.assertFalse(errs["late_entry"].recurring)

    def test_report_and_stats_commands(self):
        for n in range(1, 13):
            self.write_trade(f"T-{n:04d}", setups=["liquidity_sweep"] if n % 2 else ["breakout"],
                             regime=["range"] if n % 3 else ["strong_trend"],
                             result={"r": 2.0 if n % 3 == 0 else -1.0},
                             review={"mistakes": [], "behaviors": [],
                                     "scores": {"setup": 4, "context": 4, "execution": 4, "risk": 4,
                                                "management": 4}})
        self.write_trade("T-0013", status="missed", result={"hypothetical_r": 3.0})
        code, out = self.run_cli("report")
        self.assertEqual(code, 0)
        self.assertIn("## 2. By setup", out)
        self.assertIn("COUNTERFACTUAL", out)
        self.assertIn("n=12", out)
        code, out = self.run_cli("stats", "--by", "setup", "--where", "regime=range")
        self.assertEqual(code, 0)
        self.assertIn("n = 8", out)
        code, out = self.run_cli("compare", "setup", "liquidity_sweep", "breakout")
        self.assertEqual(code, 0)
        self.assertIn("Verdict", out)

    def test_status_and_size_commands(self):
        code, out = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("INITIALIZATION", out)
        code, _ = self.run_cli("size", "--entry", "100", "--stop", "98")
        self.assertEqual(code, 2)  # risk per trade unresolved: refuse rather than invent one
        code, out = self.run_cli("size", "--entry", "100", "--stop", "97", "--risk-amount", "100",
                                 "--equity", "10000", "--leverage", "50")
        self.assertEqual(code, 1)  # CRITICAL: liquidation before stop
        self.assertIn("BEFORE the stop", out)


if __name__ == "__main__":
    unittest.main()
