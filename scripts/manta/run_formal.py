"""Frozen 80-scenario MANTA x AgentDojo queue with paired controls and resume."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def fingerprint():
    digest = hashlib.sha256()
    for base in (ROOT / "src", ROOT / "scripts" / "manta", ROOT / "upstreams" / "manta"):
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".json", ".md"}:
                digest.update(str(path.relative_to(ROOT)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def freeze_plan(model):
    from agentdojo.task_suite.load_suites import get_suites
    from agentdojo.attacks.attack_registry import load_attack
    config = dict(benchmark_version="v1.2.2", model=model, num_agents=3,
                  max_turns=2, repair_budget=1, planner_mode="task_conditioned",
                  audit_mode="heuristic", seed=42)
    jobs, scenes, reserved = [], [], []
    for name, suite in sorted(get_suites(config["benchmark_version"]).items()):
        rng = random.Random(f"42:{name}")
        tasks, injections = sorted(suite.user_tasks), sorted(suite.injection_tasks)
        rng.shuffle(tasks)
        rng.shuffle(injections)
        reserved.extend(dict(suite=name, task_id=task) for task in tasks[20:])
        # Balance user tasks first and rotate official targets. Banking has 16
        # user tasks, so four are reused with different targets; controls remain
        # paired per scenario. These are 80 scenarios, not 80 unique user tasks.
        attack = load_attack("direct", suite, None)
        for index in range(20):
            task_id, injection_id = tasks[index % len(tasks)], injections[index % len(injections)]
            task, goal = suite.user_tasks[task_id], suite.injection_tasks[injection_id]
            payload = attack.attack(task, goal)
            if not payload or not any(payload.values()):
                raise ValueError(f"Empty official attack: {name}/{task_id}/{injection_id}")
            scene_id = f"{name}_{index:02d}"
            scene = dict(scene_id=scene_id, suite=name, task_id=task_id, injection_task=injection_id,
                         payload_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
            scenes.append(scene)
            for condition in ("clean", "attack"):
                jobs.append(dict(**scene, condition=condition, run_id=f"{scene_id}__{condition}"))
    assert len({(s['suite'], s['task_id'], s['injection_task']) for s in scenes}) == 80
    return dict(protocol="manta-agentdojo-formal-80-v1", config=config, scenes=scenes, jobs=jobs,
                reserved_user_tasks=reserved,
                runtime_env={k: v for k, v in sorted(os.environ.items())
                             if k.startswith(("MAS_", "MANTA_", "OPENROUTER_"))
                             and not k.endswith(("_KEY", "_ACCESS_TOKEN", "_SECRET", "_PASSWORD"))},
                planner_model=os.getenv("DEEPSEEK_PLANNER_MODEL", model),
                auditor_model=os.getenv("DEEPSEEK_AUDITOR_MODEL", model),
                sampling="seed42;20 scenes/suite; shuffled user tasks and rotated official injection targets",
                statistical_unit="scenario; paired controls; repeated banking user tasks are not independent tasks",
                unique_user_tasks=len({(s['suite'], s['task_id']) for s in scenes}),
                adaptive_limits=dict(max_initial_agents=5, max_total_agents=10),
                source_sha256=fingerprint(), pricing_source="https://api-docs.deepseek.com/quick_start/pricing/",
                budget_accounting="peak rates; cache discounts ignored; full-context request reservations; not invoice cost")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parallelism", type=int, default=None)
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--provider", choices=["deepseek", "openai", "qdd"], default=None)
    parser.add_argument("--pilot", action="store_true", help="Four frozen scenes, clean/attack pairs; real API, $10 cap")
    parser.add_argument("--pilot-dir", type=Path, default=ROOT / "results/v1/pilot_4_seed42_gpt4o")
    parser.add_argument("--skip-pilot-check", action="store_true",
                        help="Operator explicitly waives remaining pilot validation; recorded in the formal manifest")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--limit", type=int, help="Smoke-only episode limit")
    parser.add_argument("--max-attempts", type=int, default=2)
    args = parser.parse_args()
    if args.parallelism is None:
        args.parallelism = 1 if args.pilot else 8
    if args.pilot and args.parallelism > 2:
        parser.error("Initial GPT-4o pilot parallelism must be 1 or 2")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    if args.provider:
        os.environ["MANTA_PROVIDER"] = args.provider
    provider = os.getenv("MANTA_PROVIDER", "deepseek")
    gpt4o = provider != "deepseek"
    if args.pilot and (not gpt4o or args.smoke):
        parser.error("--pilot requires a real GPT-4o provider; mock pilot is forbidden")
    if args.run_dir is None:
        args.run_dir = (args.pilot_dir if args.pilot else ROOT / "results/v1/formal_80_seed42_gpt4o") if gpt4o else ROOT / "results/v1/formal_80_seed42"
    from agentdojo_manta.adapter import AdapterPaths, _import_manta
    from agentdojo_manta.budget import RequestBudget, GPT4oBudget
    from agentdojo_manta.metrics import summarize
    if not 1 <= args.parallelism <= 8 or args.max_attempts < 1:
        parser.error("parallelism must be 1..8; max-attempts must be positive")
    if args.limit and (not args.smoke or args.limit < 1):
        parser.error("--limit is positive and smoke-only")
    if args.smoke and args.run_dir.resolve() == (ROOT / "results" / "v1" / "formal_80_seed42").resolve():
        parser.error("Smoke requires a separate --run-dir")
    _import_manta(AdapterPaths.from_repo(ROOT))
    if gpt4o:
        from agentdojo_manta.providers import provider_config
        from agentdojo_manta.replication import load_replication_plan
        binding = provider_config("gpt-4o")
        # The published baseline contains no environment overrides. Prevent accidental
        # inherited settings from changing its engine, sampling, tool memory or roles.
        forbidden = [k for k in os.environ if k.startswith(("MAS_", "MANTA_", "OPENROUTER_")) and k != "MANTA_PROVIDER"]
        if forbidden:
            parser.error(f"Remove unverified inherited runtime overrides: {', '.join(sorted(forbidden))}")
        manifest = load_replication_plan(ROOT, provider=provider, source_digest=fingerprint(), pilot=args.pilot)
        manifest["pilot_validation"] = "waived_by_operator" if args.skip_pilot_check else "required"
        manifest["pricing_multiplier"] = os.getenv("GPT4O_PRICE_MULTIPLIER", "1")
        if provider == "qdd" and os.getenv("GPT4O_PRICING_EVIDENCE"):
            manifest["pricing_evidence_sha256"] = hashlib.sha256(Path(os.environ["GPT4O_PRICING_EVIDENCE"]).read_bytes()).hexdigest()
    else:
        manifest = freeze_plan(os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    manifest["mock"] = args.smoke
    if args.limit:
        jobs = manifest["jobs"]
        manifest["jobs"] = [jobs[offset + index] for index in range(40)
                            for offset in range(0, 160, 40)][:args.limit]
    run_dir = args.run_dir.resolve()
    if gpt4o and run_dir == (ROOT / "results/v1/formal_80_seed42").resolve():
        parser.error("GPT-4o must never write to the original DeepSeek result directory")
    if gpt4o and args.smoke and run_dir in {(ROOT / "results/v1/formal_80_seed42_gpt4o").resolve(), args.pilot_dir.resolve()}:
        parser.error("Mock smoke requires its own result directory")
    run_dir.mkdir(parents=True, exist_ok=True)
    # Cross-process launch lock. Windows releases the byte lock on process exit.
    lockfile = (run_dir / "launch.lock").open("a+b")
    lockfile.write(b"0")
    lockfile.flush()
    lockfile.seek(0)
    if os.name == "nt":
        import msvcrt
        try:
            msvcrt.locking(lockfile.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            parser.error("This queue already has a running launcher")
    else:
        import fcntl
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        frozen = json.loads(manifest_path.read_text(encoding="utf-8"))
        if frozen != manifest:
            if any((run_dir / "attempts").glob("*/*")):
                parser.error("Frozen source/config differs; preserve this run and use a new --run-dir")
            manifest_path.rename(run_dir / f"manifest.preflight.{uuid.uuid4().hex[:8]}.json")
            write_json(manifest_path, manifest)
    else:
        write_json(manifest_path, manifest)
    print(f"RUN_DIR={run_dir}", flush=True)
    print(f"Frozen: {len(manifest['scenes'])} attack scenarios, {manifest['unique_user_tasks']} original unique user tasks, "
          f"{len(manifest['jobs'])} paired episodes; parallelism={args.parallelism}.", flush=True)
    if args.dry_run:
        print("PRECHECK_OK: frozen queue saved; zero API requests.", flush=True)
        return 0
    pid_path = run_dir / "active_pids.json"
    if os.name == "nt" and pid_path.exists():
        for pid in json.loads(pid_path.read_text(encoding="utf-8")):
            listing = subprocess.check_output(["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
                                              text=True, errors="replace")
            if f'","{int(pid)}","' in listing:
                parser.error(f"Previous child PID {pid} is still alive; do not resume concurrently")
    budget = None
    if not args.smoke:
        if gpt4o:
            if not binding.api_key:
                parser.error("OPENAI_API_KEY missing")
            if args.pilot:
                os.environ["GPT4O_MAX_COST_USD"] = "10"
            else:
                if not os.getenv("GPT4O_MAX_COST_USD"):
                    parser.error("Explicit cumulative GPT4O_MAX_COST_USD required before formal launch")
                if not args.skip_pilot_check:
                    acceptance_path = args.pilot_dir / "pilot_acceptance.json"
                    if not acceptance_path.exists():
                        parser.error("An accepted real GPT-4o pilot is required, or explicitly use --skip-pilot-check")
                    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
                    if not acceptance.get("accepted") or any(acceptance.get(k) != manifest.get(k) for k in ("source_sha256", "provider", "original_manifest_sha256")):
                        parser.error("Pilot acceptance failed or source/provider/scenes have changed")
                else:
                    connectivity_path = ROOT / "results/v1/gpt4o_preflight/connectivity.json"
                    connectivity = json.loads(connectivity_path.read_text(encoding="utf-8"))
                    if connectivity.get("status") != "completed" or connectivity.get("requested_model") != "gpt-4o" or connectivity.get("endpoint") != binding.base_url:
                        parser.error("A successful real GPT-4o connectivity check for this endpoint is required")
                    print("Operator waived remaining pilot validation; recorded in manifest.", flush=True)
            budget = GPT4oBudget(run_dir / "budget.sqlite", os.environ["GPT4O_MAX_COST_USD"])
        elif not os.getenv("DEEPSEEK_API_KEY"):
            parser.error("DEEPSEEK_API_KEY missing; existing environment/.env is reused")
        if not gpt4o and not os.getenv("V1_MAX_COST_USD"):
            parser.error("Task book requires explicit V1_MAX_COST_USD before the paid formal run")
        if not gpt4o and any(model not in RequestBudget.MODELS for model in
               (manifest["config"]["model"], manifest["planner_model"], manifest["auditor_model"])):
            parser.error("Verified monetary guard supports the DeepSeek Flash model family only")
        if not gpt4o:
            budget = RequestBudget(run_dir / "budget.sqlite", os.environ["V1_MAX_COST_USD"])
        with budget.connect() as db:
            # Previous launcher may have lost a response. Retain the reservation.
            db.execute("UPDATE requests SET state='uncertain' WHERE state='pending'")
            db.execute("UPDATE settings SET value='0' WHERE key='blocked'")
        print(f"Budget cap ${budget.snapshot()['cap_usd']}; conservative request accounting.", flush=True)
    active, active_lock, stop = set(), threading.Lock(), threading.Event()

    def run_one(job):
        job_dir = run_dir / "attempts" / job["run_id"]
        job_dir.mkdir(parents=True, exist_ok=True)
        attempts = sorted(job_dir.glob("attempt_*"))
        for attempt in attempts:
            path = attempt / "result.json"
            if path.exists():
                saved = attempt / "queue_result.json"
                row = json.loads((saved if saved.exists() else path).read_text(encoding="utf-8"))
                if row.get("evaluation_valid") is True or (args.smoke and row.get("mock_used")):
                    row.update(queue_run_id=job["run_id"], scene_id=job["scene_id"])
                    return row
        row = dict(run_id=job["run_id"], condition=job["condition"], suite=job["suite"],
                   evaluation_valid=False, run_status="BLOCKED", error="Attempt limit or budget; evidence retained")
        if attempts and (attempts[-1] / "queue_result.json").exists():
            row = json.loads((attempts[-1] / "queue_result.json").read_text(encoding="utf-8"))
        for index in range(len(attempts) + 1, args.max_attempts + 1):
            if stop.is_set() or (budget and budget.snapshot()["blocked"]):
                break
            attempt = job_dir / f"attempt_{index:03d}"
            attempt.mkdir()
            command = [sys.executable, "-u", str(ROOT / "scripts" / "manta" / "run_agentdojo_manta.py"),
                       "--suite", job["suite"], "--user-task", job["task_id"],
                       "--run-id", attempt.name, "--output-dir", str(job_dir),
                       "--logdir", str(run_dir / "logs" / job["run_id"])]
            for key, value in manifest["config"].items():
                command.extend(["--" + key.replace("_", "-"), str(value)])
            if job["condition"] == "clean":
                command.append("--clean")
            else:
                command.extend(["--attack", "direct", "--injection-task", job["injection_task"]])
            if args.smoke:
                command.append("--allow-mock")
            env = os.environ.copy()
            env.update(MANTA_MAX_INITIAL_AGENTS="5", MANTA_MAX_TOTAL_AGENTS="10",
                       V1_LLM_TIMEOUT_S="180", PYTHONIOENCODING="utf-8")
            if budget:
                if gpt4o:
                    env["GPT4O_BUDGET_DB"] = budget.path
                    env["GPT4O_REQUEST_JOURNAL"] = str(attempt / "requests.jsonl")
                    env.pop("V1_BUDGET_DB", None)
                else:
                    env["V1_BUDGET_DB"] = budget.path
            else:
                env.pop("V1_BUDGET_DB", None)
            with (attempt / "console.log").open("w", encoding="utf-8") as console:
                with active_lock:
                    if stop.is_set():
                        break
                    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=console, stderr=subprocess.STDOUT)
                    active.add(process)
                    write_json(pid_path, sorted(p.pid for p in active))
                try:
                    returncode = process.wait()
                finally:
                    with active_lock:
                        active.discard(process)
                        write_json(pid_path, sorted(p.pid for p in active))
            path = attempt / "result.json"
            if path.exists():
                row = json.loads(path.read_text(encoding="utf-8"))
                row["process_returncode"] = returncode
            else:
                row = dict(run_id=job["run_id"], condition=job["condition"], suite=job["suite"],
                           evaluation_valid=False, run_status="INFRA_ERROR", error="See console.log")
            row["queue_run_id"] = job["run_id"]
            row["scene_id"] = job["scene_id"]
            write_json(attempt / "queue_result.json", row)
            if gpt4o and any(r.get("http_status") in (400, 401, 403, 404) or r.get("error_type") == "ValueError" for r in row.get("llm_requests", [])):
                stop.set()
            if row.get("evaluation_valid") is True or args.smoke or row.get("run_status") == "BLOCKED":
                break
        return row

    rows = []
    with ThreadPoolExecutor(max_workers=args.parallelism) as pool:
        futures = {pool.submit(run_one, job): job for job in manifest["jobs"]}
        try:
            for future in as_completed(futures):
                job = futures[future]
                try:
                    row = future.result()
                except Exception as exc:
                    row = dict(run_id=job["run_id"], condition=job["condition"], suite=job["suite"],
                               evaluation_valid=False, run_status="INFRA_ERROR", error=repr(exc))
                rows.append(row)
                print(f"[{len(rows)}/{len(futures)}] {job['run_id']} {row.get('run_status')}", flush=True)
                write_json(run_dir / "progress.json", dict(processed=len(rows), planned=len(futures),
                           valid=sum(r.get("evaluation_valid") is True for r in rows),
                           budget=budget.snapshot() if budget else None))
        except KeyboardInterrupt:
            stop.set()
            for future in futures:
                future.cancel()
            with active_lock:
                for process in list(active):
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                    else:
                        process.kill()
            print("Interrupted: completed evidence retained; same command resumes.", flush=True)
    complete = len(rows) == len(manifest["jobs"]) and all(r.get("evaluation_valid") is True for r in rows)
    summary = dict(**summarize(rows), formal_e2_row_complete=complete and not args.smoke,
                   planned_episodes=len(manifest["jobs"]), mock=args.smoke,
                   by_suite={s: summarize([r for r in rows if r.get("suite") == s])
                             for s in ("workspace", "travel", "banking", "slack")},
                   budget=budget.snapshot() if budget else None)
    write_json(run_dir / "summary.json", summary)
    if gpt4o and args.pilot and not args.smoke:
        from agentdojo_manta.replication import check_pilot
        acceptance = check_pilot(run_dir, manifest, summary["budget"])
        write_json(run_dir / "pilot_acceptance.json", acceptance)
        print(f"PILOT_ACCEPTED={acceptance['accepted']}", flush=True)
    print(f"{'COMPLETE' if complete else 'INCOMPLETE'}: {run_dir / 'summary.json'}", flush=True)
    smoke_ok = args.smoke and len(rows) == len(manifest["jobs"]) and all(
        r.get("mock_used") is True and r.get("process_returncode") == 0 for r in rows)
    return 130 if stop.is_set() else 0 if complete or smoke_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
