[CmdletBinding()]
param(
    [string]$TaskName = 'Xuangu-LocalSelectionImport',
    [string]$PythonPath = ''
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runner = Join-Path $ProjectRoot 'scripts\run-local-selection-import.ps1'
if (-not $PythonPath) {
    $PythonPath = Join-Path $ProjectRoot 'backend\.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $Runner)) { throw "Runner not found: $Runner" }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw "Python executable not found: $PythonPath" }

# Runs only while the domestic-network Windows user is logged on; no password
# or token is embedded in the task definition.
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -PythonPath `"$PythonPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At 3:05PM
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Output "Installed $TaskName for 15:05 local Windows time. Verify: Get-ScheduledTask -TaskName '$TaskName'"
