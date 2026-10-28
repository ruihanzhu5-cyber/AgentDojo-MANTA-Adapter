# GPT-4o replication implementation

Date: 2026-10-28 (Asia/Shanghai). Branch: `exp/gpt4o-agentdojo-replication`.

## Changes

| File | Purpose |
|---|---|
| `src/agentdojo_manta/providers.py` | Explicit DeepSeek/OpenAI/QDD endpoint and credential binding; exact GPT-4o for every role; inherited 4096 output policy; reject unexpected response models or invalid usage |
| `src/agentdojo_manta/budget.py` | Independent GPT-4o input/output rates, 128000 input / 16384 output bounds, SQLite price identity, required QDD price evidence; preserve DeepSeek accounting |
| `src/agentdojo_manta/adapter.py` | Select explicit provider, disable SDK/provider fallbacks, persist each HTTP request before submission and its response/error, include role/retry/usage/model metadata |
| `src/agentdojo_manta/replication.py` | Load the original published manifest, verify all 80 official direct payload hashes and 160 exact jobs, select deterministic 8-episode pilot, verify scores and reconcile journals with SQLite |
| `scripts/manta/run_formal.py` | Preserve the existing independent-process/resume queue; add real pilot, separate output directories, explicit formal cap and accepted-pilot gates |
| `scripts/manta/run_agentdojo_manta.py` | Record actual configured provider/model and reject invalid GPT-4o model/usage execution |
| `scripts/manta/check_gpt4o_route.py` | Read-only model/price/billing evidence, with credential and account details excluded |
| `scripts/manta/probe_gpt4o.py` | One real connectivity request sharing the pilot's cumulative $10 ledger |
| `tests/manta/test_gpt4o.py` | Focused zero-cost routing, budget, frozen-scene and SDK/tool-message checks |

No changes to `upstreams/manta/` or `src/agentdojo/`. The engine, planner, tool handlers, communication, topology mutation, recovery algorithm, official tasks, attacks and scoring remain unchanged.

## Configuration preserved

Formal execution: 80 frozen scenes; 80 clean + 80 attack; four suites × 20; official direct attack; seed 42; task_conditioned planner; heuristic audit; initial/max initial/max total agents 3/5/10; max_turns 2; repair_budget 1; max_tool_iterations 8; output cap 4096; parallel tool calls disabled; timeout 180s; 8 episode processes; default maximum 2 attempts per job. Pilot uses 1 process and first frozen scene of each suite. No extra context truncation, mock execution or model substitution is enabled for paid runs.

## Verification

- 11 focused GPT-4o tests passed, including real OpenAI SDK serialization through a local HTTP transport. Those protocol fixtures are offline tests and are not counted as real API verification.
- Existing 3 DeepSeek budget and 12 score/resource tests passed (15 total).
- Original scene/job equality and all 80 official payload hashes passed. Pilot dry-run saved 8 paired jobs and sent zero requests.
- `git diff --check` passed; no upstream MANTA or official AgentDojo source changes.
- Initial broad test discovery also attempted unrelated context-replay/graph-checkpoint tests. These depend on ignored historical raw result files absent from a clean clone. Initial sandbox runs additionally could not use temporary SQLite directories. Relevant budget tests were rerun successfully outside that sandbox restriction. These environmental failures are not claimed as passed tests, and no unrelated tests or historical results were changed.
- Environment recorded in `results/v1/gpt4o_preflight/environment.json`: Python 3.12.13, openai 1.76.2, pydantic 2.11.4, langgraph 1.0.1; all runtime dependencies installed from uv.lock (`uv sync --locked --no-dev --python 3.12`).

## Real API connectivity

`results/v1/gpt4o_preflight/connectivity.json` records a completed live request to the configured endpoint: requested `gpt-4o`, returned `gpt-4o-2024-08-06`, input 12 / output 2 tokens, finish_reason stop, cost upper bound $0.00005. This probe is excluded from episode metrics and included in the pilot budget ledger.

Current route evidence is saved privately at `results/v1/gpt4o_preflight/route_evidence.json`: authenticated model listing includes exact `gpt-4o`; current public model_ratio 1.25 and completion_ratio 4; three latest accessible charges for this token show group_ratio 1 and no custom user multiplier. The configured uncached accounting rates are $2.50/M input and $10/M output. Cache discounts are ignored. Accounting assumes those verified rates remain applicable; it is not a supplier invoice. Price evidence and rate identity are frozen with the run.

## Commands

Run from this repository with its isolated environment and ignored `.env` containing the existing connection. Never print or commit the key.

```powershell
.\.venv\Scripts\python.exe scripts\manta\check_gpt4o_route.py
.\.venv\Scripts\python.exe scripts\manta\probe_gpt4o.py
.\.venv\Scripts\python.exe scripts\manta\run_formal.py --provider qdd --pilot --dry-run --parallelism 1
.\.venv\Scripts\python.exe -u scripts\manta\run_formal.py --provider qdd --pilot --parallelism 1
```

The pilot cap is fixed at $10 cumulative and includes the probe. Formal execution additionally requires accepted pilot evidence, unchanged source/config, and an explicit `GPT4O_MAX_COST_USD`. The final formal configuration table and pilot-based cost estimate must be presented before launch. Formal results use `results/v1/formal_80_seed42_gpt4o/`; original DeepSeek raw data are never overwritten.
