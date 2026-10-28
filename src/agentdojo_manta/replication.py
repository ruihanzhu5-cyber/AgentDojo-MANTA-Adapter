"""Frozen-scene verification and pilot acceptance for the GPT-4o replication."""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path


def load_replication_plan(root: Path, *, provider: str, source_digest: str, pilot: bool = False, model: str = "gpt-4o"):
    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.task_suite.load_suites import get_suites
    source = root / "reports/2026-10-19-manta-agentdojo/manifest.json"
    original = json.loads(source.read_text(encoding="utf-8"))
    expected_config = dict(benchmark_version="v1.2.2", model="deepseek-v4-flash", num_agents=3,
                           max_turns=2, repair_budget=1, planner_mode="task_conditioned",
                           audit_mode="heuristic", seed=42)
    if original["config"] != expected_config or original["adaptive_limits"] != dict(max_initial_agents=5, max_total_agents=10):
        raise ValueError("Published baseline configuration differs from requested protocol")
    scenes, jobs = original["scenes"], original["jobs"]
    if len(scenes) != 80 or Counter(s["suite"] for s in scenes) != dict.fromkeys(("banking", "slack", "travel", "workspace"), 20):
        raise ValueError("Expected original 80 scenes, 20 per suite")
    if len({s["scene_id"] for s in scenes}) != 80:
        raise ValueError("Duplicate scene identity")
    suites = get_suites("v1.2.2")
    expected_jobs = []
    for scene in scenes:
        suite = suites[scene["suite"]]
        payload = load_attack("direct", suite, None).attack(suite.user_tasks[scene["task_id"]], suite.injection_tasks[scene["injection_task"]])
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if digest != scene["payload_sha256"] or not payload or not any(payload.values()):
            raise ValueError(f"Official payload hash mismatch: {scene['scene_id']}")
        expected_jobs.extend(dict(**scene, condition=c, run_id=f"{scene['scene_id']}__{c}") for c in ("clean", "attack"))
    if jobs != expected_jobs:
        raise ValueError("Original job scene/task/injection/payload pairing differs")
    plan = copy.deepcopy(original)
    if model not in {"gpt-4o", "deepseek-v4-pro"} or (model == "deepseek-v4-pro" and provider != "deepseek"):
        raise ValueError("Unsupported model/provider replication pair")
    plan.update(provider=provider, endpoint={"qdd": "https://api2.aigcbest.top/v1", "openai": "https://api.openai.com/v1", "deepseek": "https://api.deepseek.com/v1"}[provider],
                original_manifest_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                source_sha256=source_digest, planner_model=model, auditor_model=model,
                stage="pilot" if pilot else "formal", max_tool_iterations=8,
                pricing_source="https://api2.aigcbest.top/api/pricing" if provider == "qdd" else "https://developers.openai.com/api/docs/models/gpt-4o",
                budget_accounting="GPT-4o independent rates; uncached upper bound; unresolved requests retain full reservation")
    plan["config"]["model"] = model
    if model == "deepseek-v4-pro":
        plan.update(pricing_source="https://api-docs.deepseek.com/quick_start/pricing/",
                    budget_accounting="Pro peak uncached rates; full-context reservations; not invoice cost",
                    thinking="enabled (provider default); actual reasoning_content preserved on retained tool turns")
    if pilot:
        ids = {next(s["scene_id"] for s in scenes if s["suite"] == suite) for suite in sorted(suites)}
        plan["scenes"] = [s for s in scenes if s["scene_id"] in ids]
        plan["jobs"] = [j for j in jobs if j["scene_id"] in ids]
    return plan


def check_pilot(run_dir: Path, manifest: dict, budget: dict):
    failures, rows = [], []
    if len(manifest["jobs"]) != 8 or manifest.get("stage") != "pilot":
        failures.append("Expected an eight-episode real pilot")
    for job in manifest["jobs"]:
        selected = []
        for path in (run_dir / "attempts" / job["run_id"]).glob("attempt_*/result.json"):
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("evaluation_valid") is True:
                selected.append(row)
        if len(selected) != 1:
            failures.append(f"{job['run_id']}: expected exactly one valid attempt")
            continue
        row = selected[0]
        rows.append(row)
        requests = row.get("llm_requests", [])
        if row.get("mock_used") or row.get("model") != "gpt-4o" or not requests:
            failures.append(f"{job['run_id']}: mock, wrong model, or no requests")
        if not all(r.get("status") == "completed" and r.get("usage_available") and r.get("model") == "gpt-4o" for r in requests):
            failures.append(f"{job['run_id']}: request error, missing usage, or model mismatch")
        if row.get("token_in") != sum(r.get("token_in") or 0 for r in requests) or row.get("token_out") != sum(r.get("token_out") or 0 for r in requests):
            failures.append(f"{job['run_id']}: usage aggregation mismatch")
        if not isinstance(row.get("official_utility"), bool) or not isinstance(row.get("official_security"), bool):
            failures.append(f"{job['run_id']}: missing official scoring")
        if row.get("real_multiagent_handoff") is not True or not row.get("manta_metadata") or not row.get("manta_trace_events"):
            failures.append(f"{job['run_id']}: missing handoff or topology evidence")
        # Cross-check the score against the official logger's saved trace.
        traces = [json.loads(p.read_text(encoding="utf-8")) for p in Path(row["official_logdir"]).rglob("*.json")]
        if not any(t.get("utility") == row["official_utility"] and t.get("security") == row["official_security"] and not t.get("error") for t in traces):
            failures.append(f"{job['run_id']}: official trace score mismatch")
    if not budget or budget["cap_usd"] > 10 or budget["accounted_upper_bound_usd"] > 10 or budget["unreturned_reservations_usd"]:
        failures.append("Pilot budget exceeded or has unresolved requests")
    # Reconcile persisted per-request usage against every SQLite reservation,
    # including the separate connectivity probe and any unsuccessful attempt.
    with sqlite3.connect(run_dir / "budget.sqlite") as db:
        ledger = {rid: (amount, state) for rid, amount, state in db.execute("SELECT id, amount, state FROM requests")}
        identity = db.execute("SELECT value FROM settings WHERE key='pricing_identity'").fetchone()[0].split(":")
        input_rate, output_rate = int(identity[2]), int(identity[3])
    journal_requests = {}
    for path in (run_dir / "attempts").glob("*/attempt_*/requests.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry.get("status") == "completed":
                journal_requests[entry["budget_request_id"]] = entry["token_in"] * input_rate + entry["token_out"] * output_rate
    probe_path = run_dir.parent / "gpt4o_preflight/connectivity.json"
    if probe_path.exists():
        probe = json.loads(probe_path.read_text(encoding="utf-8"))
        if probe.get("status") == "completed":
            usage = probe["usage"]
            journal_requests[probe["budget_request_id"]] = usage["prompt_tokens"] * input_rate + usage["completion_tokens"] * output_rate
    if set(journal_requests) != set(ledger) or any(ledger[rid] != (amount, "settled") for rid, amount in journal_requests.items()):
        failures.append("SQLite ledger does not reconcile with durable API usage journals")
    return dict(accepted=not failures, failures=failures, valid_episodes=len(rows),
                source_sha256=manifest["source_sha256"], provider=manifest["provider"],
                original_manifest_sha256=manifest["original_manifest_sha256"],
                token_in=sum(r.get("token_in") or 0 for r in rows),
                token_out=sum(r.get("token_out") or 0 for r in rows), budget=budget)
