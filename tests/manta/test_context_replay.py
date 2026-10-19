"""No-network tests of real input fixtures, native tool loops and replay metrics."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import context_replay_lib as replay
import run_context_replay as queue


class ContextReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http_block = patch("httpx.Client.send", side_effect=AssertionError("Network disabled in replay tests"))
        cls.http_block.start()
        cls.fixtures = replay.build_fixtures()

    @classmethod
    def tearDownClass(cls):
        cls.http_block.stop()

    def test_original_prompts_exact_and_clean_changes_are_confined_to_packet(self):
        original = replay.load(replay.SOURCE)
        for actor, f in self.fixtures.items():
            stage = next(l for l in original["manta_metadata"]["interaction_logs"] if l["agent_id"] == actor)
            self.assertEqual(stage["prompt_messages"], f["original_prompt"])
            i, _, old = replay.get_context(f["original_prompt"])
            j, _, clean = replay.get_context(f["clean_prompt"])
            self.assertEqual(i, j)
            old.pop("visible_packets")
            clean.pop("visible_packets")
            self.assertEqual(old, clean)
            self.assertEqual(f["original_prompt"][:i], f["clean_prompt"][:i])
            self.assertNotIn(replay.TARGET, json.dumps(f["clean_prompt"]))
            self.assertIn("7.2%", json.dumps(f["clean_prompt"]))
            self.assertIn(replay.PAYLOAD, json.dumps(f["original_prompt"]))

    def test_environment_prefix_is_same_and_T_only_changes_page_body(self):
        for f in self.fixtures.values():
            _, _, a, ha = replay.environment(f, False)
            _, _, b, hb = replay.environment(f, True)
            self.assertEqual(ha, hb)
            self.assertEqual(a.web.web_requests, b.web.web_requests)
            self.assertTrue(any(replay.TARGET in u for u in a.web.web_requests))
            a.web.web_content[replay.NORMAL] = b.web.web_content[replay.NORMAL]
            self.assertEqual(a.model_dump(), b.model_dump())
            a.web.web_requests.append("isolation-check")
            self.assertNotIn("isolation-check", b.web.web_requests)

    def test_unexpected_attack_residue_fails_closed(self):
        f = self.fixtures["agent_1"]
        _, _, context = replay.get_context(f["original_prompt"])
        packet = context["visible_packets"][0]
        packet["payload"]["critique"] = f"Extra reference: {replay.TARGET}"
        with self.assertRaisesRegex(ValueError, "residue"):
            replay.clean_packet(packet, f["clean_page"])

    def scripted_factory(self, *, finish_reason="stop", fail=False):
        from openai.types.chat import ChatCompletion
        from agentdojo_manta.adapter import _make_llm_client

        def factory(paths, model, observation):
            client = _make_llm_client(paths, model, observer=observation)

            def create(**kwargs):
                if fail:
                    raise ValueError("scripted provider failure")
                messages = kwargs["messages"]
                tool_messages = [m for m in messages if m["role"] == "tool"]
                if not tool_messages:
                    url = replay.NORMAL
                elif replay.TARGET in json.dumps(messages) and not any(
                    replay.TARGET in json.dumps(m.get("tool_calls", []))
                    for m in messages if m["role"] == "assistant"
                ):
                    url = replay.TARGET
                else:
                    url = None
                if url:
                    message = dict(role="assistant", content=None, tool_calls=[dict(
                        id=f"call_{len(tool_messages)}", type="function",
                        function=dict(name="get_webpage", arguments=json.dumps(dict(url=url))))])
                    reason = "tool_calls"
                else:
                    message = dict(role="assistant", content=json.dumps(dict(
                        answer_artifact="The page reports unemployment edged down to 7.2%.",
                        summary="Read the requested page.", confidence=0.8,
                        evidence_summary=["Observed the page."], unresolved_issues=[])))
                    reason = finish_reason
                return ChatCompletion.model_validate(dict(id="engineering-fixture", object="chat.completion",
                    created=0, model="deepseek-flash", choices=[dict(index=0, message=message, finish_reason=reason)],
                    usage=dict(prompt_tokens=1000, completion_tokens=100, total_tokens=1100)))

            client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            return client
        return factory

    def env_patch(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(
            ("MAS_", "MANTA_", "OPENROUTER_", "V1_"))}
        env.update(MAS_REQUIRE_LIVE_LLM="1", DEEPSEEK_API_KEY="unit-test-not-a-real-key")
        return patch.dict(os.environ, env, clear=True)

    def test_real_native_stage_all_eight_cells_and_saturated_prefix_score(self):
        with self.env_patch(), tempfile.TemporaryDirectory() as tmp:
            for actor, fixture in self.fixtures.items():
                for m in (0, 1):
                    for t in (0, 1):
                        with self.subTest(actor=actor, M=m, T=t):
                            output = Path(tmp) / f"{actor}_{m}_{t}"
                            output.mkdir()
                            job = dict(id=output.name, actor=actor, M=m, T=t, repeat=1)
                            row = replay.run_worker(fixture, job, "deepseek-v4-flash", output,
                                                    client_factory=self.scripted_factory())
                            self.assertIsNone(row["error"])
                            self.assertEqual(row["observed_target_reached"], bool(m or t))
                            self.assertEqual(row["observed_target_visit_count"], int(bool(m or t)))
                            self.assertTrue(row["baseline_official_goal"])
                            self.assertTrue(row["full_prefix_official_goal"])
                            self.assertFalse(row["evaluation_valid"])
                            self.assertTrue(row["stage_execution_complete"])
                            self.assertIsNone(row["downstream_target_reached"])
                            self.assertTrue(row["engineering_fixture"])
                            inputs = replay.load(output / "provider_inputs.json")
                            self.assertEqual(len(inputs), 3 if m or t else 2)
                            self.assertEqual(inputs[0]["request"]["messages"],
                                             fixture["original_prompt"] if m else fixture["clean_prompt"])
                            self.assertTrue(all(q["status"] == "completed" for q in row["request_records"]))

    def test_truncation_keeps_observed_positive_but_is_not_valid_negative(self):
        with self.env_patch(), tempfile.TemporaryDirectory() as tmp:
            job = dict(id="test", actor="agent_2", M=1, T=1, repeat=1)
            row = replay.run_worker(self.fixtures["agent_2"], job, "deepseek-v4-flash", Path(tmp),
                                    client_factory=self.scripted_factory(finish_reason="length"))
            self.assertIn("hit_output_limit", row["incomplete_flags"])
            self.assertTrue(row["observed_target_reached"])
            self.assertIsNone(row["downstream_target_reached"])

    def test_provider_failure_and_request_limit_are_incomplete(self):
        with self.env_patch(), tempfile.TemporaryDirectory() as tmp:
            job = dict(id="test", actor="agent_1", M=1, T=1, repeat=1)
            for name, factory, limit in (("error", self.scripted_factory(fail=True), 36),
                                         ("limit", self.scripted_factory(), 1)):
                p = Path(tmp) / name
                p.mkdir()
                row = replay.run_worker(self.fixtures["agent_1"], job, "deepseek-v4-flash", p,
                                        client_factory=factory, max_requests=limit)
                self.assertIsNotNone(row["error"])
                self.assertFalse(row["evaluation_valid"])
                self.assertIsNone(row["downstream_target_reached"])

    def test_frozen_schedule_and_summary_denominators(self):
        plan, _ = queue.frozen_plan()
        self.assertEqual(len(plan["jobs"]), 24)
        self.assertEqual(len({j["id"] for j in plan["jobs"]}), 24)
        self.assertTrue(all(j["repeat"] == 1 for j in plan["jobs"][:8]))
        self.assertEqual(plan, queue.frozen_plan()[0])
        job = plan["jobs"][0]
        valid = dict(job=job, evaluation_valid=True, downstream_target_reached=False,
                     normal_page_read=True, observed_target_reached=False)
        bad_job = copy.deepcopy(job)
        bad_job["id"] += "_bad"
        invalid = dict(job=bad_job, evaluation_valid=False, observed_target_reached=True)
        s = replay.summarize([valid, invalid], plan["jobs"])
        cell = next(c for c in s["groups"] if (c["actor"], c["M"], c["T"]) ==
                    (job["actor"], job["M"], job["T"]))
        self.assertEqual(cell["valid_n"], 1)
        self.assertEqual(cell["target_n"], 0)
        self.assertEqual(cell["incomplete_n"], 1)
        self.assertEqual(cell["observed_target_positive_in_incomplete"], 1)
        self.assertFalse(s["complete"])

    def fake_process_factory(self, plan, invalid_id=None):
        class Process:
            count = 0

            def __init__(self, command, **kwargs):
                Process.count += 1
                self.pid = 900000 + Process.count
                self.returncode = 0
                run_dir = Path(command[command.index("--run-dir") + 1])
                job = next(j for j in plan["jobs"] if j["id"] == command[command.index("--child") + 1])
                index = int(command[command.index("--attempt") + 1])
                # Synthetic launcher test records live only in TemporaryDirectory.
                row = dict(protocol=replay.PROTOCOL, job=job, evaluation_valid=job["id"] != invalid_id,
                           run_status="INCOMPLETE" if job["id"] == invalid_id else "VALID_REPLAY",
                           downstream_target_reached=False, normal_page_read=True, observed_target_reached=False)
                replay.save(run_dir / "attempts" / job["id"] / f"attempt_{index:03d}" / "result.json", row)

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -1
        return Process

    def test_launcher_full_queue_then_resume_without_rerunning_valid_jobs(self):
        plan, _ = queue.frozen_plan()
        with self.env_patch(), tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(run_dir=Path(tmp), budget_usd="3", parallelism=4,
                                   retry_incomplete=False, worker_timeout=1200)
            process = self.fake_process_factory(plan)
            with patch.object(queue.subprocess, "Popen", process):
                self.assertEqual(queue.execute(args, plan), 0)
                self.assertEqual(process.count, 24)
                self.assertEqual(queue.execute(args, plan), 0)
                self.assertEqual(process.count, 24)
            self.assertEqual(replay.load(Path(tmp) / "summary.json")["valid"], 24)

    def test_launcher_incomplete_first_wave_stops_and_explicit_retry_resumes(self):
        plan, _ = queue.frozen_plan()
        with self.env_patch(), tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(run_dir=Path(tmp), budget_usd="3", parallelism=4,
                                   retry_incomplete=False, worker_timeout=1200)
            process = self.fake_process_factory(plan, invalid_id=plan["jobs"][0]["id"])
            with patch.object(queue.subprocess, "Popen", process):
                self.assertEqual(queue.execute(args, plan), 1)
                self.assertEqual(process.count, 8)
                self.assertEqual(queue.execute(args, plan), 1)
                self.assertEqual(process.count, 8)
            args.retry_incomplete = True
            resumed = self.fake_process_factory(plan)
            with patch.object(queue.subprocess, "Popen", resumed):
                self.assertEqual(queue.execute(args, plan), 0)
                self.assertEqual(resumed.count, 17)


if __name__ == "__main__":
    unittest.main()
