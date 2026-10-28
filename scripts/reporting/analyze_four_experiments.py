"""Offline common-failure analysis of four completed, paired MANTA experiments."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/2026-10-28-four-experiment-analysis"
RUNS = {
    "flash_star": Path(r"D:\AgentDojo-MANTA-Adapter\results\v1\formal_80_seed42"),
    "gpt4o_star": ROOT.parent / "gpt4o-replication/results/v1/formal_80_seed42_gpt4o",
    "pro16k_star": ROOT.parent / "deepseek-pro-16k/results/v1/formal_80_seed42_deepseek_pro_16k",
    "flash16k_adaptive": Path(r"D:\MANTA_DATA\AgentDojo\formal_80_seed42_deepseek_flash_adaptive"),
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(name, value):
    (OUT / name).write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def csv_out(name, rows):
    with (OUT / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from texts(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from texts(item)


def full_match(payloads, text):
    return any(p and (p in text or json.dumps(p, ensure_ascii=False)[1:-1] in text) for p in payloads)


def actor_category(actor):
    if str(actor).startswith("agent_"):
        return "team_agents"
    if actor == "topology_planner":
        return "topology_planner"
    if actor == "trace_auditor":
        return "trace_auditor"
    return "other_auxiliary"


def signature(call):
    return call["tool_name"], json.dumps(call.get("arguments"), sort_keys=True, ensure_ascii=False)


def mean(rows, key):
    return statistics.mean(r[key] for r in rows) if rows else None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    features, overview, provenance, success_cases, expensive, role_totals = [], [], [], [], [], []
    anchor = None
    for run_name, run in RUNS.items():
        manifest = load(run / "manifest.json")
        jobs = manifest["jobs"]
        identity = [{k: j[k] for k in ("scene_id", "suite", "task_id", "injection_task", "payload_sha256", "condition", "run_id")} for j in jobs]
        if anchor is None:
            anchor = identity
        assert identity == anchor and len(jobs) == 160
        selected = []
        hashes = []
        stage_stops, runtime_names = Counter(), Counter()
        grouped_roles = defaultdict(Counter)
        for job in jobs:
            candidates = [(p, load(p)) for p in sorted((run / "attempts" / job["run_id"]).glob("*/result.json"))]
            valid = [(p, r) for p, r in candidates if r.get("evaluation_valid") is True]
            assert len(valid) == 1, (run_name, job["run_id"])
            path, row = valid[0]
            assert not row["mock_used"] and row["condition"] == job["condition"] and row["task_id"] == job["task_id"]
            hashes.append(dict(job_id=job["run_id"], selected_attempt=path.parent.name, result_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            calls = row["agentdojo_runtime_calls"]
            seen, seen_read, previous_outputs = set(), set(), {}
            duplicates = duplicate_reads = repeated_same_read_output = 0
            for call in calls:
                key = signature(call)
                runtime_names[call["tool_name"]] += 1
                duplicates += key in seen
                seen.add(key)
                if call["tool_name"].startswith(("get_", "read_", "search_", "list_", "browse_")):
                    duplicate_reads += key in seen_read
                    output = json.dumps([call.get("output"), call.get("error")], ensure_ascii=False, sort_keys=True)
                    repeated_same_read_output += key in previous_outputs and previous_outputs[key] == output
                    seen_read.add(key)
                    previous_outputs[key] = output
            requests = [q for q in row["llm_requests"] if q["status"] == "completed"]
            assert sum(q["token_in"] for q in requests) == row["token_in"]
            assert sum(q["token_out"] for q in requests) == row["token_out"]
            reasoning = []
            for q in requests:
                role = actor_category(q.get("agent_id"))
                for key in ("token_in", "token_out"):
                    grouped_roles[role][key] += q[key]
                grouped_roles[role]["completed_requests"] += 1
                value = (q.get("raw_usage") or {}).get("completion_tokens_details") or {}
                if isinstance(value.get("reasoning_tokens"), int):
                    reasoning.append(value["reasoning_tokens"])
                    grouped_roles[role]["reasoning_tokens"] += value["reasoning_tokens"]
                    grouped_roles[role]["reasoning_usage_requests"] += 1
            meta, se = row["manta_metadata"], row["manta_metadata"]["self_evolved"]
            stages = meta.get("interaction_logs", [])
            trace_paths = list((run / "logs" / job["run_id"] / path.parent.name).rglob("*.json"))
            assert len(trace_paths) == 1
            trace = load(trace_paths[0])
            assert (trace["utility"], trace["security"]) == (row["official_utility"], row["official_security"])
            payloads = sorted(set((trace.get("injections") or {}).values())) if row["condition"] == "attack" else []
            urls = {u.rstrip(".,;)") for p in payloads for u in re.findall(r"(?:https?://|www\.)[^\s\"<>]+", p)}
            full_peer_actors, target_peer_actors = set(), set()
            stage_signatures = defaultdict(set)
            for stage in stages:
                peer = [p for p in stage.get("visible_messages", []) if str(p.get("sender", "")).startswith("agent_") and p.get("sender") != stage["agent_id"]]
                peer_text = "\n".join(texts(peer))
                if full_match(payloads, peer_text):
                    full_peer_actors.add(stage["agent_id"])
                if any(url in peer_text for url in urls):
                    target_peer_actors.add(stage["agent_id"])
                for call in stage.get("tool_calls", []):
                    stage_signatures[signature(call)].add(stage["agent_id"])
                llm_meta = stage.get("llm", {}).get("metadata", {})
                if llm_meta.get("tool_loop_stopped_reason"):
                    stage_stops[llm_meta["tool_loop_stopped_reason"].split(":")[0]] += 1
            row_feature = dict(run=run_name, job_id=job["run_id"], scene_id=job["scene_id"], suite=row["suite"], task_id=row["task_id"], condition=row["condition"], utility=row["task_success"], attack_success=row["attack_success"], attack_exposed=row["attack_exposed"], token_in=row["token_in"], token_out=row["token_out"], tokens=row["observed_tokens"], latency_s=row["latency_s"], requests=len(requests), mean_input_per_request=row["token_in"]/len(requests), max_input_request=max(q["token_in"] for q in requests), handoffs=row["handoff_count"], mutations=row["topology_mutation_count"], repair_rounds=max(0,meta.get("turns_executed",1)-1), initial_agents=row["initial_agent_count"], peak_agents=row["peak_agent_count"], runtime_calls=len(calls), duplicate_calls=duplicates, duplicate_reads=duplicate_reads, repeated_same_read_output=repeated_same_read_output, runtime_errors=sum(bool(c.get("error")) for c in calls), captured_stages=len(stages), cross_agent_tool_signatures=sum(len(actors)>1 for actors in stage_signatures.values()), compacted_stages=sum(bool(s.get("llm",{}).get("metadata",{}).get("tool_context_compacted")) for s in stages), output_limited_stages=sum(bool(s.get("llm",{}).get("metadata",{}).get("hit_output_limit")) for s in stages), full_payload_in_peer_packet=bool(full_peer_actors), target_url_in_peer_packet=bool(target_peer_actors), reasoning_tokens=sum(reasoning) if reasoning else None, reasoning_usage_requests=len(reasoning))
            features.append(row_feature)
            selected.append(row_feature)
            if row["attack_success"] is True:
                selected_artifact = next((a for a in meta.get("artifact_records",[]) if a.get("artifact_id")==meta.get("selected_artifact_id")), {})
                successful_case = dict(**row_feature, first_audit_repair_recommended=(se.get("audit_reports") or [{}])[0].get("repair_recommended"), audit_modes=[[d.get("mode") for d in a.get("detected_modes",[])] for a in se.get("audit_reports",[])], final_termination_reason=(meta.get("termination_history") or [{}])[-1].get("reason"), selected_confidence=selected_artifact.get("confidence"), peer_full_payload_actors=sorted(full_peer_actors), peer_target_url_actors=sorted(target_peer_actors), tool_counts=dict(Counter(c["tool_name"] for c in calls)))
                success_cases.append(successful_case)
        def sub(condition):
            return [r for r in selected if r["condition"]==condition]
        clean, attack = sub("clean"), sub("attack")
        repaired = [r for r in selected if r["repair_rounds"]]
        unrepaired = [r for r in selected if not r["repair_rounds"]]
        failed = [r for r in selected if not r["utility"]]
        solved = [r for r in selected if r["utility"]]
        total_in, total_out = sum(r["token_in"] for r in selected), sum(r["token_out"] for r in selected)
        total_calls = sum(r["runtime_calls"] for r in selected)
        stat = dict(run=run_name, episodes=160, clean_success=sum(r["utility"] for r in clean), attacked_success=sum(r["utility"] for r in attack), asr_success=sum(r["attack_success"] is True for r in attack), token_in=total_in, token_out=total_out, total_tokens=total_in+total_out, input_fraction=total_in/(total_in+total_out), mean_tokens=mean(selected,"tokens"), median_tokens=statistics.median(r["tokens"] for r in selected), p90_tokens=sorted(r["tokens"] for r in selected)[143], mean_latency_s=mean(selected,"latency_s"), total_requests=sum(r["requests"] for r in selected), runtime_calls=total_calls, duplicate_calls=sum(r["duplicate_calls"] for r in selected), duplicate_reads=sum(r["duplicate_reads"] for r in selected), repeated_same_read_output=sum(r["repeated_same_read_output"] for r in selected), duplicate_fraction=sum(r["duplicate_calls"] for r in selected)/total_calls, handoffs=sum(r["handoffs"] for r in selected), mutations=sum(r["mutations"] for r in selected), repaired_episodes=len(repaired), mean_tokens_repaired=mean(repaired,"tokens"), mean_tokens_unrepaired=mean(unrepaired,"tokens"), utility_repaired=mean(repaired,"utility"), utility_unrepaired=mean(unrepaired,"utility"), mean_tokens_failed=mean(failed,"tokens"), mean_tokens_solved=mean(solved,"tokens"), clean_tokens=sum(r["tokens"] for r in clean), attack_tokens=sum(r["tokens"] for r in attack), attack_vs_clean_token_ratio=sum(r["tokens"] for r in attack)/sum(r["tokens"] for r in clean), full_payload_peer_episodes=sum(r["full_payload_in_peer_packet"] for r in attack), target_url_peer_episodes=sum(r["target_url_in_peer_packet"] for r in attack), compacted_stages=sum(r["compacted_stages"] for r in selected), output_limited_stages=sum(r["output_limited_stages"] for r in selected), reasoning_tokens=sum(r["reasoning_tokens"] or 0 for r in selected) if any(r["reasoning_tokens"] is not None for r in selected) else None, reasoning_usage_requests=sum(r["reasoning_usage_requests"] for r in selected), cross_agent_tool_signatures=sum(r["cross_agent_tool_signatures"] for r in selected), runtime_errors=sum(r["runtime_errors"] for r in selected))
        stat["top10_token_fraction"] = sum(r["tokens"] for r in sorted(selected,key=lambda r:r["tokens"],reverse=True)[:16]) / stat["total_tokens"]
        stat["failed_tokens_fraction"] = sum(r["tokens"] for r in failed) / stat["total_tokens"]
        stat["stage_stop_reasons"] = dict(stage_stops)
        stat["top_runtime_tools"] = runtime_names.most_common(8)
        overview.append(stat)
        for role, values in grouped_roles.items():
            role_totals.append(dict(run=run_name, actor_category=role, token_in=values["token_in"], token_out=values["token_out"], completed_requests=values["completed_requests"], total_tokens=values["token_in"]+values["token_out"], reasoning_tokens=values.get("reasoning_tokens") if values.get("reasoning_usage_requests") else None, reasoning_usage_requests=values["reasoning_usage_requests"]))
        expensive.extend(sorted(selected,key=lambda r:r["tokens"],reverse=True)[:5])
        provenance.append(dict(run=run_name, manifest_sha256=hashlib.sha256((run/"manifest.json").read_bytes()).hexdigest(), selected_results=hashes))
        print(run_name,json.dumps(stat,ensure_ascii=False),flush=True)
    save("summary.json",overview)
    save("role_usage.json",role_totals)
    save("successful_attack_cases.json",success_cases)
    save("source_inventory.json",provenance)
    save("top_cost_cases.json",expensive)
    csv_out("episode_features.csv",features)
    csv_out("overview.csv",[{k:v for k,v in r.items() if not isinstance(v,(dict,list))} for r in overview])
    csv_out("role_usage.csv",role_totals)
    csv_out("top_cost_cases.csv",expensive)
    save("analysis_scope.json",dict(episodes=640,scenarios_per_run=80,unique_user_tasks=76,paired_conditions=True,attack_family="direct",seed=42,note="Descriptive comparison of complete configurations; no single-agent control or isolated topology intervention. Exact repeated reads are not automatically waste or attack effects. Reasoning absent in provider usage means UNKNOWN, not zero."))
    from render_four_experiment_analysis import render
    render()


if __name__ == "__main__":
    main()
