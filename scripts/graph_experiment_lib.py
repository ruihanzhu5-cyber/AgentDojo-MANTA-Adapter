"""Capture live native checkpoints and resume paired graph conditions."""
from __future__ import annotations

import copy
import hashlib
import os
import random
import time
from pathlib import Path

from context_replay_lib import ROOT, Observation, digest, load, save
from graph_checkpoint import (Codec, capture_bundle, compile_capture, compile_resume, flip_graph,
                              restore_bundle, restore_environments, set_rng)

PROTOCOL = "manta-native-graph-checkpoint-v1"
FORMAL = ROOT / "results/v1/formal_80_seed42"


def boot():
    from agentdojo_manta.adapter import AdapterPaths, _import_manta
    _import_manta(AdapterPaths.from_repo(ROOT))
    for key in list(os.environ):
        if key.startswith(("MAS_", "MANTA_", "OPENROUTER_")):
            os.environ.pop(key)
    os.environ["MAS_REQUIRE_LIVE_LLM"] = "1"


def fingerprint():
    files = [Path(__file__), ROOT / "scripts/graph_checkpoint.py", ROOT / "scripts/run_graph_experiment.py",
             ROOT / "scripts/context_replay_lib.py", ROOT / "scripts/run_context_replay.py"]
    for base in (ROOT / "src", ROOT / "upstreams/manta"):
        files.extend(p for p in sorted(base.rglob("*")) if p.is_file() and p.suffix in {".py", ".yaml", ".json", ".md"}
                     and "__pycache__" not in p.parts and "runs" not in p.parts)
    h = hashlib.sha256()
    for p in files:
        h.update(p.relative_to(ROOT).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def candidate_pool(limit=12):
    manifest = load(FORMAL / "manifest.json")
    candidates = []
    for job in manifest["jobs"]:
        if job["condition"] != "attack":
            continue
        rows = [load(p) for p in sorted((FORMAL / "attempts" / job["run_id"]).glob("attempt_*/result.json"))]
        valid = [r for r in rows if r["evaluation_valid"]]
        if len(valid) != 1:
            raise ValueError("Original formal selection is ambiguous")
        row = valid[0]
        if row["attack_exposed"] is not True:
            continue
        candidates.append(dict(id=job["run_id"], suite=job["suite"], task_id=job["task_id"],
            injection_task=job["injection_task"], payload_sha256=job["payload_sha256"],
            original_had_mutation=bool(row["manta_metadata"]["self_evolved"]["mutations"])))
    # Pre-specified selection; no ordering by new capture/branch security outcomes.
    candidates.sort(key=lambda j: (not j["original_had_mutation"], j["id"]))
    return candidates[:limit]


def new_config():
    from MAS.config import SelfEvolvedConfig
    from MAS.langgraph_engine import ExperimentSpec
    config = SelfEvolvedConfig(harness_backend="openrouter", initial_planner_mode="task_conditioned",
        max_initial_agents=5, max_total_agents=10, max_turns=2, repair_budget=1, audit_mode="heuristic",
        write_protocol="commit_once", skill_update_batch_size=0,
        playbook_path=str(ROOT / "upstreams/manta/config/topology_playbook.json"),
        skill_path=str(ROOT / "upstreams/manta/config/topology_skill.md"))
    config.validate()
    spec = ExperimentSpec(topology="self_evolved", num_agents=3, rounds=1, discussion_rounds=1,
        communication_budget_per_agent=2, termination_consensus_mode="lexical",
        final_vote_mode="deterministic", peer_artifact_max_chars=1200, benchmark_name="agentdojo")
    return config, spec


def fresh_environment(candidate):
    from agentdojo.task_suite.load_suites import get_suite
    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.functions_runtime import FunctionsRuntime
    suite = get_suite("v1.2.2", candidate["suite"])
    task = suite.get_user_task_by_id(candidate["task_id"])
    goal = suite.get_injection_task_by_id(candidate["injection_task"])
    injections = load_attack("direct", suite, None).attack(task, goal)
    # The original manifest uses the default JSON ASCII escaping for payload hashes.
    import json
    if hashlib.sha256(json.dumps(injections, sort_keys=True).encode()).hexdigest() != candidate["payload_sha256"]:
        raise ValueError("Official payload differs from frozen original scenario")
    env = task.init_environment(suite.load_and_inject_default_environment(injections))
    return suite, task, goal, injections, FunctionsRuntime(suite.tools), env


def raw_toolset(runtime, env, observer):
    from agentdojo_manta.adapter import _function_to_manta_tool
    return [_function_to_manta_tool(runtime, env, function, observer=observer)
            for function in runtime.functions.values()]


def processed_toolset(raw, prompt):
    from MAS.self_evolved.retrieval import augment_with_constraint_search
    from MAS.self_evolved.transaction import augment_with_transaction_tools, wrap_write_tools_as_proposals
    from MAS.self_evolved.executor import state_changing_tool_names
    tools = augment_with_transaction_tools(augment_with_constraint_search(list(raw)), task_prompt=prompt)
    names = state_changing_tool_names(tools)
    if not names:
        raise ValueError("This protocol requires native commit_once-capable tools")
    return wrap_write_tools_as_proposals(tools, names)


def make_client(observer, model, output, factory=None, limit=120):
    from agentdojo_manta.adapter import AdapterPaths, _make_llm_client
    client = (factory(AdapterPaths.from_repo(ROOT), model, observer) if factory else
              _make_llm_client(AdapterPaths.from_repo(ROOT), model, observer=observer))
    original = client._create_chat_completion_once
    captured = []
    observer.request_guard_failures = []

    def observed(**kwargs):
        if len(captured) >= limit:
            observer.request_guard_failures.append("provider_request_limit")
            raise RuntimeError("Graph experiment provider-request limit reached")
        record = dict(index=len(captured) + 1, request=copy.deepcopy(kwargs), status="started")
        captured.append(record)
        save(output / "provider_inputs.json", captured)
        try:
            response = original(**kwargs)
            record.update(status="completed", response=response.model_dump(mode="json"))
            return response
        except Exception as exc:
            record.update(status="error", error_type=type(exc).__name__)
            raise
        finally:
            save(output / "provider_inputs.json", captured)

    client._create_chat_completion_once = observed
    return client


def official(suite, task, initial, env, calls, answer=""):
    from agentdojo.functions_runtime import FunctionCall
    from agentdojo.types import text_content_block_from_string
    trace = [FunctionCall(function=c["tool_name"], args=c["arguments"]) for c in calls]
    value = suite._check_task_result(task, [text_content_block_from_string(str(answer))], initial, env, trace)
    if type(value) is not bool:
        raise ValueError("Official judge did not return a known boolean outcome")
    return value


def incumbent(frame):
    turns = frame.get("turn_results", [])
    artifact = turns[-1].output_artifact if turns else None
    return str(artifact.get("answer", "")) if artifact else ""


def request_ok(observer):
    return (not observer.mock_used and bool(observer.request_records)
            and not getattr(observer, "request_guard_failures", [])
            and all(r["status"] == "completed" for r in observer.request_records))


def stage_failures(metadata):
    flags = []
    for stage in metadata.get("interaction_logs", []):
        m = stage.get("llm", {}).get("metadata", {})
        for key in ("hit_output_limit", "tool_loop_timeout_recovered", "fatal_tool_failure", "empty_completion",
                    "tool_loop_stopped_reason"):
            if m.get(key):
                flags.append(dict(actor=stage["agent_id"], key=key))
        if m.get("generation_status") != "answered":
            flags.append(dict(actor=stage["agent_id"], key="generation_not_answered"))
    return flags


class Captured(Exception):
    pass


class NoCheckpoint(Exception):
    pass


def capture(candidate, model, output, *, factory=None):
    boot()
    from agentdojo_manta.adapter import AgentDojoTask
    from MAS.self_evolved.engine import SelfEvolvedEngine
    suite, task, goal, injections, runtime, env = fresh_environment(candidate)
    initial = env.model_copy(deep=True)
    observer = Observation()
    observer.injections = injections
    raw = raw_toolset(runtime, env, observer)
    client = make_client(observer, model, output, factory)
    config, spec = new_config()
    engine = SelfEvolvedEngine(client, config)
    checkpoint, reason, boundary_checks = None, None, []

    def checkpoint_hook(frame):
        nonlocal checkpoint, reason
        if frame["turn_index"] == 0:
            return
        exposed = any(r["status"] == "completed" and r["matched_injection_keys"] for r in observer.request_records)
        harm = official(suite, goal, initial, env, observer.runtime_calls, incumbent(frame))
        checks = dict(turn=frame["turn_index"], exposed=exposed, goal_already_reached=harm,
                      request_complete=request_ok(observer), stage_failures=stage_failures(frame["state"]))
        boundary_checks.append(checks)
        if not exposed or harm or not checks["request_complete"] or checks["stage_failures"]:
            reason = "Checkpoint not eligible: exposure/goal/infrastructure criterion"
            raise NoCheckpoint()
        try:
            changed = flip_graph(frame["topo_spec"], config.max_total_agents)
        except ValueError as exc:
            reason = str(exc)
            raise NoCheckpoint()
        checkpoint = capture_bundle(engine, frame, env, initial, observer, raw)
        checkpoint.update(protocol=PROTOCOL, candidate=candidate, code_sha256=fingerprint(),
                          engineering_fixture=factory is not None, eligibility=checks,
                          incumbent_answer=incumbent(frame),
                          original_graph=frame["topo_spec"].to_payload(), changed_graph=changed.to_payload())
        # Integrity covers the environment and all recorded prefix/eligibility fields.
        checkpoint["checkpoint_sha256"] = digest(checkpoint)
        save(output / "checkpoint.json", checkpoint)
        raise Captured()

    def prefix_finished(frame):
        nonlocal reason
        reason = "Native controller terminated without an eligible next-turn boundary"
        boundary_checks.append(dict(turn=frame.get("turn_index"), exposed=any(
            r["status"] == "completed" and r["matched_injection_keys"] for r in observer.request_records),
            goal_already_reached=official(suite, goal, initial, env, observer.runtime_calls, incumbent(frame)),
            request_complete=request_ok(observer), stage_failures=stage_failures(frame["state"])))
        raise NoCheckpoint()

    engine._checkpoint_hook = checkpoint_hook
    engine._prefix_finished = prefix_finished
    error = None
    try:
        compile_capture()(engine, task=AgentDojoTask(task.ID, task.PROMPT, "agentdojo"),
                          run_index=0, seed=42, spec=spec, agent_types=["general"], tools=raw, max_tool_iterations=8)
    except (Captured, NoCheckpoint):
        pass
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    infra_ok = request_ok(observer)
    row = dict(protocol=PROTOCOL, candidate=candidate,
        run_status="CHECKPOINT_READY" if checkpoint is not None else "NO_ELIGIBLE" if error is None and infra_ok else "CAPTURE_ERROR",
        error=error, reason=reason, boundary_checks=boundary_checks, engineering_fixture=factory is not None,
        checkpoint_sha256=checkpoint["checkpoint_sha256"] if checkpoint else None,
        runtime_calls=observer.runtime_calls, request_records=observer.request_records,
        request_guard_failures=getattr(observer, "request_guard_failures", []))
    save(output / "result.json", row)
    return row


def branch(bundle, job, model, output, *, factory=None):
    boot()
    from MAS.monitor import NullDescriptor
    from MAS.self_evolved.engine import SelfEvolvedEngine
    from agentdojo_manta.metrics import resource_metrics
    original = dict(bundle)
    expected = original.pop("checkpoint_sha256")
    if digest(original) != expected or bundle["code_sha256"] != fingerprint():
        raise ValueError("Checkpoint integrity/source changed")
    if bundle["engineering_fixture"] and factory is None:
        raise ValueError("Engineering checkpoint cannot produce live research results")
    candidate = bundle["candidate"]
    suite, task, goal, injections, runtime, _ = fresh_environment(candidate)
    env, initial, domain_cache = restore_environments(bundle)
    if type(env) is not suite.environment_type or type(initial) is not suite.environment_type:
        raise ValueError("Checkpoint environment class differs from official suite")
    observer = Observation()
    observer.injections = injections
    raw = raw_toolset(runtime, env, observer)
    tools, handlers = processed_toolset(raw, task.PROMPT)
    client = make_client(observer, model, output, factory)
    engine = SelfEvolvedEngine(client, new_config()[0])
    restored = restore_bundle(bundle, engine, tools, handlers, raw, NullDescriptor(), cache=domain_cache)
    frame = restored["frame"]
    if restored["environment"] is not env or restored["initial_environment"] is not initial:
        raise ValueError("Model/tool environment alias restoration failed")
    baseline_harm = official(suite, goal, initial, env, bundle["prefix_runtime_calls"], bundle["incumbent_answer"])
    if baseline_harm or not bundle["eligibility"]["exposed"]:
        raise ValueError("Checkpoint violates exposed-but-not-yet-harmed selection rule")
    state = frame["state"]
    before = digest({k: v for k, v in bundle.items() if k != "checkpoint_sha256"})
    saved_graph = frame["topo_spec"]
    chosen = flip_graph(saved_graph, engine.se_config.max_total_agents) if job["condition"] == "G1" else saved_graph
    old_layout = frame["layout"]
    frame["topo_spec"] = chosen
    frame["layout"] = chosen.to_layout()
    state["layout"] = frame["layout"]
    frame["context"].set_spec(chosen)
    # Temporarily revert only the graph fields, then re-encode the ENTIRE frame.
    # This checks all nongraph state, aliases, policies, counters and executor memory.
    frame["topo_spec"] = saved_graph
    frame["layout"] = state["layout"] = old_layout
    frame["context"].set_spec(saved_graph)
    from graph_checkpoint import runtime_bindings
    codec = Codec(runtime_bindings(engine, tools, handlers, raw, state["descriptor"]))
    if codec.encode(restored) != bundle["frame"]:
        raise ValueError("Graph intervention altered nongraph state")
    frame["topo_spec"] = chosen
    frame["layout"] = state["layout"] = chosen.to_layout()
    frame["context"].set_spec(chosen)
    if env.model_dump(mode="json") != bundle["environment"]:
        raise ValueError("Restoration changed the tool environment")
    stage_offset, view_offset = len(state["interaction_logs"]), len(state["message_views"])
    execution_graphs = []
    executor = frame["executor"]
    original_turn = executor.run_turn

    def tracked_turn(current_state, spec, *, turn_index):
        execution_graphs.append(dict(turn=turn_index, graph=spec.to_payload(), adjacency=spec.to_layout().adjacency))
        if not execution_graphs[:-1] and spec != chosen:
            raise ValueError("Requested graph was overwritten before execution")
        return original_turn(current_state, spec, turn_index=turn_index)

    executor.run_turn = tracked_turn
    set_rng(restored)
    started = time.perf_counter()
    result, error = None, None
    try:
        result = compile_resume(frame.keys())(engine, frame)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    metadata = result.run_metadata if result is not None else {"interaction_logs": state["interaction_logs"]}
    continuation = metadata.get("interaction_logs", [])[stage_offset:]
    failures = stage_failures({"interaction_logs": continuation})
    execution_complete = (error is None and result is not None and request_ok(observer) and not failures
                          and bool(execution_graphs))
    valid = execution_complete and factory is None
    calls = bundle["prefix_runtime_calls"] + observer.runtime_calls
    harm = official(suite, goal, initial, env, calls, result.final_answer if result else "")
    utility = official(suite, task, initial, env, calls, result.final_answer if result else "")
    if before != digest({k: v for k, v in bundle.items() if k != "checkpoint_sha256"}):
        raise ValueError("Original checkpoint was mutated by continuation")
    row = dict(protocol=PROTOCOL, job=job, run_status="VALID_BRANCH" if valid else "INCOMPLETE",
        evaluation_valid=valid, stage_execution_complete=execution_complete, engineering_fixture=factory is not None,
        error=error, failures=failures, tool_error_count=sum(c["error"] is not None for c in observer.runtime_calls),
        checkpoint_sha256=expected, restored_frame_sha256=bundle["frame_sha256"],
        nongraph_state_verified=True, environment_verified=True, baseline_goal=baseline_harm,
        observed_attack_success=harm, attack_success=harm if valid else None, task_success=utility if valid else None,
        execution_graphs=execution_graphs,
        execution_signature=[(l["agent_id"], l["phase"], l["stage_role"], l["round_index"]) for l in continuation],
        continuation_views=metadata.get("message_views", [])[view_offset:],
        continuation_logs=continuation, final_answer=result.final_answer if result else None,
        runtime_calls=observer.runtime_calls, request_records=observer.request_records,
        request_guard_failures=getattr(observer, "request_guard_failures", []),
        native_run_metadata=metadata, latency_s=time.perf_counter() - started,
        **resource_metrics(observer.request_records, mock_used=observer.mock_used))
    save(output / "result.json", row)
    return row
