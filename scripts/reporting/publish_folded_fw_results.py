"""Publish selected formal Folded/FW evidence offline; no experiment/model imports."""
from __future__ import annotations

import csv
import functools
import gzip
import hashlib
import io
import json
import os
import tarfile
from collections import Counter, defaultdict
from pathlib import Path

from publish_manta_results import Redactor

ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "reports/2026-10-29-completed-experiments"
RUNS = [
    ("folded_initial", "folded-initial-reference", Path(r"D:\MANTA_DATA\AgentDojo\formal_80_seed42_deepseek_flash_folded"), ROOT / "reports/2026-10-29-agentdojo-flash16k-folded"),
    ("F", "fw-F-on-demand", Path(r"D:\MANTA_DATA\AgentDojo\ablation_fw_flash16k_seed42\F"), ROOT / "reports/2026-10-29-agentdojo-flash16k-fw"),
    ("W", "fw-W-fixed-two", Path(r"D:\MANTA_DATA\AgentDojo\ablation_fw_flash16k_seed42\W"), ROOT / "reports/2026-10-29-agentdojo-flash16k-fw"),
]


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def csv_out(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def public_bytes(path, redactor):
    raw = path.read_bytes()
    if path.suffix == ".json":
        public = (json.dumps(redactor.obj(json.loads(raw.decode("utf-8-sig"))), ensure_ascii=False, indent=2) + "\n").encode()
    elif path.suffix == ".jsonl":
        public = ("\n".join(json.dumps(redactor.obj(json.loads(line)), ensure_ascii=False) for line in raw.decode("utf-8-sig").splitlines() if line.strip()) + "\n").encode()
    else:
        raise ValueError(f"Non-allowlisted publication suffix: {path.suffix}")
    redactor.scan(public)
    return raw, public


def save_json(path, value, redactor):
    data = (json.dumps(redactor.obj(value), ensure_ascii=False, indent=2) + "\n").encode()
    redactor.scan(data)
    path.write_bytes(data)


def checksums(out):
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "checksums.sha256")
    (out / "checksums.sha256").write_bytes(("\n".join(f"{sha(p.read_bytes())}  {p.relative_to(out).as_posix()}" for p in files) + "\n").encode())


