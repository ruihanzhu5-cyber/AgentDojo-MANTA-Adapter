$ErrorActionPreference = 'Stop'
$replicationRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location -LiteralPath $replicationRoot

# Operator-selected cumulative formal cap, confirmed 2026-10-28.
$env:GPT4O_MAX_COST_USD = '100'
$env:OPENAI_BASE_URL = 'https://api2.aigcbest.top/v1'

# Existing credential and verified pricing evidence are loaded from ignored .env.
# The user stopped remaining pilot validation after four valid episodes.
& (Join-Path $replicationRoot '.venv/Scripts/python.exe') -u `
    (Join-Path $replicationRoot 'scripts/manta/run_formal.py') `
    --provider qdd --parallelism 8 --skip-pilot-check `
    --run-dir (Join-Path $replicationRoot 'results/v1/formal_80_seed42_gpt4o')
exit $LASTEXITCODE
