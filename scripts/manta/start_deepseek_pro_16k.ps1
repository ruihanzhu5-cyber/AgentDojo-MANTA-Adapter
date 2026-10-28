$ErrorActionPreference = 'Stop'
$largeOutputRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$originalProRoot = Join-Path (Split-Path $largeOutputRoot -Parent) 'gpt4o-replication'
$originalProRun = Join-Path $originalProRoot 'results/v1/formal_80_seed42_deepseek_pro'
$originalPids = Join-Path $originalProRun 'active_pids.json'
if (Test-Path -LiteralPath $originalPids) {
    $runningIds = Get-Content -LiteralPath $originalPids -Raw | ConvertFrom-Json
    foreach ($proChildId in $runningIds) {
        if (Get-Process -Id ([int]$proChildId) -ErrorAction SilentlyContinue) {
            throw 'The original 4096-token run is still active. Press Ctrl+C in its terminal first.'
        }
    }
}
$largeOutputPython = Join-Path $originalProRoot '.venv/Scripts/python.exe'
$largeOutputRun = Join-Path $largeOutputRoot 'results/v1/formal_80_seed42_deepseek_pro_16k'
New-Item -ItemType Directory -Path $largeOutputRun -Force | Out-Null
$receipt = Join-Path $largeOutputRun 'connectivity.json'
if (-not (Test-Path -LiteralPath $receipt)) {
    Copy-Item -LiteralPath (Join-Path $originalProRun 'connectivity.json') -Destination $receipt
}
$env:MANTA_PROVIDER = 'deepseek'
$env:DEEPSEEK_BASE_URL = 'https://api.deepseek.com/v1'
$env:DEEPSEEK_MODEL = 'deepseek-v4-pro'
$env:DEEPSEEK_PLANNER_MODEL = 'deepseek-v4-pro'
$env:DEEPSEEK_AUDITOR_MODEL = 'deepseek-v4-pro'
$env:V1_MAX_COST_USD = '100'
Set-Location -LiteralPath $largeOutputRoot
& $largeOutputPython -u scripts/manta/run_formal.py --provider deepseek --parallelism 8 `
    --max-output-tokens 16384 --budget-db (Join-Path $originalProRun 'budget.sqlite') `
    --run-dir $largeOutputRun
exit $LASTEXITCODE
