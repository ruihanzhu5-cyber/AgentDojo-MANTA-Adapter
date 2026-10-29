$ErrorActionPreference = 'Stop'
$foldedRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$sharedRoot = Join-Path (Split-Path $foldedRoot -Parent) 'gpt4o-replication'
$foldedPython = Join-Path $sharedRoot '.venv/Scripts/python.exe'
$foldedConfig = Get-Content -LiteralPath (Join-Path $foldedRoot 'docs/manta/flash_folded_config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$foldedRun = $foldedConfig.run_dir
if (-not (Test-Path -LiteralPath $foldedPython)) { throw "Existing Python environment is missing: $foldedPython" }
$ownedNames = @('MANTA_PROVIDER','DEEPSEEK_BASE_URL','DEEPSEEK_MODEL','DEEPSEEK_PLANNER_MODEL','DEEPSEEK_AUDITOR_MODEL','V1_MAX_COST_USD','V1_BUDGET_DB','V1_REQUEST_JOURNAL','OPENROUTER_MAX_TOKENS','PYTHONIOENCODING','DOTENV_SOURCE_FILE')
$savedEnvironment = @{}
foreach ($ownedName in $ownedNames) { $savedEnvironment[$ownedName] = [Environment]::GetEnvironmentVariable($ownedName, 'Process') }
$savedDirectory = Get-Location
try {
    $env:MANTA_PROVIDER = 'deepseek'
    $env:DEEPSEEK_BASE_URL = $foldedConfig.endpoint
    $env:DEEPSEEK_MODEL = $foldedConfig.model
    $env:DEEPSEEK_PLANNER_MODEL = $foldedConfig.model
    $env:DEEPSEEK_AUDITOR_MODEL = $foldedConfig.model
    $env:V1_MAX_COST_USD = [string]$foldedConfig.budget_usd
    $env:V1_BUDGET_DB = Join-Path $foldedRun 'budget.sqlite'
    $env:PYTHONIOENCODING = 'utf-8'
    Remove-Item Env:V1_REQUEST_JOURNAL -ErrorAction SilentlyContinue
    Remove-Item Env:OPENROUTER_MAX_TOKENS -ErrorAction SilentlyContinue
    Set-Location -LiteralPath $foldedRoot
    # Reuse the existing ignored credentials file; never copy or print its key.
    $credentialCandidates = @((Join-Path $foldedRoot '.env'), (Join-Path (Split-Path $foldedRoot -Parent) 'deepseek-flash-adaptive/.env'), (Join-Path $sharedRoot '.env'))
    foreach ($credentialFile in $credentialCandidates) {
        if (Test-Path -LiteralPath $credentialFile) { $env:DOTENV_SOURCE_FILE = $credentialFile; break }
    }
    $formalArguments = @('-u','scripts/manta/run_formal.py','--provider','deepseek','--team-profile','folded_adaptive','--max-output-tokens','16384','--parallelism','8','--run-dir',$foldedRun)
    & $foldedPython @formalArguments --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'Offline configuration check failed; no API request was sent.' }
    & $foldedPython -u scripts/manta/probe_deepseek_flash.py --run-dir $foldedRun
    if ($LASTEXITCODE -ne 0) { throw 'Flash connectivity check failed; formal episodes were not started.' }
    & $foldedPython @formalArguments
    if ($LASTEXITCODE -ne 0) { throw 'Experiment stopped before completion; evidence is retained in the new run directory.' }
} finally {
    foreach ($ownedName in $ownedNames) { [Environment]::SetEnvironmentVariable($ownedName, $savedEnvironment[$ownedName], 'Process') }
    Set-Location -LiteralPath $savedDirectory.Path
}
