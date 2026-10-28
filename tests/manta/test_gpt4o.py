"""Zero-cost GPT-4o protocol, routing, immutable queue and monetary regressions."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agentdojo_manta.budget import BudgetExceeded, GPT4oBudget
from agentdojo_manta.providers import gpt4o_sampling, provider_config, validate_gpt4o_response

ROOT = Path(__file__).resolve().parents[2]


class GPT4oTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"MANTA_PROVIDER": "openai", "OPENAI_BASE_URL": "https://api.openai.com/v1"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_all_roles_and_endpoint_are_exact(self):
        os.environ["DEEPSEEK_MODEL"] = "wrong-provider-model"
        provider = provider_config()
        self.assertEqual(provider.base_url, "https://api.openai.com/v1")
        self.assertEqual((provider.model, provider.planner_model, provider.auditor_model), ("gpt-4o",) * 3)
        self.assertIsNone(provider.api_key)

    def test_no_provider_or_model_substitution(self):
        for name, value in (("OPENAI_BASE_URL", "https://other.invalid/v1"), ("OPENAI_PLANNER_MODEL", "gpt-4o-mini")):
            with patch.dict(os.environ, {name: value}):
                with self.assertRaises(ValueError):
                    provider_config()
        with self.assertRaises(ValueError):
            provider_config("gpt-4.1")

    def test_baseline_sampling_ignores_openrouter_overrides(self):
        os.environ["OPENROUTER_MAX_TOKENS"] = "393216"
        result = gpt4o_sampling({"model": "gpt-4o", "max_tokens": 100, "extra_body": {"provider": {}}}, temperature=0)
        self.assertEqual(result["max_tokens"], 4096)
        self.assertNotIn("extra_body", result)

    def test_usage_and_response_model_are_required(self):
        response = SimpleNamespace(model="gpt-4o-2024-11-20", usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12))
        validate_gpt4o_response(response)
        response.model = "gpt-4o-mini"
        with self.assertRaises(ValueError):
            validate_gpt4o_response(response)
        response.model, response.usage = "gpt-4o", None
        with self.assertRaises(ValueError):
            validate_gpt4o_response(response)

    def test_independent_rates_and_shared_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "budget.sqlite"
            first = GPT4oBudget(path, "0.8")
            second = GPT4oBudget(path, "0.8")
            request = first.reserve("gpt-4o", 4096)
            charge = first.settle(request, SimpleNamespace(prompt_tokens=1000, completion_tokens=100))
            self.assertAlmostEqual(charge, 0.0035)
            self.assertAlmostEqual(second.snapshot()["response_cost_upper_bound_usd"], charge)
            request = second.reserve("gpt-4o", 4096)
            second.uncertain(request)
            self.assertGreater(first.snapshot()["unreturned_reservations_usd"], 0.36)

    def test_hard_cap_retains_uncertain_request(self):
        with tempfile.TemporaryDirectory() as folder:
            budget = GPT4oBudget(Path(folder) / "budget.sqlite", "0.4")
            request = budget.reserve("gpt-4o", 4096)
            with self.assertRaises(ValueError):
                budget.settle(request, None)
            with self.assertRaises(BudgetExceeded):
                budget.reserve("gpt-4o", 4096)
            self.assertLessEqual(budget.snapshot()["accounted_upper_bound_usd"], 0.4)

    def test_pricing_identity_cannot_change(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "budget.sqlite"
            GPT4oBudget(path, "10")
            with patch.dict(os.environ, {"GPT4O_PRICE_MULTIPLIER": "2"}):
                with self.assertRaises(ValueError):
                    GPT4oBudget(path, "10")

    def test_unpriced_models_and_outputs_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            budget = GPT4oBudget(Path(folder) / "budget.sqlite", "10")
            for model, count in (("gpt-4o-mini", 4096), ("deepseek-v4-flash", 4096), ("gpt-4o", 16385)):
                with self.assertRaises(ValueError):
                    budget.reserve(model, count)

    def test_qdd_requires_pricing_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            os.environ["MANTA_PROVIDER"] = "qdd"
            with self.assertRaises(ValueError):
                GPT4oBudget(Path(folder) / "budget.sqlite", "10")

    def test_original_scene_and_job_identity_is_preserved(self):
        from agentdojo_manta.replication import load_replication_plan
        full = load_replication_plan(ROOT, provider="openai", source_digest="test")
        original = json.loads((ROOT / "reports/2026-10-19-manta-agentdojo/manifest.json").read_text())
        self.assertEqual(full["scenes"], original["scenes"])
        self.assertEqual(full["jobs"], original["jobs"])
        self.assertEqual(len(full["jobs"]), 160)
        pilot = load_replication_plan(ROOT, provider="openai", source_digest="test", pilot=True)
        self.assertEqual(len(pilot["jobs"]), 8)
        self.assertEqual({s["scene_id"] for s in pilot["scenes"]}, {"banking_00", "slack_00", "travel_00", "workspace_00"})

    def test_real_sdk_tool_protocol_with_local_transport(self):
        import httpx
        import openai
        from agentdojo_manta.adapter import AdapterPaths, _make_llm_client
        with tempfile.TemporaryDirectory() as folder:
            os.environ.update(OPENAI_API_KEY="offline-test-only", MAS_REQUIRE_LIVE_LLM="1",
                              GPT4O_BUDGET_DB=str(Path(folder) / "budget.sqlite"), GPT4O_MAX_COST_USD="10",
                              GPT4O_REQUEST_JOURNAL=str(Path(folder) / "requests.jsonl"))
            observer = SimpleNamespace(_metrics_lock=threading.Lock(), mock_used=False, injections={"payload": "injected text"}, request_records=[])
            client = _make_llm_client(AdapterPaths.from_repo(ROOT), "gpt-4o", observer=observer)
            calls = []

            def transport(request):
                body = json.loads(request.content)
                calls.append(body)
                if len(calls) == 1:
                    message = dict(role="assistant", content=None, tool_calls=[dict(id="call_1", type="function", function=dict(name="lookup", arguments="{}"))])
                    reason = "tool_calls"
                else:
                    self.assertTrue(any(m["role"] == "tool" and m["tool_call_id"] == "call_1" for m in body["messages"]))
                    message, reason = dict(role="assistant", content="Done."), "stop"
                return httpx.Response(200, json=dict(id=f"chatcmpl_{len(calls)}", object="chat.completion", created=1,
                    model="gpt-4o-2024-11-20", choices=[dict(index=0, message=message, finish_reason=reason)],
                    usage=dict(prompt_tokens=10, completion_tokens=2, total_tokens=12)))

            client.client = openai.OpenAI(api_key="offline-test-only", max_retries=0,
                                          http_client=httpx.Client(transport=httpx.MockTransport(transport)))
            result = client.generate(prompt="injected text", agent_type="general", task_id="offline", run_index=0,
                                     agent_id="agent_0", tools=[dict(name="lookup", description="Read", parameters={"type": "object", "properties": {}}, handler=lambda args: "found")])
            self.assertFalse(result.mock_used)
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(c["model"] == "gpt-4o" and c["max_tokens"] == 4096 for c in calls))
            self.assertFalse(calls[0]["parallel_tool_calls"])
            self.assertEqual(sum(r["token_in"] for r in observer.request_records), 20)
            events = [json.loads(line) for line in Path(os.environ["GPT4O_REQUEST_JOURNAL"]).read_text().splitlines()]
            self.assertEqual([e["status"] for e in events], ["pending", "completed", "pending", "completed"])
            self.assertTrue(observer.request_records[0]["matched_injection_keys"])


if __name__ == "__main__":
    unittest.main()
