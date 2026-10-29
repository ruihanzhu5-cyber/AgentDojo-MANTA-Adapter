param([ValidateSet('both','F','W')][string]$Arm = 'both')
$ErrorActionPreference = 'Stop'
$fwRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$workspaceParent = Split-Path $fwRoot -Parent
$fwPython = Join-Path $workspaceParent 'gpt4o-replication/.venv/Scripts/python.exe'
$fwConfig = Get-Content -LiteralPath (Join-Path $fwRoot 'docs/manta/fw_ablation_config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$fwRun = $fwConfig.run_dir
if (-not (Test-Path -LiteralPath $fwPython)) { throw "Existing Python environment missing: $fwPython" }
$ownedNames = @('MANTA_PROVIDER','DEEPSEEK_BASE_URL','DEEPSEEK_MODEL','DEEPSEEK_PLANNER_MODEL','DEEPSEEK_AUDITOR_MODEL','V1_MAX_COST_USD','V1_BUDGET_DB','V1_REQUEST_JOURNAL','OPENROUTER_MAX_TOKENS','PYTHONIOENCODING','DOTENV_SOURCE_FILE')
$savedEnvironment = @{}
foreach ($ownedName in $ownedNames) { $savedEnvironment[$ownedName] = [Environment]::GetEnvironmentVariable($ownedName, 'Process') }
$savedDirectory = Get-Location
try {
    $env:MANTA_PROVIDER = 'deepseek'
    $env:DEEPSEEK_BASE_URL = $fwConfig.endpoint
    $env:DEEPSEEK_MODEL = $fwConfig.model
    $env:DEEPSEEK_PLANNER_MODEL = $fwConfig.model
    $env:DEEPSEEK_AUDITOR_MODEL = $fwConfig.model
    $env:V1_MAX_COST_USD = [string]$fwConfig.budget_usd
    $env:V1_BUDGET_DB = Join-Path $fwRun 'budget.sqlite'
    $env:PYTHONIOENCODING = 'utf-8'
    Remove-Item Env:V1_REQUEST_JOURNAL -ErrorAction SilentlyContinue
    Remove-Item Env:OPENROUTER_MAX_TOKENS -ErrorAction SilentlyContinue
    Set-Location -LiteralPath $fwRoot
    $credentialCandidates = @((Join-Path $fwRoot '.env'), (Join-Path $workspaceParent 'manta-folded-flash16k/.env'), (Join-Path $workspaceParent 'deepseek-flash-adaptive/.env'), (Join-Path $workspaceParent 'gpt4o-replication/.env'))
    foreach ($credentialFile in $credentialCandidates) {
        if (Test-Path -LiteralPath $credentialFile) { $env:DOTENV_SOURCE_FILE = $credentialFile; break }
    }
    & $fwPython -u scripts/manta/run_fw.py --arm $Arm --run-dir $fwRun --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'Offline F/W configuration check failed; no API request sent.' }
    # The coordinator holds one lock across connectivity and both arm queues.
    & $fwPython -u scripts/manta/run_fw.py --arm $Arm --run-dir $fwRun --connectivity
    if ($LASTEXITCODE -ne 0) { throw 'F/W stopped before completion. Completed evidence retained; same command resumes.' }
} finally {
    foreach ($ownedName in $ownedNames) { [Environment]::SetEnvironmentVariable($ownedName, $savedEnvironment[$ownedName], 'Process') }
    Set-Location -LiteralPath $savedDirectory.Path
}
