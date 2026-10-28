"""Publish retained Pro 16K evidence offline using the existing redaction exporter.

No provider calls, experiment launches, raw-evidence changes or Git operations.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "results/v1/formal_80_seed42_deepseek_pro_16k"
OUT = ROOT / "reports/2026-10-28-deepseek-pro-16k"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget-db", type=Path)
    args = parser.parse_args()
    export = module("pro_export", ROOT / "scripts/reporting/publish_gpt4o_results.py")
    shared = module("pro_redactor", ROOT / "scripts/reporting/publish_manta_results.py")
    runner = module("pro_frozen_runner", ROOT / "scripts/manta/run_formal.py")
    export.SOURCE, export.RUN, export.OUT = RUN.parent, RUN, OUT
    redactor = shared.Redactor()
    original_save = export.save_json

    def save(name, value, redact=None):
        if name == "redaction_summary.json":
            value["scope"] = "all retained DeepSeek Pro 16K formal logs"
            value["notes"] = [
                "Credentials, local homes and synthetic contact/account secrets are redacted.",
                "Metrics are computed on original logs before redaction.",
                "Redacted copies do not preserve byte-exact prompts or judge inputs.",
                "The separate shared budget export includes the interrupted 4K batch; its episodes are not included in 16K scores.",
            ]
        return original_save(name, value, redact)

    export.save_json = save
    export.archive_group = lambda path: (
        "formal-" + path.relative_to(RUN).parts[1].split("_")[0]
        if len(path.relative_to(RUN).parts) > 2
        and path.relative_to(RUN).parts[0] in {"attempts", "logs"}
        else "formal-control-and-resume"
    )
    manifest, summary = export.load(RUN / "manifest.json"), export.load(RUN / "summary.json")
    assert export.load(RUN / "active_pids.json") == []
    assert runner.fingerprint() == manifest["source_sha256"]
    rows, completed = [], {}
    limits = Counter()
    for job in manifest["jobs"]:
        found = [export.load(p) for p in (RUN / "attempts" / job["run_id"]).glob("*/result.json")]
        valid = [r for r in found if r.get("evaluation_valid") is True]
        assert len(valid) == 1, job["run_id"]
        row = valid[0]
        assert not row["mock_used"] and row["max_output_tokens"] == 16384
        assert all(row[k] == job[k] for k in ("suite", "condition", "task_id"))
        assert row["injection_task"] == (job["injection_task"] if job["condition"] == "attack" else None)
        rows.append(row)
    for path in RUN.rglob("requests.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            q = json.loads(line)
            if q["status"] == "pending":
                limits[q["max_tokens"]] += 1
            elif q["status"] == "completed":
                assert q["provider_model"] == "deepseek-v4-pro"
                cost = q["token_in"] * 1320 + q["token_out"] * 3960
                assert abs(cost / 1e9 - q["cost_upper_bound_usd"]) < 1e-10
                completed[q["budget_request_id"]] = cost
    assert set(limits) == {16384} and len(rows) == 160
    db_path = (args.budget_db or Path(manifest["budget_db"])).resolve()
    with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
        requests = {i: dict(amount_nanodollars=a, state=s) for i, a, s in db.execute("SELECT id,amount,state FROM requests")}
        settings = dict(db.execute("SELECT key,value FROM settings"))
    assert not any(r["state"] == "pending" for r in requests.values())
    assert abs(sum(r["amount_nanodollars"] for r in requests.values()) / 1e9 - summary["budget"]["accounted_upper_bound_usd"]) < 1e-9
    for key, amount in completed.items():
        assert requests[key] == dict(amount_nanodollars=amount, state="settled")
    from agentdojo_manta.metrics import summarize
    for key, value in summarize(rows).items():
        assert summary[key] == value, key
    for name in ("manifest.json", "summary.json", "connectivity.json"):
        save(name, export.load(RUN / name), redactor)
    save("shared_budget_ledger.json", dict(scope="cumulative Pro 4K and 16K; not invoice cost", settings=settings, requests=requests), redactor)
    save("audit_checks.json", dict(valid_episodes=160, frozen_source_matches=True, actual_models=["deepseek-v4-pro"], request_output_limits=dict(limits), completed_16k_requests_reconciled=len(completed), budget_pending_requests=0, execution_commits=sorted({r["agentdojo_commit"] for r in rows}), adapter_digests=sorted({r["adapter_source_digest"] for r in rows}), manta_digests=sorted({r["manta_source_digest"] for r in rows})))
    export.archive_logs(redactor)
    archives=export.load(OUT / "redaction_summary.json")["archives"]
    lines=["# DeepSeek Pro 16K 脱敏日志", "", "所有 16K 正式运行保留文件的脱敏副本，按套件分包。原始证据留在本机；不上传 .env。", "", "| 日志包 | 文件数 | MiB |", "|---|---:|---:|"]
    lines += [f"| [{Path(a['archive']).name}]({Path(a['archive']).name}) | {a['files']} | {a['compressed_bytes']/2**20:.2f} |" for a in archives]
    lines += ["", "逐文件原始/公开 SHA256 见 [inventory](../published_log_inventory.csv)，压缩包和报告校验值见 [checksums](../checksums.sha256)。", "", "共享预算 JSON 包含此前中断的 4K 批次费用；该批次的任务不进入本轮 160 条统计。", ""]
    (OUT / "logs/README.md").write_text("\n".join(lines), encoding="utf-8")
    for path in OUT.rglob("*"):
        if path.is_file() and path.suffix != ".gz":
            data = path.read_bytes().replace(b"\r\n", b"\n")
            redactor.scan(data)
            path.write_bytes(data)
    export.checksums()
    print(f"Published {sum(a['files'] for a in archives)} redacted files in {len(archives)} archives", flush=True)


if __name__ == "__main__":
    main()
