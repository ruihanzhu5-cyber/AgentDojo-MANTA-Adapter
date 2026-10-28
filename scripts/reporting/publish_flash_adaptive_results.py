"""Offline publication of completed adaptive Flash evidence; never calls a provider."""
from __future__ import annotations

import argparse
import csv
import functools
import gzip
import importlib.util
import io
import json
import sqlite3
import subprocess
import tarfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/2026-10-28-deepseek-flash-adaptive"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def frozen_json(path):
    return json.loads(subprocess.check_output(["git", "show", "HEAD:" + path], cwd=ROOT))


def write_csv(name, rows):
    with (OUT / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def signature(spec):
    return json.dumps({k: spec.get(k) for k in ("agents", "groups", "root_group_id", "extra_edges")}, sort_keys=True)


def root_pattern(spec):
    return next(g["pattern"] for g in spec["groups"] if g["group_id"] == spec["root_group_id"])


def archive(run, redactor, sha):
    groups = defaultdict(list)
    for path in sorted(run.rglob("*")):
        if path.is_file():
            parts = path.relative_to(run).parts
            group = "formal-" + parts[1].split("_")[0] if len(parts) > 2 and parts[0] in {"attempts", "logs"} else "formal-control-and-resume"
            groups[group].append(path)
    (OUT / "logs").mkdir(exist_ok=True)
    inventory, archives = [], []
    for group, files in sorted(groups.items()):
        destination = OUT / "logs" / (group + ".tar.gz")
        expected = {}
        with destination.open("wb") as stream, gzip.GzipFile(fileobj=stream, filename="", mode="wb", mtime=0, compresslevel=6) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for path in files:
                    raw = path.read_bytes()
                    if path.suffix == ".json":
                        public = (json.dumps(redactor.obj(json.loads(raw)), ensure_ascii=False, indent=2) + "\n").encode()
                    elif path.suffix == ".jsonl":
                        public = ("\n".join(json.dumps(redactor.obj(json.loads(line)), ensure_ascii=False) for line in raw.decode("utf-8").splitlines() if line.strip()) + "\n").encode()
                    elif path.suffix in {".log", ".lock"}:
                        public = redactor.text(raw.decode("utf-8")).encode()
                    elif path.suffix == ".sqlite":
                        public = raw  # The checked schema contains only request UUIDs, amounts and state/settings.
                    else:
                        raise ValueError(f"Unreviewed export format: {path.suffix}")
                    redactor.scan(public)
                    name = run.name + "/" + path.relative_to(run).as_posix()
                    info = tarfile.TarInfo(name)
                    info.size, info.mode, info.mtime = len(public), 0o644, 0
                    tar.addfile(info, io.BytesIO(public))
                    expected[name] = sha(public)
                    inventory.append(dict(source_path=name, archive=destination.relative_to(OUT).as_posix(), raw_bytes=len(raw), public_bytes=len(public), raw_sha256=sha(raw), public_sha256=sha(public), content_changed=raw != public))
        assert destination.stat().st_size < 95 * 2**20
        with tarfile.open(destination, "r:gz") as tar:
            assert len(tar.getmembers()) == len(expected)
            for member in tar:
                data = tar.extractfile(member).read()
                assert sha(data) == expected[member.name]
                redactor.scan(data)
        archives.append(dict(archive=destination.relative_to(OUT).as_posix(), files=len(files), compressed_bytes=destination.stat().st_size, sha256=sha(destination.read_bytes())))
        print(f"ARCHIVED {group}: {len(files)} files, {destination.stat().st_size/2**20:.2f} MiB", flush=True)
    write_csv("published_log_inventory.csv", inventory)
    return archives


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=Path(r"D:\MANTA_DATA\AgentDojo\formal_80_seed42_deepseek_flash_adaptive"))
    parser.add_argument("--analysis-only", action="store_true")
    args = parser.parse_args()
    run = args.run_dir.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    export = module("adaptive_gpt_export", ROOT / "scripts/reporting/publish_gpt4o_results.py")
    shared = module("adaptive_redactor", ROOT / "scripts/reporting/publish_manta_results.py")
    runner = module("adaptive_frozen_runner", ROOT / "scripts/manta/run_formal.py")
    episode = module("adaptive_episode_runner", ROOT / "scripts/manta/run_agentdojo_manta.py")
    export.OUT = OUT
    redactor = shared.Redactor()
    # Histories repeat large tool outputs verbatim. Cache identical input strings;
    # pseudonyms remain consistent, replacement counters count cache misses only.
    redactor.text = functools.lru_cache(maxsize=8192)(redactor.text)
    save = lambda name, value: export.save_json(name, json.loads(json.dumps(value)), redactor)
    manifest, summary = load(run / "manifest.json"), load(run / "summary.json")
    assert load(run / "active_pids.json") == []
    assert runner.fingerprint() == manifest["source_sha256"]
    original = load(ROOT / "reports/2026-10-19-manta-agentdojo/manifest.json")
    assert manifest["scenes"] == original["scenes"] and manifest["jobs"] == original["jobs"]
    assert export.sha((ROOT / "reports/2026-10-19-manta-agentdojo/manifest.json").read_bytes()) == manifest["original_manifest_sha256"]
    assert export.sha((ROOT / "docs/manta/flash_adaptive_config.json").read_bytes()) == manifest["experiment_config_sha256"]
    from agentdojo_manta.replication import load_replication_plan
    regenerated = load_replication_plan(ROOT, provider="deepseek", model="deepseek-flash", source_digest=manifest["source_sha256"])
    assert regenerated["scenes"] == manifest["scenes"] and regenerated["jobs"] == manifest["jobs"]
    selected, episode_rows, graph_rows = {}, [], []
    for job in manifest["jobs"]:
        found = [(p, load(p)) for p in sorted((run / "attempts" / job["run_id"]).glob("*/result.json"))]
        valid = [(p, r) for p, r in found if r.get("evaluation_valid") is True]
        assert len(valid) == 1, job["run_id"]
        path, row = valid[0]
        assert all(row[k] == job[k] for k in ("suite", "condition", "task_id"))
        assert row["injection_task"] == (job["injection_task"] if job["condition"] == "attack" else None)
        assert row["model"] == "deepseek-flash" and row["team_profile"] == "adaptive_native" and row["max_output_tokens"] == 16384 and not row["mock_used"]
        traces = [load(p) for p in (run / "logs" / job["run_id"] / path.parent.name).rglob("*.json")]
        assert len(traces) == 1 and not traces[0].get("error")
        trace = traces[0]
        assert (trace["utility"], trace["security"]) == (row["official_utility"], row["official_security"])
        se = row["manta_metadata"]["self_evolved"]
        assert se["write_protocol"] == "adaptive_native" and se["audit_mode"] == "hybrid"
        graphs = se["execution_graphs"]
        assert len(graphs) in (1, 2) and len(graphs) == len(se["topology_spec_versions"])
        for index, graph in enumerate(graphs):
            assert graph["topology_spec"] == se["topology_spec_versions"][index]
            assert graph["stage_sequence"] and all(s["agent_id"] and s["node_name"] for s in graph["stage_sequence"])
            spec = graph["topology_spec"]
            graph_rows.append(dict(job_id=job["run_id"], turn_index=graph["turn_index"], root_pattern=root_pattern(spec), groups=len(spec["groups"]), agents=len(spec["agents"]), group_patterns=json.dumps([g["pattern"] for g in spec["groups"]]), stage_sequence=json.dumps(graph["stage_sequence"])))
        completed = [q for q in row["llm_requests"] if q["status"] == "completed"]
        assert sum(q["token_in"] for q in completed) == row["token_in"] and sum(q["token_out"] for q in completed) == row["token_out"]
        selected[job["run_id"]] = export.enrich(row)
        episode_rows.append(dict(job_id=job["run_id"], selected_attempt=path.parent.name, suite=row["suite"], condition=row["condition"], task_success=row["task_success"], attack_success=row["attack_success"], attack_exposed=row["attack_exposed"], initial_root_pattern=root_pattern(graphs[0]["topology_spec"]), final_root_pattern=root_pattern(graphs[-1]["topology_spec"]), executed_turns=len(graphs), actual_spec_changed=any(signature(g["topology_spec"]) != signature(graphs[0]["topology_spec"]) for g in graphs[1:]), token_in=row["token_in"], token_out=row["token_out"], latency_s=row["latency_s"], initial_agents=row["initial_agent_count"], peak_agents=row["peak_agent_count"], handoffs=row["handoff_count"], mutations=row["topology_mutation_count"]))
    rows = list(selected.values())
    from agentdojo_manta.metrics import summarize
    for key, value in summarize(rows).items():
        assert summary[key] == value, key
    assert len(rows) == 160
    adapter_digest = episode._source_digest([ROOT / "src/agentdojo_manta", ROOT / "scripts/manta/run_agentdojo_manta.py"])
    manta_digest = episode._source_digest([ROOT / "upstreams/manta"])
    assert {r["adapter_source_digest"] for r in rows} == {adapter_digest}
    assert {r["manta_source_digest"] for r in rows} == {manta_digest}
    with sqlite3.connect((run / "budget.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        assert {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {"requests", "settings"}
        ledger = {i: dict(amount_nanodollars=a, state=s) for i, a, s in db.execute("SELECT id,amount,state FROM requests")}
        settings = dict(db.execute("SELECT key,value FROM settings"))
    assert not any(r["state"] == "pending" for r in ledger.values())
    assert abs(sum(r["amount_nanodollars"] for r in ledger.values()) / 1e9 - summary["budget"]["accounted_upper_bound_usd"]) < 1e-9
    completions, models, limits, errors = {}, Counter(), Counter(), Counter()
    for path in run.rglob("requests.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            q = json.loads(line)
            if q["status"] == "pending":
                limits[q["max_tokens"]] += 1
            elif q["status"] == "completed":
                models[q["provider_model"]] += 1
                amount = q["token_in"] * 300 + q["token_out"] * 1200
                assert abs(amount / 1e9 - q["cost_upper_bound_usd"]) < 1e-10
                assert ledger[q["budget_request_id"]] == dict(amount_nanodollars=amount, state="settled")
                completions[q["budget_request_id"]] = amount
            else:
                errors[q.get("error_type", q["status"])] += 1
    probe = load(run / "connectivity.json")
    assert probe["status"] == "completed" and probe["requested_model"] == "deepseek-flash"
    probe_amount = probe["usage"]["prompt_tokens"] * 300 + probe["usage"]["completion_tokens"] * 1200
    assert ledger[probe["budget_request_id"]] == dict(amount_nanodollars=probe_amount, state="settled")
    assert set(completions) | {probe["budget_request_id"]} == {k for k, v in ledger.items() if v["state"] == "settled"}
    assert set(limits) == {16384}
    current = export.aggregate(rows)
    graph_metrics = dict(initial_root_patterns=dict(Counter(r["initial_root_pattern"] for r in episode_rows)), executed_group_pattern_occurrences=dict(Counter(g["pattern"] for r in rows for e in r["manta_metadata"]["self_evolved"]["execution_graphs"] for g in e["topology_spec"]["groups"])), repair_execution_episodes=sum(r["executed_turns"] > 1 for r in episode_rows), actual_spec_changed_episodes=sum(r["actual_spec_changed"] for r in episode_rows), root_pattern_changed_episodes=sum(r["initial_root_pattern"] != r["final_root_pattern"] for r in episode_rows), nested_group_episodes=sum(any(len(e["topology_spec"]["groups"]) > 1 for e in r["manta_metadata"]["self_evolved"]["execution_graphs"]) for r in rows))
    old = frozen_json("reports/2026-10-28-gpt4o-agentdojo/comparison_summary.json")["models"]
    old["DeepSeek Pro 16K"] = frozen_json("reports/2026-10-28-deepseek-pro-16k/metrics.json")
    old["Flash adaptive 16K"] = current
    with (ROOT / "reports/2026-10-19-manta-agentdojo/episode_results.csv").open(encoding="utf-8-sig", newline="") as stream:
        baseline_rows = {r["queue_run_id"]: r for r in csv.DictReader(stream)}
    paired = {}
    for condition in ("clean", "attack"):
        paired[condition] = dict(Counter(("both_success" if left and right else "both_fail" if not left and not right else "baseline_only_success" if left else "adaptive_only_success") for job, row in selected.items() if row["condition"] == condition for left, right in [(baseline_rows[job]["task_success"] == "True", row["task_success"] is True)]))
    write_csv("episode_results.csv", episode_rows)
    write_csv("execution_graphs.csv", graph_rows)
    write_csv("model_comparison.csv", [dict(experiment=name, clean_success=round(m["benign_utility"] * 80), attacked_task_success=round(m["utility_under_attack"] * 80), attack_goal_success=round(m["targeted_asr"] * 80), token_in=m["token_in"], token_out=m["token_out"], mean_latency_s=m["mean_latency_s"]) for name, m in old.items()])
    for name, value in (("manifest.json", manifest), ("summary.json", summary), ("metrics.json", current), ("topology_summary.json", graph_metrics), ("paired_comparison.json", paired), ("connectivity.json", probe), ("budget_ledger.json", dict(scope="independent Flash adaptive run including connectivity; not invoice cost", settings=settings, requests=ledger))):
        save(name, value)
    save("audit_checks.json", dict(valid_episodes=160, official_trace_matches=160, original_scene_and_payload_checks=80, frozen_source_matches=True, source_sha256=manifest["source_sha256"], adapter_digest=adapter_digest, manta_digest=manta_digest, execution_commits=sorted({r["agentdojo_commit"] for r in rows}), actual_response_models=dict(models), request_output_limits=dict(limits), completed_requests_reconciled=len(completions), connectivity_reconciled=True, budget_pending_requests=0, journal_errors=dict(errors)))
    interesting = {"banking_01__clean", *[job for job, r in selected.items() if r["attack_success"] is True]}
    interesting.update(job for job, r in selected.items() if any(len(e["topology_spec"]["groups"]) > 1 for e in r["manta_metadata"]["self_evolved"]["execution_graphs"]))
    save("topology_cases.json", {job: dict(task_success=selected[job]["task_success"], attack_success=selected[job]["attack_success"], execution_graphs=selected[job]["manta_metadata"]["self_evolved"]["execution_graphs"]) for job in sorted(interesting)})
    lines = ["# DeepSeek Flash：自适应拓扑实验", "", "已完成 80 个冻结场景、160/160 条有效 Clean/direct 配对 episode；0 条无效。原始证据位于本机 D 盘，本报告与脱敏导出全部为离线操作。", "", "## 四组结果", "", "| 实验 | Clean 成功 | 攻击下任务成功 | 攻击成功 ASR | 平均 episode 时间 |", "|---|---:|---:|---:|---:|"]
    for name, metric in old.items():
        lines.append(f"| {name} | {round(metric['benign_utility']*80)}/80 ({metric['benign_utility']:.2%}) | {round(metric['utility_under_attack']*80)}/80 ({metric['utility_under_attack']:.2%}) | {round(metric['targeted_asr']*80)}/80 ({metric['targeted_asr']:.2%}) | {metric['mean_latency_s']:.2f} s |")
    lines += ["", "## 这轮实际执行的结构", "", f"- 初始根结构：{graph_metrics['initial_root_patterns']}。", f"- 全部执行轮次的组模式出现次数：{graph_metrics['executed_group_pattern_occurrences']}，包含嵌套子组，不是 episode 数。", f"- {graph_metrics['repair_execution_episodes']} 条 episode 执行了第二轮；其中 {graph_metrics['actual_spec_changed_episodes']} 条实际规格改变，{graph_metrics['root_pattern_changed_episodes']} 条根模式改变，{graph_metrics['nested_group_episodes']} 条出现嵌套子组。", f"- 初始人数分布：{current['initial_agent_counts']}；峰值人数：{current['peak_agent_counts']}。", "- 逐轮实际图及 stage 顺序见 [execution_graphs.csv](execution_graphs.csv)，代表案例见 [topology_cases.json](topology_cases.json)。修复提案和接受后的规格仍完整保存在日志中。", "", "## 配置与适用范围", "", "所有模型角色使用 deepseek-flash，thinking enabled，输出 16384；初始预算 5、总上限 10、hybrid audit、max_turns=2、repair_budget=1、每次最多 3 个操作；8 条 episode 并发，seed42。", "", "本轮 adaptive_native 是显式源码补丁：保留工具即时改变官方模拟环境的语义，取消强制 star 归一和成功写操作后的直接停修复。长期 playbook 冻结，没有原文每 12 次运行的在线更新。本轮是论文式任务内自适应在 AgentDojo 上的适配，不能称为原论文全部设置的精确复现。", "", "相较旧 Flash，还改变了输出上限、初始团队预算和审计方式，因此四组表属于完整配置的描述性比较，不能将差异归因于单一拓扑因素。只有单 seed，且 Banking 有重复用户任务。", "", "## 结果与费用", "", f"- Clean 65/80、攻击下任务成功 66/80、ASR 1/80，与旧 Flash 的汇总数相同。Clean 共同成功 {paired['clean'].get('both_success',0)}、共同失败 {paired['clean'].get('both_fail',0)}、仅旧轮成功 {paired['clean'].get('baseline_only_success',0)}、仅本轮成功 {paired['clean'].get('adaptive_only_success',0)}；攻击下对应为 {paired['attack'].get('both_success',0)}、{paired['attack'].get('both_fail',0)}、{paired['attack'].get('baseline_only_success',0)}、{paired['attack'].get('adaptive_only_success',0)}。", "- 本轮唯一攻击成功为 slack_14__attack；旧 Flash 为 slack_07__attack。相同汇总 ASR 不表示同一场景被攻破。", f"- 输入 {current['token_in']:,}、输出 {current['token_out']:,}，合计 {current['observed_tokens']:,} tokens。", f"- 独立预算累计估算上界 ${summary['budget']['accounted_upper_bound_usd']:.7f}/$100：已返回用量 ${summary['budget']['response_cost_upper_bound_usd']:.7f}，未返回用量预留 ${summary['budget']['unreturned_reservations_usd']:.7f}。缓存与非峰时折扣忽略，实际账单 UNKNOWN。", f"- 确认攻击暴露 {summary['exposed_attack_n']}/80，UNKNOWN {summary['exposure_unknown_n']}/80；有效结果内保留请求错误 {current['selected_request_errors']} 次。", "", "## 文件入口", "", "- [160 条结果](episode_results.csv) · [四组比较](model_comparison.csv) · [冻结配置](manifest.json) · [核对记录](audit_checks.json)", "- [日志包](logs/README.md) · [逐文件清单](published_log_inventory.csv) · [校验值](checksums.sha256) · [预算台账](budget_ledger.json)", "- 分支 codex/deepseek-flash-adaptive；实验执行提交：" + ", ".join(sorted({r['agentdojo_commit'] for r in rows})) + "。", ""]
    (OUT / "README.md").write_bytes("\n".join(lines).encode())
    print("ANALYZED " + json.dumps(dict(valid=160, topology=graph_metrics, paired=paired, models=dict(models)), ensure_ascii=False), flush=True)
    if args.analysis_only:
        return
    archives = archive(run, redactor, export.sha)
    save("redaction_summary.json", dict(scope="all retained adaptive Flash files", archives=archives, replacements=dict(redactor.counts), text_cache=redactor.text.cache_info()._asdict(), replacement_counter_note="Text substitutions counted on unique-string cache misses; sensitive fields counted per visit.", raw_files_untouched=True, notes=["Credentials, home paths and synthetic contact/account secrets are redacted.", "Scores and topology metrics are computed on original evidence; public copies are not byte-exact judge inputs."]))
    lines = ["# 自适应 Flash 脱敏日志", "", "本轮全部保留文件按套件分包，包含请求、工具轨迹、实际执行图、官方判分、失败请求和独立预算台账。", "", "| 压缩包 | 文件数 | MiB |", "|---|---:|---:|"]
    lines += [f"| [{Path(a['archive']).name}]({Path(a['archive']).name}) | {a['files']} | {a['compressed_bytes']/2**20:.2f} |" for a in archives]
    lines += ["", "原始和公开文件哈希见 [inventory](../published_log_inventory.csv)，全部报告与包哈希见 [checksums](../checksums.sha256)。原始证据保持在本机 D 盘。", ""]
    (OUT / "logs/README.md").write_bytes("\n".join(lines).encode())
    for path in OUT.rglob("*"):
        if path.is_file() and path.suffix != ".gz":
            redactor.scan(path.read_bytes())
    export.checksums()
    print(f"PUBLICATION_READY {sum(a['files'] for a in archives)} files; {len(archives)} archives", flush=True)


if __name__ == "__main__":
    main()
