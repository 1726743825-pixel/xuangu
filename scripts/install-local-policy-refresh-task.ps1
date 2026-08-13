[CmdletBinding()]
param(
    [string]$TaskName = 'Xuangu-PolicyNewsRefresh',
    [string]$NodePath = 'node'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runner = Join-Path $ProjectRoot 'scripts\run-local-policy-refresh.ps1'
if (-not (Test-Path -LiteralPath $Runner)) { throw "Runner not found: $Runner" }

# Runs once immediately when this Windows user logs on, then every 2 hours
# while the user remains logged on. Company model prefilters news first, then
# DeepSeek V4 Flash writes the final daily score cache when applicable. The
# later selection task refuses to run until this final cache exists for the
# current day.
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -NodePath `"$NodePath`""
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$repeatTrigger = New-ScheduledTaskTrigger -Once -At 12:00AM -RepetitionInterval (New-TimeSpan -Hours 2) -RepetitionDuration (New-TimeSpan -Days 1)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($logonTrigger, $repeatTrigger) -Principal $principal -Settings $settings -Force | Out-Null
Write-Output "Installed $TaskName for logon refresh plus every 2 hours while logged on. Verify: Get-ScheduledTask -TaskName '$TaskName'"
