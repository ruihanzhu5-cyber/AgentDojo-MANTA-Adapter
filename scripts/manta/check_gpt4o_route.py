"""Read-only route/pricing evidence. Never sends a model-generation request."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main():
    load_dotenv(ROOT / ".env", override=False)
    from agentdojo_manta.providers import provider_config
    provider = provider_config("gpt-4o")
    if provider.name != "qdd" or not provider.api_key:
        raise SystemExit("Expected configured QDD GPT-4o credential")
    origin = "https://" + urlsplit(provider.base_url).netloc
    output = dict(checked_at=datetime.now(timezone.utc).isoformat(), provider=provider.name,
                  endpoint=provider.base_url, model="gpt-4o", generation_requests=0, sources=[])
    for endpoint in ("/v1/models", "/api/pricing", "/api/usage/token", "/api/log/token"):
        headers = {} if endpoint == "/api/pricing" else {"Authorization": "Bearer " + provider.api_key}
        try:
            response = requests.get(origin + endpoint, headers=headers, timeout=30, allow_redirects=False)
            row = {"path": endpoint, "http_status": response.status_code}
            if response.status_code == 200:
                data = response.json()
                if endpoint == "/v1/models":
                    row["gpt4o_visible"] = any(x.get("id") == "gpt-4o" for x in data.get("data", []))
                elif endpoint == "/api/pricing":
                    row["gpt4o"] = [{k: x.get(k) for k in ("model_name", "model_ratio", "completion_ratio", "cache_ratio", "quota_type")} for x in data.get("data", []) if x.get("model_name") == "gpt-4o"]
                    row["group_ratio"] = data.get("group_ratio")
                elif endpoint == "/api/usage/token":
                    value = data.get("data", {})
                    row["field_names"] = sorted(value) if isinstance(value, dict) else []
                    row["group"] = value.get("group") if isinstance(value, dict) else None
                else:
                    rows = data.get("data", [])
                    if isinstance(rows, dict):
                        rows = rows.get("items", rows.get("logs", []))
                    billing = []
                    for item in rows if isinstance(rows, list) else []:
                        if item.get("model_name") != "gpt-4o":
                            continue
                        other = item.get("other", {})
                        if isinstance(other, str):
                            other = json.loads(other)
                        billing.append(dict(created_at=item.get("created_at"), **{k: other.get(k) for k in ("model_ratio", "completion_ratio", "group_ratio", "user_group_ratio")}))
                    row["gpt4o_billing_count"] = len(billing)
                    row["latest_gpt4o_billing"] = sorted(billing, key=lambda x: x["created_at"] or 0, reverse=True)[:3]
            output["sources"].append(row)
        except (requests.RequestException, ValueError) as exc:
            output["sources"].append({"path": endpoint, "error_type": type(exc).__name__})
    dest = ROOT / "results" / "v1" / "gpt4o_preflight"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "route_evidence.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
