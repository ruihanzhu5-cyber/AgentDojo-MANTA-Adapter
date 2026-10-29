"""F/W scheduling and paid-queue guards checked with local stubs only."""
import copy
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import shutil
import uuid
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_folded_execution import ROOT, ScriptClient, response, Call, tool
from MAS.self_evolved.agent_loop import DEFAULTS, FoldedEngine, FoldedSession

sys.path.insert(0, str(ROOT / "scripts/manta"))
import run_fw


@contextmanager
def local_temp():
    base = ROOT / "results/offline_fw_unit"
    base.mkdir(parents=True, exist_ok=True)
    # Python's Windows mkdtemp(mode=0700) can deny the sandbox token access.
    # Use an inherited-ACL workspace directory and verify it before cleanup.
    folder = base / ("case-" + uuid.uuid4().hex)
    folder.mkdir()
    try:
        yield str(folder)
    finally:
        if not folder.resolve().is_relative_to(base.resolve()):
            raise AssertionError("Temporary cleanup must remain in the workspace scratch directory")
        shutil.rmtree(folder)


def assignments():
    return dict(workers=[dict(subgoal=goal, evidence_need=need, allowed_tools=["get_balance"], completion_condition="Return evidence or a precise gap")
        for goal, need in [("Collect balance facts", "Primary evidence"), ("Check balance independently", "Independent verification")]])


class SchedulingChecks(unittest.TestCase):
    def test_fixed_two_really_calls_two_isolated_workers_then_continues_main(self):
        script = [response(json.dumps(assignments())),
            response("", [Call("load_tools", {"names": ["get_balance"]}, "a")]),
            response("", [Call("get_balance", {}, "b")]), response("COLLECTOR_REPORT_SECRET"),
            response("", [Call("load_tools", {"names": ["get_balance"]}, "c")]),
            response("", [Call("get_balance", {}, "d")]), response("Independent result is 10"),
            response("Final answer is 10")]
        client = ScriptClient(script)
        reads = []
        session = FoldedSession(client, "Check my balance", [tool("get_balance", lambda a: reads.append(a) or 10)], DEFAULTS, "fixed_two")
        result = session.run("local", 42)
        self.assertEqual([q["agent_id"] for q in client.requests], ["agent_0"] + ["agent_1"] * 3 + ["agent_2"] * 3 + ["agent_0"])
        self.assertTrue(result.run_metadata["fixed_two_fulfilled"])
        self.assertEqual(result.run_metadata["folded_usage"]["model_calls"], 8)
        self.assertEqual(result.run_metadata["folded_usage"]["tokens"], 8 * 15)
        self.assertEqual(len(reads), 1, "Both arms retain the same ordinary read cache")
        self.assertNotIn("COLLECTOR_REPORT_SECRET", json.dumps(client.requests[4]["messages"]))
        self.assertIn("COLLECTOR_REPORT_SECRET", json.dumps(client.requests[-1]["messages"]))
        self.assertEqual(result.final_answer, "Final answer is 10")

    def test_invalid_plan_still_executes_two_real_contexts_and_records_fallback(self):
        client = ScriptClient([response("not JSON"), response("No new evidence"), response("No new evidence"), response("final")])
        session = FoldedSession(client, "Check", [tool("get_balance", lambda a: 10)], DEFAULTS, "fixed_two")
        result = session.run("local", 42)
        self.assertTrue(result.run_metadata["fixed_assignment"]["fallback"])
        self.assertTrue(result.run_metadata["fixed_two_fulfilled"])
        self.assertEqual([r["model_calls"] for r in result.run_metadata["worker_execution"]], [1, 1])

    def test_global_budget_stops_without_faking_second_worker_execution(self):
        client = ScriptClient([response(json.dumps(assignments())), response("first worker")])
        session = FoldedSession(client, "Check", [tool("get_balance", lambda a: 10)], {**DEFAULTS, "max_model_calls": 2}, "fixed_two")
        result = session.run("local", 42)
        self.assertFalse(result.run_metadata["fixed_two_fulfilled"])
        self.assertEqual([w["model_calls"] for w in result.run_metadata["worker_execution"]], [1, 0])
        self.assertEqual(result.run_metadata["termination_reason"], "episode_resource_limit")
        self.assertTrue(result.final_answer.startswith("Incomplete"))

    def test_on_demand_does_not_force_any_worker_or_extra_planning(self):
        client = ScriptClient([response("answer")])
        result = FoldedSession(client, "Check", [], DEFAULTS, "on_demand").run("local", 42)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(result.run_metadata["worker_execution"], [])
        self.assertIsNone(result.run_metadata["fixed_assignment"])

    def test_unknown_policy_and_wrong_fixed_worker_slots_are_rejected(self):
        with self.assertRaises(ValueError):
            FoldedEngine(None, worker_policy="invalid")
        with self.assertRaises(ValueError):
            FoldedEngine(None, {"max_workers": 1}, "fixed_two")


class QueueChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(run_fw.CONFIG.read_text(encoding="utf-8"))
        cls.manifest = run_fw.freeze_plan(cls.config)

    def test_paired_schedule_has_identical_160_jobs_per_arm_and_is_deterministic(self):
        m = self.manifest
        self.assertEqual(len(m["execution_order"]), 320)
        for arm in ("F", "W"):
            actual = [{k: v for k, v in j.items() if k not in {"arm", "worker_policy", "comparison_job_id"}}
                      for j in m["execution_order"] if j["arm"] == arm]
            self.assertEqual(sorted(actual, key=lambda j: j["run_id"]), sorted(m["jobs"], key=lambda j: j["run_id"]))
        for i in range(0, 320, 2):
            pair = m["execution_order"][i:i+2]
            self.assertEqual(pair[0]["run_id"], pair[1]["run_id"])
            self.assertEqual({j["arm"] for j in pair}, {"F", "W"})
        self.assertEqual(m["execution_order"], run_fw.freeze_plan(self.config)["execution_order"])

    def test_changed_base_path_or_resource_limits_cannot_silently_change_protocol(self):
        changed = copy.deepcopy(self.config)
        changed["base_config"] = "other.json"
        with self.assertRaises(ValueError):
            run_fw.freeze_plan(changed)

    def test_old_result_directory_is_protected(self):
        for name in run_fw.PROTECTED:
            with self.assertRaises(ValueError):
                run_fw.check_run_root(Path("D:/MANTA_DATA/AgentDojo") / name / "nested")

    def test_unbound_financial_state_or_changed_source_refuses_binding(self):
        with local_temp() as temp:
            root = Path(temp)
            (root / "budget.sqlite").write_text("unbound", encoding="utf-8")
            with self.assertRaises(ValueError):
                run_fw.bind_manifest(root, self.manifest)
        with patch.object(run_fw, "fingerprint", return_value="changed"):
            with self.assertRaises(ValueError):
                run_fw.check_source(self.manifest)

    def test_result_validation_rejects_wrong_source_policy_or_configuration(self):
        m = self.manifest
        job = m["execution_order"][0]
        row = dict(evaluation_valid=True, worker_policy=job["worker_policy"], model="deepseek-flash", max_output_tokens=16384,
            team_profile="folded_adaptive", suite=job["suite"], task_id=job["task_id"], condition=job["condition"], seed=42,
            provider="deepseek", benchmark_version="v1.2.2", process_returncode=0, comparison_source_sha256=m["source_sha256"],
            adapter_source_digest=m["adapter_source_digest"], manta_source_digest=m["manta_source_digest"], config=m["config"],
            manta_metadata={"folded_config": m["folded"]}, injection_task=job["injection_task"] if job["condition"] == "attack" else None)
        row["attack"] = "direct" if job["condition"] == "attack" else None
        self.assertTrue(run_fw.matches_job(row, job, m))
        for key, value in [("comparison_source_sha256", "bad"), ("worker_policy", "bad"), ("process_returncode", 1), ("provider", "other")]:
            self.assertFalse(run_fw.matches_job({**row, key: value}, job, m))

    def test_probe_receipt_must_reconcile_to_the_shared_ledger(self):
        from agentdojo_manta.budget import RequestBudget
        with local_temp() as temp:
            root = Path(temp).resolve()
            budget = run_fw.bind_budget(root, self.manifest)
            rid = budget.reserve("deepseek-flash", 256)
            budget.settle(rid, SimpleNamespace(prompt_tokens=2, completion_tokens=3))
            receipt = dict(status="completed", requested_model="deepseek-flash", endpoint=self.manifest["endpoint"],
                budget_db=str(root / "budget.sqlite"), budget_request_id=rid, usage=dict(prompt_tokens=2, completion_tokens=3))
            (root / "connectivity.json").write_text(json.dumps(receipt), encoding="utf-8")
            env = dict(MANTA_PROVIDER="deepseek", DEEPSEEK_MODEL="deepseek-flash", DEEPSEEK_PLANNER_MODEL="deepseek-flash",
                DEEPSEEK_AUDITOR_MODEL="deepseek-flash", DEEPSEEK_BASE_URL=self.manifest["endpoint"],
                DEEPSEEK_API_KEY="local-test-placeholder", V1_MAX_COST_USD="100")
            with patch.dict(os.environ, env):
                run_fw.verify_receipt(root, self.manifest)
                with budget.connect() as db:
                    db.execute("UPDATE requests SET amount=amount+1 WHERE id=?", (rid,))
                with self.assertRaises(ValueError):
                    run_fw.verify_receipt(root, self.manifest)

    def test_failed_attempt_journal_usage_remains_in_accounting(self):
        with local_temp() as temp:
            root = Path(temp)
            attempt = root / "F/attempts/example/attempt_001"
            attempt.mkdir(parents=True)
            (attempt / "result.json").write_text(json.dumps(dict(evaluation_valid=False)), encoding="utf-8")
            (attempt / "requests.jsonl").write_text(json.dumps(dict(status="completed", budget_request_id="local", token_in=20, token_out=3)) + "\n", encoding="utf-8")
            data = run_fw.attempt_accounting(root, "F")
            self.assertEqual(data["invalid_attempts"], 1)
            self.assertEqual(data["all_attempt_observed_tokens"], 23)

    def test_truncated_child_result_is_preserved_and_can_resume(self):
        job = self.manifest["execution_order"][0]
        with local_temp() as temp:
            root = Path(temp)
            attempt = root / job["arm"] / "attempts" / job["run_id"] / "attempt_001"
            attempt.mkdir(parents=True)
            path = attempt / "result.json"
            path.write_text('{"evaluation_valid":', encoding="utf-8")
            self.assertIsNone(run_fw.saved_result(root, job, self.manifest))
            self.assertEqual(path.read_text(encoding="utf-8"), '{"evaluation_valid":')
            data = run_fw.attempt_accounting(root, job["arm"])
            self.assertEqual(data["invalid_attempts"], 1)
            self.assertEqual(len(data["malformed_result_files"]), 1)

    def test_coordinator_exception_stops_instead_of_continuing_queue(self):
        with local_temp() as temp:
            root = Path(temp)
            budget = run_fw.bind_budget(root, self.manifest)
            summary = {"arms": {a: {"complete": False} for a in ("F", "W")}}
            with patch.object(run_fw, "verify_receipt"), patch.object(run_fw, "assert_no_children"), \
                 patch.object(run_fw, "bind_budget", return_value=budget), patch.object(run_fw, "check_source"), \
                 patch.object(run_fw, "summary_rows", return_value=summary), \
                 patch.object(run_fw.subprocess, "Popen", side_effect=OSError("local controlled launch failure")) as launch:
                result = run_fw.run_queue(root, self.manifest, parallelism=1)
            self.assertNotEqual(result, 0)
            self.assertTrue((root / "coordinator_error.json").exists())
            self.assertLess(launch.call_count, 320)


if __name__ == "__main__":
    unittest.main()
