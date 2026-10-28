"""One user-launched live Pro connectivity request, charged to the formal cap."""
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
    parser.add_argument("--run-dir", type=Path, default=ROOT / "results/v1/formal_80_seed42_deepseek_pro")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    from agentdojo_manta.providers import provider_config
    from agentdojo_manta.budget import DeepSeekProBudget
    from agentdojo_manta.deepseek_pro import validate_pro_response
    binding = provider_config("deepseek-v4-pro")
    if binding.name != "deepseek" or binding.base_url.rstrip("/") not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"} or not binding.api_key:
        raise SystemExit("Existing DEEPSEEK_API_KEY and official endpoint required")
    folder = args.run_dir.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "connectivity.json"
    if path.exists():
        prior = json.loads(path.read_text(encoding="utf-8"))
        if prior.get("status") == "completed" and prior.get("endpoint") == binding.base_url and prior.get("requested_model") == "deepseek-v4-pro":
            print("Completed Pro connectivity receipt retained; no new probe request.", flush=True)
            return
        path.rename(folder / f"connectivity.failed.{uuid.uuid4().hex[:8]}.json")
    budget = DeepSeekProBudget(folder / "budget.sqlite", os.environ["V1_MAX_COST_USD"])
    reservation = budget.reserve("deepseek-v4-pro", 256)
    record = dict(status="pending", request_kind="connectivity_probe", requested_model="deepseek-v4-pro",
                  endpoint=binding.base_url, max_tokens=256, budget_request_id=reservation)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    start = time.perf_counter()
    try:
        with OpenAI(api_key=binding.api_key, base_url=binding.base_url, max_retries=0, timeout=180) as client:
            response = client.chat.completions.create(model="deepseek-v4-pro", max_tokens=256,
                messages=[{"role": "user", "content": "Reply OK."}], extra_body={"thinking": {"type": "enabled"}})
        validate_pro_response(response)
        record.update(provider_model=response.model, response_id=response.id, usage=response.usage.model_dump(),
                      cost_upper_bound_usd=budget.settle(reservation, response.usage), status="completed")
    except Exception as exc:
        budget.uncertain(reservation)
        record.update(status="error", error_type=type(exc).__name__, http_status=getattr(exc, "status_code", None))
        raise
    finally:
        record.update(latency_s=time.perf_counter()-start, budget=budget.snapshot())
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(record, indent=2), flush=True)


if __name__ == "__main__":
    main()
