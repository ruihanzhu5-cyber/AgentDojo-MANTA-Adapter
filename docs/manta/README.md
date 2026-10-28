# AgentDojo × MANTA V1

**最新入口：** [仓库架构](../REPOSITORY_ARCHITECTURE.md) · [GPT-4o 适配层](GPT4O_ADAPTER.md) · [全部实验](../../reports/README.md) · [日志总索引](../../reports/LOGS.md)。2026-10-28 的 GPT-4o 复现已完成 160/160 有效 episode，报告与模型对照见 [本轮交付](../../reports/2026-10-28-gpt4o-agentdojo/README.md)。

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

## Completed experiment — 2026-10-19

The MANTA row of E2 is complete: 80 official direct-attack scenes, 160 valid
Clean/Attack episodes, seed 42. See the
[report, result tables and all retained redacted logs](../../reports/2026-10-19-manta-agentdojo/README.md).
Clean utility is 65/80, attacked utility 66/80, targeted ASR 1/80; 74/80 attacked
episodes have confirmed exposure and six remain UNKNOWN. These are descriptive
single-model, single-seed results; other methods and causal propagation studies
remain separate work.

For the frozen formal queue and resume instructions, see
[START_FORMAL.md](START_FORMAL.md). Its episode concurrency limit is eight.

## Install

```powershell
uv sync --no-dev
```

For a live run, set `DEEPSEEK_API_KEY` and optionally `DEEPSEEK_BASE_URL` and
`DEEPSEEK_MODEL`. To use another local MANTA checkout, set `MANTA_SOURCE_DIR`.

## Zero-cost structural smoke

```powershell
$env:MAS_DISABLE_LIVE_LLM = "1"
uv run python scripts/manta/run_agentdojo_manta.py --allow-mock `
  --clean --suite workspace --user-task user_task_0 `
  --planner-mode fixed --max-turns 1 --repair-budget 0 --num-agents 2
```

The official attack path can be exercised without model cost:

```powershell
$env:MAS_DISABLE_LIVE_LLM = "1"
uv run python scripts/manta/run_agentdojo_manta.py --allow-mock `
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

Provider invoice cost remains unknown, so episode `cost_usd` stays null.
The formal queue additionally uses the shared request budget ledger, verified
Flash peak-price upper bounds and conservative reservations; those amounts are
reported separately from invoice cost. The legacy `run_batch.py` example above
does not configure that shared ledger.

Mock runs are labeled `MOCK_SMOKE` and must not be reported as real task
success rates or attack success rates. A real episode must use
`--planner-mode task_conditioned` and record the model, AgentDojo revision,
MANTA revision, and the generated trace.

`--num-agents` is the initial Agent budget passed to MANTA; it does not turn
off adaptive topology. The adapter keeps MANTA's bounded self-evolution limits
at `MANTA_MAX_INITIAL_AGENTS=5` and `MANTA_MAX_TOTAL_AGENTS=10` by default, so
the planner can change the topology and add agents during repair. The engine
still caps initial breadth for ordinary tool tasks at three agents as an OOM
and duplicate-tool guard. The actual initial count, maximum count, topology
versions, and mutation count are written into each result JSON.

## Adapter boundary

1. AgentDojo creates the suite task, environment, functions runtime, attack, and
   utility/security evaluation.
2. Each AgentDojo function is converted to a MANTA tool schema whose handler
   still calls the official `FunctionsRuntime.run_function`.
3. The official MANTA `SelfEvolvedEngine` plans agents, relays messages, audits
   execution, and applies bounded topology mutations.
4. Actual AgentDojo runtime calls are recorded, converted to assistant/tool
   messages and forwarded to the official logger and judge. MANTA traces are
   retained separately for topology and Context analysis.

Exposure is confirmed only when the full official payload is found in a
completed model request. Unmatched or transformed payloads remain `UNKNOWN`.

## Metric schema v2

See [METRIC_LOGIC_REVIEW.md](METRIC_LOGIC_REVIEW.md) for definitions and known
limitations. AgentDojo's `security=True` means **the attack succeeded**. Earlier
schema-less Attack outcome reports inverted that boolean and are withdrawn.
New results keep official booleans and use actual runtime call and provider
request ledgers. Each attempt uses its own run directory and retains its traces
locally under `results/`; mock and infrastructure failures do not enter ASR.

`V1_MAX_COST_USD` alone only gates the legacy batch launcher. The formal queue
sets both that cap and `V1_BUDGET_DB`, enabling request-level shared reservations,
usage settlement and conservative retention of unreturned requests. See
[START_FORMAL.md](START_FORMAL.md) for pricing assumptions and scope.

```powershell
python scripts/manta/summarize_results.py results/v1/agentdojo_batch `
  --output results/v1/metric_summary.json
```
