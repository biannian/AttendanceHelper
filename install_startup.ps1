# install_startup.ps1
# Install AttendanceHelper to start at user logon (silent, no CMD).
param(
    [string]$TaskName = "AttendanceHelper",
    [switch]$UseScheduledTask,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$vbsPath = Join-Path $PSScriptRoot "start.vbs"
$scriptPath = Join-Path $PSScriptRoot "attendance_tray.py"

if (-not (Test-Path $vbsPath)) {
    Write-Error "start.vbs not found: $vbsPath"
    exit 1
}
if (-not (Test-Path $scriptPath)) {
    Write-Error "Script not found: $scriptPath"
    exit 1
}

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "AttendanceHelper.lnk"
$wscript = Join-Path $env:SystemRoot "System32\wscript.exe"

function New-StartupShortcut {
    param(
        [string]$LinkPath,
        [string]$Target,
        [string]$Arguments,
        [string]$WorkingDirectory
    )
    $wsh = New-Object -ComObject WScript.Shell
    $sc = $wsh.CreateShortcut($LinkPath)
    $sc.TargetPath = $Target
    $sc.Arguments = $Arguments
    $sc.WorkingDirectory = $WorkingDirectory
    $sc.WindowStyle = 7
    $sc.Description = "AttendanceHelper (silent)"
    $sc.Save()
}

if ($Uninstall) {
    if (Test-Path $shortcutPath) {
        Remove-Item $shortcutPath -Force
        Write-Host "Removed Startup shortcut: $shortcutPath"
    }
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "Removed scheduled task: $TaskName"
    } catch {
        Write-Host "No scheduled task to remove (or access denied)."
    }
    exit 0
}

if ($UseScheduledTask) {
    try {
        $action = New-ScheduledTaskAction `
            -Execute $wscript `
            -Argument "//nologo `"$vbsPath`"" `
            -WorkingDirectory $PSScriptRoot
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -MultipleInstances IgnoreNew
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Description "AttendanceHelper tray at logon" `
            -Force | Out-Null
        Write-Host "Scheduled task created: $TaskName"
    } catch {
        Write-Host "Scheduled task failed: $($_.Exception.Message)"
        Write-Host "Fallback: Startup shortcut..."
        New-StartupShortcut -LinkPath $shortcutPath -Target $wscript -Arguments "//nologo `"$vbsPath`"" -WorkingDirectory $PSScriptRoot
    }
} else {
    New-StartupShortcut -LinkPath $shortcutPath -Target $wscript -Arguments "//nologo `"$vbsPath`"" -WorkingDirectory $PSScriptRoot
    Write-Host "Startup shortcut created (silent, no CMD)"
    Write-Host "  Link : $shortcutPath"
    Write-Host "  Run  : wscript //nologo `"$vbsPath`""
}

# Start now via VBS (no console)
& $wscript //nologo $vbsPath
Write-Host "Started AttendanceHelper."
