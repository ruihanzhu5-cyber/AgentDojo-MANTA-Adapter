"""Offline regressions for official score polarity and metric denominators."""
import unittest

from agentdojo_manta.metrics import official_outcomes, resource_metrics, summarize, topology_metrics


class MetricTests(unittest.TestCase):
    def test_official_goal_true_means_attack_success(self):
        from agentdojo.agent_pipeline.ground_truth_pipeline import GroundTruthPipeline
        from agentdojo.task_suite.load_suites import get_suite
        suite = get_suite("v1.2.2", "workspace")
        goal = suite.get_injection_task_by_id("injection_task_0")
        utility, security = suite.run_task_with_pipeline(
            GroundTruthPipeline(goal), suite.get_user_task_by_id("user_task_0"), goal, {})
        self.assertTrue(security)
        self.assertTrue(official_outcomes(utility, security, clean=False)["attack_success"])

    def test_unchanged_sandbox_is_attack_failure(self):
        from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
        from agentdojo.task_suite.load_suites import get_suite

        class NoAction(BasePipelineElement):
            def query(self, query, runtime, env, **kwargs):
                return query, runtime, env, [{"role": "assistant", "content": [
                    {"type": "text", "content": "No action."}], "tool_calls": None}], {}
        suite = get_suite("v1.2.2", "workspace")
        utility, security = suite.run_task_with_pipeline(
            NoAction(), suite.get_user_task_by_id("user_task_0"),
            suite.get_injection_task_by_id("injection_task_0"), {})
        self.assertFalse(security)
        self.assertFalse(official_outcomes(utility, security, clean=False)["attack_success"])

    def test_clean_sentinel_never_enters_asr(self):
        self.assertIsNone(official_outcomes(True, True, clean=True)["attack_success"])

    def test_infra_failure_never_counts_as_safe(self):
        result = official_outcomes(False, False, clean=False, error_status="INFRA_ERROR")
        self.assertIsNone(result["attack_success"])
        self.assertIsNone(result["task_success"])
        self.assertFalse(result["evaluation_valid"])

    def test_mock_is_excluded(self):
        result = official_outcomes(True, True, clean=False, mock_used=True)
        self.assertFalse(result["evaluation_valid"])
        self.assertIsNone(result["task_success"])

    def test_tokens_include_planner_and_discarded_worker(self):
        requests = [dict(status="completed", usage_available=True, token_in=10, token_out=2,
                         agent_id=actor) for actor in ["topology_planner", "agent_0", "auditor"]]
        result = resource_metrics(requests, mock_used=False)
        self.assertEqual(result["tokens"], 36)
        self.assertIsNone(result["cost_usd"])

    def test_missing_usage_is_unknown(self):
        result = resource_metrics([dict(status="completed", usage_available=False)], mock_used=False)
        self.assertIsNone(result["tokens"])

    def test_handoff_requires_cross_agent_view(self):
        metadata = dict(topology_layout={"agent_ids": ["a", "b"]},
                        relay_messages=[dict(message_id="m1", sender="a", recipients=["b"]),
                                        dict(message_id="m2", sender="shared_context", recipients=["b"]),
                                        dict(message_id="m3", sender="a", recipients=["b"])],
                        message_views=[dict(viewer="b", visible_message_ids=["m1", "m2"]),
                                       dict(viewer="b", visible_message_ids=["m1"])],
                        self_evolved={"mutations": []})
        result = topology_metrics(metadata, [dict(agent_id="a"), dict(agent_id="b")])
        self.assertEqual(result["handoff_count"], 1)
        self.assertEqual(result["relay_packet_count"], 3)
        self.assertEqual(result["real_multiagent_handoff"], "UNKNOWN")
        live = topology_metrics(metadata, [dict(agent_id="a", status="completed"),
                                           dict(agent_id="b", status="completed")])
        self.assertTrue(live["real_multiagent_handoff"])

    def test_missing_topology_is_unknown(self):
        result = topology_metrics({}, [])
        self.assertIsNone(result["actual_agent_count"])
        self.assertIsNone(result["handoff_count"])
        self.assertIsNone(result["topology_mutation_count"])

    def test_rates_keep_failures_and_unknown_exposure_distinct(self):
        rows = [{**official_outcomes(True, success, clean=False),
                 "condition": "attack", "attack_exposed": exposure}
                for success, exposure in [(True, True), (False, "UNKNOWN")]]
        rows.append({**official_outcomes(False, False, clean=False, error_status="TIMEOUT"),
                     "condition": "attack", "attack_exposed": "UNKNOWN"})
        result = summarize(rows)
        self.assertEqual(result["targeted_asr"], 0.5)
        self.assertEqual(result["conditional_asr"], 1.0)
        self.assertEqual(result["invalid_episodes"], 1)
        self.assertEqual(result["exposure_unknown_n"], 1)

    def test_provider_observer_records_calls_missing_from_stage_logs(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from pathlib import Path
        import threading
        from agentdojo_manta.adapter import AdapterPaths, _make_llm_client

        class FakeClient:
            def __init__(self, *args):
                pass

            def _create_chat_completion_once(self, **kwargs):
                if kwargs["model"] == "fail":
                    raise RuntimeError("unavailable")
                return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3), mock_used=False)

            def _create_chat_completion(self, **kwargs):
                return self._create_chat_completion_once(**kwargs)

            def generate(self, **kwargs):
                return self._create_chat_completion(model=kwargs.get("model", "ok"),
                                                    messages=[{"role": "tool", "content": "prefix\nPAYLOAD\nsuffix"}])

        observer = SimpleNamespace(_metrics_lock=threading.Lock(), injections={"injection": "PAYLOAD"},
                                   request_records=[], mock_used=False)
        with patch("agentdojo_manta.adapter._import_manta", return_value=(SimpleNamespace, None, FakeClient, None, None)):
            client = _make_llm_client(AdapterPaths.from_repo(Path.cwd()), observer=observer)
            client.generate(agent_id="topology_planner")
            with self.assertRaises(RuntimeError):
                client.generate(agent_id="agent_0", model="fail")
        self.assertEqual(len(observer.request_records), 2)
        self.assertEqual(observer.request_records[0]["agent_id"], "topology_planner")
        self.assertEqual(observer.request_records[0]["matched_injection_keys"], ["injection"])
        self.assertEqual(observer.request_records[1]["status"], "error")
        self.assertEqual(resource_metrics(observer.request_records, mock_used=False)["tokens"], 14)

    def test_official_trace_uses_actual_runtime_calls_only(self):
        import threading
        from types import SimpleNamespace
        from agentdojo.task_suite.load_suites import get_suite
        from agentdojo.task_suite.task_suite import functions_stack_trace_from_messages
        from agentdojo.functions_runtime import FunctionsRuntime
        from agentdojo_manta.adapter import _function_to_manta_tool, _build_agentdojo_messages
        suite = get_suite("v1.2.2", "workspace")
        runtime = FunctionsRuntime(suite.tools)
        observer = SimpleNamespace(_metrics_lock=threading.Lock(), runtime_calls=[])
        tool = _function_to_manta_tool(runtime, suite.load_and_inject_default_environment({}),
                                      runtime.functions["get_current_day"], observer=observer)
        tool["handler"]({})
        metadata = {"agentdojo_runtime_calls": observer.runtime_calls,
                    "interaction_logs": [{"tool_calls": [{"tool_name": "unexecuted_synthetic_call"}]}]}
        messages = _build_agentdojo_messages("task", metadata, "done")
        calls = functions_stack_trace_from_messages(messages)
        self.assertEqual([call.function for call in calls], ["get_current_day"])


if __name__ == "__main__":
    unittest.main()
