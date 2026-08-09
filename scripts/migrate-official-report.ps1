[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$DeleteTradeDate,
    [Parameter(Mandatory)]
    [string]$ReportPath,
    [Parameter(Mandatory)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$TargetTradeDate,
    [Parameter(Mandatory)]
    [switch]$ConfirmPurge,
    [string]$PythonPath = '',
    [string]$EnvFile = ''
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $PythonPath) {
    $PythonPath = Join-Path $ProjectRoot 'backend\.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python executable not found: $PythonPath. Create backend/.venv and install requirements-dev.txt first."
}
if (-not (Test-Path -LiteralPath $ReportPath -PathType Leaf)) {
    throw "Official report not found: $ReportPath"
}
if (-not $EnvFile) {
    $EnvFile = Join-Path $ProjectRoot '.env'
}

# This tool is never referenced by the daily Scheduled Task.  Its Python
# entry point parses the exact HTML before issuing the confirmed DELETE call.
$BackendRoot = Join-Path $ProjectRoot 'backend'
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$BackendRoot;$env:PYTHONPATH" } else { $BackendRoot }
$arguments = @(
    (Join-Path $BackendRoot 'existing\migrate_official_report.py'),
    '--delete-trade-date', $DeleteTradeDate,
    '--report-path', $ReportPath,
    '--target-trade-date', $TargetTradeDate,
    '--confirm-purge',
    '--env-file', $EnvFile
)
& $PythonPath @arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
