"""Focused zero-API checks for Pro prices, wire history and frozen identities."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agentdojo_manta.budget import DeepSeekProBudget, RequestBudget
from agentdojo_manta.deepseek_pro import ProReasoningHistory, validate_pro_response


class ProTests(unittest.TestCase):
    def test_pro_rates_and_flash_ledger_separation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pro.sqlite"
            budget = DeepSeekProBudget(path, "100")
            rid = budget.reserve("deepseek-v4-pro", 4096)
            self.assertAlmostEqual(budget.settle(rid, SimpleNamespace(prompt_tokens=1000, completion_tokens=100)), .001716)
            with self.assertRaises(ValueError):
                budget.reserve("deepseek-v4-flash", 4096)
            flash_path = Path(folder) / "flash.sqlite"
            flash = RequestBudget(flash_path, "100")
            flash.uncertain(flash.reserve("deepseek-v4-flash", 4096))
            with self.assertRaises(ValueError):
                DeepSeekProBudget(flash_path, "100")

    def test_actual_reasoning_is_preserved_and_missing_history_rejected(self):
        history = ProReasoningHistory()
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None,
            reasoning_content="recorded provider reasoning", tool_calls=[SimpleNamespace(id="call_1")]))])
        history.remember(response)
        messages = [{"role": "assistant", "content": "", "tool_calls": [{"id": "call_1"}]}]
        request = history.prepare({"messages": messages})
        self.assertEqual(request["messages"][0]["reasoning_content"], "recorded provider reasoning")
        self.assertNotIn("reasoning_content", messages[0])
        with self.assertRaises(ValueError):
            ProReasoningHistory().prepare({"messages": messages})

    def test_wrong_model_and_missing_usage_are_not_accepted(self):
        response = SimpleNamespace(model="deepseek-v4-pro", usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2,total_tokens=12))
        validate_pro_response(response)
        response.model = "deepseek-flash"
        with self.assertRaises(ValueError):
            validate_pro_response(response)
        response.model, response.usage = "deepseek-v4-pro", None
        with self.assertRaises(ValueError):
            validate_pro_response(response)


if __name__ == "__main__":
    unittest.main()
