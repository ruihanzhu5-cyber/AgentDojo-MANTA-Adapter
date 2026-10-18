# AgentDojo × MANTA V1

This repository is a standalone experiment checkout based on the official
[AgentDojo](https://github.com/ethz-spylab/agentdojo) source. The adapter keeps
AgentDojo responsible for task suites, tool execution, attack injection, and the
utility/security judges; MANTA owns only the multi-agent execution layer.

## Layout

- `src/agentdojo/`: pinned AgentDojo source.
- `src/agentdojo_manta/`: MANTA pipeline adapter.
- `scripts/manta/run_agentdojo_manta.py`: one-episode runner.
- `upstreams/manta/`: MANTA source snapshot pinned at `3da4087`.
- `results/v1/agentdojo/`: local episode outputs and official TraceLogger files.

The MANTA snapshot is included as an upstream source copy for reproducibility;
its license is retained in `upstreams/manta/LICENSE`.

## Install

```powershell
uv sync --no-dev
```

For a live run, set `DEEPSEEK_API_KEY` and optionally `DEEPSEEK_BASE_URL` and
`DEEPSEEK_MODEL`. To use another local MANTA checkout, set `MANTA_SOURCE_DIR`.

## Zero-cost structural smoke

```powershell
$env:MAS_DISABLE_LIVE_LLM = "1"
uv run python scripts/manta/run_agentdojo_manta.py `
  --clean --suite workspace --user-task user_task_0 `
  --planner-mode fixed --max-turns 1 --repair-budget 0 --num-agents 2
```

The official attack path can be exercised without model cost:

```powershell
$env:MAS_DISABLE_LIVE_LLM = "1"
uv run python scripts/manta/run_agentdojo_manta.py `
  --suite workspace --user-task user_task_0 `
  --attack direct --injection-task injection_task_0 `
  --planner-mode fixed --max-turns 1 --repair-budget 0 --num-agents 2
```

## Bounded live concurrency

Use `scripts/manta/run_batch.py` for independent episodes. Each task runs in a
separate process with its own AgentDojo environment and TraceLogger directory.
Start with two workers and increase only after checking the per-task console
logs for `429`, timeout, or retry events:

```powershell
$env:MAS_REQUIRE_LIVE_LLM = "1"
$env:V1_MAX_COST_USD = "5"
uv run python scripts/manta/run_batch.py `
  --user-tasks user_task_1,user_task_2 `
  --suite workspace --clean --parallelism 2
```

The batch runner caps `--parallelism` at 4. Process-level isolation is required
because AgentDojo tool environments are mutable; sharing one environment across
threads would invalidate task and attack traces. The runner never treats a
failed live request as a mock success when `MAS_REQUIRE_LIVE_LLM=1`.

Provider pricing is not returned by the current DeepSeek-compatible endpoint,
so live results record `cost_usd` as `null` with
`cost_status=UNKNOWN_PROVIDER_PRICE`; token counts and latency remain recorded.

Mock runs are labeled `MOCK_SMOKE` and must not be reported as real task
success rates or attack success rates. A real episode must use
`--planner-mode task_conditioned` and record the model, AgentDojo revision,
MANTA revision, and the generated trace.

## Adapter boundary

1. AgentDojo creates the suite task, environment, functions runtime, attack, and
   utility/security evaluation.
2. Each AgentDojo function is converted to a MANTA tool schema whose handler
   still calls the official `FunctionsRuntime.run_function`.
3. The official MANTA `SelfEvolvedEngine` plans agents, relays messages, audits
   execution, and applies bounded topology mutations.
4. MANTA interaction logs are projected back into AgentDojo assistant/tool
   messages and forwarded to the official logger.

The first implementation leaves `attack_exposed` as `UNKNOWN`; it requires a
separate trace-to-injection mapping before it can be used in a final result
table.
