"""One real, budgeted GPT-4o connectivity request, separate from episode results."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main():
    load_dotenv(ROOT / ".env", override=False)
    from agentdojo_manta.budget import GPT4oBudget
    from agentdojo_manta.providers import provider_config, validate_gpt4o_response
    binding = provider_config("gpt-4o")
    folder = ROOT / "results/v1/gpt4o_preflight"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "connectivity.json"
    if path.exists():
        prior = json.loads(path.read_text(encoding="utf-8"))
        if prior.get("status") != "completed":
            raise SystemExit("Previous probe failed; inspect evidence before another request")
        print("Previously completed real connectivity probe retained.")
        return
    pilot = ROOT / "results/v1/pilot_4_seed42_gpt4o"
    pilot.mkdir(parents=True, exist_ok=True)
    budget = GPT4oBudget(pilot / "budget.sqlite", "10")
    record = dict(provider=binding.name, endpoint=binding.base_url, requested_model="gpt-4o",
                  status="pending", max_tokens=16, request_kind="connectivity_probe")
    reservation = budget.reserve("gpt-4o", 16)
    record["budget_request_id"] = reservation
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    start = time.perf_counter()
    try:
        with OpenAI(api_key=binding.api_key, base_url=binding.base_url, max_retries=0, timeout=60) as client:
            response = client.chat.completions.create(model="gpt-4o", temperature=0, max_tokens=16,
                messages=[{"role": "user", "content": "Reply with API_OK."}])
        record.update(provider_model=response.model, response_id=response.id,
                      usage=response.usage.model_dump() if response.usage else None,
                      finish_reason=response.choices[0].finish_reason if response.choices else None)
        validate_gpt4o_response(response)
        record["cost_upper_bound_usd"] = budget.settle(reservation, response.usage)
        record["status"] = "completed"
    except Exception as exc:
        budget.uncertain(reservation)
        record.update(status="error", error_type=type(exc).__name__, http_status=getattr(exc, "status_code", None))
        raise
    finally:
        record.update(latency_s=time.perf_counter() - start, budget=budget.snapshot())
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
