"""Run the frozen 24 worker replays. --preflight never calls a model."""
from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import os
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from context_replay_lib import (PROTOCOL, SOURCE, build_fixtures, digest, load, run_worker,
                                save, source_fingerprint, summarize)


def frozen_plan():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    fixtures = build_fixtures()
    jobs = []
    rng = random.Random(42)
    for repeat in range(1, 4):
        wave = [dict(id=f"{actor}_M{m}T{t}_r{repeat}", actor=actor, M=m, T=t, repeat=repeat)
                for actor in fixtures for m in (0, 1) for t in (0, 1)]
        rng.shuffle(wave)
        jobs += wave
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    url = urlparse(base_url)
    if url.scheme != "https" or url.hostname != "api.deepseek.com" or url.username or url.password:
        raise ValueError("This replay's monetary guard requires the official HTTPS DeepSeek endpoint")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    from agentdojo_manta.budget import RequestBudget
    if model not in RequestBudget.MODELS:
        raise ValueError("Use a model supported by the existing DeepSeek Flash budget guard")
    plan = dict(protocol=PROTOCOL, source_path=str(SOURCE), source_result_sha256=digest(load(SOURCE)),
                code_sha256=source_fingerprint(), model=model, base_url=base_url, jobs=jobs,
                fixture_sha256={k: digest(v) for k, v in fixtures.items()},
                temperature=0.0, max_tool_iterations=8, max_provider_requests_per_worker=36,
                output_tokens_per_request=4096, request_timeout_s=180,
                repetitions=3, ordering_seed=42, endpoint_seed_supported=False,
                runtime=dict(python=sys.version, dependencies={name: importlib.metadata.version(name)
                             for name in ("openai", "pydantic", "langgraph", "python-dotenv")}),
                runtime_env_policy="Remove inherited MAS_/MANTA_/OPENROUTER_ overrides; use native defaults",
                pricing=dict(input_nanodollars_per_token=RequestBudget.INPUT_RATE,
                             output_nanodollars_per_token=RequestBudget.OUTPUT_RATE,
                             max_input_reservation_tokens=RequestBudget.MAX_INPUT,
                             source="Existing budget.py conservative rates pinned 2026-10-18; not invoice cost"),
                scope="Local worker replays; no topology intervention or full-run checkpoint claim")
    return plan, fixtures


@contextmanager
def launch_lock(path):
    handle = path.open("a+b")
    try:
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        handle.close()


