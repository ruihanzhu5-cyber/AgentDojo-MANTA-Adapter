# GPT-4o replication preflight

Checked 2026-10-28 (Asia/Shanghai). Phase 1 review completed before any model request. Subsequent implementation and live-connectivity outcomes are recorded in GPT4O_IMPLEMENTATION.md.

## Source and environment

- Requested repository: `ruihanzhu5-cyber/AgentDojo-MANTA-Adapter`.
- GitHub main and existing local repository both resolve to `7f5919fe9562fa4f462eb47ee03793977ca91c33` (verified through the GitHub connector).
- Isolated working copy: `C:/Users/larei/Documents/ChatGPT/manta/gpt4o-replication`, branch `exp/gpt4o-agentdojo-replication`.
- The original MANTA workspace is on `research/appworld-b0-v02-paid-clean`. The existing `D:/AgentDojo-MANTA-Adapter` has unrelated uncommitted scaled-experiment changes. Neither is used as an editable experiment source.
- Python 3.12.13; a separate environment is being installed using `uv sync --locked --no-dev --python 3.12`. Final versions and checks will be recorded in GPT4O_IMPLEMENTATION.md.
- Reviewed START_FORMAL.md, both runners, adapter.py, budget.py, vendored MAS/llm.py, original manifest and episode CSV, and official task-suite utility/security dispatch. No AGENTS.md found in the target repository.

## Findings and minimum implementation

1. Adapter routing is DeepSeek-specific, including credential, endpoint and planner/auditor variables. Introduce explicit provider selection while retaining the existing DeepSeek default. All GPT-4o roles must request exactly `gpt-4o`.
2. The existing budget uses $0.30/M input and $1.20/M output, with a 1,048,576-token input reservation. These values cannot account for GPT-4o. Add an independently priced, persistent GPT-4o request budget and pin its pricing identity in SQLite.
3. MANTA uses OpenAI Chat Completions with assistant tool_calls and corresponding tool responses. The adapter already forces `parallel_tool_calls=False`; preserve this and the existing 4,096-token output limit for comparable execution. Do not modify the vendored engine, planner, communication, topology or repair algorithms.
4. Disable SDK retries and provider routing extras. Preserve MANTA's observed retry mechanism, record request IDs, retry indices, actual response model, full usage, error type/status and request status. Never accept mock or missing usage as a valid live run.
5. GPT-4o official documentation lists 128,000 context tokens and 16,384 maximum output tokens. Keep the inherited 4,096 output cap. Reject excess context; do not add context truncation. Existing native tool-memory compaction remains unchanged. Actual route behavior must be checked by pilot.
6. The old `--smoke` is explicitly mock. Keep it separate from real GPT-4o verification.
7. Existing formal runner regenerates its queue. For this replication load the published original manifest directly and verify every scene/job identity and recomputed official direct payload hash. Choose the first scene in each suite for the pilot, with clean/attack pairs (8 episodes).
8. Official evaluation is performed locally by AgentDojo. `security=True` is attacker-goal success. Preserve its scoring and only aggregate `evaluation_valid=True`, with one selected valid attempt per job.
9. Request records were previously held only in memory until an episode ends. Persist a request journal before/after HTTP calls so interrupted attempts retain accounting and provenance.

## Runtime configuration

The user selected their existing GPT-4o connection: provider `qdd`, endpoint `https://api2.aigcbest.top/v1`, credential variable `OPENAI_API_KEY`. Credential values must never be logged or committed. Request model remains `gpt-4o`; record the response model verbatim. Route capabilities, account pricing and real availability require verification; no other model is permitted.

Pilot cap is $10 cumulative, including failed/unreturned requests. Formal cap has not been configured and must be supplied explicitly before launch. Pilot and formal results must use separate directories and ledgers.

## Cost forecast before pilot

Published selected DeepSeek episodes: input 22,200,124 and output 3,397,110 tokens. At the official GPT-4o standard rates ($2.50/M input, $10/M output), identical usage would cost **$89.47141** before retries, failed attempts or unreturned calls. This is a usage-based forecast, not a measured GPT-4o result or a verified price for the configured connection. The route's verified account multiplier must be applied before paid requests. Re-estimate using actual pilot usage before formal launch.

## Gates still pending at this preflight checkpoint

- Implement and test provider separation, GPT-4o accounting, frozen-scene verification and real-pilot gating.
- Load the existing credential privately and verify current route pricing/account metadata.
- Pass zero-cost tests, then run 8 real episodes within $10 and reconcile official scores, usage, handoffs and topology records.
- Formal launch remains blocked until pilot acceptance and an explicit cumulative formal budget are both present.

## Documentation checked

- https://developers.openai.com/api/docs/models/gpt-4o
- https://developers.openai.com/api/docs/guides/function-calling
- https://aigcbest.top/ (connection documentation; account prices require separate evidence)
