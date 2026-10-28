$ErrorActionPreference = 'Stop'
$proExperimentRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location -LiteralPath $proExperimentRoot
$env:MANTA_PROVIDER = 'deepseek'
$env:DEEPSEEK_BASE_URL = 'https://api.deepseek.com/v1'
$env:DEEPSEEK_MODEL = 'deepseek-v4-pro'
$env:DEEPSEEK_PLANNER_MODEL = 'deepseek-v4-pro'
$env:DEEPSEEK_AUDITOR_MODEL = 'deepseek-v4-pro'
$env:V1_MAX_COST_USD = '100'
$proPython = Join-Path $proExperimentRoot '.venv/Scripts/python.exe'
$proRunDirectory = Join-Path $proExperimentRoot 'results/v1/formal_80_seed42_deepseek_pro'

# First verify the frozen scenes without sending API requests.
& $proPython -u scripts/manta/run_formal.py --provider deepseek --parallelism 8 --run-dir $proRunDirectory --dry-run
if ($LASTEXITCODE -ne 0) { throw 'Frozen-scene validation failed; stopped.' }
# The user starts this single live request; it shares the formal $100 cap.
& $proPython -u scripts/manta/probe_deepseek_pro.py --run-dir $proRunDirectory
if ($LASTEXITCODE -ne 0) { throw 'DeepSeek Pro connectivity failed; formal episodes not started.' }
& $proPython -u scripts/manta/run_formal.py --provider deepseek --parallelism 8 --run-dir $proRunDirectory
exit $LASTEXITCODE
