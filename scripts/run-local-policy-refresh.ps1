[CmdletBinding()]
param(
    [string]$NodePath = 'node',
    [string]$ScreenerPath = 'D:\Program Files\xuangu\zhuizhang\stock_screener.js',
    [string]$LogDirectory = '',
    [switch]$Force,
    [switch]$SkipSelection
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ScreenerPath)) {
    throw "Zhuizhang screener not found: $ScreenerPath"
}

if (-not $LogDirectory) {
    $LogDirectory = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'logs'
}
if (-not (Test-Path -LiteralPath $LogDirectory)) {
    New-Item -ItemType Directory -Path $LogDirectory | Out-Null
}

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logFile = Join-Path $LogDirectory "policy-refresh-$timestamp.log"
$scriptDir = Split-Path -Parent $ScreenerPath
$scriptName = Split-Path -Leaf $ScreenerPath

Push-Location $scriptDir
try {
    "[$(Get-Date -Format s)] starting policy refresh" | Tee-Object -FilePath $logFile
    $nodeArgs = @($scriptName, '--policy-refresh-only')
    if ($Force) { $nodeArgs += '--force-policy-refresh' }
    & $NodePath @nodeArgs *>&1 | Tee-Object -FilePath $logFile -Append
    if ($LASTEXITCODE -ne 0) {
        throw "policy refresh failed with exit code $LASTEXITCODE. See log: $logFile"
    }
    "[$(Get-Date -Format s)] policy refresh completed" | Tee-Object -FilePath $logFile -Append
} finally {
    Pop-Location
}

$marketClose = Get-Date -Hour 15 -Minute 0 -Second 0
if (-not $SkipSelection -and (Get-Date) -ge $marketClose) {
    $selectionRunner = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'scripts\run-local-selection-import.ps1'
    "[$(Get-Date -Format s)] starting selection import after policy final" | Tee-Object -FilePath $logFile -Append
    & $selectionRunner *>&1 | Tee-Object -FilePath $logFile -Append
    if ($LASTEXITCODE -ne 0) {
        throw "selection import failed with exit code $LASTEXITCODE. See log: $logFile"
    }
    "[$(Get-Date -Format s)] selection import completed after policy final" | Tee-Object -FilePath $logFile -Append
} elseif (-not $SkipSelection) {
    "[$(Get-Date -Format s)] selection import skipped before 15:00 market close" | Tee-Object -FilePath $logFile -Append
}
