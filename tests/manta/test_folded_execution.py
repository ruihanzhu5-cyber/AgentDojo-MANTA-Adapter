"""Deterministic local code checks. No API clients, benchmark episodes or network."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from agentdojo_manta.adapter import AdapterPaths, _import_manta
_import_manta(AdapterPaths.from_repo(ROOT))
from MAS.self_evolved.action_policy import TaskContract, effect
from MAS.self_evolved.agent_loop import DEFAULTS, FoldedSession, ResourceLimit
from MAS.self_evolved.evidence_store import EvidenceStore
from MAS.self_evolved.tool_gateway import ToolGateway


class Call:
    def __init__(self, name, args, ident):
        self.id = ident
        self.function = SimpleNamespace(name=name, arguments=json.dumps(args))

    def model_dump(self):
        return dict(id=self.id, type="function", function=vars(self.function))


def response(content="done", calls=()):
    return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=list(calls)),
            finish_reason="tool_calls" if calls else "stop")])


class ScriptClient:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def complete_folded(self, **kwargs):
        self.requests.append(copy.deepcopy({k: v for k, v in kwargs.items() if k != "history"}))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def tool(name, handler):
    return dict(name=name, description="Local controlled operation", parameters=dict(type="object", properties={}), handler=handler)


class GatewayChecks(unittest.TestCase):
    def build(self, review=lambda *a: ("allow", "local controlled verdict")):
        self.reads, self.writes = [], []
        tools = [tool("get_balance", lambda a: self.reads.append(a) or 10),
                 tool("send_money", lambda a: self.writes.append(a) or {"ok": True})]
        store = EvidenceStore()
        gateway = ToolGateway(tools, store, TaskContract("Pay the requested amount"), review)
        gateway.permit("agent_0", [t["name"] for t in tools])
        gateway.permit("agent_1", ["get_balance"])
        return gateway, store

    def test_cache_is_before_handler_and_invalidates_after_effect(self):
        g, store = self.build()
        g.call("agent_0", "get_balance", {})
        g.call("agent_1", "get_balance", {})
        self.assertEqual(len(self.reads), 1)
        self.assertEqual(g.events[-1]["status"], "cache_hit")
        self.assertFalse(g.events[-1]["handler_invoked"])
        g.call("agent_0", "send_money", {"amount": 1})
        g.call("agent_0", "get_balance", {})
        self.assertEqual(len(self.reads), 2)

    def test_denial_and_worker_permissions_prevent_real_effects(self):
        g, _ = self.build(lambda *a: ("deny", "unrelated destination"))
        self.assertIn("error", g.call("agent_0", "send_money", {"amount": 1}))
        self.assertIn("error", g.call("agent_1", "send_money", {"amount": 1}))
        self.assertEqual(self.writes, [])

    def test_exact_successful_write_is_not_replayed(self):
        g, _ = self.build()
        g.call("agent_0", "send_money", {"amount": 1})
        result = g.call("agent_0", "send_money", {"amount": 1})
        self.assertTrue(result["already_applied"])
        self.assertEqual(len(self.writes), 1)

    def test_navigation_is_retrieved_again_after_state_changes(self):
        count = []
        tools = [tool("get_webpage", lambda a: count.append(a) or len(count)),
                 tool("post_webpage", lambda a: "updated")]
        g = ToolGateway(tools, EvidenceStore(), TaskContract("Read and update this page"), lambda *a: ("allow", "local"))
        g.permit("agent_0", [t["name"] for t in tools])
        g.call("agent_0", "get_webpage", {"url": "https://example.test"})
        g.call("agent_0", "post_webpage", {"url": "https://example.test"})
        g.call("agent_0", "get_webpage", {"url": "https://example.test"})
        self.assertEqual(len(count), 2)

    def test_unread_mail_is_stateful_and_cannot_be_worker_cached(self):
        self.assertEqual(effect("get_unread_emails"), "consume")
        contract = TaskContract("Check my unread mail")
        self.assertEqual(contract.initial_decision("get_unread_emails", {}, "agent_1")[0], "deny")
        self.assertEqual(contract.initial_decision("get_unread_emails", {}, "agent_0")[0], "review")

    def test_unknown_read_like_name_does_not_gain_read_authority(self):
        self.assertEqual(effect("get_execute_payment"), "unknown")

    def test_evidence_permissions_and_selected_later_slice(self):
        store = EvidenceStore()
        ref = store.add("a" * 10000 + "decisive", tool="get_balance", arguments={}, version=0, actor="agent_0")
        with self.assertRaises(ValueError):
            store.read("agent_1", ref)
        store.read("agent_0", ref, 10000, 100, select=True)
        self.assertEqual(store.review_slice("agent_0", ref)["content"], "decisive")
        self.assertEqual(store.review_slice("agent_0", ref)["origin"], "external_tool_result")

    def test_review_resource_failure_is_not_policy_denial_or_execution(self):
        def unavailable(*args):
            raise ResourceLimit("local budget")
        g, _ = self.build(unavailable)
        with self.assertRaises(ResourceLimit):
            g.call("agent_0", "send_money", {"amount": 1})
        self.assertEqual(g.events[-1]["status"], "review_error")
        self.assertFalse(g.events[-1]["handler_invoked"])
        self.assertEqual(self.writes, [])


class LoopChecks(unittest.TestCase):
    def test_one_context_reuses_real_tool_result_without_schema_copy(self):
        reads = []
        client = ScriptClient([
            response("", [Call("load_tools", {"names": ["get_balance"]}, "a")]),
            response("", [Call("get_balance", {}, "b")]), response("Balance is 10.")])
        session = FoldedSession(client, "What is my balance?", [tool("get_balance", lambda a: reads.append(a) or 10)], DEFAULTS)
        result = session.run("local", 42)
        self.assertEqual(reads, [{}])
        self.assertEqual(result.final_answer, "Balance is 10.")
        self.assertEqual([r["agent_id"] for r in client.requests], ["agent_0"] * 3)
        self.assertEqual(len(client.requests[2]["messages"]), 6)
        self.assertNotIn("Available tools:", client.requests[0]["messages"][0]["content"])
        self.assertEqual(result.run_metadata["execution_plan"]["physical_loop_count"], 1)

    def test_bad_internal_arguments_are_local_validation_errors(self):
        session = FoldedSession(ScriptClient([]), "Read", [], DEFAULTS)
        for name, args in [("find_tools", {"query": None}), ("load_tools", {"names": "get_balance"}),
                           ("read_evidence", {"evidence_id": "e1", "start": True})]:
            with self.assertRaises(ValueError):
                session.dispatch("agent_0", name, args)

    def test_delegation_uses_a_fresh_bounded_read_context_and_returns_evidence(self):
        client = ScriptClient([
            response("", [Call("load_tools", {"names": ["get_balance"]}, "w-load")]),
            response("", [Call("get_balance", {}, "w-read")]), response("Balance verified: 10.")])
        reads = []
        session = FoldedSession(client, "Check my balance", [tool("get_balance", lambda a: reads.append(a) or 10)], DEFAULTS)
        result = session.dispatch("agent_0", "delegate_investigation", dict(subgoal="Verify account balance",
            evidence_need="Independent balance lookup", allowed_tools=["get_balance"], evidence_ids=[], completion_condition="Return balance with evidence"))
        self.assertEqual([r["agent_id"] for r in client.requests], ["agent_1"] * 3)
        self.assertEqual(session.gateway.permissions["agent_1"], {"get_balance"})
        self.assertEqual(reads, [{}])
        self.assertEqual(result["evidence_ids"], ["e0001"])
        self.assertIn("e0001", session.store.visible["agent_0"])
        self.assertEqual(session.plan.versions[-1]["groups"][0]["pattern"], "star")

    def test_selected_slice_changes_verdict_cache_identity(self):
        client = ScriptClient([response('{"decision":"deny","reason":"missing"}'),
                               response('{"decision":"allow","reason":"supported"}')])
        session = FoldedSession(client, "Send the requested report", [], DEFAULTS)
        ref = session.store.add("a" * 10000 + "destination fact", tool="get_balance", arguments={}, version=0, actor="agent_0")
        self.assertEqual(session.review_action("send_email", {"to": "x"}, [ref])[0], "deny")
        session.store.read("agent_0", ref, 10000, 100, select=True)
        self.assertEqual(session.review_action("send_email", {"to": "x"}, [ref])[0], "allow")
        self.assertEqual(session.audits[-1]["evidence_slices"][0][1], 10000)
        self.assertEqual(len(client.requests), 2)

    def test_resource_limit_has_explicit_termination(self):
        session = FoldedSession(ScriptClient([ResourceLimit("local limit")]), "Read", [], DEFAULTS)
        result = session.run("local", 42)
        self.assertEqual(result.run_metadata["termination_reason"], "episode_resource_limit")

    def test_empty_choice_is_infrastructure_failure_even_nested(self):
        session = FoldedSession(ScriptClient([SimpleNamespace(usage=SimpleNamespace(prompt_tokens=1, completion_tokens=0), choices=[])]), "Read", [], DEFAULTS)
        with self.assertRaises(RuntimeError):
            session.complete("action_verifier", [])

    def test_registered_official_tools_have_explicit_effects(self):
        from agentdojo.task_suite.load_suites import get_suites
        unknown = [(s, t.name) for s, suite in get_suites("v1.2.2").items()
                   for t in suite.tools if effect(t.name) == "unknown"]
        self.assertEqual(unknown, [])


class TransportChecks(unittest.TestCase):
    def test_real_adapter_wiring_is_observed_once_and_keeps_separate_reasoning(self):
        # Replace the transport class before construction: no SDK/client/network.
        from agentdojo_manta.adapter import _make_llm_client
        from MAS.llm import OpenRouterLLMClient
        class Usage:
            prompt_tokens, completion_tokens, total_tokens = 10, 5, 15
            def model_dump(self):
                return dict(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        class Budget:
            def __init__(self):
                self.requests = []
            def reserve(self, model, limit):
                self.requests.append((model, limit))
                return str(len(self.requests))
            def settle(self, *a):
                return 0.0
            def uncertain(self, *a):
                pass
        class SDK:
            def with_options(self, **kw):
                return self
        class Transport:
            def __init__(self, config, models):
                self.config, self.models, self.client = config, models, SDK()
                self.wire_calls = []
            def generate(self, **kw):
                raise AssertionError("Legacy generate must not run")
            def _create_chat_completion(self, **kw):
                raise AssertionError("Hidden retry wrapper must not run")
            def _apply_openrouter_sampling_overrides(self, kwargs, **kw):
                return {**kwargs, "max_tokens": 16384}
            _completion_has_usable_choice = staticmethod(OpenRouterLLMClient._completion_has_usable_choice)
            def _create_chat_completion_once(self, **kw):
                self.wire_calls.append(copy.deepcopy(kw))
                item = response("inspecting", [Call("get_balance", {}, "root-call")]) if len(self.wire_calls) == 1 else response("" if getattr(self, "force_empty", False) else "done")
                item.model = "deepseek-flash"
                item.usage = Usage()
                item.choices[0].message.reasoning_content = "actual root reasoning" if len(self.wire_calls) == 1 else "other reasoning"
                return item
        observer = SimpleNamespace(_metrics_lock=threading.Lock(), request_records=[], injections={}, mock_used=False)
        budget = Budget()
        env = dict(MANTA_PROVIDER="deepseek", DEEPSEEK_MODEL="deepseek-flash", DEEPSEEK_API_KEY="local-test-placeholder",
                   DEEPSEEK_BASE_URL="https://api.deepseek.com/v1", MAS_DISABLE_LIVE_LLM="0", V1_REQUEST_JOURNAL="")
        with patch.dict("os.environ", env), patch("agentdojo_manta.adapter._import_manta", return_value=(SimpleNamespace, None, Transport, None, None)), \
             patch("agentdojo_manta.budget.configured_budget", return_value=budget):
            client = _make_llm_client(AdapterPaths.from_repo(ROOT), "deepseek-flash", observer=observer, thinking_protocol=True)
            main_history = {"remaining_tokens": 400000}
            first = client.complete_folded(messages=[dict(role="user", content="read")], tools=[], agent_id="agent_0", history=main_history)
            client.complete_folded(messages=[dict(role="user", content="verify")], tools=[], agent_id="action_verifier", history={"remaining_tokens": 400000})
            retained = [dict(role="user", content="read"), dict(role="assistant", content="inspecting", tool_calls=[c.model_dump() for c in first.choices[0].message.tool_calls]),
                        dict(role="tool", tool_call_id="root-call", content="10")]
            client.complete_folded(messages=retained, tools=[], agent_id="agent_0", history=main_history)
            self.assertEqual(client.wire_calls[-1]["messages"][1]["reasoning_content"], "actual root reasoning")
            self.assertEqual([r["agent_id"] for r in observer.request_records], ["agent_0", "action_verifier", "agent_0"])
            self.assertEqual(len(budget.requests), 3)
            with self.assertRaises(ResourceLimit):
                client.complete_folded(messages=retained, tools=[], agent_id="agent_0", history={**main_history, "remaining_tokens": 1})
            self.assertEqual(len(client.wire_calls), 3)
            client.force_empty = True
            with self.assertRaises(RuntimeError):
                client.complete_folded(messages=[dict(role="user", content="read")], tools=[], agent_id="action_verifier", history={"remaining_tokens": 400000})
            self.assertEqual(observer.request_records[-1]["status"], "error")
            self.assertEqual(observer.request_records[-1]["error_type"], "ValueError")


if __name__ == "__main__":
    unittest.main()
