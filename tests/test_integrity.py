"""Timeframes, top-down, durations, and the audit's ability to catch corruption."""
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

import yaml

from tests.test_kb import REPO, KBTestCase
from tradekb import analysis
from tradekb.audit import run as audit
from tradekb.store import load_kb

WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8L\x0d\x00\x00\x00/\x00\x00\x00\x10\x07\x10\x11\x11\x88\x88\xfe\x07\x00"


class TimeframeRulesTest(KBTestCase):
    def test_notation(self):
        self.write_trade("T-0001", result={"r": 1.0}, timeframes={"htf": "4H", "execution": "1m", "chain": ["1D", "15min"]})
        errors = [i.msg for i in self.issues("ERROR")]
        self.assertTrue(any("timeframes.htf '4H'" in m for m in errors))
        self.assertTrue(any("'15min' is not a timeframe" in m for m in errors))

    def test_one_capital_m_is_a_month(self):
        self.write_trade("T-0001", result={"r": 1.0}, timeframes={"execution": "1M"})
        self.assertTrue(any("means 1 month" in i.msg for i in self.issues("WARN")))

    def test_top_down_consistency(self):
        self.write_trade("T-0001", result={"r": 1.0}, timeframes={"execution": "1m", "chain": ["1m"], "top_down": True})
        self.write_trade("T-0002", result={"r": 1.0}, timeframes={"execution": "1m", "chain": ["4h", "15m"], "top_down": True})
        warns = [(i.where, i.msg) for i in self.issues("WARN")]
        self.assertTrue(any(w == "T-0001.yaml" and "fewer than two" in m for w, m in warns))
        self.assertTrue(any(w == "T-0002.yaml" and "should end at the execution timeframe" in m for w, m in warns))

    def test_duration_must_fit_dates(self):
        self.write_trade("T-0001", result={"r": 1.0}, opened="2026-04-19", closed="2026-04-19", fills={"exits": [], "duration_minutes": 45})
        self.write_trade("T-0002", result={"r": 1.0}, opened="2026-04-19", closed="2026-04-19", fills={"exits": [], "duration_minutes": 3000})
        warns = [i for i in self.issues("WARN") if "duration_minutes" in i.msg]
        self.assertEqual([i.where for i in warns], ["T-0002.yaml"])

    def test_trade_timeframe_against_strategy(self):
        dest = self.tmp / "playbook" / "strategies" / "sd"
        shutil.copytree(REPO / "templates" / "strategy", dest)
        (dest / "strategy.yaml").write_text((dest / "strategy.yaml").read_text().replace("__SLUG__", "sd"))
        v = yaml.safe_load((dest / "v1.0.yaml").read_text()); v["timeframes"] = {"structure": "4h", "execution": "4h"}
        (dest / "v1.0.yaml").write_text(yaml.safe_dump(v))
        self.write_trade("T-0001", result={"r": 1.0}, strategy={"id": "sd", "version": "1.0"}, timeframes={"execution": "1m"})
        self.write_trade("T-0002", result={"r": 1.0}, strategy={"id": "sd", "version": "1.0"})
        self.assertTrue(any("differs from sd v1.0 (4h)" in i.msg for i in self.issues("WARN")))
        self.assertTrue(any(i.where == "T-0002.yaml" and "states 4h" in i.msg for i in self.issues("INFO")))


class HoldingAndGroupingTest(KBTestCase):
    def test_holding_hours_prefers_stated_minutes(self):
        self.write_trade("T-0001", result={"r": 1.0}, opened="2026-04-19", closed="2026-04-19", fills={"exits": [], "duration_minutes": 45})
        self.write_trade("T-0002", result={"r": 1.0}, opened="2026-04-20", closed="2026-05-10")
        self.write_trade("T-0003", result={"r": 1.0}, opened="2026-04-20", closed="2026-04-20")
        hours = {r.trade.id: analysis.holding_hours(r) for r in analysis.realized(load_kb())}
        self.assertEqual(hours, {"T-0001": 0.75, "T-0002": 480.0, "T-0003": None})

    def test_top_down_grouper(self):
        self.write_trade("T-0001", result={"r": 1.0}, timeframes={"execution": "1m", "chain": ["1m"], "top_down": False})
        self.write_trade("T-0002", result={"r": 1.0}, timeframes={"execution": "1m", "chain": ["4h", "1m"], "top_down": True})
        self.write_trade("T-0003", result={"r": 1.0})
        groups = analysis.group(analysis.realized(load_kb()), "top_down")
        self.assertEqual({k: len(v) for k, v in groups.items()}, {"no": 1, "yes": 1, "(unknown)": 1})


class AuditTest(KBTestCase):
    def setUp(self):
        super().setUp()
        (self.tmp / "journal" / "charts" / "T-0001.webp").write_bytes(WEBP)
        self.write_trade("T-0001", direction="short", plan={"entry": 100, "stop": 101, "targets": [97]},
                         fills={"exits": [{"price": 97}]}, evidence={"charts": ["journal/charts/T-0001.webp"]})
        self.write_trade("T-0002", result={"r": -1.0})
        self.run_cli("build")

    def test_clean_build_passes_and_webp_is_embedded(self):
        result = audit(load_kb())
        self.assertEqual(result.failures, [])
        html = (self.tmp / "terminal.html").read_text()
        self.assertIn('"journal/charts/T-0001.webp":"data:image/webp;base64,', html)

    def test_tampered_export_is_caught(self):
        path = self.tmp / "exports" / "kb.json"
        doc = json.loads(path.read_text()); doc["stats"]["overall"]["total"] = 99.0
        path.write_text(json.dumps(doc))
        failures = audit(load_kb()).failures
        self.assertTrue(any("kb.json content equals a fresh build" in f for f in failures))
        self.assertTrue(any("embeds exactly exports/kb.json" in f for f in failures))

    def test_tampered_terminal_is_caught(self):
        path = self.tmp / "terminal.html"
        path.write_text(path.read_text().replace('"schema_version":1', '"schema_version":2', 1))
        self.assertTrue(any("embeds exactly" in f for f in audit(load_kb()).failures))

    def test_corrupted_chart_is_caught(self):
        (self.tmp / "journal" / "charts" / "T-0001.webp").write_bytes(b"not an image")
        failures = audit(load_kb()).failures
        self.assertTrue(any("valid .webp image" in f for f in failures))
        self.assertTrue(any("fingerprint" in f for f in failures))  # outputs no longer match the inputs

    def test_stale_outputs_are_caught(self):
        self.write_trade("T-0002", result={"r": 2.0})
        self.assertTrue(any("fingerprint" in f for f in audit(load_kb()).failures))

    def test_calculation_bug_is_caught_by_independent_recompute(self):
        from tradekb import model
        real = model.r_multiple
        with mock.patch.object(model, "r_multiple", lambda t: ((real(t)[0] or 0) + 0.01, "bug")):
            failures = audit(load_kb(), check_outputs=False).failures
        self.assertTrue(any("T-0001: R" in f for f in failures))


class LiveKnowledgeBaseTest(unittest.TestCase):
    """The real journal must satisfy every invariant (read-only; outputs are checked by `tj audit`)."""

    def test_live_invariants(self):
        with mock.patch.dict(os.environ, {"TJ_ROOT": str(REPO)}):
            result = audit(load_kb(), check_outputs=False)
        self.assertEqual(result.failures, [])

    def test_live_records_validate(self):
        from tradekb.validate import validate
        with mock.patch.dict(os.environ, {"TJ_ROOT": str(REPO)}):
            errors = [str(i) for i in validate(load_kb(), check_build=False) if i.level == "ERROR"]
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
