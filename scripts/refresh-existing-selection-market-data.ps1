[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$TradeDate,
    [string]$PythonPath = '',
    [string]$EnvFile = ''
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $PythonPath) {
    $PythonPath = Join-Path $ProjectRoot 'backend\.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python executable not found: $PythonPath. Install backend/requirements-local.txt first."
}
if (-not $EnvFile) {
    $EnvFile = Join-Path $ProjectRoot '.env'
}

$BackendRoot = Join-Path $ProjectRoot 'backend'
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$BackendRoot;$env:PYTHONPATH" } else { $BackendRoot }
& $PythonPath (Join-Path $BackendRoot 'existing\import_local_selections.py') `
    '--refresh-existing-date' $TradeDate '--env-file' $EnvFile
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
