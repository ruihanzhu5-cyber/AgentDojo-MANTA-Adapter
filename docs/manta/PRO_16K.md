# Pro output budget: 16,384 tokens

Operator authorized a larger output allowance after the 4096-token run repeatedly exhausted the entire budget on reasoning. This is a separate configuration and output directory; its 160 results must not be mixed with the incomplete 4096-token batch.

The isolated checkout leaves the active 4096-token source untouched. The new CLI records max_output_tokens=16384 in its immutable manifest and every result, and passes the cap to every Pro role. Other scenario, tool, scoring, seed, Agent, repair and concurrency settings are unchanged.

The canonical launcher is scripts/manta/start_deepseek_pro_16k.ps1 in the isolated deepseek-pro-16k checkout. The original checkout used a local forwarding script to invoke it after the operator stopped the 4096-token terminal with Ctrl+C. That forwarding script is local only. The canonical launcher expects the sibling gpt4o-replication checkout with its existing Python environment and Pro results. It refuses while recorded old episode processes are still alive and reuses the existing real connectivity receipt. No new probe is needed for the same model/endpoint.

The new configuration shares the original Pro request ledger and user-authorized $100 cumulative cap. Earlier returned usage and unresolved reservations remain charged to that cap; this does not create another $100 allowance. New episode files go under this checkout's results/v1/formal_80_seed42_deepseek_pro_16k/. The shared ledger path is explicitly recorded in the new manifest.

No Pro request was sent, stopped or restarted while preparing this configuration. Any independent later publication must report the changed output cap and separate the old and new batches.

The completed 160/160 run, comparison tables and redacted logs are published in [the Pro 16K report](../../reports/2026-10-28-deepseek-pro-16k/README.md). Offline export uses scripts/reporting/publish_deepseek_pro_results.py; --budget-db can select the preserved shared ledger after relocating private evidence. It requires the original logs and existing metric tables and never calls a provider.
