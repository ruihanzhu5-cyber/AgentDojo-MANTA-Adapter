$ErrorActionPreference = 'Stop'
$adaptiveRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$originalRoot = Join-Path (Split-Path $adaptiveRoot -Parent) 'gpt4o-replication'
$adaptivePython = Join-Path $originalRoot '.venv/Scripts/python.exe'
$adaptiveRun = 'D:\MANTA_DATA\AgentDojo\formal_80_seed42_deepseek_flash_adaptive'
if (-not (Test-Path -LiteralPath $adaptivePython)) { throw "Existing Python environment is missing: $adaptivePython" }
$ownedNames = @('MANTA_PROVIDER','DEEPSEEK_BASE_URL','DEEPSEEK_MODEL','DEEPSEEK_PLANNER_MODEL','DEEPSEEK_AUDITOR_MODEL','V1_MAX_COST_USD','V1_BUDGET_DB','V1_REQUEST_JOURNAL','OPENROUTER_MAX_TOKENS','PYTHONIOENCODING')
$savedEnvironment = @{}
foreach ($ownedName in $ownedNames) { $savedEnvironment[$ownedName] = [Environment]::GetEnvironmentVariable($ownedName, 'Process') }
$savedDirectory = Get-Location
try {
    $env:MANTA_PROVIDER = 'deepseek'
    $env:DEEPSEEK_BASE_URL = 'https://api.deepseek.com/v1'
    $env:DEEPSEEK_MODEL = 'deepseek-flash'
    $env:DEEPSEEK_PLANNER_MODEL = 'deepseek-flash'
    $env:DEEPSEEK_AUDITOR_MODEL = 'deepseek-flash'
    $env:V1_MAX_COST_USD = '100'
    $env:V1_BUDGET_DB = Join-Path $adaptiveRun 'budget.sqlite'
    $env:PYTHONIOENCODING = 'utf-8'
    Remove-Item Env:V1_REQUEST_JOURNAL -ErrorAction SilentlyContinue
    Remove-Item Env:OPENROUTER_MAX_TOKENS -ErrorAction SilentlyContinue
    Set-Location -LiteralPath $adaptiveRoot
    $formalArguments = @('-u','scripts/manta/run_formal.py','--provider','deepseek','--team-profile','adaptive_native','--max-output-tokens','16384','--parallelism','8','--run-dir',$adaptiveRun)
    & $adaptivePython @formalArguments --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'Offline configuration check failed; no API request was sent.' }
    & $adaptivePython -u scripts/manta/probe_deepseek_flash.py --run-dir $adaptiveRun
    if ($LASTEXITCODE -ne 0) { throw 'Flash connectivity check failed; formal episodes were not started.' }
    & $adaptivePython @formalArguments
    if ($LASTEXITCODE -ne 0) { throw 'Experiment stopped before completion; evidence is retained in the run directory.' }
} finally {
    foreach ($ownedName in $ownedNames) { [Environment]::SetEnvironmentVariable($ownedName, $savedEnvironment[$ownedName], 'Process') }
    Set-Location -LiteralPath $savedDirectory.Path
}
