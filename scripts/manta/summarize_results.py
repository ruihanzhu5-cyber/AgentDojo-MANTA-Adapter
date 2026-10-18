"""Aggregate schema-v2 episode results without mixing experiment settings."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from agentdojo_manta.metrics import summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    groups = defaultdict(list)
    identities = set()
    rejected = []
    for path in sorted(args.root.rglob("result.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("metric_schema_version") != "2":
            rejected.append(str(path))
            continue
        config = row.get("config", {})
        settings = {key: config.get(key) for key in
                    ("planner_mode", "num_agents", "max_turns", "repair_budget", "audit_mode", "allow_mock")}
        settings.update(row.get("manta_metadata", {}).get("manta_config", {}))
        settings.update({key: row.get(key) for key in
                         ("system", "benchmark", "benchmark_version", "agentdojo_commit", "manta_commit", "model",
                          "adapter_source_digest", "manta_source_digest")})
        settings["attack"] = row.get("attack") or "paired-clean"
        # Clean and Attack are grouped below by compatible settings. Attack
        # families remain separate; Clean is explicitly an independent group.
        group = json.dumps(settings, sort_keys=True)
        identity = (group, row.get("suite"), row.get("task_id"), row.get("injection_task"),
                    row.get("condition"), row.get("seed"))
        if identity in identities:
            raise SystemExit(f"Duplicate episode identity at {path}; select the intended runs before aggregating")
        identities.add(identity)
        groups[group].append(row)
    output = {"metric_schema_version": "2", "rejected_legacy_files": rejected,
              "groups": [{"settings": json.loads(key), **summarize(rows)} for key, rows in groups.items()],
              "note": "Rates are episode-weighted. Clean tasks are separate groups; do not duplicate them per attack or mix seeds as independent tasks. Confidence intervals require clustering by user task."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"groups={len(groups)} rejected_legacy={len(rejected)} output={args.output}")


if __name__ == "__main__":
    main()