def main():
    redactor = Redactor()
    from dotenv import dotenv_values
    for worktree in ("gpt4o-replication", "manta-folded-flash16k", "manta-fw-ablation"):
        values = dotenv_values(ROOT.parent / worktree / ".env")
        redactor.secrets.extend(v for k, v in values.items() if v and len(v) >= 12 and k.upper().endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")))
    redactor.secrets = sorted(set(redactor.secrets), key=len, reverse=True)
    redactor.text = functools.lru_cache(maxsize=8192)(redactor.text)
    totals = {r["run"]: r for r in load(SUMMARY / "summary.json")["runs"]}
    source_index = {r["run"]: r for r in load(SUMMARY / "source_inventory.json")}
    all_rows = list(csv.DictReader((SUMMARY / "episode_results.csv").open(encoding="utf-8", newline="")))
    datasets = defaultdict(list)
    source_inventory, archive_inventory = defaultdict(list), defaultdict(list)
    for key, name, run, out in RUNS:
        out.mkdir(parents=True, exist_ok=True)
        (out / "logs").mkdir(exist_ok=True)
        if (run / "active_pids.json").exists():
            assert load(run / "active_pids.json") == []
        elif (run.parent / "active_pids.json").exists():
            assert load(run.parent / "active_pids.json") == []
        manifest = load(run / "manifest.json")
        assert sha((run / "manifest.json").read_bytes()) == source_index[key]["manifest_sha256"]
        expected = {r["job_id"]: r for r in source_index[key]["selected_results"]}
        groups, rows, timestamps, commits = defaultdict(list), [], [], set()
        attempt_count = invalid_count = no_result = 0
        for job in manifest["jobs"]:
            candidates = []
            for directory in sorted((run / "attempts" / job["run_id"]).glob("attempt_*")):
                attempt_count += 1
                path = directory / "result.json"
                if not path.exists():
                    no_result += 1
                    continue
                row = load(path)
                if row.get("evaluation_valid") is True:
                    candidates.append((path, row))
                else:
                    invalid_count += 1
            assert len(candidates) == 1, (key, job["run_id"])
            path, row = candidates[0]
            assert sha(path.read_bytes()) == expected[job["run_id"]]["result_sha256"]
            assert not row["mock_used"] and row["max_output_tokens"] == 16384
            assert row["condition"] == job["condition"] and row["task_id"] == job["task_id"]
            traces = list((run / "logs" / job["run_id"] / path.parent.name).rglob("*.json"))
            assert len(traces) == 1
            trace = load(traces[0])
            assert sha(traces[0].read_bytes()) == expected[job["run_id"]]["official_trace_sha256"]
            assert (trace["utility"], trace["security"]) == (row["official_utility"], row["official_security"])
            assert row["task_success"] == row["official_utility"]
            completed = [q for q in row["llm_requests"] if q["status"] == "completed"]
            assert sum(q["token_in"] for q in completed) == row["token_in"]
            assert sum(q["token_out"] for q in completed) == row["token_out"]
            timestamps.append(trace["evaluation_timestamp"])
            commits.add(row["agentdojo_commit"])
            requests = path.parent / "requests.jsonl"
            assert requests.exists()
            groups[job["suite"]].extend([path, requests, traces[0]])
            rows.append(next(r for r in all_rows if r["run"] == key and r["job_id"] == job["run_id"]))
        assert len(rows) == 160 and sum(int(r["total_tokens"]) for r in rows) == totals[key]["total_tokens"]
        dates = {str(t)[:10] for t in timestamps}
        assert dates == {"2026-10-29"}, dates
        save_json(out / ("manifest.json" if key == "folded_initial" else f"manifest_{key}.json"), manifest, redactor)
        save_json(out / ("retained_summary.json" if key == "folded_initial" else f"retained_summary_{key}.json"), load(run / "summary.json"), redactor)
        metadata = dict(run=key, publication_name=name, run_date="2026-10-29", publication_date="2026-10-29", first_evaluation=min(timestamps), last_evaluation=max(timestamps),
                        timestamp_note="As recorded; raw timestamps contain no UTC offset; no timezone conversion was applied.",
                        selected_valid_episodes=160, retained_attempt_directories=attempt_count, excluded_invalid_attempts=invalid_count, excluded_attempts_without_result=no_result,
                        retained_source_commits=sorted(commits), manifest_raw_sha256=source_index[key]["manifest_sha256"], metrics=totals[key],
                        selection="Frozen manifest unique evaluation_valid result, including official task failures and resource-limited episodes; excludes infrastructure-invalid attempts, not task failures.")
        datasets[out].append(metadata)
        for suite, files in sorted(groups.items()):
            destination = out / "logs" / f"2026-10-29_agentdojo_flash16k_{name}_{suite}_valid.tar.gz"
            expected_members = {}
            with destination.open("wb") as stream, gzip.GzipFile(fileobj=stream, filename="", mode="wb", mtime=0, compresslevel=6) as zipped:
                with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tar:
                    for path in sorted(files):
                        raw, public = public_bytes(path, redactor)
                        member_name = name + "/" + path.relative_to(run).as_posix()
                        info = tarfile.TarInfo(member_name)
                        info.size, info.mode, info.mtime = len(public), 0o644, 0
                        tar.addfile(info, io.BytesIO(public))
                        expected_members[member_name] = sha(public)
                        source_inventory[out].append(dict(run=key, job_id=path.relative_to(run).parts[1], archive=destination.relative_to(out).as_posix(), member=member_name,
                                                          raw_bytes=len(raw), public_bytes=len(public), raw_sha256=sha(raw), public_sha256=sha(public)))
            assert destination.stat().st_size < 95 * 2**20
            with tarfile.open(destination, "r:gz") as tar:
                assert len(tar.getmembers()) == len(expected_members)
                for member in tar:
                    assert member.isfile() and not member.name.startswith("/") and ".." not in Path(member.name).parts
                    data = tar.extractfile(member).read()
                    assert sha(data) == expected_members[member.name]
                    redactor.scan(data)
            archive_inventory[out].append(dict(run=key, suite=suite, archive=destination.relative_to(out).as_posix(), episodes=40, files=len(files), compressed_bytes=destination.stat().st_size, sha256=sha(destination.read_bytes())))
            print(f"ARCHIVED {name}/{suite}: {len(files)} files, {destination.stat().st_size/2**20:.2f} MiB", flush=True)
    for out, cohorts in datasets.items():
        keys = {c["run"] for c in cohorts}
        save_json(out / "publication.json", dict(date="2026-10-29", cohorts=cohorts, included="Selected valid results, request journals, official scored traces, frozen manifests, aggregate attempt/budget disclosure.",
                                                  excluded="Connectivity probes, smoke/pilot runs, console and queue duplicates, locks, active PID files, raw SQLite, invalid-attempt traces; raw evidence remains local."), redactor)
        if "F" in keys:
            run = next(r for k, _, r, _ in RUNS if k == "F")
            save_json(out / "manifest_common.json", load(run.parent / "manifest.json"), redactor)
            save_json(out / "retained_summary_common.json", load(run.parent / "summary.json"), redactor)
            (out / "fw_paired.csv").write_bytes((SUMMARY / "fw_paired.csv").read_bytes())
        csv_out(out / "episode_results.csv", [r for r in all_rows if r["run"] in keys])
        for file in ("overview.csv", "by_suite.csv", "role_usage.csv"):
            data = list(csv.DictReader((SUMMARY / file).open(encoding="utf-8", newline="")))
            csv_out(out / file, [r for r in data if r["run"] in keys])
        csv_out(out / "published_log_inventory.csv", source_inventory[out])
        save_json(out / "archives.json", archive_inventory[out], redactor)
        title = "Flash 16K：F/W 按需与固定双 worker 对照" if "F" in keys else "Flash 16K：Folded 首次正式运行（重复参考）"
        lines = [f"# {title}", "", "实验日期：**2026-10-29**。归档日期：**2026-10-29**。逐条运行时间范围见 [publication.json](publication.json)，时间按原始日志记录，未擅自转换时区。", "",
                 "只归档有比较价值的正式证据：每组冻结 80 场景，clean 80 + direct attack 80。包含任务失败和资源终止的有效评分；不是只选成功案例。", "",
                 "| 组别 | Clean 完成 | Attack 完成 | 攻击成功 | 安全完成 | 总 token |", "|---|---:|---:|---:|---:|---:|"]
        for cohort in cohorts:
            r = totals[cohort["run"]]
            lines.append(f"| {cohort['publication_name']} | {r['clean_success']}/80 | {r['attack_successful_tasks']}/80 | {r['attacker_successes']}/80 | {r['safe_attack_successful_tasks']}/80 | {r['total_tokens']:,} |")
        if "F" in keys:
            lines += ["", "F 为按需调查，W 为一次 main 分派后固定两个真实只读 worker；两组共 320 条有效 episode，共享同一版本代码与资源上限。W 的 160 条均实际启动 agent_1 和 agent_2；F 仅 2 条启动一个调查 worker。", "",
                      "W 比 F 多完成 4 个攻击下任务，总 token 多 84.12%。这是包含分派/汇报的调度协议对照，不是通用运行中 fold/split 的纯消融。两组各 76 条确认暴露、4 条 UNKNOWN；0/80 是本次 direct 测试的观测 ASR。", "",
                      "每组保留 163 次尝试，其中 3 次基础设施无效尝试不打包；其观测用量与预留成本仍完整披露在 retained_summary_F/W.json 的 all_attempts。共同账本估算上界 $9.6466629，其中已返回响应上界 $7.6412613、未返回预留 $2.0054016；不是实际账单。"]
        else:
            lines += ["", "本组是按需 Folded 的首次完整运行，作为同一核心策略的重复参考保留；不当成第七种方法、不与 F/W 轮 F 合并成多 seed 平均。", "",
                      "160 条有效记录中包含 2 条资源终止；唯一官方攻击成功为 travel_18__attack，属于最终回答引用攻击目标名称。保留官方分数，不重新判分。", "",
                      "原预算估算上界 $3.5697726，已返回响应上界 $2.5670718、未返回预留 $1.0027008；不是实际账单。"]
        lines += ["", "## 日志包", "", "每个包按组别和 suite 命名，包含 40 条 episode 的 result.json、requests.jsonl 与官方评分 trace，共 120 个文件。重复 console/queue、探测、锁文件和测试不上传。", "",
                  "| 包 | Episode | 文件 | MiB |", "|---|---:|---:|---:|"]
        for a in archive_inventory[out]:
            lines.append(f"| [{Path(a['archive']).name}]({a['archive']}) | {a['episodes']} | {a['files']} | {a['compressed_bytes']/2**20:.2f} |")
        lines += ["", "## 复核与使用", "", "- [逐条结果](episode_results.csv)、[总表](overview.csv)、[分 suite](by_suite.csv)、[角色 token](role_usage.csv)。",
                  "- [逐文件原始/公开哈希](published_log_inventory.csv)、[压缩包清单](archives.json)、[所有文件校验值](checksums.sha256)。",
                  "- 原始结果和官方 utility/security 已逐条匹配；token 已逐请求求和，不重新调用模型或评分器。",
                  "- 公开副本脱敏凭证、用户路径及合成联系/账户敏感值；原始文件未修改。公开 trace 不是逐字节原始评分输入，不应直接重算评分替代官方结果。",
                  "- 总 token 仅包含所选有效 episode 的已完成请求；完整尝试/预算信息另看 retained_summary。",
                  "- [全部已完成正式实验汇总](../2026-10-29-completed-experiments/README.md)。", ""]
        (out / "README.md").write_bytes("\n".join(lines).encode())
        save_json(out / "redaction_summary.json", dict(raw_files_untouched=True, selected_file_count=len(source_inventory[out]), replacement_counts_cumulative=dict(redactor.counts),
                                                        note="Counters are cumulative across this export; cached identical strings counted once. Credentials, home paths, synthetic contact/account secrets redacted; scores/tokens unchanged."), redactor)
        for path in out.rglob("*"):
            if path.is_file() and path.suffix != ".gz":
                redactor.scan(path.read_bytes())
        checksums(out)
        print(f"PUBLISHED {out.name}: {sum(c['selected_valid_episodes'] for c in cohorts)} valid episodes", flush=True)


if __name__ == "__main__":
    main()
