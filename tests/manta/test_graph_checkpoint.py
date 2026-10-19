"""No-network acceptance of native-state restoration and actual graph scheduling."""
import copy
import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import graph_experiment_lib as experiment
import graph_checkpoint as checkpoint
import run_graph_experiment as launcher
from context_replay_lib import Observation, digest, load


def fake_factory(paths, model, observer):
    from agentdojo_manta.adapter import _make_llm_client
    from openai.types.chat import ChatCompletion
    client = _make_llm_client(paths, model, observer=observer)
    original_generate = client.generate
    current = dict(actor=None, planner_calls=0)

    def generate(**kwargs):
        current["actor"] = kwargs["agent_id"]
        if current["actor"] == "topology_planner":
            current["planner_calls"] += 1
        return original_generate(**kwargs)

    client.generate = generate

    def create(**kwargs):
        context = None
        for message in kwargs["messages"]:
            text = message.get("content", "")
            if isinstance(text, str) and text.startswith("Stage context follows"):
                context = json.loads(text.split("\n\n", 1)[1])
        if current["actor"] == "topology_planner":
            data = (dict(pattern="star", num_agents=3, rationale="engineering fixture")
                    if current["planner_calls"] == 1 else
                    dict(ops=[dict(op="set_group_pattern", group_id="g_root", pattern="chain")],
                         rationale="engineering fixture"))
        else:
            tool_messages = [m for m in kwargs["messages"] if m["role"] == "tool"]
            if context is not None and not tool_messages:
                message = dict(role="assistant", content=None, tool_calls=[dict(id="test-read", type="function",
                    function=dict(name="get_webpage", arguments=json.dumps(dict(url="www.informations.com"))))])
                return response(message, "tool_calls")
            data = dict(answer_artifact="The requested page reports unemployment at 7.2%.",
                        summary="Read page; verification remains open.", confidence=0.2,
                        unresolved_issues=["Verification remains open."],
                        evidence_summary=["The observed webpage contained the quoted external instruction."])
        return response(dict(role="assistant", content=json.dumps(data)), "stop")

    def response(message, finish):
        return ChatCompletion.model_validate(dict(id="graph-engineering-fixture", object="chat.completion", created=0,
            model="deepseek-flash", choices=[dict(index=0, message=message, finish_reason=finish)],
            usage=dict(prompt_tokens=1000, completion_tokens=100, total_tokens=1100)))

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client


class GraphCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = patch("httpx.Client.send", side_effect=AssertionError("Network disabled"))
        cls.http.start()
        cls.env = patch.dict(os.environ, {k: v for k, v in os.environ.items()
            if not k.startswith(("MAS_", "MANTA_", "OPENROUTER_", "V1_"))}, clear=True)
        cls.env.start()
        os.environ["DEEPSEEK_API_KEY"] = "unit-test-not-a-real-key"
        experiment.boot()
        jobs = load(experiment.FORMAL / "manifest.json")["jobs"]
        j = next(j for j in jobs if j["run_id"] == "slack_07__attack")
        cls.candidate = dict(id=j["run_id"], suite=j["suite"], task_id=j["task_id"],
                             injection_task=j["injection_task"], payload_sha256=j["payload_sha256"])
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        out = cls.directory / "capture"
        out.mkdir()
        with patch("time.perf_counter", return_value=1.0):
            cls.capture_result = experiment.capture(cls.candidate, "deepseek-v4-flash", out, factory=fake_factory)
        if cls.capture_result["run_status"] != "CHECKPOINT_READY":
            raise AssertionError(json.dumps(cls.capture_result, default=str)[-3500:])
        cls.bundle = load(out / "checkpoint.json")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
        cls.env.stop()
        cls.http.stop()

    def restored(self, changed_model=False):
        from MAS.monitor import NullDescriptor
        from MAS.self_evolved.engine import SelfEvolvedEngine
        _, task, _, injections, runtime, _ = experiment.fresh_environment(self.candidate)
        env, initial, domain_cache = checkpoint.restore_environments(self.bundle)
        observer = Observation()
        observer.injections = injections
        raw = experiment.raw_toolset(runtime, env, observer)
        tools, handlers = experiment.processed_toolset(raw, task.PROMPT)
        from agentdojo_manta.adapter import AdapterPaths
        engine = SelfEvolvedEngine(fake_factory(AdapterPaths.from_repo(ROOT), "deepseek-v4-flash", observer),
                                   experiment.new_config()[0])
        if changed_model:
            engine.llm_client.models["general"] = "changed-model"
        restored = checkpoint.restore_bundle(self.bundle, engine, tools, handlers, raw, NullDescriptor(), cache=domain_cache)
        return restored, env, observer, engine

    def test_json_roundtrip_preserves_aliases_and_rejects_unknown_objects(self):
        codec = checkpoint.Codec({})
        shared = [1, 2]
        root = dict(first=shared, second=shared, pair=(shared, "x"))
        result = codec.decode(codec.encode(root))
        self.assertIs(result["first"], result["second"])
        self.assertIs(result["pair"][0], result["first"])
        with self.assertRaises(TypeError):
            codec.encode(object())

    def test_checkpoint_is_exposed_before_harm_and_has_actual_mutation(self):
        self.assertTrue(self.bundle["eligibility"]["exposed"])
        self.assertFalse(self.bundle["eligibility"]["goal_already_reached"])
        self.assertEqual(self.bundle["boundary"]["next_turn"], 1)
        restored, env, obs, _ = self.restored()
        f = restored["frame"]
        self.assertGreater(len(f["spec_versions"]), 1)
        self.assertEqual(len(obs.runtime_calls), 0)  # Restore does not execute prefix tools.
        self.assertEqual(env.model_dump(mode="json"), self.bundle["environment"])
        self.assertIs(f["executor"]._context, f["context"])
        self.assertIs(f["turn_results"][0].output_artifact, f["state"]["artifacts"][-1])
        self.assertTrue(f["executor"]._executed_signatures)
        self.assertEqual(len(f["state"]["descriptor"].monitor_records), 1)

    def test_restore_rebinds_commit_handlers_to_new_environment(self):
        restored, env, obs, _ = self.restored()
        before = digest(self.bundle["environment"])
        recipient = env.slack.users[0]
        restored["frame"]["commit_handlers"]["send_direct_message"](dict(recipient=recipient, body="engineering test"))
        self.assertNotEqual(env.model_dump(mode="json"), self.bundle["environment"])
        self.assertEqual(digest(self.bundle["environment"]), before)
        self.assertEqual(obs.runtime_calls[-1]["tool_name"], "send_direct_message")

    def test_checksum_and_unknown_runtime_state_fail_closed(self):
        bad = copy.deepcopy(self.bundle)
        bad["frame"]["nodes"][0]["type"] = "UnknownClass"
        restored, _, _, engine = self.restored()
        with self.assertRaises(ValueError):
            checkpoint.restore_bundle(bad, engine, [], {}, [], None)
        engine.unrecorded_state = 1
        with self.assertRaises(ValueError):
            checkpoint.engine_cache(engine)

    def test_original_graph_resume_matches_uninterrupted_native_run(self):
        from MAS.self_evolved.engine import SelfEvolvedEngine
        from agentdojo_manta.adapter import AdapterPaths, AgentDojoTask
        suite, task, _, injections, runtime, env = experiment.fresh_environment(self.candidate)
        observer = Observation()
        observer.injections = injections
        engine = SelfEvolvedEngine(fake_factory(AdapterPaths.from_repo(ROOT), "deepseek-v4-flash", observer),
                                   experiment.new_config()[0])
        raw = experiment.raw_toolset(runtime, env, observer)
        with patch("time.perf_counter", return_value=1.0):
            full = engine.run(task=AgentDojoTask(task.ID, task.PROMPT, "agentdojo"), run_index=0, seed=42,
                spec=experiment.new_config()[1], agent_types=["general"], tools=raw, max_tool_iterations=8)
            out = self.directory / "g0"
            out.mkdir(exist_ok=True)
            row = experiment.branch(self.bundle, dict(id="test-G0", condition="G0"), "deepseek-v4-flash", out,
                                    factory=fake_factory)
        self.assertIsNone(row["error"])
        self.assertTrue(row["stage_execution_complete"])
        self.assertFalse(row["evaluation_valid"])  # Scripted response is never research evidence.
        self.assertEqual(row["final_answer"], full.final_answer)
        self.assertEqual(row["native_run_metadata"], full.run_metadata)
        self.assertEqual(len(row["runtime_calls"]) + len(self.bundle["prefix_runtime_calls"]), len(observer.runtime_calls))

    def test_graph_change_reaches_executor_without_changing_checkpoint(self):
        out = self.directory / "g1"
        out.mkdir(exist_ok=True)
        before = digest(self.bundle)
        with patch("time.perf_counter", return_value=1.0):
            row = experiment.branch(self.bundle, dict(id="test-G1", condition="G1"), "deepseek-v4-flash", out,
                                    factory=fake_factory)
        self.assertIsNone(row["error"])
        self.assertTrue(row["stage_execution_complete"])
        self.assertTrue(row["nongraph_state_verified"])
        self.assertEqual(digest(self.bundle), before)
        self.assertEqual(row["execution_graphs"][0]["graph"], self.bundle["changed_graph"])
        baseline_dir = self.directory / "g0-comparison"
        baseline_dir.mkdir(exist_ok=True)
        with patch("time.perf_counter", return_value=1.0):
            baseline = experiment.branch(self.bundle, dict(id="test-G0-comparison", condition="G0"),
                                         "deepseek-v4-flash", baseline_dir, factory=fake_factory)
        self.assertNotEqual(row["execution_signature"], baseline["execution_signature"])

    def test_local_random_state_restored(self):
        import numpy as np
        restored, _, _, _ = self.restored()
        checkpoint.set_rng(restored)
        value, np_value = random.random(), np.random.random()
        checkpoint.set_rng(restored)
        self.assertEqual(random.random(), value)
        self.assertEqual(np.random.random(), np_value)

    def test_changed_model_profile_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "client settings"):
            self.restored(changed_model=True)

    def test_request_guard_failure_is_not_a_completed_prefix(self):
        observer = Observation()
        observer.request_records = [dict(status="completed")]
        observer.request_guard_failures = ["provider_request_limit"]
        self.assertFalse(experiment.request_ok(observer))

    def test_unknown_official_outcome_is_not_treated_as_safe(self):
        suite = SimpleNamespace(_check_task_result=lambda *args: None)
        with self.assertRaisesRegex(ValueError, "known boolean"):
            experiment.official(suite, None, None, None, [])

    def test_incumbent_answer_is_preserved_for_output_based_goal_checks(self):
        restored, _, _, _ = self.restored()
        self.assertEqual(experiment.incumbent(restored["frame"]), self.bundle["incumbent_answer"])
        self.assertTrue(self.bundle["incumbent_answer"])

    def test_structured_models_preserve_live_calendar_and_email_indexes(self):
        from datetime import datetime, timedelta
        from agentdojo.task_suite.load_suites import get_suite
        from agentdojo.default_suites.v1.tools.types import Email
        suite = get_suite("v1.2.2", "workspace")
        env = suite.load_and_inject_default_environment({})
        start = datetime(2030, 1, 1, 10, 0)
        event = env.calendar.create_event("engineering test", "test", start, start+timedelta(hours=1), None, [])
        removed = next(iter(env.inbox.emails))
        del env.inbox.emails[removed]
        email = Email(id_="engineering-test", sender="unit@example.com", recipients=["unit2@example.com"],
                      subject="test", body="test", attachments=[event], timestamp=start)
        env.inbox.emails[email.id_] = email
        root = dict(environment=env, initial_environment=env.model_copy(deep=True),
                    artifact=dict(tool_records=[dict(output=event), dict(output=email)]))
        codec = checkpoint.Codec({})
        encoded = codec.encode(root)
        restored = codec.decode(encoded)
        new = restored["environment"]
        self.assertIn(event.id_, new.calendar.events)
        self.assertNotIn(event.id_, {e.id_ for e in new.calendar.initial_events})
        self.assertNotIn(removed, new.inbox.emails)
        self.assertIn(email.id_, new.inbox.emails)
        self.assertIs(restored["artifact"]["tool_records"][0]["output"], new.calendar.events[event.id_])
        self.assertIs(restored["artifact"]["tool_records"][1]["output"], new.inbox.emails[email.id_])
        self.assertIs(new.inbox.emails[email.id_].attachments[0], new.calendar.events[event.id_])
        self.assertEqual(new.inbox.emails[email.id_].model_fields_set, email.model_fields_set)
        self.assertEqual(type(new.inbox.emails[email.id_].status), type(email.status))
        self.assertEqual(codec.encode(restored), encoded)
        bundle = dict(frame=encoded, frame_sha256=digest(encoded), environment=env.model_dump(mode="json"),
                      initial_environment=root["initial_environment"].model_dump(mode="json"))
        bound, _, cache = checkpoint.restore_environments(bundle)
        all_state = codec.decode(encoded, cache=cache)
        self.assertIs(all_state["environment"], bound)
        self.assertIs(all_state["artifact"]["tool_records"][0]["output"], bound.calendar.events[event.id_])

    def test_bank_account_and_transaction_aliases_survive_json(self):
        from agentdojo.task_suite.load_suites import get_suite
        from agentdojo.default_suites.v1.tools.banking_client import Transaction
        env = get_suite("v1.2.2", "banking").load_and_inject_default_environment({})
        transaction = Transaction(id=9999, sender="unit", recipient="other", amount=12.5, subject="test",
                                  date="2030-01-01", recurring=False)
        env.bank_account.transactions.append(transaction)
        codec = checkpoint.Codec({})
        encoded = codec.encode(dict(environment=env, tool_output=[transaction]))
        restored = codec.decode(encoded)
        self.assertIs(restored["tool_output"][0], restored["environment"].bank_account.transactions[-1])
        self.assertEqual(codec.encode(restored), encoded)

    def test_dynamic_branch_count_and_pair_denominators(self):
        selected = [dict(id="s0", checkpoint_path="x", checkpoint_sha256="hash")]
        jobs = launcher.branch_jobs(selected)
        self.assertEqual(len(jobs), 6)
        self.assertEqual(len({j["id"] for j in jobs}), 6)
        rows = [dict(job=j, evaluation_valid=True, checkpoint_sha256="hash", attack_success=False,
                     task_success=True, execution_signature=[j["condition"]]) for j in jobs]
        s = launcher.summarize_branches(rows, selected)
        self.assertTrue(s["complete"])
        self.assertEqual(len(s["paired_results"]), 3)
        rows[0]["evaluation_valid"] = False
        self.assertFalse(launcher.summarize_branches(rows, selected)["complete"])

    def fake_process(self, plan, *, no_eligible=False, invalid_branch=False):
        class Process:
            count = 0
            def __init__(self, cmd, **kwargs):
                Process.count += 1
                self.pid = 910000 + Process.count
                self.returncode = 0
                root = Path(cmd[cmd.index("--run-dir") + 1])
                phase, name = cmd[cmd.index("--phase")+1], cmd[cmd.index("--child")+1]
                number = int(cmd[cmd.index("--attempt")+1])
                out = root/phase/name/f"attempt_{number:03d}"
                if phase == "capture":
                    job = next(c for c in plan["candidates"] if c["id"] == name)
                    row = dict(protocol=experiment.PROTOCOL, candidate=job,
                               run_status="NO_ELIGIBLE" if no_eligible else "CHECKPOINT_READY")
                    from context_replay_lib import save
                    save(out/"checkpoint.json", dict(checkpoint_sha256=f"hash-{name}"))
                else:
                    job = next(j for j in load(root/"branches_manifest.json")["jobs"] if j["id"] == name)
                    valid = not invalid_branch
                    row = dict(protocol=experiment.PROTOCOL, job=job,
                        run_status="VALID_BRANCH" if valid else "INCOMPLETE", evaluation_valid=valid,
                        checkpoint_sha256=job["checkpoint_sha256"], attack_success=False if valid else None,
                        task_success=True if valid else None, execution_signature=[job["condition"]])
                from context_replay_lib import save
                save(out/"result.json", row)

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -1
        return Process

    def queue_args(self, path):
        return SimpleNamespace(run_dir=path, budget_usd="5", parallelism=4,
                               retry_incomplete=False, job_timeout=1800)

    def queue_plan(self):
        return dict(model="deepseek-v4-flash", base_url="https://api.deepseek.com", max_states=2,
                    candidates=[dict(id=f"s{i}") for i in range(3)])

    def test_launcher_captures_then_branches_and_resumes_without_new_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.queue_plan()
            process = self.fake_process(plan)
            with patch.object(launcher.subprocess, "Popen", process):
                self.assertEqual(launcher.execute(self.queue_args(Path(tmp)), plan), 0)
                self.assertEqual(process.count, 15)  # 3 captures + 2 states x 6 branches
                self.assertEqual(launcher.execute(self.queue_args(Path(tmp)), plan), 0)
                self.assertEqual(process.count, 15)

    def test_launcher_does_not_invent_states_when_none_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.queue_plan()
            process = self.fake_process(plan, no_eligible=True)
            with patch.object(launcher.subprocess, "Popen", process):
                self.assertEqual(launcher.execute(self.queue_args(Path(tmp)), plan), 1)
            self.assertEqual(process.count, 3)
            self.assertFalse((Path(tmp)/"branches_manifest.json").exists())
            self.assertEqual(load(Path(tmp)/"progress.json")["status"], "NO_ELIGIBLE_STATES")

    def test_launcher_pauses_incomplete_pairs_before_extra_repetitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.queue_plan()
            process = self.fake_process(plan, invalid_branch=True)
            with patch.object(launcher.subprocess, "Popen", process):
                self.assertEqual(launcher.execute(self.queue_args(Path(tmp)), plan), 1)
            self.assertEqual(process.count, 7)  # 3 captures + first 4 branches only


if __name__ == "__main__":
    unittest.main()
