"""Live checkpoint capture, then paired native graph continuations. Preflight is free."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from context_replay_lib import digest, load, save
from run_context_replay import launch_lock, process_alive
from graph_experiment_lib import PROTOCOL, boot, branch, candidate_pool, capture, fingerprint


def plan_for(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    boot()
    from graph_checkpoint import Codec, native_parts, compile_capture, compile_resume
    from graph_experiment_lib import new_config, fresh_environment, processed_toolset, raw_toolset
    from context_replay_lib import Observation
    from agentdojo_manta.budget import RequestBudget
    native_parts()
    compile_capture()
    compile_resume(["state", "max_turns", "turn_index"])
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    parsed = urlparse(url)
    if model not in RequestBudget.MODELS or parsed.scheme != "https" or parsed.hostname != "api.deepseek.com" or parsed.username:
        raise ValueError("Verified budget requires the official DeepSeek HTTPS endpoint and Flash model")
    candidates = candidate_pool(args.candidates)
    for c in candidates:
        _, task, _, _, runtime, env = fresh_environment(c)
        processed_toolset(raw_toolset(runtime, env, Observation()), task.PROMPT)
        codec = Codec({})
        encoded = codec.encode(env)
        if codec.encode(codec.decode(encoded)) != encoded:
            raise ValueError("Candidate domain model cannot be restored exactly")
    config, spec = new_config()
    import dataclasses
    return dict(protocol=PROTOCOL, code_sha256=fingerprint(), candidates=candidates,
        max_states=args.states, repeats=3, model=model, base_url=url,
        se_config=dataclasses.asdict(config), experiment_spec=dataclasses.asdict(spec), seed=42,
        runtime=dict(python=sys.version, dependencies={n: importlib.metadata.version(n)
                     for n in ("openai", "pydantic", "langgraph", "numpy")}),
        intervention="First eligible group, root first then group_id; chain->star, all other supported patterns->chain",
        eligibility="Actual native next-turn boundary; exact completed-request exposure; official goal false; valid graph switch",
        sample_scope="Runtime-evolved checkpoints only; not the earlier proposed mixed mutation/nonmutation sample",
        capture_window="Before native executor.run_turn at turn_index=1; no prefix replay during restore",
        max_provider_requests_per_job=120, request_timeout_s=180,
        pricing=dict(input_nanodollars_per_token=RequestBudget.INPUT_RATE,
                     output_nanodollars_per_token=RequestBudget.OUTPUT_RATE,
                     note="Pinned existing conservative rates, not actual invoice"))


def invalid(job, message):
    return dict(protocol=PROTOCOL, job=job, run_status="INCOMPLETE", evaluation_valid=False,
                error=message, observed_attack_success=None, attack_success=None, task_success=None)


def child(args):
    plan = load(args.run_dir / "manifest.json")
    if plan["code_sha256"] != fingerprint():
        raise ValueError("Source changed after plan freeze")
    if (not os.getenv("DEEPSEEK_API_KEY") or
        Path(os.getenv("V1_BUDGET_DB", "")).resolve() != args.run_dir / "budget.sqlite" or
        os.getenv("DEEPSEEK_BASE_URL") != plan["base_url"]):
        raise ValueError("Child must use this launcher's credentials, endpoint and budget")
    if args.phase == "capture":
        job = next(c for c in plan["candidates"] if c["id"] == args.child)
    else:
        job = next(j for j in load(args.run_dir / "branches_manifest.json")["jobs"] if j["id"] == args.child)
    attempt = args.run_dir / args.phase / job["id"] / f"attempt_{args.attempt:03d}"
    if (attempt / "result.json").exists():
        raise ValueError("Refusing to overwrite result")
    try:
        if args.phase == "capture":
            row = capture(job, plan["model"], attempt)
        else:
            bundle = load(args.run_dir / job["checkpoint_path"])
            if bundle["checkpoint_sha256"] != job["checkpoint_sha256"]:
                raise ValueError("Branch checkpoint differs from frozen pairing")
            row = branch(bundle, job, plan["model"], attempt)
    except Exception as exc:
        row = invalid(job, f"{type(exc).__name__}: {exc}")
        row["run_status"] = "CAPTURE_ERROR" if args.phase == "capture" else "INCOMPLETE"
        save(attempt / "result.json", row)
    return 0 if row["run_status"] in {"CHECKPOINT_READY", "NO_ELIGIBLE", "VALID_BRANCH"} else 1


def branch_jobs(selected):
    jobs, rng = [], random.Random(42)
    for repeat in range(1, 4):
        wave = [dict(id=f"{s['id']}__{condition}_r{repeat}", state_id=s["id"], condition=condition,
                     repeat=repeat, checkpoint_path=s["checkpoint_path"], checkpoint_sha256=s["checkpoint_sha256"])
                for s in selected for condition in ("G0", "G1")]
        rng.shuffle(wave)
        jobs.extend(wave)
    return jobs


def summarize_branches(rows, selected):
    conditions = []
    for condition in ("G0", "G1"):
        group = [r for r in rows if r["job"]["condition"] == condition]
        valid = [r for r in group if r["evaluation_valid"]]
        conditions.append(dict(condition=condition, valid_n=len(valid), attack_n=sum(r["attack_success"] for r in valid),
            task_n=sum(r["task_success"] for r in valid), incomplete_n=len(group)-len(valid)))
    pairs, graph_checks = [], []
    for s in selected:
        for repeat in range(1, 4):
            g = {r["job"]["condition"]: r for r in rows if r["job"]["state_id"] == s["id"] and r["job"]["repeat"] == repeat}
            if set(g) != {"G0", "G1"}:
                continue
            identical = g["G0"].get("checkpoint_sha256") == g["G1"].get("checkpoint_sha256") == s["checkpoint_sha256"]
            different = bool(g["G0"].get("execution_signature")) and bool(g["G1"].get("execution_signature")) and (
                g["G0"]["execution_signature"] != g["G1"]["execution_signature"])
            graph_checks.append(dict(state_id=s["id"], repeat=repeat, same_checkpoint=identical, different_execution=different))
            if identical and different and all(v["evaluation_valid"] for v in g.values()):
                pairs.append(dict(state_id=s["id"], repeat=repeat,
                    G0_attack=g["G0"]["attack_success"], G1_attack=g["G1"]["attack_success"],
                    G0_task=g["G0"]["task_success"], G1_task=g["G1"]["task_success"]))
    return dict(protocol=PROTOCOL, eligible_states=len(selected), planned_branches=len(selected)*6,
        processed=len(rows), valid=sum(r["evaluation_valid"] for r in rows), conditions=conditions,
        paired_results=pairs, graph_execution_checks=graph_checks,
        complete=bool(selected) and len(rows)==len(selected)*6 and len(pairs)==len(selected)*3,
        interpretation="Conditional on eligible evolved states; one predefined native group-pattern intervention, not all graph defenses")


def execute(args, plan):
    from agentdojo_manta.budget import RequestBudget
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise ValueError("DEEPSEEK_API_KEY missing; reuse the Windows user environment")
    pids = args.run_dir / "active_pids.json"
    if pids.exists() and any(process_alive(pid) for pid in load(pids)):
        raise ValueError("A previous child is still running")
    budget = RequestBudget(args.run_dir / "budget.sqlite", args.budget_usd)
    with budget.connect() as db:
        db.execute("UPDATE requests SET state='uncertain' WHERE state='pending'")
        db.execute("UPDATE settings SET value='0' WHERE key='blocked'")
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("MAS_", "MANTA_", "OPENROUTER_")):
            env.pop(key)
    env.update(DEEPSEEK_MODEL=plan["model"], DEEPSEEK_PLANNER_MODEL=plan["model"],
               DEEPSEEK_AUDITOR_MODEL=plan["model"], DEEPSEEK_BASE_URL=plan["base_url"],
               MAS_REQUIRE_LIVE_LLM="1", V1_LLM_TIMEOUT_S="180", PYTHONIOENCODING="utf-8",
               V1_BUDGET_DB=str(args.run_dir/"budget.sqlite"), V1_MAX_COST_USD=args.budget_usd)
    mutex, active, stop = threading.Lock(), set(), threading.Event()
    with (args.run_dir / "launch_history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(dict(time=time.time(), budget=args.budget_usd, parallelism=args.parallelism,
                               retry=args.retry_incomplete, job_timeout=args.job_timeout)) + "\n")

    def run_one(phase, job):
        folder = args.run_dir / phase / job["id"]
        folder.mkdir(parents=True, exist_ok=True)
        attempts = sorted(folder.glob("attempt_*"))
        previous = None
        for p in attempts:
            if not (p / "result.json").exists():
                continue
            previous = load(p / "result.json")
            identity = previous.get("candidate") if phase == "capture" else previous.get("job")
            if previous.get("protocol") != PROTOCOL or (identity is not None and identity != job):
                raise ValueError("Saved result identity differs from frozen job")
            if previous.get("engineering_fixture"):
                raise ValueError("Engineering result cannot be resumed as live data")
            if previous.get("run_status") in {"CHECKPOINT_READY", "NO_ELIGIBLE", "VALID_BRANCH"}:
                return p, previous
        if attempts and (not args.retry_incomplete or len(attempts) >= 3):
            return attempts[-1], previous or invalid(job, "Inspect incomplete attempt before explicit retry")
        if stop.is_set() or budget.snapshot()["blocked"]:
            return folder, invalid(job, "Budget/interruption stopped job before launch")
        number = len(attempts) + 1
        out = folder / f"attempt_{number:03d}"
        out.mkdir()
        cmd = [sys.executable, "-u", str(Path(__file__).resolve()), "--run-dir", str(args.run_dir),
               "--child", job["id"], "--phase", phase, "--attempt", str(number)]
        with (out / "console.log").open("w", encoding="utf-8") as log:
            with mutex:
                if stop.is_set():
                    return out, invalid(job, "Interrupted before launch")
                process = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                active.add(process)
                save(pids, sorted(p.pid for p in active))
            try:
                process.wait(timeout=args.job_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            finally:
                with mutex:
                    active.discard(process)
                    save(pids, sorted(p.pid for p in active))
        if (out / "result.json").exists():
            return out, load(out / "result.json")
        row = invalid(job, "Child failed/interrupted/timed out; inspect console/provider logs")
        if phase == "capture":
            row["run_status"] = "CAPTURE_ERROR"
        save(out / "result.json", row)
        return out, row

    pool = ThreadPoolExecutor(max_workers=args.parallelism)
    try:
        futures = {pool.submit(run_one, "capture", c): c for c in plan["candidates"]}
        captures = {}
        for future in as_completed(futures):
            out, row = future.result()
            c = futures[future]
            captures[c["id"]] = (out, row)
            print(f"CAPTURE [{len(captures)}/{len(futures)}] {c['id']} {row['run_status']}", flush=True)
            save(args.run_dir / "progress.json", dict(phase="capture", processed=len(captures),
                 planned=len(futures), budget=budget.snapshot()))
        selected = []
        for c in plan["candidates"]:
            out, row = captures[c["id"]]
            if row["run_status"] == "CHECKPOINT_READY":
                bundle = load(out / "checkpoint.json")
                selected.append(dict(id=c["id"], checkpoint_path=(out/"checkpoint.json").relative_to(args.run_dir).as_posix(),
                                     checkpoint_sha256=bundle["checkpoint_sha256"]))
        selected = selected[:plan["max_states"]]
        save(args.run_dir / "capture_summary.json", dict(selected=selected,
             candidates=[dict(id=c["id"], result=captures[c["id"]][1]) for c in plan["candidates"]], budget=budget.snapshot()))
        if any(r[1]["run_status"] not in {"CHECKPOINT_READY", "NO_ELIGIBLE"} for r in captures.values()):
            save(args.run_dir / "progress.json", dict(phase="capture", status="CAPTURE_INCOMPLETE", complete=False,
                 selected_states=len(selected), budget=budget.snapshot()))
            print("CAPTURE_INCOMPLETE: inspect infrastructure errors before branches.", flush=True)
            return 1
        if not selected:
            save(args.run_dir / "progress.json", dict(phase="capture", status="NO_ELIGIBLE_STATES", complete=False,
                 selected_states=0, budget=budget.snapshot()))
            print("NO_ELIGIBLE_STATES: no paired inference; native controller/selection criteria preserved.", flush=True)
            return 1
        jobs = branch_jobs(selected)
        branch_plan = dict(selected=selected, jobs=jobs)
        frozen = args.run_dir / "branches_manifest.json"
        if frozen.exists() and load(frozen) != branch_plan:
            raise ValueError("Checkpoint selection differs from already frozen branches")
        if not frozen.exists():
            save(frozen, branch_plan)
        rows = {}
        for wave in ([j for j in jobs if j["repeat"] == 1], [j for j in jobs if j["repeat"] > 1]):
            futures = {pool.submit(run_one, "branch", j): j for j in wave}
            for future in as_completed(futures):
                _, row = future.result()
                rows[row["job"]["id"]] = row
                summary = summarize_branches(list(rows.values()), selected)
                summary["budget"] = budget.snapshot()
                save(args.run_dir / "summary.json", summary)
                save(args.run_dir / "progress.json", dict(phase="branch", processed=len(rows), planned=len(jobs),
                     valid=summary["valid"], complete=summary["complete"], budget=budget.snapshot()))
                print(f"BRANCH [{len(rows)}/{len(jobs)}] {row['job']['id']} {row['run_status']} "
                      f"attack={row.get('attack_success')} task={row.get('task_success')}", flush=True)
            summary = summarize_branches(list(rows.values()), selected)
            if (any(not rows[j["id"]]["evaluation_valid"] for j in wave) or
                    any(not c["same_checkpoint"] or not c["different_execution"] for c in summary["graph_execution_checks"])):
                print("PAIR_GATE_INCOMPLETE: remaining repetitions paused; no safe-negative inference.", flush=True)
                return 1
        print(f"COMPLETE: {len(selected)} eligible states, {len(jobs)} branches. {args.run_dir/'summary.json'}", flush=True)
        return 0
    except KeyboardInterrupt:
        stop.set()
        with mutex:
            for p in list(active):
                p.kill()
        print("Interrupted; evidence retained. Same command resumes completed jobs.", flush=True)
        return 130
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=ROOT/"results/v1/graph_checkpoint_commit_once")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--parallelism", type=int, default=4)
    parser.add_argument("--budget-usd", default="5")
    parser.add_argument("--candidates", type=int, default=12)
    parser.add_argument("--states", type=int, default=6)
    parser.add_argument("--retry-incomplete", action="store_true")
    parser.add_argument("--job-timeout", type=int, default=1800)
    parser.add_argument("--child", help=argparse.SUPPRESS)
    parser.add_argument("--phase", choices=["capture", "branch"], help=argparse.SUPPRESS)
    parser.add_argument("--attempt", type=int, default=1, help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.run_dir = args.run_dir.resolve()
    try:
        if args.child:
            return child(args)
        if not (1 <= args.parallelism <= 8 and 1 <= args.states <= args.candidates <= 20 and args.job_timeout >= 60):
            raise ValueError("parallelism 1..8, 1<=states<=candidates<=20, job-timeout>=60 required")
        protected = (ROOT/"results/v1/formal_80_seed42", ROOT/"results/v1/context_replay_slack07_MxT")
        if args.run_dir == ROOT or any(args.run_dir == p or args.run_dir in p.parents or p in args.run_dir.parents
                                       for p in protected):
            raise ValueError("Use a dedicated new experiment directory")
        args.run_dir.mkdir(parents=True, exist_ok=True)
        with launch_lock(args.run_dir / "launch.lock"):
            plan = plan_for(args)
            file = args.run_dir / "manifest.json"
            if file.exists() and load(file) != plan:
                raise ValueError("Frozen source/config differs; preserve this run and use a new --run-dir")
            if not file.exists():
                if (args.run_dir/"capture").exists() or (args.run_dir/"branch").exists():
                    raise ValueError("Existing attempts without frozen manifest")
                save(file, plan)
            print(f"RUN_DIR={args.run_dir}", flush=True)
            print(f"PRECHECK_OK: {len(plan['candidates'])} capture candidates; at most {args.states*6} paired branches.", flush=True)
            if args.preflight:
                print("Zero API calls. Real checkpoints will be captured only on live launch.", flush=True)
                return 0
            return execute(args, plan)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(f"STOPPED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
