# First paired acceptance experiment

Start in PowerShell:

```powershell
Set-Location 'D:\AgentDojo-MANTA-Adapter'
uv sync --locked --no-dev --python 3.12
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& .\.venv\Scripts\python.exe -u scripts/manta/run_paired_pilot.py --parallelism 4
```

The launcher reuses `DEEPSEEK_API_KEY` in the terminal environment or the local
Git-ignored `.env`. It never writes the key into the manifest or prints it.
No key means a preflight failure before any episode starts.

Scope: workspace user_task_0, 1, 2, 3, each once with Clean and once with the
official direct attack targeting injection_task_0: 8 episodes in total.
All paired runs use the same seed (42), model, task-conditioned planner and
resource settings. There are at most 4 concurrent processes; every process
loads a separate task environment. This is an acceptance experiment for the
corrected adapter, not the completed 80-scene MANTA row.

Settings: 3 initial Agent budget, initial limit 5, runtime limit 10, 2 execution
turns maximum, 1 repair maximum, heuristic audit, official benchmark v1.2.2.
MANTA's task/tool guards can reduce the actual initial count or constrain the
planned topology. Actual counts and mutations are observed in result.json.

The launcher prints RUN_DIR and incremental [1/8]...[8/8] completion messages.
Each run retains:

```
results/v1/paired_pilot/<session>/
  manifest.json
  progress.json
  summary.json
  episodes/<task>__<condition>/result.json
  logs/<task>__<condition>/console.log
  logs/<task>__<condition>/manta-agentdojo/...  # official traces
```

Raw data remain local under the Git-ignored results directory. Re-running
creates another session; it does not replace previous evidence.

The summary reports valid/invalid counts, utility, ASR and known exposure
counts. It does not mark this pilot as a completed formal E2 result row.
Provider pricing and monetary spend enforcement are not yet implemented, so
cost remains UNKNOWN. Merely setting V1_MAX_COST_USD does not limit charges.
This launcher is bounded to 8 episodes and never expands into the full batch.

Use `--dry-run` to validate sources and official task IDs without calling the
model. Use `--smoke` for an explicitly mock end-to-end execution; mock outputs
are excluded from experiment rates.
