"""Run independent AgentDojo episodes with a bounded process-level concurrency.

Each episode gets its own Python process, output directory, and TraceLogger
directory.  This keeps AgentDojo's mutable tool environment isolated while
allowing multiple independent tasks to use the same model endpoint.  Start at
``--parallelism 2`` and increase only after checking for 429s and timeout rates.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-tasks", required=True, help="Comma-separated AgentDojo task IDs")
    parser.add_argument("--suite", default="workspace")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--attack", default=None)
    parser.add_argument("--injection-task", default=None)
    parser.add_argument("--parallelism", type=int, default=2)
    parser.add_argument("--model", default=None)
    parser.add_argument("--num-agents", type=int, default=3)
    parser.add_argument("--max-turns", type=int, default=2)
    parser.add_argument("--repair-budget", type=int, default=1)
    parser.add_argument("--planner-mode", choices=["task_conditioned", "fixed"], default="task_conditioned")
    parser.add_argument("--audit-mode", choices=["heuristic", "hybrid", "llm_judge"], default="heuristic")
    parser.add_argument("--benchmark-version", default="v1.2.2")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--logdir", type=Path, default=None)
    parser.add_argument("--allow-mock", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    return parser


def _run_one(args: argparse.Namespace, task_id: str, output_root: Path, log_root: Path) -> dict[str, Any]:
    runner = _repo_root() / "scripts" / "manta" / "run_agentdojo_manta.py"
    run_id = f"{args.suite}__{task_id}__{'clean' if args.clean else 'attack'}"
    output_dir = output_root / run_id
    logdir = log_root / run_id
    command = [
        sys.executable,
        str(runner),
        "--suite",
        args.suite,
        "--user-task",
        task_id,
        "--num-agents",
        str(args.num_agents),
        "--max-turns",
        str(args.max_turns),
        "--repair-budget",
        str(args.repair_budget),
        "--planner-mode",
        args.planner_mode,
        "--audit-mode",
        args.audit_mode,
        "--benchmark-version",
        args.benchmark_version,
        "--output-dir",
        str(output_dir),
        "--logdir",
        str(logdir),
        "--run-id", "episode",
        "--seed", str(args.seed),
    ]
    if args.allow_mock:
        command.append("--allow-mock")
    if args.model:
        command.extend(["--model", args.model])
    if args.clean:
        command.append("--clean")
    else:
        if not args.attack or not args.injection_task:
            raise ValueError("attack batches require --attack and --injection-task")
        command.extend(["--attack", args.attack, "--injection-task", args.injection_task])

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_repo_root() / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["MAS_REQUIRE_LIVE_LLM"] = "0" if args.allow_mock else "1"
    if args.allow_mock:
        env["MAS_DISABLE_LIVE_LLM"] = "1"
    else:
        env.pop("MAS_DISABLE_LIVE_LLM", None)
    console_path = logdir / "console.log"
    logdir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        command,
        cwd=_repo_root(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    console_path.write_text(completed.stdout + "\n--- STDERR ---\n" + completed.stderr, encoding="utf-8")
    result_path = output_dir / "episode" / "result.json"
    result: dict[str, Any] = {
        "task_id": task_id,
        "returncode": completed.returncode,
        "console_path": str(console_path),
    }
    if result_path.exists():
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        result.update(
            {
                "result_path": str(result_path),
                "run_status": payload.get("run_status"),
                "task_success": payload.get("task_success"),
                "mock_used": payload.get("mock_used"),
                "tokens": payload.get("tokens"),
                "cost_usd": payload.get("cost_usd"),
                "latency_s": payload.get("latency_s"),
            }
        )
    return result


def main() -> int:
    args = _parser().parse_args()
    if args.parallelism < 1 or args.parallelism > 4:
        raise SystemExit("--parallelism must be between 1 and 4")
    task_ids = [item.strip() for item in args.user_tasks.split(",") if item.strip()]
    if not task_ids:
        raise SystemExit("--user-tasks must contain at least one task ID")
    if len(task_ids) != len(set(task_ids)):
        raise SystemExit("duplicate task IDs would collide within one batch")
    if args.clean and (args.attack or args.injection_task):
        raise SystemExit("--clean cannot be combined with attack options")
    if not args.allow_mock and not os.getenv("V1_MAX_COST_USD", "").strip():
        raise SystemExit("set V1_MAX_COST_USD before starting a live batch")
    root = _repo_root()
    batch_id = uuid.uuid4().hex
    output_root = (args.output_dir or root / "results" / "v1" / "agentdojo_batch") / batch_id
    log_root = (args.logdir or root / "results" / "v1" / "agentdojo_batch_logs") / batch_id
    output_root.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(args.parallelism, len(task_ids))) as executor:
        futures = {
            executor.submit(_run_one, args, task_id, output_root, log_root): task_id
            for task_id in task_ids
        }
        for future in as_completed(futures):
            task_id = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"task_id": task_id, "returncode": -1, "error": repr(exc)})

    results.sort(key=lambda item: str(item.get("task_id", "")))
    summary = {
        "suite": args.suite,
        "tasks": task_ids,
        "parallelism": args.parallelism,
        "allow_mock": args.allow_mock,
        "results": results,
    }
    summary_path = output_root / "batch_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"summary_path={summary_path}")
    return 0 if all(item.get("returncode") == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
