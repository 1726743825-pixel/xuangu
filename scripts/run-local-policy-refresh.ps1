[CmdletBinding()]
param(
    [string]$NodePath = 'node',
    [string]$ScreenerPath = 'D:\Program Files\xuangu\zhuizhang\stock_screener.js',
    [string]$LogDirectory = '',
    [switch]$Force
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
