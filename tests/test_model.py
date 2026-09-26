import unittest

from tradekb.model import derive, initial_risk, outcome, process_grade, r_multiple, realized_pnl
from tradekb.store import DEFAULT_CONFIG as CFG


def trade(**overrides):
    base = {
        "id": "T-0001", "status": "closed", "direction": "long",
        "plan": {"entry": 100, "stop": 98, "targets": [104]},
        "risk": {"risk_amount": 100, "size": 50},
        "fills": {"exits": [{"price": 104, "qty": 50}], "fees": 0},
        "result": {},
        "review": {"scores": {}},
    }
    for key, value in overrides.items():
        base[key] = value
    return base


class RMultipleTest(unittest.TestCase):
    def test_stated_r_wins(self):
        self.assertEqual(r_multiple(trade(result={"r": 1.7, "pnl": 999})), (1.7, "stated"))

    def test_pnl_over_stated_risk(self):
        r, src = r_multiple(trade(result={"pnl": 250}))
        self.assertAlmostEqual(r, 2.5)
        self.assertIn("stated risk_amount", src)

    def test_derived_from_exits_net_of_fees(self):
        t = trade(fills={"exits": [{"price": 104, "qty": 50}], "fees": 10})
        pnl, _ = realized_pnl(t)
        self.assertAlmostEqual(pnl, 190)
        self.assertAlmostEqual(r_multiple(t)[0], 1.9)

    def test_partial_exits_by_fraction(self):
        t = trade(fills={"exits": [{"price": 102, "fraction": 0.5}, {"price": 106, "fraction": 0.5}]})
        self.assertAlmostEqual(r_multiple(t)[0], (25 * 2 + 25 * 6) / 100)

    def test_short_loss(self):
        t = trade(direction="short", plan={"entry": 100, "stop": 102}, risk={"size": 10},
                  fills={"exits": [{"price": 102, "qty": 10}]})
        self.assertEqual(initial_risk(t), (20, "size x stop distance"))
        self.assertAlmostEqual(r_multiple(t)[0], -1.0)

    def test_oversized_loss_shows_beyond_minus_one(self):
        # Stated 1R = 100, but size 100 x 2 = 200 actual risk: a full stop-out is -2R vs plan.
        t = trade(risk={"risk_amount": 100, "size": 100}, fills={"exits": [{"price": 98, "qty": 100}]})
        self.assertAlmostEqual(r_multiple(t)[0], -2.0)

    def test_price_based_without_size(self):
        t = trade(risk={}, fills={"exits": [{"price": 103}]})
        r, src = r_multiple(t)
        self.assertAlmostEqual(r, 1.5)
        self.assertIn("price-based", src)

    def test_missing_data_reports_needs(self):
        t = trade(plan={"entry": 100}, risk={}, fills={"exits": []})
        d = derive(t, CFG)
        self.assertIsNone(d.r)
        self.assertIn("plan.stop", d.missing)

    def test_counterfactual_kept_separate(self):
        t = trade(status="missed", result={"hypothetical_r": 3.0})
        d = derive(t, CFG)
        self.assertIsNone(d.r)
        self.assertEqual(d.counterfactual_r, 3.0)


class OutcomeProcessTest(unittest.TestCase):
    def test_outcome_band(self):
        self.assertEqual(outcome(0.05, None, 0.1), "breakeven")
        self.assertEqual(outcome(-0.5, None, 0.1), "loss")
        self.assertEqual(outcome(None, 10, 0.1), "win")
        self.assertIsNone(outcome(None, None, 0.1))

    def test_good_outcome_poor_process_label(self):
        t = trade(result={"r": 3.0}, review={"scores": {"setup": 2, "context": 2, "execution": 1,
                                                       "risk": 2, "management": 3}})
        d = derive(t, CFG)
        self.assertEqual(d.grade, "poor")
        self.assertEqual(d.label, "GOOD OUTCOME / POOR PROCESS")

    def test_bad_outcome_good_process_label(self):
        t = trade(result={"r": -1.0}, review={"scores": {"setup": 5, "context": 4, "execution": 5,
                                                        "risk": 5, "management": 4}})
        self.assertEqual(derive(t, CFG).label, "BAD OUTCOME / GOOD PROCESS")

    def test_too_few_scores_is_unscored(self):
        self.assertEqual(process_grade(trade(review={"scores": {"setup": 5, "risk": 5}}), CFG), (None, None))


if __name__ == "__main__":
    unittest.main()
