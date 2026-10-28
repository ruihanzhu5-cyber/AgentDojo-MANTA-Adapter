# Pro output budget: 16,384 tokens

Operator authorized a larger output allowance after the 4096-token run repeatedly exhausted the entire budget on reasoning. This is a separate configuration and output directory; its 160 results must not be mixed with the incomplete 4096-token batch.

The isolated checkout leaves the active 4096-token source untouched. The new CLI records max_output_tokens=16384 in its immutable manifest and every result, and passes the cap to every Pro role. Other scenario, tool, scoring, seed, Agent, repair and concurrency settings are unchanged.

The operator launches scripts/manta/start_deepseek_pro_16k.ps1 from the original checkout after stopping its terminal with Ctrl+C. The launcher refuses while recorded old episode processes are still alive. It reuses the existing real connectivity receipt and Python environment. No new probe is needed for the same model/endpoint.

The new configuration shares the original Pro request ledger and user-authorized $100 cumulative cap. Earlier returned usage and unresolved reservations remain charged to that cap; this does not create another $100 allowance. New episode files go under this checkout's results/v1/formal_80_seed42_deepseek_pro_16k/. The shared ledger path is explicitly recorded in the new manifest.

No Pro request was sent, stopped or restarted while preparing this configuration. Any independent later publication must report the changed output cap and separate the old and new batches.
