"""Publish the retained context experiments offline, preserving raw evidence."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import gzip
import io
import json
from pathlib import Path
import re
import sqlite3
import tarfile

from publish_manta_results import ROOT, SOURCE, Redactor, sha

OUT = ROOT / "reports/2026-10-19-context-mechanisms"


def render(path, redactor):
    raw = path.read_bytes()
    if path.suffix == ".json":
        data = (json.dumps(redactor.obj(json.loads(raw.decode("utf-8"))), ensure_ascii=False, indent=2) + "\n").encode()
    elif path.suffix == ".jsonl":
        data = "".join(json.dumps(redactor.obj(json.loads(line)), ensure_ascii=False) + "\n"
                       for line in raw.decode("utf-8").splitlines() if line.strip()).encode()
    elif path.suffix in {".md", ".csv", ".log", ".lock"}:
        data = redactor.text(raw.decode("utf-8")).encode()
    elif path.suffix == ".sqlite":
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert tables == {"requests", "settings"}, "Unexpected private database content"
        data = raw
    else:
        raise ValueError(f"Unreviewed suffix: {path.suffix}")
    redactor.scan(data)
    return raw, data


def main():
    for name in ("context_replay_slack07_MxT", "graph_checkpoint_commit_once"):
        run = SOURCE / name
        assert json.loads((run / "progress.json").read_text(encoding="utf-8"))["complete"]
        assert json.loads((run / "active_pids.json").read_text(encoding="utf-8")) == []
    selected = sorted(f for f in SOURCE.rglob("*") if f.is_file()
                      and f.relative_to(SOURCE).parts[0].startswith(("context_replay", "graph_checkpoint")))
    groups = defaultdict(list)
    for path in selected:
        relative = path.relative_to(SOURCE)
        groups[relative.parts[0] if len(relative.parts) > 1 else "qa_root_logs"].append(path)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "logs").mkdir(exist_ok=True)
    redactor, inventory, archives = Redactor(), [], []
    for name, files in sorted(groups.items()):
        output = OUT / "logs" / f"{name}.tar.gz"
        before = Counter(redactor.counts)
        expected = {}
        with output.open("wb") as stream, gzip.GzipFile(fileobj=stream, filename="", mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for path in files:
                    raw, data = render(path, redactor)
                    relative = path.relative_to(SOURCE).as_posix()
                    member = tarfile.TarInfo(relative)
                    member.size, member.mode, member.mtime = len(data), 0o644, 0
                    tar.addfile(member, io.BytesIO(data))
                    expected[relative] = sha(data)
                    inventory.append(dict(source_path=relative, archive=output.relative_to(OUT).as_posix(),
                        raw_bytes=len(raw), public_bytes=len(data), raw_sha256=sha(raw), public_sha256=sha(data),
                        content_changed=raw != data))
        with tarfile.open(output, "r:gz") as tar:
            members = tar.getmembers()
            assert {m.name for m in members} == set(expected)
            for member in members:
                data = tar.extractfile(member).read()
                assert member.isfile() and sha(data) == expected[member.name]
                redactor.scan(data)
        assert output.stat().st_size < 90_000_000, "Split archives before GitHub upload"
        archives.append(dict(archive=output.relative_to(OUT).as_posix(), files=len(files),
            compressed_bytes=output.stat().st_size, sha256=sha(output.read_bytes()),
            redactions=dict(redactor.counts - before)))
        print(f"ARCHIVED {name}: {len(files)} files, {output.stat().st_size} bytes", flush=True)
    assert len(inventory) == len(selected)
    with (OUT / "published_log_inventory.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(inventory[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(inventory)
    curated = {
        "context_replay": ("context_replay_slack07_MxT", ["EXPERIMENT_REPORT.md", "summary.json", "manifest.json", "groups.csv"]),
        "graph_checkpoint": ("graph_checkpoint_commit_once", ["EXPERIMENT_REPORT.md", "summary.json", "manifest.json",
                             "branches_manifest.json", "progress.json", "analysis_evidence.json"]),
    }
    for folder, (run, names) in curated.items():
        destination = OUT / folder
        destination.mkdir(exist_ok=True)
        for name in names:
            _, data = render(SOURCE / run / name, redactor)
            if name == "EXPERIMENT_REPORT.md":
                text = data.decode("utf-8")
                text = re.sub(r"\]\(attempts/[^)]+\)", f"](../logs/{run}.tar.gz)", text)
                text += ("\n\n## 公开日志说明\n\n"
                         "本页为脱敏报告副本。逐次原始记录的链接指向对应日志压缩包；解压后按报告中的相对路径查找。"
                         "预检、失败尝试与有效运行一并留存，结果分母按报告定义。公开 checkpoint 已脱敏，不能直接用于严格恢复。\n")
                data = text.encode("utf-8")
                redactor.scan(data)
            (destination / name).write_bytes(data)
    (OUT / "FINDINGS.md").write_bytes(render(ROOT / "findings.md", redactor)[1])
    notes = dict(scope="All currently retained results/v1 paths whose first component starts with context_replay or graph_checkpoint",
        files=len(selected), raw_bytes=sum(f.stat().st_size for f in selected), archives=archives,
        redactions=dict(redactor.counts), notes=[
            "The earlier formal 80-scene experiment is published separately; its artifacts are not overwritten.",
            "Engineering fixtures, preflights, incomplete and failed attempts are retained but excluded from valid result denominators.",
            "Raw evidence is unchanged. Public files redact credentials, local paths and synthetic sensitive values.",
            "Public checkpoint frames and prompts are for inspection; redaction changes hashes and may change model inputs, so they are not exact runtime-restorable snapshots.",
            "raw_sha256 hashes whole original files; public_sha256 hashes exported bytes. Original metrics were evaluated before redaction.",
            "Reviewer conversation traces remain local and are not part of this public package."])
    (OUT / "redaction_summary.json").write_text(json.dumps(notes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    for path in OUT.rglob("*"):
        if path.is_file() and path.suffix != ".gz":
            redactor.scan(path.read_bytes())
    entries = [f"{sha(f.read_bytes())}  {f.relative_to(OUT).as_posix()}" for f in sorted(OUT.rglob("*"))
               if f.is_file() and f.name != "checksums.sha256"]
    (OUT / "checksums.sha256").write_text("\n".join(entries) + "\n", encoding="utf-8", newline="\n")
    print(f"COMPLETE: {len(selected)} retained files; {len(entries)} public artifact checksums", flush=True)


if __name__ == "__main__":
    main()
