"""Operator-launched F/W scheduling comparison. --dry-run never sends requests."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from run_formal import fingerprint, write_json

CONFIG = ROOT / "docs/manta/fw_ablation_config.json"
PROTECTED = {"formal_80_seed42", "formal_80_seed42_gpt4o", "formal_80_seed42_deepseek_pro",
             "formal_80_seed42_deepseek_pro_16k", "formal_80_seed42_deepseek_flash_adaptive",
             "formal_80_seed42_deepseek_flash_folded"}
EXPECTED_FOLDED = dict(max_workers=2, worker_turns=8, main_turns=16, recovery_turns=8,
    max_action_reviews=6, max_model_calls=48, episode_token_budget=400000,
    evidence_preview_chars=6000, history_compact_chars=60000, retained_tool_results=4)


def freeze_plan(config):
    from agentdojo_manta.replication import load_replication_plan
    original = load_replication_plan(ROOT, provider="deepseek", source_digest=fingerprint(), model="deepseek-flash")
    if config["base_config"] != "docs/manta/flash_folded_config.json":
        raise ValueError("F/W must bind the same canonical config read by the adapter")
    base_path = ROOT / config["base_config"]
    base = json.loads(base_path.read_text(encoding="utf-8"))
    if config["arms"] != {
        "F": {"worker_policy": "on_demand", "description": "Current complete folded method; worker creation remains optional"},
        "W": {"worker_policy": "fixed_two", "description": "One charged main assignment response, then two real pure-read investigations before main continuation"}}:
        raise ValueError("F/W policies differ from the frozen scheduling protocol")
    if (config["model"], config["endpoint"], config["max_output_tokens"], config["seed"], config["budget_usd"]) != (
            "deepseek-flash", "https://api.deepseek.com/v1", 16384, 42, 100):
        raise ValueError("F/W route, generation or shared budget changed; create a new protocol")
    if base["folded"] != EXPECTED_FOLDED or any(base[k] != expected for k, expected in dict(
            model="deepseek-flash", endpoint="https://api.deepseek.com/v1", max_output_tokens=16384,
            thinking="enabled", temperature=0.0, seed=42, long_term_learning=False,
            audit_mode="selective_pre_action").items()):
        raise ValueError("Both arms must retain the same folded settings")
    from run_agentdojo_manta import _source_digest
    adapter_digest = _source_digest([ROOT / "src/agentdojo_manta", ROOT / "scripts/manta/run_agentdojo_manta.py"])
    manta_digest = _source_digest([ROOT / "upstreams/manta"])
    jobs = list(original["jobs"])
    rng = random.Random(config["seed"])
    rng.shuffle(jobs)
    schedule = []
    for job in jobs:
        arms = ["F", "W"]
        rng.shuffle(arms)
        for arm in arms:
            schedule.append({**job, "arm": arm, "worker_policy": config["arms"][arm]["worker_policy"],
                             "comparison_job_id": arm + "__" + job["run_id"]})
    return dict(protocol=config["protocol"], source_sha256=original["source_sha256"],
        adapter_source_digest=adapter_digest, manta_source_digest=manta_digest,
        config_sha256=hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
        base_config_sha256=hashlib.sha256(base_path.read_bytes()).hexdigest(),
        original_manifest_sha256=original["original_manifest_sha256"],
        config=dict(model="deepseek-flash", benchmark_version="v1.2.2", num_agents=1, max_turns=2,
                    repair_budget=1, planner_mode="task_conditioned", audit_mode="selective_pre_action",
                    team_profile="folded_adaptive", seed=42),
        experiment=config, folded=base["folded"], scenes=original["scenes"], jobs=original["jobs"],
        execution_order=schedule, endpoint=config["endpoint"], max_output_tokens=16384,
        statistical_unit="paired scenario-condition; repeated Banking tasks are not independent user tasks")


def check_run_root(folder):
    folder = folder.resolve()
    if any(p.name in PROTECTED for p in (folder, *folder.parents)) or folder.is_relative_to(ROOT / "reports"):
        raise ValueError("F/W must use a new directory outside historical experiment roots and reports")
    return folder


@contextmanager
def launch_lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "launch.lock").open("a+b") as lock:
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def bind_manifest(folder, manifest):
    path = folder / "manifest.json"
    if not path.exists() and any(p.name != "launch.lock" for p in folder.iterdir()):
        raise ValueError("Unbound existing experiment state: select a fresh run directory")
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != manifest:
        raise ValueError("Frozen source/config differs: preserve this directory and select a new --run-dir")
    if not path.exists():
        write_json(path, manifest)
    for arm in ("F", "W"):
        arm_root = folder / arm
        arm_root.mkdir(exist_ok=True)
        write_json(arm_root / "manifest.json", {k: v for k, v in manifest.items() if k != "execution_order"} |
                   dict(arm=arm, worker_policy=manifest["experiment"]["arms"][arm]["worker_policy"]))


def matches_job(row, job, manifest):
    return (row.get("evaluation_valid") is True and row.get("worker_policy") == job["worker_policy"]
        and row.get("model") == "deepseek-flash" and row.get("max_output_tokens") == 16384
        and row.get("team_profile") == "folded_adaptive" and row.get("suite") == job["suite"]
        and row.get("task_id") == job["task_id"] and row.get("condition") == job["condition"]
        and row.get("seed") == 42
        and row.get("provider") == "deepseek" and row.get("benchmark_version") == "v1.2.2"
        and row.get("process_returncode", 0) == 0
        and row.get("comparison_source_sha256") == manifest["source_sha256"]
        and row.get("adapter_source_digest") == manifest["adapter_source_digest"]
        and row.get("manta_source_digest") == manifest["manta_source_digest"]
        and all(row.get("config", {}).get(k) == v for k, v in manifest["config"].items())
        and row.get("manta_metadata", {}).get("folded_config") == manifest["folded"]
        and row.get("attack") == ("direct" if job["condition"] == "attack" else None)
        and row.get("injection_task") == (job["injection_task"] if job["condition"] == "attack" else None))


def saved_result(folder, job, manifest):
    valid = []
    for attempt in sorted((folder / job["arm"] / "attempts" / job["run_id"]).glob("attempt_*")):
        path = attempt / "queue_result.json"
        if not path.exists():
            path = attempt / "result.json"
        if path.exists():
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(row, dict):
                    raise ValueError("Result must be an object")
            except (ValueError, UnicodeDecodeError):
                if path.name == "queue_result.json":
                    raise ValueError("Corrupt queue provenance receipt: " + str(path))
                # A prior interrupted child cannot be reused; preserve its
                # bytes and permit a fresh separately accounted attempt.
                continue
            if matches_job(row, job, manifest):
                logroot = Path(row.get("official_logdir", "")).resolve()
                if not logroot.is_relative_to((folder / job["arm"] / "logs" / job["run_id"]).resolve()):
                    raise ValueError("Result references logs outside its frozen arm/job")
                valid.append(row)
            elif row.get("evaluation_valid") is True:
                raise ValueError("Valid-looking saved result has wrong source/config/arm: " + job["comparison_job_id"])
    if len(valid) > 1:
        raise ValueError("Multiple valid attempts for " + job["comparison_job_id"])
    return valid[0] if valid else None


def verify_receipt(folder, manifest):
    from agentdojo_manta.providers import provider_config
    binding = provider_config("deepseek-flash")
    if binding.name != "deepseek" or binding.base_url.rstrip("/") != manifest["endpoint"] or not binding.api_key:
        raise ValueError("Official Flash route and existing credentials required")
    if any(m != "deepseek-flash" for m in (binding.model, binding.planner_model, binding.auditor_model)):
        raise ValueError("All F/W model roles must use deepseek-flash")
    if os.getenv("V1_MAX_COST_USD") != "100":
        raise ValueError("F+W share one explicit independent $100 cap")
    path = folder / "connectivity.json"
    receipt = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if (receipt.get("status") != "completed" or receipt.get("requested_model") != "deepseek-flash"
            or receipt.get("endpoint", "").rstrip("/") != manifest["endpoint"]
            or receipt.get("budget_db") != str(folder / "budget.sqlite")):
        raise ValueError("Successful connectivity receipt must belong to this shared F/W budget")
    from agentdojo_manta.budget import RequestBudget
    ledger = folder / "budget.sqlite"
    if not ledger.exists():
        raise ValueError("Connectivity ledger is missing; do not recreate past charges")
    usage = receipt.get("usage") or {}
    if any(type(usage.get(k)) is not int or usage[k] < 0 for k in ("prompt_tokens", "completion_tokens")):
        raise ValueError("Probe usage is missing or invalid")
    expected = usage["prompt_tokens"] * RequestBudget.INPUT_RATE + usage["completion_tokens"] * RequestBudget.OUTPUT_RATE
    with closing(sqlite3.connect(ledger)) as db:
        row = db.execute("SELECT amount,state FROM requests WHERE id=?", (receipt.get("budget_request_id"),)).fetchone()
    if row != (expected, "settled"):
        raise ValueError("Connectivity usage does not reconcile with its settled ledger entry")


def check_source(manifest):
    if (fingerprint() != manifest["source_sha256"] or hashlib.sha256(CONFIG.read_bytes()).hexdigest() != manifest["config_sha256"]
            or hashlib.sha256((ROOT / manifest["experiment"]["base_config"]).read_bytes()).hexdigest() != manifest["base_config_sha256"]):
        raise ValueError("Source/config changed while F/W was running; stop and use a new run directory")


def bind_budget(folder, manifest):
    from agentdojo_manta.budget import RequestBudget
    budget = RequestBudget(folder / "budget.sqlite", "100")
    identity = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    with budget.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT value FROM settings WHERE key='fw_manifest_sha256'").fetchone()
        if row is None:
            if db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]:
                raise ValueError("Shared ledger already contains unbound charges")
            db.execute("INSERT INTO settings VALUES ('fw_manifest_sha256', ?)", (identity,))
        elif row[0] != identity:
            raise ValueError("Shared ledger belongs to another frozen comparison")
    probe = folder / "connectivity.json"
    if probe.exists():
        request_id = json.loads(probe.read_text(encoding="utf-8")).get("budget_request_id")
        if request_id:
            with budget.connect() as db:
                if db.execute("SELECT id FROM requests WHERE id=?", (request_id,)).fetchone() is None:
                    raise ValueError("Existing probe charge is missing from the shared ledger")
    return budget


def attempt_accounting(folder, arm):
    attempts = list((folder / arm / "attempts").glob("*/attempt_*"))
    invalid, missing, completed, requests, malformed, malformed_results = 0, 0, {}, set(), 0, []
    attempted_jobs = set()
    for attempt in attempts:
        attempted_jobs.add(attempt.parent.name)
        path = attempt / "queue_result.json"
        if not path.exists():
            path = attempt / "result.json"
        if path.exists():
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(row, dict):
                    raise ValueError("Result must be an object")
                invalid += row.get("evaluation_valid") is not True
            except (ValueError, UnicodeDecodeError):
                invalid += 1
                malformed_results.append(str(path.relative_to(folder)))
        else:
            missing += 1
        journal = attempt / "requests.jsonl"
        if journal.exists():
            for line in journal.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except ValueError:
                    malformed += 1
                    continue
                rid = entry.get("budget_request_id")
                if rid:
                    requests.add(rid)
                    if entry.get("status") == "completed":
                        completed[rid] = entry
    ledger_amount, unreturned = 0, 0
    ledger = folder / "budget.sqlite"
    if ledger.exists():
        with closing(sqlite3.connect(ledger)) as db:
            for rid in requests:
                row = db.execute("SELECT amount,state FROM requests WHERE id=?", (rid,)).fetchone()
                if row:
                    ledger_amount += row[0]
                    if row[1] != "settled":
                        unreturned += row[0]
    return dict(attempted_jobs=len(attempted_jobs), attempts=len(attempts), invalid_attempts=invalid,
        attempts_without_result=missing, all_attempt_completed_requests=len(completed),
        all_attempt_observed_tokens=sum((r.get("token_in") or 0) + (r.get("token_out") or 0) for r in completed.values()),
        known_request_accounted_upper_bound_usd=ledger_amount / 1e9, known_unreturned_reservations_usd=unreturned / 1e9,
        malformed_journal_lines=malformed, malformed_result_files=malformed_results,
        scope="all attempts; observed usage excludes unreturned responses; shared probe is in common budget only")


def summary_rows(folder, manifest, budget=None):
    from agentdojo_manta.metrics import summarize
    by_arm = {}
    selected = {}
    for arm in ("F", "W"):
        rows = []
        provenance_errors = {}
        for job in manifest["execution_order"]:
            if job["arm"] != arm:
                continue
            try:
                row = saved_result(folder, job, manifest)
            except ValueError as exc:
                provenance_errors[job["run_id"]] = str(exc)
                row = None
            if row is not None:
                rows.append(row)
                selected[(arm, job["run_id"])] = row
        data = dict(**summarize(rows), planned_episodes=160, complete=len(rows) == 160,
                    tokens=sum(r.get("tokens") or 0 for r in rows),
                    token_in=sum(r.get("token_in") or 0 for r in rows),
                    token_out=sum(r.get("token_out") or 0 for r in rows),
                    worker_policy=manifest["experiment"]["arms"][arm]["worker_policy"])
        data["selected_valid_tokens"] = data["tokens"]
        data["all_attempts"] = attempt_accounting(folder, arm)
        data["attempted_episodes"] = data["all_attempts"]["attempted_jobs"]
        data["invalid_episodes"] = data["attempted_episodes"] - len(rows)
        data["provenance_errors"] = provenance_errors
        data["missing_valid_jobs"] = 160 - len(rows)
        if arm == "W":
            data["fixed_two_fulfilled_n"] = sum(r.get("fixed_two_fulfilled") is True for r in rows)
            data["fixed_two_shortfall_jobs"] = [r.get("queue_run_id", r.get("run_id")) for r in rows if r.get("fixed_two_fulfilled") is not True]
        write_json(folder / arm / "summary.json", data)
        by_arm[arm] = data
    flips = {c: dict(F_only=[], W_only=[]) for c in ("clean", "attack")}
    paired = 0
    for job in manifest["jobs"]:
        f, w = selected.get(("F", job["run_id"])), selected.get(("W", job["run_id"]))
        if f is None or w is None:
            continue
        paired += 1
        if f["task_success"] and not w["task_success"]:
            flips[job["condition"]]["F_only"].append(job["run_id"])
        if w["task_success"] and not f["task_success"]:
            flips[job["condition"]]["W_only"].append(job["run_id"])
    combined = dict(arms=by_arm, complete=all(v["complete"] for v in by_arm.values()),
        paired_episode_conditions=paired, paired_flips=flips, planned_episodes=320,
        budget=budget.snapshot() if budget else None)
    write_json(folder / "summary.json", combined)
    return combined


def assert_no_children(folder):
    pid_path = folder / "active_pids.json"
    if pid_path.exists():
        for pid in json.loads(pid_path.read_text(encoding="utf-8")):
            if os.name == "nt":
                listing = subprocess.check_output(["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"], text=True, errors="replace")
                if f'","{int(pid)}","' in listing:
                    raise ValueError(f"Previous child {pid} remains alive; do not resume concurrently")
            else:
                try:
                    os.kill(int(pid), 0)
                except ProcessLookupError:
                    continue
                raise ValueError(f"Previous child {pid} remains alive")


def run_queue(folder, manifest, arm="both", parallelism=8, max_attempts=2):
    verify_receipt(folder, manifest)
    assert_no_children(folder)
    budget = bind_budget(folder, manifest)
    pid_path = folder / "active_pids.json"
    with budget.connect() as db:
        db.execute("UPDATE requests SET state='uncertain' WHERE state='pending'")
        db.execute("UPDATE settings SET value='0' WHERE key='blocked'")
    active, active_lock, stop = set(), threading.Lock(), threading.Event()
    jobs = [j for j in manifest["execution_order"] if arm == "both" or j["arm"] == arm]

    def run_one(job):
        saved = saved_result(folder, job, manifest)
        if saved is not None:
            return saved
        job_dir = folder / job["arm"] / "attempts" / job["run_id"]
        job_dir.mkdir(parents=True, exist_ok=True)
        attempts = sorted(job_dir.glob("attempt_*"))
        row = dict(evaluation_valid=False, run_status="BLOCKED", arm=job["arm"], queue_run_id=job["run_id"],
                   error="Not started: attempt limit, interruption or budget; evidence retained")
        # The limit is per operator launch. A manual resume may add new infra
        # attempts without touching the frozen source/config or valid results.
        for index in range(len(attempts) + 1, len(attempts) + max_attempts + 1):
            if stop.is_set() or budget.snapshot()["blocked"]:
                break
            attempt = job_dir / f"attempt_{index:03d}"
            attempt.mkdir()
            command = [sys.executable, "-u", str(ROOT / "scripts/manta/run_agentdojo_manta.py"),
                "--suite", job["suite"], "--user-task", job["task_id"], "--run-id", attempt.name,
                "--output-dir", str(job_dir), "--logdir", str(folder / job["arm"] / "logs" / job["run_id"]),
                "--worker-policy", job["worker_policy"]]
            command.extend(["--comparison-source-sha256", manifest["source_sha256"]])
            for key, value in manifest["config"].items():
                command.extend(["--" + key.replace("_", "-"), str(value)])
            command.extend(["--clean"] if job["condition"] == "clean" else ["--attack", "direct", "--injection-task", job["injection_task"]])
            env = dict(os.environ, MANTA_PROVIDER="deepseek", DEEPSEEK_BASE_URL=manifest["endpoint"],
                DEEPSEEK_MODEL="deepseek-flash", DEEPSEEK_PLANNER_MODEL="deepseek-flash", DEEPSEEK_AUDITOR_MODEL="deepseek-flash",
                MANTA_MAX_INITIAL_AGENTS="1", MANTA_MAX_TOTAL_AGENTS="4", V1_LLM_TIMEOUT_S="180", PYTHONIOENCODING="utf-8",
                V1_BUDGET_DB=budget.path, V1_MAX_COST_USD="100", V1_REQUEST_JOURNAL=str(attempt / "requests.jsonl"),
                OPENROUTER_MAX_TOKENS="16384")
            with (attempt / "console.log").open("w", encoding="utf-8") as console:
                with active_lock:
                    if stop.is_set():
                        break
                    check_source(manifest)
                    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=console, stderr=subprocess.STDOUT)
                    active.add(process)
                    write_json(pid_path, sorted(p.pid for p in active))
                try:
                    code = process.wait()
                finally:
                    with active_lock:
                        active.discard(process)
                        write_json(pid_path, sorted(p.pid for p in active))
            path = attempt / "result.json"
            try:
                row = json.loads(path.read_text(encoding="utf-8")) if path.exists() else dict(
                    evaluation_valid=False, run_status="INFRA_ERROR", error="See console.log")
                if not isinstance(row, dict):
                    raise ValueError("Result must be an object")
            except (ValueError, UnicodeDecodeError):
                row = dict(evaluation_valid=False, run_status="INFRA_ERROR", error="Malformed child result retained; see console.log")
            row.update(arm=job["arm"], queue_run_id=job["run_id"], scene_id=job["scene_id"], process_returncode=code,
                       queue_source_sha256=manifest["source_sha256"])
            check_source(manifest)
            if row.get("evaluation_valid") is True and not matches_job(row, job, manifest):
                row.update(evaluation_valid=False, run_status="CONFIG_ERROR", error="Child result differs from frozen arm/job")
                stop.set()
            write_json(attempt / "queue_result.json", row)
            if any(q.get("http_status") in (400, 401, 403, 404) or q.get("error_type") == "ValueError" for q in row.get("llm_requests", [])):
                stop.set()
            if matches_job(row, job, manifest) or row.get("run_status") == "BLOCKED":
                break
        return row

    processed = 0
    with ThreadPoolExecutor(max_workers=parallelism) as pool:
        def guarded_run_one(job):
            try:
                return run_one(job)
            except BaseException:
                stop.set()
                raise
        futures = {pool.submit(guarded_run_one, j): j for j in jobs}
        def stop_children():
            stop.set()
            for future in futures:
                future.cancel()
            with active_lock:
                for process in list(active):
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                    else:
                        process.kill()
        try:
            for future in as_completed(futures):
                row = future.result()
                processed += 1
                print(f"[{processed}/{len(jobs)}] {row.get('arm')} {row.get('queue_run_id')} {row.get('run_status')}", flush=True)
                write_json(folder / "progress.json", dict(processed_this_launch=processed, scheduled_this_launch=len(jobs),
                           selected_arm=arm, budget=budget.snapshot()))
        except KeyboardInterrupt:
            stop_children()
            print("Interrupted; completed evidence retained. The same command resumes.", flush=True)
        except Exception as exc:
            stop_children()
            write_json(folder / "coordinator_error.json", dict(error_type=type(exc).__name__, error=str(exc),
                       processed_this_launch=processed, active_children_stopped=True))
            print("Coordinator failed; queued work stopped and evidence retained.", flush=True)
    summary = summary_rows(folder, manifest, budget)
    selected_complete = all(summary["arms"][a]["complete"] for a in (("F", "W") if arm == "both" else (arm,)))
    print(f"{'COMPLETE' if selected_complete else 'INCOMPLETE'}: {folder / 'summary.json'}", flush=True)
    return 130 if stop.is_set() else 0 if selected_complete else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--arm", choices=["both", "F", "W"], default="both")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--connectivity", action="store_true", help="Operator-authorized one-time probe under the same queue lock")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(Path(os.getenv("DOTENV_SOURCE_FILE", str(ROOT / ".env"))), override=False)
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    folder = check_run_root(args.run_dir or Path(config["run_dir"]))
    if not 1 <= config["parallelism"] <= 8 or config["max_attempts"] < 1:
        raise ValueError("Invalid F/W concurrency or attempt limit")
    # The pinned MANTA config may auto-load credentials; unused credentials are
    # harmless, but inherited generation or execution overrides are not.
    from agentdojo_manta.adapter import AdapterPaths, _import_manta
    _import_manta(AdapterPaths.from_repo(ROOT))
    forbidden = [k for k in os.environ if k.startswith(("MAS_", "MANTA_", "OPENROUTER_")) and k != "MANTA_PROVIDER"
                 and not k.endswith(("_KEY", "_ACCESS_TOKEN", "_SECRET", "_PASSWORD"))]
    if forbidden:
        raise ValueError("Remove unverified runtime overrides: " + ", ".join(sorted(forbidden)))
    manifest = freeze_plan(config)
    with launch_lock(folder):
        bind_manifest(folder, manifest)
        print(f"F/W frozen: 80 scenarios x clean/attack x 2 arms = 320 episodes; total concurrency {config['parallelism']}.", flush=True)
        if args.dry_run:
            print("PRECHECK_OK: policies, source, payload hashes and paired order frozen; zero API requests.", flush=True)
            return 0
        check_source(manifest)
        assert_no_children(folder)
        for job in manifest["execution_order"]:
            saved_result(folder, job, manifest)
        bind_budget(folder, manifest)
        if args.connectivity:
            import probe_deepseek_flash
            previous_argv = sys.argv
            try:
                sys.argv = ["probe_deepseek_flash.py", "--run-dir", str(folder)]
                probe_deepseek_flash.main()
            finally:
                sys.argv = previous_argv
        return run_queue(folder, manifest, args.arm, config["parallelism"], config["max_attempts"])


if __name__ == "__main__":
    raise SystemExit(main())
