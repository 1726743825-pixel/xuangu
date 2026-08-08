[CmdletBinding()]
param(
    [string]$TradeDate = (Get-Date -Format 'yyyy-MM-dd'),
    [string]$PythonPath = ''
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $PythonPath) {
    $PythonPath = Join-Path $ProjectRoot 'backend\.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python executable not found: $PythonPath. Create backend/.venv and install requirements-dev.txt first."
}

& $PythonPath (Join-Path $ProjectRoot 'backend\existing\import_local_selections.py') --trade-date $TradeDate
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