def process_alive(pid):
    if os.name == "nt":
        result = subprocess.check_output(["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
                                         text=True, errors="replace")
        return any(len(row) > 1 and row[1] == str(pid) for row in csv.reader(result.splitlines()))
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def invalid_result(job, error):
    return dict(protocol=PROTOCOL, job=job, evaluation_valid=False, run_status="INCOMPLETE",
                error=error, observed_target_reached=None, downstream_target_reached=None)


def run_child(args):
    plan = load(args.run_dir / "manifest.json")
    if plan["protocol"] != PROTOCOL or plan["code_sha256"] != source_fingerprint():
        raise ValueError("Frozen code differs")
    job = next(j for j in plan["jobs"] if j["id"] == args.child)
    fixture = load(args.run_dir / "fixtures" / f"{job['actor']}.json")
    if digest(fixture) != plan["fixture_sha256"][job["actor"]]:
        raise ValueError("Frozen fixture changed")
    attempt = args.run_dir / "attempts" / job["id"] / f"attempt_{args.attempt:03d}"
    if (attempt / "result.json").exists():
        raise ValueError("Refusing to overwrite a previous result")
    # Parent builds a clean environment for child processes, including a separate DB.
    if (not os.getenv("V1_BUDGET_DB") or not os.getenv("DEEPSEEK_API_KEY")
            or Path(os.environ["V1_BUDGET_DB"]).resolve() != args.run_dir / "budget.sqlite"
            or os.getenv("DEEPSEEK_BASE_URL") != plan["base_url"]
            or os.getenv("DEEPSEEK_MODEL") != plan["model"]):
        raise ValueError("Child requires the guarded launcher and existing API key")
    try:
        row = run_worker(fixture, job, plan["model"], attempt,
                         max_requests=plan["max_provider_requests_per_worker"])
    except Exception as exc:
        row = invalid_result(job, f"{type(exc).__name__}: {exc}")
        save(attempt / "result.json", row)
    return 0 if row["evaluation_valid"] else 1


def execute(args, plan):
    from agentdojo_manta.budget import RequestBudget
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise ValueError("DEEPSEEK_API_KEY missing; reuse the existing environment or repo .env")
    budget = RequestBudget(args.run_dir / "budget.sqlite", args.budget_usd)
    pid_path = args.run_dir / "active_pids.json"
    if pid_path.exists() and any(process_alive(p) for p in load(pid_path)):
        raise ValueError("A previous child is still alive; do not launch concurrently")
    with budget.connect() as db:
        db.execute("UPDATE requests SET state='uncertain' WHERE state='pending'")
        db.execute("UPDATE settings SET value='0' WHERE key='blocked'")
    # Budget reservation uses full maximum input, so four simultaneous reservations
    # need > $1.27 even when actual requests are short. The cap is an accounting cap.
    print(f"Guarded live replay: cap=${args.budget_usd}; parallelism={args.parallelism}; 24 jobs", flush=True)
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("MAS_", "MANTA_", "OPENROUTER_")):
            env.pop(key)
    env.update(MAS_REQUIRE_LIVE_LLM="1", DEEPSEEK_MODEL=plan["model"], DEEPSEEK_BASE_URL=plan["base_url"],
               V1_BUDGET_DB=str(args.run_dir / "budget.sqlite"), V1_MAX_COST_USD=args.budget_usd,
               V1_LLM_TIMEOUT_S=str(plan["request_timeout_s"]), PYTHONIOENCODING="utf-8")
    active, mutex, stop, rows = set(), threading.Lock(), threading.Event(), {}
    with (args.run_dir / "launch_history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(dict(time=time.time(), parallelism=args.parallelism,
                                budget_cap_usd=args.budget_usd, retry_incomplete=args.retry_incomplete,
                                worker_timeout_s=args.worker_timeout)) + "\n")

    def run_one(job):
        directory = args.run_dir / "attempts" / job["id"]
        directory.mkdir(parents=True, exist_ok=True)
        previous = sorted(directory.glob("attempt_*"))
        last = None
        for p in previous:
            if (p / "result.json").exists():
                last = load(p / "result.json")
                if last.get("job") != job or last.get("protocol") != PROTOCOL:
                    raise ValueError("Saved result identity differs from frozen job")
                if last.get("engineering_fixture"):
                    raise ValueError("Engineering fixtures cannot be resumed as live results")
                if last["evaluation_valid"]:
                    return last
        if previous and not args.retry_incomplete:
            return last or invalid_result(job, "Unfinished earlier attempt; use --retry-incomplete after inspection")
        if len(previous) >= 3:
            return last or invalid_result(job, "Three-attempt limit reached; evidence retained")
        if stop.is_set() or budget.snapshot()["blocked"]:
            return invalid_result(job, "Budget/launcher stopped before this job")
        index = len(previous) + 1
        attempt = directory / f"attempt_{index:03d}"
        attempt.mkdir()
        command = [sys.executable, "-u", str(Path(__file__).resolve()), "--run-dir", str(args.run_dir),
                   "--child", job["id"], "--attempt", str(index)]
        with (attempt / "console.log").open("w", encoding="utf-8") as console:
            with mutex:
                if stop.is_set():
                    return invalid_result(job, "Interrupted before launch")
                process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=console, stderr=subprocess.STDOUT)
                active.add(process)
                save(pid_path, sorted(p.pid for p in active))
            try:
                process.wait(timeout=args.worker_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            finally:
                with mutex:
                    active.discard(process)
                    save(pid_path, sorted(p.pid for p in active))
        result_path = attempt / "result.json"
        if result_path.exists():
            return load(result_path)
        row = invalid_result(job, "Child failed, timed out or was interrupted; see console/provider inputs")
        save(result_path, row)
        return row

    def record():
        summary = summarize(list(rows.values()), plan["jobs"])
        summary["budget"] = budget.snapshot()
        save(args.run_dir / "summary.json", summary)
        save(args.run_dir / "progress.json", {k: summary[k] for k in ("processed", "planned", "valid", "complete", "budget")})
        with (args.run_dir / "groups.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary["groups"][0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(summary["groups"])
        return summary

    pool = ThreadPoolExecutor(max_workers=args.parallelism)
    futures = []
    try:
        for wave in ([j for j in plan["jobs"] if j["repeat"] == 1],
                     [j for j in plan["jobs"] if j["repeat"] > 1]):
            futures = {pool.submit(run_one, job): job for job in wave}
            for future in as_completed(futures):
                try:
                    row = future.result()
                except Exception as exc:
                    row = invalid_result(futures[future], f"Launcher error: {type(exc).__name__}: {exc}")
                rows[row["job"]["id"]] = row
                print(f"[{len(rows)}/24] {row['job']['id']} {row['run_status']} "
                      f"new_target={row.get('downstream_target_reached')}", flush=True)
                record()
            if any(not rows[j["id"]]["evaluation_valid"] for j in wave):
                print("Wave incomplete: remaining repeats are paused. Inspect errors; no safe-negative inference.", flush=True)
                break
    except KeyboardInterrupt:
        stop.set()
        for future in futures:
            future.cancel()
        with mutex:
            for process in list(active):
                process.kill()
        print("Interrupted; completed results retained. Same command resumes valid jobs.", flush=True)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    summary = record()
    print(f"{'COMPLETE' if summary['complete'] else 'INCOMPLETE'}: {args.run_dir / 'summary.json'}", flush=True)
    return 0 if summary["complete"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=ROOT / "results/v1/context_replay_slack07_MxT")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--parallelism", type=int, default=4)
    parser.add_argument("--budget-usd", default="3")
    parser.add_argument("--retry-incomplete", action="store_true")
    parser.add_argument("--worker-timeout", type=int, default=1200)
    parser.add_argument("--child", help=argparse.SUPPRESS)
    parser.add_argument("--attempt", type=int, default=1, help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.run_dir = args.run_dir.resolve()
    try:
        if args.child:
            return run_child(args)
        if not 1 <= args.parallelism <= 8 or args.worker_timeout < 60:
            parser.error("parallelism must be 1..8 and worker-timeout >= 60 seconds")
        if args.run_dir == SOURCE.parent or args.run_dir in SOURCE.parents:
            parser.error("Run directory must not contain the original formal evidence")
        args.run_dir.mkdir(parents=True, exist_ok=True)
        with launch_lock(args.run_dir / "launch.lock"):
            plan, fixtures = frozen_plan()
            manifest = args.run_dir / "manifest.json"
            if manifest.exists():
                if load(manifest) != plan:
                    raise ValueError("Frozen code/source/config differs; preserve this run and select a new --run-dir")
                for actor, fixture in fixtures.items():
                    if load(args.run_dir / "fixtures" / f"{actor}.json") != fixture:
                        raise ValueError("Frozen fixture was edited; refusing to overwrite")
            else:
                if (args.run_dir / "attempts").exists():
                    raise ValueError("Attempts exist without manifest; refusing to adopt them")
                (args.run_dir / "fixtures").mkdir(exist_ok=True)
                for actor, fixture in fixtures.items():
                    save(args.run_dir / "fixtures" / f"{actor}.json", fixture)
                save(manifest, plan)
            print(f"RUN_DIR={args.run_dir}", flush=True)
            print("PRECHECK_OK: 2 workers x 4 conditions x 3 repeats; prefix, schemas and inputs verified.", flush=True)
            if args.preflight:
                print("Zero model requests. Fixtures and condition diffs saved.", flush=True)
                return 0
            return execute(args, plan)
    except (ValueError, OSError, StopIteration) as exc:
        print(f"STOPPED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
