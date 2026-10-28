"""One operator-launched Flash connectivity request, included in the new $100 cap."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    from agentdojo_manta.providers import provider_config
    from agentdojo_manta.budget import RequestBudget
    from agentdojo_manta.deepseek_pro import validate_flash_response
    binding = provider_config("deepseek-flash")
    if binding.name != "deepseek" or binding.base_url.rstrip("/") != "https://api.deepseek.com/v1" or not binding.api_key:
        raise SystemExit("Official Flash route and existing DEEPSEEK_API_KEY required")
    if os.getenv("V1_MAX_COST_USD") != "100":
        raise SystemExit("This run requires the approved independent $100 cap")
    folder = args.run_dir.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    ledger = str(folder / "budget.sqlite")
    budget = RequestBudget(ledger, "100")
    path = folder / "connectivity.json"
    if path.exists():
        prior = json.loads(path.read_text(encoding="utf-8"))
        if prior.get("status") == "completed" and prior.get("requested_model") == "deepseek-flash" and prior.get("endpoint") == binding.base_url and prior.get("budget_db") == ledger:
            print("Successful Flash connectivity receipt retained; no repeated probe.", flush=True)
            return
        if prior.get("budget_request_id"):
            budget.uncertain(prior["budget_request_id"])
        path.rename(folder / f"connectivity.failed.{uuid.uuid4().hex[:8]}.json")
    request_id = budget.reserve("deepseek-flash", 256)
    record = dict(status="pending", requested_model="deepseek-flash", endpoint=binding.base_url,
                  budget_db=ledger, budget_request_id=request_id, max_tokens=256)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    start = time.perf_counter()
    try:
        with OpenAI(api_key=binding.api_key, base_url=binding.base_url, timeout=180, max_retries=0) as client:
            response = client.chat.completions.create(model="deepseek-flash", max_tokens=256,
                messages=[{"role": "user", "content": "Reply OK."}], extra_body={"thinking": {"type": "enabled"}})
        validate_flash_response(response)
        record.update(status="completed", provider_model=response.model, response_id=response.id,
                      usage=response.usage.model_dump(), cost_upper_bound_usd=budget.settle(request_id, response.usage))
    except Exception as exc:
        budget.uncertain(request_id)
        record.update(status="error", error_type=type(exc).__name__, http_status=getattr(exc, "status_code", None))
        raise
    finally:
        record.update(latency_s=time.perf_counter() - start, budget=budget.snapshot())
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(record, indent=2), flush=True)


if __name__ == "__main__":
    main()
