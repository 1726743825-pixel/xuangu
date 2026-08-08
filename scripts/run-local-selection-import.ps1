[CmdletBinding()]
param(
    [string]$TradeDate = (Get-Date -Format 'yyyy-MM-dd'),
    [string]$PythonPath = '',
    [string]$EnvFile = '',
    [switch]$ReplaceExisting
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $PythonPath) {
    $PythonPath = Join-Path $ProjectRoot 'backend\.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python executable not found: $PythonPath. Create backend/.venv and install requirements-dev.txt first."
}

$BackendRoot = Join-Path $ProjectRoot 'backend'
if (-not $EnvFile) {
    $EnvFile = Join-Path $ProjectRoot '.env'
}
# The executable lives in backend/existing, while the application package is
# backend/app.  Make the package root explicit so this works from Task
# Scheduler as well as an interactive project-root PowerShell session.
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$BackendRoot;$env:PYTHONPATH" } else { $BackendRoot }
$arguments = @((Join-Path $BackendRoot 'existing\import_local_selections.py'), '--trade-date', $TradeDate, '--env-file', $EnvFile)
if ($ReplaceExisting) { $arguments += '--replace-existing' }
& $PythonPath @arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
