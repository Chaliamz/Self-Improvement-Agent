import unittest

from tradekb.stats import compare, evidence_tier, histogram, max_drawdown, streaks, summarize
from tradekb.store import DEFAULT_CONFIG as CFG


class SummaryTest(unittest.TestCase):
    def test_system_prompt_expectancy_example(self):
        # §11: 45% at +2R, 55% at -1R -> +0.35R.
        rs = [2.0] * 9 + [-1.0] * 11
        s = summarize(rs, CFG)
        self.assertEqual((s.n, s.wins, s.losses, s.breakevens), (20, 9, 11, 0))
        self.assertAlmostEqual(s.win_rate, 0.45)
        self.assertAlmostEqual(s.expectancy, 0.35)
        self.assertAlmostEqual(s.profit_factor, 18 / 11)
        self.assertAlmostEqual(s.payoff, 2.0)
        self.assertEqual(s.evidence, "MODERATE")

    def test_breakeven_band(self):
        s = summarize([0.05, -0.1, 1.0, -1.0], CFG)
        self.assertEqual((s.wins, s.losses, s.breakevens), (1, 1, 2))

    def test_small_sample_suppresses_ratios_and_ci(self):
        s = summarize([2.0, -1.0, 3.0], CFG)
        self.assertIsNone(s.profit_factor)
        self.assertIsNone(s.payoff)
        self.assertIsNone(s.ci)
        self.assertEqual(s.evidence, "LOW")

    def test_empty(self):
        s = summarize([], CFG)
        self.assertEqual(s.n, 0)
        self.assertIsNone(s.expectancy)

    def test_no_losses_profit_factor_undefined(self):
        self.assertIsNone(summarize([1.0] * 12, CFG).profit_factor)

    def test_streaks_breakeven_resets(self):
        kinds = ["win", "win", "breakeven", "win", "loss", "loss", "loss", "win"]
        self.assertEqual(streaks(kinds), (2, 3))

    def test_drawdown_is_path_dependent(self):
        self.assertAlmostEqual(max_drawdown([1, 1, -1, -1, -1, 2]), 3)
        self.assertAlmostEqual(max_drawdown([-1, -1]), 2)  # peak is the starting 0
        self.assertAlmostEqual(max_drawdown([1, 2, 3]), 0)

    def test_bootstrap_is_deterministic_and_brackets_mean(self):
        rs = [2.0, -1.0, -1.0, 3.0, -1.0, 0.5, -1.0, 2.5]
        a, b = summarize(rs, CFG), summarize(rs, CFG)
        self.assertEqual(a.ci, b.ci)
        self.assertLess(a.ci[0], a.expectancy)
        self.assertGreater(a.ci[1], a.expectancy)

    def test_evidence_tier_needs_conditions_for_higher(self):
        self.assertEqual(evidence_tier(60, 1, CFG), "MODERATE")
        self.assertEqual(evidence_tier(60, 2, CFG), "HIGHER")
        self.assertEqual(evidence_tier(19, 5, CFG), "LOW")

    def test_histogram_isolates_oversized_losses(self):
        bins = dict(histogram([-2.0, -1.0, 0.0, 0.5, 1.5, 2.5, 4.0], 0.1))
        self.assertEqual(bins["< -1.1R (loss exceeded 1R)"], 1)
        self.assertEqual(bins["-1.1R to BE"], 1)
        self.assertEqual(bins["breakeven"], 1)
        self.assertEqual(bins[">= +3R"], 1)
        self.assertEqual(sum(bins.values()), 7)


class CompareTest(unittest.TestCase):
    def test_insufficient_data(self):
        c = compare([1.0, -1.0], [2.0, -1.0, 1.0, 1.0, 1.0], CFG)
        self.assertIn("INSUFFICIENT", c.verdict)
        self.assertIsNone(c.ci)

    def test_identical_arms_no_difference(self):
        rs = [2.0, -1.0, -1.0, 1.5, -1.0, 3.0, -1.0, 0.2]
        c = compare(rs, list(rs), CFG)
        self.assertIn("NO DETECTABLE DIFFERENCE", c.verdict)

    def test_clear_difference_small_sample_is_hypothesis_only(self):
        c = compare([2.0, 2.1, 1.9, 2.0, 2.2, 1.8], [-1.0, -0.9, -1.1, -1.0, -1.0, -0.8], CFG)
        self.assertGreater(c.ci[0], 0)
        self.assertIn("hypothesis", c.verdict)

    def test_clear_difference_adequate_sample(self):
        a = [2.0, -1.0, 1.5, 2.5] * 6
        b = [-1.0, -1.0, 0.5, -1.0] * 6
        c = compare(a, b, CFG)
        self.assertIn("A shows higher expectancy", c.verdict)


if __name__ == "__main__":
    unittest.main()
