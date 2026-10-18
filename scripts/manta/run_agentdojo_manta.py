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
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if not args.clean and not (args.attack and args.injection_task):
        raise SystemExit("use --clean, or provide --attack and --injection-task")
    if args.clean and (args.attack or args.injection_task):
        raise SystemExit("--clean cannot be combined with an attack")

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

    logdir = args.logdir or (repo_root / "results" / "v1" / "agentdojo" / "logs")
    logdir.mkdir(parents=True, exist_ok=True)
    output_dir = args.output_dir or (repo_root / "results" / "v1" / "agentdojo")
    output_dir.mkdir(parents=True, exist_ok=True)

    condition = "clean" if args.clean else "attack"
    episode_started = time.perf_counter()
    with OutputLogger(str(logdir)):
        if args.clean:
            task_success, attack_success = run_task_without_injection_tasks(
                suite,
                pipeline,
                task,
                logdir,
                force_rerun=True,
                benchmark_version=args.benchmark_version,
            )
            attack_success_value: bool | None = None
        else:
            if args.injection_task not in suite.injection_tasks:
                raise SystemExit(f"unknown injection task: {args.injection_task}")
            attacker = load_attack(args.attack, suite, pipeline)
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
            task_success = utility_results[(args.user_task, args.injection_task)]
            # AgentDojo's official security result is True when the attack did not succeed.
            attack_success_value = not security_results[(args.user_task, args.injection_task)]

    latency_s = max(time.perf_counter() - episode_started, 0.0)
    metadata = dict(pipeline.last_run_metadata)
    interaction_logs = [
        log for log in metadata.get("interaction_logs", []) if isinstance(log, dict)
    ]
    mock_used = any(bool(log.get("llm", {}).get("mock_used")) for log in interaction_logs)
    reported_costs = [
        float(log.get("llm", {}).get("cost_usd", 0.0))
        for log in interaction_logs
    ]
    cost_unavailable = any(
        bool(log.get("llm", {}).get("metadata", {}).get("missing_cost_note"))
        for log in interaction_logs
    )
    cost_usd: float | None = None if (not mock_used and cost_unavailable) else sum(reported_costs)
    result: dict[str, Any] = {
        "benchmark": "agentdojo",
        "benchmark_version": args.benchmark_version,
        "agentdojo_commit": _git_sha(dojo_root),
        "manta_commit": _manta_commit(manta_root),
        "suite": args.suite,
        "task_id": args.user_task,
        "injection_task": args.injection_task,
        "attack": args.attack,
        "condition": condition,
        "model": args.model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "task_success": bool(task_success),
        "attack_success": attack_success_value,
        "attack_exposed": "UNKNOWN",
        "actual_agent_count": len(metadata.get("topology_layout", {}).get("agent_ids", [])),
        "handoff_count": len(metadata.get("relay_messages", [])),
        "topology_mutation_count": len(metadata.get("self_evolved", {}).get("mutations", [])),
        "tokens": sum(
            int(log.get("llm", {}).get("token_in", 0)) + int(log.get("llm", {}).get("token_out", 0))
            for log in interaction_logs
        ),
        "cost_usd": cost_usd,
        "cost_status": "UNKNOWN_PROVIDER_PRICE" if cost_usd is None else "REPORTED_OR_ZERO",
        "latency_s": round(latency_s, 3),
        "mock_used": mock_used,
        "run_status": "MOCK_SMOKE" if mock_used else ("SUCCESS" if task_success else "TASK_FAILED"),
        "manta_metadata": metadata,
    }
    stem = f"{args.suite}__{args.user_task}__{condition}"
    if args.injection_task:
        stem += f"__{args.injection_task}"
    path = output_dir / f"{stem}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: result[k] for k in result if k != "manta_metadata"}, ensure_ascii=False, indent=2))
    print(f"result_path={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
