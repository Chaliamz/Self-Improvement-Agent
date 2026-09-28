"""End-to-end render: the built terminal, in headless Chromium, every tab and every background.

Builds from a copy of the live knowledge base (never touching the repo's outputs), injects a probe
that walks the UI, and fails on any JavaScript error, unrendered panel, missing chart or horizontal
overflow. Skips when no Chromium is installed.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
TABS = ["overview", "journal", "performance", "strategy", "risk", "behaviour", "readiness", "gaps", "health"]
BACKGROUNDS = ["aurora", "borealis", "nebula", "plasma", "lava", "fireflies", "silk", "constellation", "starfield", "waves",
               "tape", "depth", "heatmap", "bubbles", "radar", "matrix", "synthwave", "off"]
CANVAS = {"borealis", "fireflies", "silk", "constellation", "starfield", "matrix", "waves", "depth", "heatmap", "bubbles", "radar"}


def chromium() -> str | None:
    for cand in (os.environ.get("CHROME_BIN"), shutil.which("chromium"), shutil.which("chromium-browser"),
                 shutil.which("google-chrome")):
        if cand:
            return cand
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    hits = sorted(glob.glob(f"{base}/chromium-*/chrome-linux*/chrome"))
    return hits[-1] if hits else None


PROBE = r"""<script>
addEventListener("load", () => {
  const tabs = %TABS%, bgs = %BGS%, out = { tabs: {} };
  let i = 0;
  const finish = () => {
    const cv = document.getElementById("bg-canvas");
    const ink = () => { const d = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data; let n = 0;
                        for (let p = 3; p < d.length; p += 64) if (d[p]) n++; return n; };
    for (const mode of bgs) {
      applyBackground(mode);
      const de = document.documentElement;
      out["bg_" + mode] = de.dataset.bg; out["kind_" + mode] = de.dataset.bgKind; out["ink_" + mode] = ink();
      out["shown_" + mode] = [...document.querySelectorAll("#bg > *")].filter(el => getComputedStyle(el).display !== "none").length;
    }
    const dlg = document.getElementById("trade-dialog");
    for (const t of KB.trades) { openTrade(t.id); out["dialog_" + t.id] = dlg.open && dlg.querySelectorAll(".card").length; dlg.close(); }
    const pre = document.createElement("pre"); pre.id = "probe";
    pre.textContent = JSON.stringify({ errs: window.__errs, out });
    document.body.append(pre);
  };
  const step = () => {
    if (i >= tabs.length) return finish();
    const id = tabs[i++]; select(id);
    setTimeout(() => {
      const panel = document.getElementById("panel-" + id), de = document.documentElement;
      out.tabs[id] = { kids: panel.children.length, svg: panel.querySelectorAll("svg").length,
                       rows: panel.querySelectorAll("tbody tr").length, overflow: de.scrollWidth - de.clientWidth,
                       grades: panel.querySelectorAll("svg[data-chart=grades] .grade-letter").length,
                       items: panel.querySelectorAll("li").length,
                       ladder: panel.querySelectorAll("svg[data-chart=ladder] .pin").length,
                       incidents: panel.querySelectorAll(".inc-title").length, guards: panel.querySelectorAll(".guard-id").length };
      step();
    }, 300);
  };
  step();
});
</script></body>"""
TRAP = '<script>window.__errs=[];addEventListener("error",e=>window.__errs.push(e.message+" @"+e.lineno));</script>'


@unittest.skipUnless(chromium(), "Chromium not installed")
class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        for name in ("taxonomy", "templates", "profile", "journal", "playbook"):
            shutil.copytree(REPO / name, cls.tmp / name)
        shutil.copy(REPO / "config.yaml", cls.tmp / "config.yaml")
        with mock.patch.dict(os.environ, {"TJ_ROOT": str(cls.tmp)}):
            from tradekb.export import build
            from tradekb.store import load_kb
            build(load_kb())
        html = (cls.tmp / "terminal.html").read_text(encoding="utf-8")
        probe = PROBE.replace("%TABS%", json.dumps(TABS)).replace("%BGS%", json.dumps(BACKGROUNDS))
        (cls.tmp / "probe.html").write_text(html.replace("<head>", "<head>" + TRAP, 1).replace("</body>", probe), encoding="utf-8")
        kb = json.loads((cls.tmp / "exports" / "kb.json").read_text(encoding="utf-8"))
        cls.want_grades = len((kb["profile"].get("grading") or {}).get("scale") or ["S", "A", "B", "C", "D"])
        cls.want_bot_questions = len(kb["readiness"].get("open_questions") or [])
        cls.want_incidents = len(kb.get("incidents") or [])
        cls.want_guards = len((kb["readiness"].get("malfunction_guard") or {}).get("checks") or [])
        cls.want_ladder = sum(1 for t in kb["trades"] if any(x is not None for x in t["derived"].get("planned_rr") or []))
        cls.results = {}
        for width in (1280, 500):
            dom = subprocess.run([chromium(), "--headless=new", "--no-sandbox", "--disable-gpu", f"--window-size={width},900",
                                  "--virtual-time-budget=8000", "--dump-dom", (cls.tmp / "probe.html").as_uri()],
                                 capture_output=True, text=True, timeout=120).stdout
            match = re.search(r'<pre id="probe">(.*?)</pre>', dom, re.S)
            cls.results[width] = json.loads(match.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")) if match else None

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_probe_completed_without_errors(self):
        for width, res in self.results.items():
            self.assertIsNotNone(res, f"probe did not complete at {width}px: the page script failed")
            self.assertEqual(res["errs"], [], f"JavaScript errors at {width}px")

    def test_every_tab_renders_without_overflow(self):
        for width, res in self.results.items():
            for tab in TABS:
                info = res["out"]["tabs"][tab]
                self.assertGreater(info["kids"], 0, f"{tab} empty at {width}px")
                self.assertLessEqual(info["overflow"], 0, f"{tab} overflows horizontally at {width}px")

    def test_charts_present(self):
        tabs = self.results[1280]["out"]["tabs"]
        self.assertGreaterEqual(tabs["overview"]["svg"], 3, "overview: cumulative R, distribution, R per trade")
        self.assertGreaterEqual(tabs["performance"]["svg"], 3, "performance: group bars and two scatters")
        self.assertEqual(tabs["performance"]["grades"], self.want_grades, "results by grade: one row per grade, S to D")
        self.assertGreaterEqual(tabs["gaps"]["items"], self.want_bot_questions, "data gaps list the bot questions")
        self.assertEqual(tabs["performance"]["ladder"], self.want_ladder, "planned R:R ladder: one pin per setup with a target")
        self.assertGreaterEqual(tabs["journal"]["rows"], 1)
        self.assertEqual(tabs["health"]["incidents"], self.want_incidents, "health: one row per logged incident")
        self.assertEqual(tabs["health"]["guards"], self.want_guards, "health: one row per malfunction-guard check")

    def test_backgrounds_and_trade_dialogs(self):
        out = self.results[1280]["out"]
        for mode in BACKGROUNDS:
            self.assertEqual(out["bg_" + mode], mode)
            self.assertEqual(out["kind_" + mode], "canvas" if mode in CANVAS else "css", mode)
            if mode in CANVAS:
                self.assertGreater(out["ink_" + mode], 0, f"{mode}: the canvas scene drew nothing")
            else:
                self.assertEqual(out["ink_" + mode], 0, f"{mode}: a stopped scene left pixels on the canvas")
            self.assertGreaterEqual(out["shown_" + mode], 1, f"{mode}: no background layer visible")
        dialogs = {k: v for k, v in out.items() if k.startswith("dialog_")}
        self.assertTrue(dialogs)
        for key, cards in dialogs.items():
            self.assertTrue(cards and cards >= 5, f"{key} did not render its cards")


if __name__ == "__main__":
    unittest.main()
