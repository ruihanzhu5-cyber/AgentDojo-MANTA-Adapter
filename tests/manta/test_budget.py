"""Budget regressions: reservations shared across processes and lost responses."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agentdojo_manta.budget import BudgetExceeded, RequestBudget


class BudgetTests(unittest.TestCase):
    def test_shared_cap_and_usage_settlement(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "budget.sqlite"
            first = RequestBudget(path, "0.4")
            second = RequestBudget(path, "0.4")
            reservation = first.reserve("deepseek-v4-flash", 4096)
            charge = first.settle(reservation, SimpleNamespace(prompt_tokens=1000, completion_tokens=100))
            self.assertAlmostEqual(charge, 0.00042)
            self.assertAlmostEqual(second.snapshot()["response_cost_upper_bound_usd"], charge)
            second.reserve("deepseek-v4-flash", 4096)
            self.assertLessEqual(second.snapshot()["accounted_upper_bound_usd"], 0.4)

    def test_lost_response_retains_reservation_and_blocks_next_call(self):
        with tempfile.TemporaryDirectory() as folder:
            budget = RequestBudget(Path(folder) / "budget.sqlite", "0.4")
            request = budget.reserve("deepseek-v4-flash", 4096)
            budget.uncertain(request)
            with self.assertRaises(BudgetExceeded):
                budget.reserve("deepseek-v4-flash", 4096)
            self.assertTrue(budget.snapshot()["blocked"])

    def test_unknown_model_is_rejected_before_request(self):
        with tempfile.TemporaryDirectory() as folder:
            budget = RequestBudget(Path(folder) / "budget.sqlite", "5")
            with self.assertRaises(ValueError):
                budget.reserve("unpriced-model", 4096)
            self.assertEqual(budget.snapshot()["accounted_upper_bound_usd"], 0)


if __name__ == "__main__":
    unittest.main()
