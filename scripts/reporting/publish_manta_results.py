"""Recompute the formal results and archive all retained V1 logs with redaction.

Offline only. Does not modify original evidence, call a model, or push to GitHub.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import sqlite3
import statistics
import sys
import tarfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "results" / "v1"
OUT = ROOT / "reports" / "2026-10-19-manta-agentdojo"
sys.path.insert(0, str(ROOT / "src"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def save_csv(name, rows):
    with (OUT / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class Redactor:
    credential = re.compile(r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{30,}|AKIA[A-Z0-9]{16})\b")
    jwt = re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b")
    home = re.compile(r"[A-Za-z]:[/\\]+Users[/\\]+[^/\\\s\"'<>]+", re.I)
    email = re.compile(r"(?<![\w.+-])[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")
    iban = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b")
    number = re.compile(r"(?<![\w.])(?:\+?\d[ -]?){10,19}(?![\w.])")
    date = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?\b")
    phone = re.compile(r"(?<!\w)(?:\+?\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\w)")
    field = re.compile(r"password|passwd|api_key|(?:^|_)token$|authorization|secret|private_key|credit_card|card_number|account_number|bank_account|iban|social_security|phone|telephone|cvv|^pin$", re.I)
    inline = re.compile(r"(?i)\b(password|passwd|api[ _-]?key|(?:access[ _-]?)?token|secret|authorization|pin|cvv)\b([\s\"'`]*(?::|=|\bis\b)[\s\"'`]*)(?!<REDACTED)([^\s,;\"'`<>\\}{\[\]]{3,256})")
    bearer = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*")
    pem = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.S)

    def __init__(self):
        self.counts, self.identities = Counter(), {}
        env = dict(os.environ)
        from dotenv import dotenv_values
        env.update({k: v for k, v in dotenv_values(ROOT / ".env").items() if v})
        self.secrets = sorted({v for k, v in env.items() if isinstance(v, str) and len(v) >= 12
                               and k.upper().endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))}, key=len, reverse=True)

    def marker(self, category, value=""):
        self.counts[category] += 1
        if category in {"EMAIL", "ACCOUNT", "LONG_IDENTIFIER"}:
            key = category, value
            if key not in self.identities:
                self.identities[key] = len(self.identities) + 1
            return f"<REDACTED_{category}_{self.identities[key]:05d}>"
        return f"<REDACTED_{category}>"

    def text(self, value):
        dates = []
        def protect_date(match):
            dates.append(match[0])
            return f"<PUBLIC_DATE_{len(dates)-1}>"
        value = self.date.sub(protect_date, value)
        for secret in self.secrets:
            self.counts["ENV_CREDENTIAL"] += value.count(secret)
            value = value.replace(secret, "<REDACTED_ENV_CREDENTIAL>")
        for source in (str(ROOT), str(ROOT).replace("\\", "/"), str(ROOT).replace("\\", "\\\\")):
            value = value.replace(source, "<REPO>")
        for pattern, category in ((self.home, "USER_HOME"), (self.pem, "PRIVATE_KEY"),
                                  (self.credential, "CREDENTIAL"), (self.jwt, "JWT"), (self.bearer, "AUTHORIZATION")):
            value = pattern.sub(lambda m: self.marker(category), value)
        for pattern, category in ((self.email, "EMAIL"), (self.iban, "ACCOUNT"), (self.phone, "PHONE"), (self.number, "LONG_IDENTIFIER")):
            value = pattern.sub(lambda m: self.marker(category, m[0]), value)
        value = self.inline.sub(lambda m: m[1] + m[2] + self.marker("INLINE_SECRET"), value)
        for index, date in enumerate(dates):
            value = value.replace(f"<PUBLIC_DATE_{index}>", date)
        return value

    def obj(self, value):
        if isinstance(value, dict):
            return {k: self.marker("SENSITIVE_FIELD") if self.field.search(k) and v not in (None, "", [], {})
                    else self.obj(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.obj(v) for v in value]
        return self.text(value) if isinstance(value, str) else value

    def scan(self, data):
        text = data.decode("utf-8", errors="ignore")
        if any(s in text for s in self.secrets) or any(p.search(text) for p in (self.credential, self.jwt, self.pem, self.home)):
            raise ValueError("Credential/private path remains in exported content; refusing publication")


def structural_change(row):
    def signature(v):
        return json.dumps({k: v.get(k) for k in ("agents", "groups", "root_group_id", "extra_edges")}, sort_keys=True)
    versions = row["manta_metadata"]["self_evolved"]["topology_spec_versions"]
    return any(signature(a) != signature(b) for a, b in zip(versions, versions[1:]))


def analyze(redactor):
    from agentdojo_manta.metrics import summarize
    run = SOURCE / "formal_80_seed42"
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    assert json.loads((run / "active_pids.json").read_text()) == []
    rows, episodes, attempts, times, errors = [], [], [], [], Counter()
    for job in manifest["jobs"]:
        valid = []
        for directory in sorted((run / "attempts" / job["run_id"]).glob("attempt_*")):
            path = directory / "result.json"
            row = json.loads(path.read_text(encoding="utf-8"))
            assert (row["suite"], row["task_id"], row["condition"], row["seed"], row["model"]) == (
                job["suite"], job["task_id"], job["condition"], manifest["config"]["seed"], manifest["config"]["model"])
            if job["condition"] == "attack":
                assert row["injection_task"] == job["injection_task"] and row["attack"] == "direct"
            for q in row["llm_requests"]:
                if q["status"] != "completed":
                    errors[(q.get("error_type"), q.get("http_status"))] += 1
            record = dict(scene_id=job["scene_id"], queue_run_id=job["run_id"], attempt=directory.name, selected=False,
                          result_path=path.relative_to(SOURCE).as_posix(), evaluation_valid=row["evaluation_valid"],
                          run_status=row["run_status"], task_success=row["task_success"], attack_success=row["attack_success"],
                          observed_tokens=row["observed_tokens"], llm_error_requests=row["llm_error_request_count"], latency_s=row["latency_s"])
            attempts.append(record)
            if row["evaluation_valid"] is True:
                valid.append((row, path, record))
        assert len(valid) == 1, job["run_id"]
        row, path, record = valid[0]
        record["selected"] = True
        assert row["mock_used"] is False and row["task_success"] == row["official_utility"]
        assert row["attack_success"] == (None if row["condition"] == "clean" else row["official_security"])
        traces = [json.loads(p.read_text(encoding="utf-8")) for p in (run / "logs" / job["run_id"] / path.parent.name).rglob("*.json")]
        assert len(traces) == 1 and not traces[0]["error"]
        trace = traces[0]
        assert (trace["utility"], trace["security"], trace["suite_name"], trace["user_task_id"]) == (
            row["official_utility"], row["official_security"], row["suite"], row["task_id"])
        times.append(trace["evaluation_timestamp"])
        row["publication_spec_changed"] = structural_change(row)
        rows.append(row)
        fields = ["suite", "task_id", "injection_task", "condition", "seed", "model", "evaluation_valid", "run_status",
                  "task_success", "attack_success", "attack_exposed", "token_in", "token_out", "observed_tokens", "latency_s",
                  "initial_agent_count", "peak_agent_count", "final_agent_count", "actual_agent_count", "handoff_count",
                  "real_multiagent_handoff", "topology_mutation_count", "publication_spec_changed", "planner_used_fallback",
                  "llm_request_count", "llm_completed_request_count", "llm_error_request_count", "cost_usd"]
        episodes.append(dict(scene_id=job["scene_id"], queue_run_id=job["run_id"], selected_attempt=path.parent.name,
                             result_path=path.relative_to(SOURCE).as_posix(), **{k: row[k] for k in fields}))
    for key, value in summarize(rows).items():
        assert summary[key] == value, key
    assert len(rows) == 160 and all(r["evaluation_valid"] for r in rows)
    resources, table = [], []
    for condition in ("clean", "attack"):
        rr = [r for r in rows if r["condition"] == condition]
        resources.append(dict(condition=condition, episodes=len(rr), observed_tokens=sum(r["observed_tokens"] for r in rr),
                              mean_tokens=statistics.mean(r["observed_tokens"] for r in rr),
                              mean_latency_s=statistics.mean(r["latency_s"] for r in rr), median_latency_s=statistics.median(r["latency_s"] for r in rr),
                              live_handoff_episodes=sum(r["real_multiagent_handoff"] is True for r in rr),
                              handoff_count=sum(r["handoff_count"] for r in rr), mutation_records=sum(r["topology_mutation_count"] for r in rr),
                              spec_changed_episodes=sum(r["publication_spec_changed"] for r in rr),
                              planner_fallback_episodes=sum(r["planner_used_fallback"] is True for r in rr)))
    for suite in ("ALL", "banking", "slack", "travel", "workspace"):
        rr = rows if suite == "ALL" else [r for r in rows if r["suite"] == suite]
        totals = summarize(rr)
        if suite != "ALL":
            assert summary["by_suite"][suite] == totals
        table.append(dict(system="MANTA", suite=suite,
                          clean_success=sum(r["task_success"] for r in rr if r["condition"] == "clean"),
                          attack_task_success=sum(r["task_success"] for r in rr if r["condition"] == "attack"),
                          attack_goal_success=sum(r["attack_success"] for r in rr if r["condition"] == "attack"),
                          **totals, observed_tokens=sum(r["observed_tokens"] for r in rr), invoice_cost_usd="UNKNOWN"))
    script = ROOT / "scripts" / "manta" / "run_agentdojo_manta.py"
    spec = importlib.util.spec_from_file_location("episode_runner", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    adapter_digest = module._source_digest([ROOT / "src" / "agentdojo_manta", script])
    manta_digest = module._source_digest([ROOT / "upstreams" / "manta"])
    assert {r["adapter_source_digest"] for r in rows} == {adapter_digest}
    assert {r["manta_source_digest"] for r in rows} == {manta_digest}
    c = sqlite3.connect((run / "budget.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
    ledger = [dict(request_id=i, amount_nanodollars=a, state=s) for i, a, s in c.execute("SELECT id,amount,state FROM requests ORDER BY id")]
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    c.close()
    assert all(r["state"] != "pending" for r in ledger)
    assert abs(sum(r["amount_nanodollars"] for r in ledger)/1e9-summary["budget"]["accounted_upper_bound_usd"]) < 1e-9
    provenance = dict(recorded_base_git_commits=sorted({r["agentdojo_commit"] for r in rows}), adapter_source_sha256=adapter_digest,
                      manta_source_sha256=manta_digest, frozen_source_sha256=manifest["source_sha256"],
                      upstream_agentdojo_commit=rows[0]["agentdojo_upstream_commit"], upstream_manta_commit=rows[0]["manta_commit"],
                      response_models=dict(Counter(q.get("provider_model") for r in rows for q in r["llm_requests"] if q["status"] == "completed")),
                      note="Execution used working-tree changes beyond the recorded baseline HEAD. Publication includes those files; SHA256 matches every selected episode.")
    paired = defaultdict(dict)
    for e in episodes:
        paired[e["scene_id"]][e["condition"]] = e["task_success"]
    pairs = Counter((r["clean"], r["attack"]) for r in paired.values())
    checks = dict(type="mechanical_consistency_checks_not_independent_cross_model_audit", selected_valid_episodes=160,
                  retained_formal_attempts=len(attempts), official_raw_trace_score_matches=160, source_digest_matches=160,
                  no_selected_mock=True, job_identities_match=True, recomputed_summary_matches=True, budget_integrity="ok",
                  requests_by_state=dict(Counter(r["state"] for r in ledger)),
                  request_errors=[dict(type=k[0], http_status=k[1], count=v) for k, v in errors.items()],
                  evaluation_timestamps=dict(first=min(times), last=max(times), timezone="as recorded, no offset stored"),
                  paired_utility_counts={"both_success": pairs[True, True], "both_failed": pairs[False, False],
                                         "clean_only_success": pairs[True, False], "attack_only_success": pairs[False, True]})
    for name, value in (("manifest.json", manifest), ("summary.json", summary), ("source_provenance.json", provenance),
                        ("audit_checks.json", checks), ("budget_ledger.json", ledger)):
        save_json(name, redactor.obj(value))
    for name, values in (("episode_results.csv", episodes), ("attempt_results.csv", attempts),
                         ("resource_metrics.csv", resources), ("table_e2_agentdojo.csv", table)):
        save_csv(name, values)


def archive_all(redactor):
    groups = defaultdict(list)
    for path in sorted(SOURCE.rglob("*")):
        if path.is_file():
            rel = path.relative_to(SOURCE)
            groups[rel.parts[0] if len(rel.parts) > 1 else "root_files"].append(path)
    inventory, archives = [], []
    (OUT / "logs").mkdir(exist_ok=True)
    for group, files in sorted(groups.items()):
        destination = OUT / "logs" / f"{group}.tar.gz"
        before = Counter(redactor.counts)
        with destination.open("wb") as f, gzip.GzipFile(fileobj=f, filename="", mode="wb", mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in files:
                    raw = path.read_bytes()
                    if path.suffix == ".json":
                        public = (json.dumps(redactor.obj(json.loads(raw.decode("utf-8"))), ensure_ascii=False, indent=2)+"\n").encode()
                    elif path.suffix in {".log", ".csv", ".lock"}:
                        public = redactor.text(raw.decode("utf-8")).encode()
                    elif path.suffix == ".sqlite":
                        public = raw  # Request UUID, state and cost ledger only; no credentials.
                    else:
                        raise ValueError(f"Unreviewed format: {path.suffix}")
                    redactor.scan(public)
                    rel = path.relative_to(SOURCE).as_posix()
                    info = tarfile.TarInfo(rel)
                    info.size, info.mode, info.mtime = len(public), 0o644, 0
                    archive.addfile(info, io.BytesIO(public))
                    inventory.append(dict(source_path=rel, archive=destination.relative_to(OUT).as_posix(),
                                          raw_bytes=len(raw), public_bytes=len(public), raw_sha256=sha(raw),
                                          public_sha256=sha(public), content_changed=raw != public))
        expected = {r["source_path"]: r for r in inventory if r["archive"] == destination.relative_to(OUT).as_posix()}
        with tarfile.open(destination, "r:gz") as archive:
            members = archive.getmembers()
            assert len(members) == len(expected)
            for member in members:
                data = archive.extractfile(member).read()
                assert sha(data) == expected[member.name]["public_sha256"]
                redactor.scan(data)
        entry = dict(archive=destination.relative_to(OUT).as_posix(), files=len(files), raw_bytes=sum(p.stat().st_size for p in files),
                     compressed_bytes=destination.stat().st_size, sha256=sha(destination.read_bytes()), redactions=dict(redactor.counts-before))
        archives.append(entry)
        print(f"ARCHIVED {group}: {len(files)} files, {entry['compressed_bytes']} compressed bytes", flush=True)
    assert len(inventory) == sum(p.is_file() for p in SOURCE.rglob("*"))
    save_csv("published_log_inventory.csv", inventory)
    save_json("redaction_summary.json", dict(scope="all currently retained results/v1 files", archives=archives,
              replacements=dict(redactor.counts), notes=["Raw originals are not overwritten.",
              "Email/account pseudonyms are consistent within the export; the mapping is not published.",
              "Real environment credentials, local user homes, and synthetic credential/contact/account values are redacted.",
              "Raw SHA256 values refer to whole files, not individual secrets.",
              "Scores and exposure were computed on original evidence before redaction; redacted content cannot replay exact judging.",
              "Earlier deleted logs cannot be recovered. Pilot/mock/blocked attempts are included but excluded from formal denominators."]))


def checksums():
    entries = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "checksums.sha256":
            entries.append(f"{sha(path.read_bytes())}  {path.relative_to(OUT).as_posix()}")
    (OUT / "checksums.sha256").write_text("\n".join(entries)+"\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    redactor = Redactor()
    analyze(redactor)
    archive_all(redactor)
    checksums()
    print(f"COMPLETE: {OUT}", flush=True)
