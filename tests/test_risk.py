import unittest

from tradekb.risk import CRITICAL, WARN, SizingInput, floor_to_step, infer_side, liquidation_price, size_position


class SizingTest(unittest.TestCase):
    def test_system_prompt_example(self):
        # §14: account 10,000, risk 1% = 100, stop distance 2% -> notional ~5,000.
        res = size_position(SizingInput(entry=100, stop=98, risk_amount=100, equity=10_000))
        self.assertEqual(res.side, "long")
        self.assertAlmostEqual(res.qty, 50)
        self.assertAlmostEqual(res.notional, 5_000)
        self.assertAlmostEqual(res.risk_pct, 1.0)
        self.assertAlmostEqual(res.effective_leverage, 0.5)
        self.assertEqual(res.flags, [])

    def test_leverage_does_not_change_loss_at_stop(self):
        # §13: "10x leverage" is not "10x account risk".
        low = size_position(SizingInput(entry=100, stop=98, risk_amount=100, equity=10_000, leverage=2))
        high = size_position(SizingInput(entry=100, stop=98, risk_amount=100, equity=10_000, leverage=20))
        self.assertAlmostEqual(low.loss_at_stop, high.loss_at_stop)
        self.assertAlmostEqual(low.qty, high.qty)
        self.assertAlmostEqual(low.margin_required, 2_500)
        self.assertAlmostEqual(high.margin_required, 250)

    def test_short_side(self):
        res = size_position(SizingInput(entry=50, stop=51, risk_amount=20))
        self.assertEqual(res.side, "short")
        self.assertAlmostEqual(res.qty, 20)

    def test_fees_and_slippage_shrink_size(self):
        base = size_position(SizingInput(entry=100, stop=99, risk_amount=100))
        fees = size_position(SizingInput(entry=100, stop=99, risk_amount=100, fee_rate=0.0005, slippage_pct=0.05))
        self.assertLess(fees.qty, base.qty)
        self.assertAlmostEqual(fees.loss_at_stop, 100)  # budget still respected exactly
        # stop fill 99 * (1 - 0.0005) = 98.9505; per unit = 1.0495 + 0.0005 * 198.9505
        self.assertAlmostEqual(fees.per_unit_loss, 1.0495 + 0.0005 * 198.9505)

    def test_tight_stop_fee_share_flag(self):
        res = size_position(SizingInput(entry=100, stop=99.9, risk_amount=100, fee_rate=0.0005))
        self.assertTrue(any(level == WARN and "fees are" in msg for level, msg in res.flags))

    def test_qty_step_floors_never_rounds_up(self):
        res = size_position(SizingInput(entry=100, stop=97, risk_amount=100, qty_step=0.1))
        self.assertAlmostEqual(res.qty_unrounded, 33.3333333, places=5)
        self.assertAlmostEqual(res.qty, 33.3)
        self.assertLessEqual(res.loss_at_stop, 100)

    def test_floor_to_step_float_edge(self):
        # 0.3 / 0.1 == 2.9999999999999996 in binary floats; Decimal avoids flooring to 0.2.
        self.assertAlmostEqual(floor_to_step(0.3, 0.1), 0.3)
        self.assertAlmostEqual(floor_to_step(1.23456, 0.001), 1.234)

    def test_budget_below_one_step(self):
        res = size_position(SizingInput(entry=60_000, stop=59_000, risk_amount=5, qty_step=0.01))
        self.assertEqual(res.qty, 0)
        self.assertTrue(any(level == CRITICAL for level, _ in res.flags))

    def test_wrong_side_and_zero_distance(self):
        with self.assertRaisesRegex(ValueError, "wrong side"):
            size_position(SizingInput(entry=100, stop=102, risk_amount=100, side="long"))
        with self.assertRaisesRegex(ValueError, "zero"):
            infer_side(100, 100)
        with self.assertRaisesRegex(ValueError, "> 0"):
            size_position(SizingInput(entry=100, stop=99, risk_amount=0))

    def test_target_on_loss_side_rejected(self):
        with self.assertRaisesRegex(ValueError, "profit side"):
            size_position(SizingInput(entry=100, stop=98, risk_amount=100, targets=(99,)))

    def test_target_rr_gross_and_net(self):
        res = size_position(SizingInput(entry=100, stop=98, risk_amount=100, targets=(106,), fee_rate=0.0005))
        self.assertAlmostEqual(res.targets[0].rr_gross, 3.0)
        expected_net = (6 - 0.0005 * 206) / (2 + 0.0005 * 198)
        self.assertAlmostEqual(res.targets[0].rr_net, expected_net)

    def test_risk_above_profile_max(self):
        res = size_position(SizingInput(entry=100, stop=98, risk_amount=300, equity=10_000, max_risk_pct=2))
        self.assertTrue(any(level == CRITICAL and "above your max" in msg for level, msg in res.flags))


class LiquidationTest(unittest.TestCase):
    def test_isolated_formula(self):
        long_liq = liquidation_price(100, "long", 1, leverage=10, margin_mode="isolated", mmr_rate=0.005)
        short_liq = liquidation_price(100, "short", 1, leverage=10, margin_mode="isolated", mmr_rate=0.005)
        self.assertAlmostEqual(long_liq, 100 * 0.9 / 0.995)
        self.assertAlmostEqual(short_liq, 100 * 1.1 / 1.005)

    def test_one_x_long_isolated_cannot_liquidate(self):
        self.assertIsNone(liquidation_price(100, "long", 1, leverage=1, margin_mode="isolated", mmr_rate=0.0))

    def test_cross_formula(self):
        # equity 1,000 behind 10 units at 100: long liquidates near (100 - 100) -> unreachable.
        self.assertIsNone(liquidation_price(100, "long", 10, leverage=None, margin_mode="cross",
                                            mmr_rate=0.005, equity=1_000))
        liq = liquidation_price(100, "long", 20, leverage=None, margin_mode="cross", mmr_rate=0.005, equity=1_000)
        self.assertAlmostEqual(liq, (100 - 50) / 0.995)

    def test_liquidation_before_stop_is_critical(self):
        # 50x isolated long: liquidation ~98.49 sits above a 97 stop.
        res = size_position(SizingInput(entry=100, stop=97, risk_amount=100, equity=10_000, leverage=50))
        self.assertTrue(any(level == CRITICAL and "BEFORE the stop" in msg for level, msg in res.flags))

    def test_liquidation_close_to_stop_warns(self):
        # 25x isolated long: liq = 100 * 0.96 / 0.995 ~ 96.48, stop 97 -> 1.17x stop distance.
        res = size_position(SizingInput(entry=100, stop=97, risk_amount=100, equity=10_000, leverage=25))
        self.assertTrue(any(level == WARN and "liquidation is only" in msg for level, msg in res.flags))

    def test_margin_exceeds_equity(self):
        res = size_position(SizingInput(entry=100, stop=99.5, risk_amount=500, equity=10_000, leverage=5))
        # qty 1000, notional 100,000, margin 20,000 > equity
        self.assertTrue(any(level == CRITICAL and "margin required" in msg for level, msg in res.flags))


if __name__ == "__main__":
    unittest.main()
