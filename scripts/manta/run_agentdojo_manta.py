"""Run one official AgentDojo task through the pinned MANTA adapter.

The script is intentionally one episode at a time.  It never changes AgentDojo's
task, attack, injection, or judge implementation.  Use ``--clean`` first; add
``--attack`` and ``--injection-task`` only after the clean episode is valid.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
import hashlib
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git_sha(path: Path) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "UNKNOWN"


def _manta_commit(path: Path) -> str:
    """The vendored MANTA snapshot has no upstream .git metadata."""
    return os.getenv("MANTA_COMMIT", "3da4087")


def _source_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        if path.is_dir():
            files = sorted(p for p in path.rglob("*") if p.is_file() and
                           p.suffix in {".py", ".md", ".json", ".toml"})
        else:
            files = [path]
        for file in files:
            digest.update(str(file.relative_to(path) if path.is_dir() else file.name).encode())
            digest.update(file.read_bytes())
    return digest.hexdigest()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="workspace")
    parser.add_argument("--user-task", default="user_task_0")
    parser.add_argument("--injection-task", default=None)
    parser.add_argument("--attack", default=None)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--num-agents", type=int, default=3)
    parser.add_argument("--max-turns", type=int, default=2)
    parser.add_argument("--repair-budget", type=int, default=1)
    parser.add_argument("--planner-mode", choices=["task_conditioned", "fixed"], default="task_conditioned")
    parser.add_argument("--audit-mode", choices=["heuristic", "hybrid", "llm_judge"], default="heuristic")
    parser.add_argument("--benchmark-version", default="v1.2.2")
    parser.add_argument("--logdir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--allow-mock", action="store_true", help="Explicit zero-cost smoke mode")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if not args.clean and not (args.attack and args.injection_task):
        raise SystemExit("use --clean, or provide --attack and --injection-task")
    if args.clean and (args.attack or args.injection_task):
        raise SystemExit("--clean cannot be combined with an attack")
    os.environ["MAS_REQUIRE_LIVE_LLM"] = "0" if args.allow_mock else "1"
    if args.allow_mock:
        os.environ["MAS_DISABLE_LIVE_LLM"] = "1"
    else:
        os.environ.pop("MAS_DISABLE_LIVE_LLM", None)

    repo_root = _repo_root()
    dojo_root = repo_root
    manta_root = Path(os.getenv("MANTA_SOURCE_DIR", str(repo_root / "upstreams" / "manta")))
    if not (dojo_root / "src" / "agentdojo").exists() or not manta_root.exists():
        raise SystemExit("AgentDojo source and the pinned MANTA snapshot must exist")

    sys.path.insert(0, str(repo_root / "src"))
    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.benchmark import run_task_with_injection_tasks, run_task_without_injection_tasks
    from agentdojo.logging import OutputLogger
    from agentdojo.task_suite.load_suites import get_suite
    from agentdojo_manta import AdapterPaths, MantaAgentDojoPipeline
    from agentdojo_manta.metrics import official_outcomes, resource_metrics, topology_metrics

    suite = get_suite(args.benchmark_version, args.suite)
    if args.user_task not in suite.user_tasks:
        raise SystemExit(f"unknown user task: {args.user_task}")
    task = suite.get_user_task_by_id(args.user_task)
    pipeline = MantaAgentDojoPipeline(
        AdapterPaths.from_repo(repo_root, manta_root),
        model=args.model,
        num_agents=args.num_agents,
        max_turns=args.max_turns,
        repair_budget=args.repair_budget,
        initial_planner_mode=args.planner_mode,
        audit_mode=args.audit_mode,
    )
    pipeline.bind_suite(suite)
    # AgentDojo does not supply extra_args when calling custom pipelines.
    pipeline.seed = args.seed

    run_id = args.run_id or uuid.uuid4().hex
    if Path(run_id).name != run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
        raise SystemExit("--run-id must be a single directory name")
    logdir = (args.logdir or (repo_root / "results" / "v1" / "agentdojo" / "logs")) / run_id
    logdir.mkdir(parents=True, exist_ok=True)
    output_dir = (args.output_dir or (repo_root / "results" / "v1" / "agentdojo")) / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    if (output_dir / "result.json").exists():
        raise SystemExit("run-id already has a result; use a new run-id to preserve evidence")

    condition = "clean" if args.clean else "attack"
    episode_started = time.perf_counter()
    utility = security = None
    error_status = error_message = None
    evaluation_phase = "execute"
    try:
        with OutputLogger(str(logdir)):
            if args.clean:
                utility, security = run_task_without_injection_tasks(
                    suite,
                    pipeline,
                    task,
                    logdir,
                    force_rerun=True,
                    benchmark_version=args.benchmark_version,
                )
            else:
                if args.injection_task not in suite.injection_tasks:
                    raise SystemExit(f"unknown injection task: {args.injection_task}")
                attacker = load_attack(args.attack, suite, pipeline)
                if attacker.is_dos_attack:
                    raise ValueError("DoS attacks require a separate non-targeted protocol")
                utility_results, security_results = run_task_with_injection_tasks(
                    suite,
                    pipeline,
                    task,
                    attacker,
                    logdir,
                    force_rerun=True,
                    injection_tasks=[args.injection_task],
                    benchmark_version=args.benchmark_version,
                )
                utility = utility_results[(args.user_task, args.injection_task)]
                security = security_results[(args.user_task, args.injection_task)]
            evaluation_phase = "official_trace_check"
            trace_files = list(logdir.rglob("*.json"))
            if not trace_files:
                error_status, error_message = "JUDGE_ERROR", "Official trace unavailable"
            for trace_file in trace_files:
                trace = json.loads(trace_file.read_text(encoding="utf-8"))
                if trace.get("error"):
                    error_status, error_message = "INFRA_ERROR", str(trace["error"])
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        if pipeline.execution_completed and evaluation_phase == "execute":
            error_status = "JUDGE_ERROR"
        else:
            error_status = "TIMEOUT" if "timeout" in error_message.lower() else "INFRA_ERROR"

    latency_s = max(time.perf_counter() - episode_started, 0.0)
    metadata = dict(pipeline.last_run_metadata)
    mock_used = pipeline.mock_used
    request_records = list(pipeline.request_records)
    if os.getenv("MANTA_PROVIDER", "deepseek") != "deepseek":
        completed = [r for r in request_records if r.get("status") == "completed"]
        if not completed or getattr(pipeline, "provider_fatal_error", None) or any(not r.get("usage_available") for r in completed):
            error_status, error_message = "INFRA_ERROR", "GPT-4o live usage/model validation failed; not a valid safety result"
    if any(r.get("error_type") == "BudgetExceeded" for r in request_records):
        error_status, error_message = "BLOCKED", "Request budget exhausted; episode is not a valid safety result"
    exposed_records = [r for r in request_records if r["status"] == "completed" and r["matched_injection_keys"]]
    result: dict[str, Any] = {
        "benchmark": "agentdojo",
        "system": "MANTA",
        "benchmark_version": args.benchmark_version,
        "agentdojo_commit": _git_sha(dojo_root),
        "agentdojo_upstream_commit": "089ed468cf3ed0322acc66b0211f26d9d90dbf60",
        "adapter_source_digest": _source_digest([repo_root / "src" / "agentdojo_manta", Path(__file__)]),
        "manta_commit": _manta_commit(manta_root),
        "manta_source_digest": _source_digest([manta_root]),
        "manta_source_status": "UPSTREAM_WITH_TOOL_PROTOCOL_PATCH",
        "suite": args.suite,
        "task_id": args.user_task,
        "injection_task": args.injection_task,
        "attack": args.attack,
        "condition": condition,
        "model": pipeline.model,
        "provider": os.getenv("MANTA_PROVIDER", "deepseek"),
        "metric_schema_version": "2",
        "run_id": run_id,
        "seed": args.seed,
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "planner_used_fallback": metadata.get("self_evolved", {}).get("planner", {}).get("used_fallback"),
        **official_outcomes(utility, security, clean=args.clean, error_status=error_status, mock_used=mock_used),
        "error": error_message,
        "attack_exposed": None if args.clean else True if exposed_records else "UNKNOWN",
        "attack_exposure_method": "exact nonempty payload in messages of completed provider requests; no match is UNKNOWN",
        "attack_exposure_evidence": exposed_records,
        **topology_metrics(metadata, request_records),
        "initial_agent_budget": metadata.get("manta_config", {}).get("initial_agent_budget"),
        "max_initial_agents": metadata.get("manta_config", {}).get("max_initial_agents"),
        "max_total_agents": metadata.get("manta_config", {}).get("max_total_agents"),
        **resource_metrics(request_records, mock_used=mock_used),
        "llm_requests": request_records,
        "agentdojo_runtime_calls": pipeline.runtime_calls,
        "tool_effect": "UNKNOWN",
        "latency_s": round(latency_s, 3),
        "mock_used": mock_used,
        "manta_metadata": metadata,
        "manta_trace_events": [event.to_dict() if hasattr(event, "to_dict") else event
                               for event in pipeline.last_trace_events],
        "official_logdir": str(logdir),
    }
    path = output_dir / "result.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    private_fields = {"manta_metadata", "manta_trace_events", "agentdojo_runtime_calls", "llm_requests", "attack_exposure_evidence"}
    print(json.dumps({k: v for k, v in result.items() if k not in private_fields}, ensure_ascii=False, indent=2))
    print(f"result_path={path}")
    return 0 if error_status is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
