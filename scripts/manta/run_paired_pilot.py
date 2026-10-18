"""Launch the first bounded, paired MANTA x AgentDojo acceptance experiment."""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parallelism", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the frozen plan without API calls")
    parser.add_argument("--smoke", action="store_true", help="Explicit zero-cost mock integration check")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    if not 1 <= args.parallelism <= 4:
        parser.error("validated episode parallelism must be 1..4")
    if not (args.dry_run or args.smoke) and not os.getenv("DEEPSEEK_API_KEY"):
        parser.error("DEEPSEEK_API_KEY is missing in this terminal; set it before launching")
    sys.path.insert(0, str(ROOT / "src"))
    from agentdojo.task_suite.load_suites import get_suite
    from agentdojo_manta.adapter import AdapterPaths, _import_manta
    from agentdojo_manta.metrics import summarize

    # Validate imports, official IDs and source layout before starting paid work.
    _import_manta(AdapterPaths.from_repo(ROOT))
    suite = get_suite("v1.2.2", "workspace")
    task_ids = ["user_task_0", "user_task_1", "user_task_2", "user_task_3"]
    for task in task_ids:
        suite.get_user_task_by_id(task)
    suite.get_injection_task_by_id("injection_task_0")
    config = dict(suite="workspace", benchmark_version="v1.2.2",
                  model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                  num_agents=3, max_turns=2, repair_budget=1,
                  planner_mode="task_conditioned", audit_mode="heuristic", seed=42)
    jobs = [dict(run_id=f"{task}__{condition}", task_id=task, condition=condition,
                 attack="direct" if condition == "attack" else None,
                 injection_task="injection_task_0" if condition == "attack" else None)
            for task in task_ids for condition in ("clean", "attack")]
    manifest = dict(protocol="agentdojo-manta-paired-acceptance-v1", phase="acceptance_pilot",
                    python=platform.python_version(), config=config,
                    adaptive_limits=dict(max_initial_agents=5, max_total_agents=10),
                    parallelism=args.parallelism, mock=args.smoke, jobs=jobs,
                    cost_status="UNKNOWN_PROVIDER_PRICE",
                    budget_note="Eight episodes only. V1_MAX_COST_USD is not a monetary spend limiter.")
    if args.dry_run:
        print(json.dumps(manifest, indent=2), flush=True)
        print("PRECHECK_OK: 4 tasks, 8 episodes, no API requests made.", flush=True)
        return 0

    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    output_root = ROOT / "results" / "v1" / "paired_pilot" / session_id
    output_root.mkdir(parents=True)
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"RUN_DIR={output_root}", flush=True)
    print(f"8 episodes, parallelism={args.parallelism}, mock={args.smoke}; pricing UNKNOWN.", flush=True)
    active = set()
    active_lock = threading.Lock()
    stop = threading.Event()

    def run_one(job):
        run_id = job["run_id"]
        command = [sys.executable, "-u", str(ROOT / "scripts" / "manta" / "run_agentdojo_manta.py"),
                   "--user-task", job["task_id"], "--run-id", run_id,
                   "--output-dir", str(output_root / "episodes"),
                   "--logdir", str(output_root / "logs")]
        for key, value in config.items():
            command.extend(["--" + key.replace("_", "-"), str(value)])
        if job["condition"] == "clean":
            command.append("--clean")
        else:
            command.extend(["--attack", job["attack"], "--injection-task", job["injection_task"]])
        if args.smoke:
            command.append("--allow-mock")
        console_path = output_root / "logs" / run_id / "console.log"
        console_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"START {run_id}", flush=True)
        env = os.environ.copy()
        env["MANTA_MAX_INITIAL_AGENTS"] = "5"
        env["MANTA_MAX_TOTAL_AGENTS"] = "10"
        env["V1_LLM_TIMEOUT_S"] = "180"
        env["PYTHONIOENCODING"] = "utf-8"
        with console_path.open("w", encoding="utf-8") as console:
            with active_lock:
                if stop.is_set():
                    return job, dict(condition=job["condition"], evaluation_valid=False,
                                     run_status="BLOCKED", process_returncode=-1)
                process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=console, stderr=subprocess.STDOUT)
                active.add(process)
            try:
                returncode = process.wait()
            except BaseException:
                process.kill()
                process.wait()
                raise
            finally:
                with active_lock:
                    active.discard(process)
        path = output_root / "episodes" / run_id / "result.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
        else:
            row = dict(condition=job["condition"], evaluation_valid=False,
                       run_status="INFRA_ERROR", error="Episode result unavailable; inspect console.log")
        row["process_returncode"] = returncode
        return job, row

    rows = []
    with ThreadPoolExecutor(max_workers=args.parallelism) as pool:
        futures = {pool.submit(run_one, job): job for job in jobs}
        try:
            for future in as_completed(futures):
                job = futures[future]
                try:
                    _, row = future.result()
                except Exception as exc:
                    row = dict(condition=job["condition"], evaluation_valid=False, run_status="INFRA_ERROR",
                               error=repr(exc), process_returncode=-1)
                rows.append(row)
                print(f"[{len(rows)}/8] {job['run_id']} {row.get('run_status')} "
                      f"utility={row.get('task_success')} attack={row.get('attack_success')}", flush=True)
                progress = dict(complete=len(rows), total=8, outcomes=[
                    {k: r.get(k) for k in ("run_id", "condition", "run_status", "evaluation_valid",
                                          "task_success", "attack_success", "tokens", "latency_s")}
                    for r in rows])
                (output_root / "progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
        except KeyboardInterrupt:
            print("Stopping this launch's episode processes; completed evidence is retained.", flush=True)
            stop.set()
            for future in futures:
                future.cancel()
            with active_lock:
                for process in list(active):
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                    else:
                        process.kill()
    summary = {**summarize(rows), "phase": "acceptance_pilot", "formal_e2_row_complete": False,
               "protocol": manifest["protocol"], "mock": args.smoke,
               "planned_episodes": 8, "interrupted": stop.is_set(),
               "request_errors": sum(r.get("llm_error_request_count", 0) for r in rows)}
    (output_root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"DONE: {output_root / 'summary.json'}", flush=True)
    accepted = all(r.get("process_returncode") == 0 and
                   (args.smoke or r.get("evaluation_valid") is True) for r in rows)
    return 130 if stop.is_set() else 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
