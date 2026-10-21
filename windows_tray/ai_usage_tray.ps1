# AI usage tray - Claude / Codex remaining quota as double-ring icons in the Windows notification area.
#
# The data, icons and all UI text come from usage_json.py, so this script only draws them.
# Keep this file ASCII-only: Windows PowerShell 5.1 misreads BOM-less UTF-8.
#
#   -Mode Native  run usage_json.py with Windows Python (Claude Code / Codex used on Windows)
#   -Mode Wsl     run it inside a WSL distro (Claude Code / Codex used in WSL)
#
# Normally started hidden at logon by the launcher that install.ps1 / install.sh put in the Startup folder.
param(
    [ValidateSet("Native", "Wsl")][string]$Mode = "Native",
    [Parameter(Mandatory = $true)][string]$Script,   # Windows path (Native) or Linux path (Wsl)
    [string]$Python = "python.exe",                   # Native only
    [string]$Distro = "",                             # Wsl only
    [int]$IntervalSec = 60
)

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class AiUsageNative {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
# Without this, a 125%/150% display reports a 16px tray icon and Windows upscales it (blurry)
[void][AiUsageNative]::SetProcessDPIAware()

# One instance only
$mutex = New-Object System.Threading.Mutex($false, "Local\AiUsageTray")
if (-not $mutex.WaitOne(0)) { exit }

$iconSize = [System.Windows.Forms.SystemInformation]::SmallIconSize.Width
$labels = @{ refresh = "Refresh"; quit = "Quit"; updated = "Updated" }

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$showMenu = [System.Windows.Forms.NotifyIcon].GetMethod(
    "ShowContextMenu", [System.Reflection.BindingFlags]"NonPublic, Instance")

# One tray icon per service, created when the service first shows up in a snapshot
# (services are auto-detected by usage_json.py, so e.g. Codex appears once it is logged in)
$tray = [ordered]@{}

function New-TrayEntry([string]$name, [string]$text) {
    $ni = New-Object System.Windows.Forms.NotifyIcon
    $ni.Icon = [System.Drawing.SystemIcons]::Application
    $ni.ContextMenuStrip = $menu
    # Left click opens the same menu as right click
    $ni.add_MouseUp({
        param($s, $e)
        if ($e.Button -eq [System.Windows.Forms.MouseButtons]::Left) { $showMenu.Invoke($s, $null) }
    })
    $ni.Visible = $true
    $entry = @{ Icon = $ni; Owned = $null }
    $tray[$name] = $entry
    Set-TrayText $entry $text
    return $entry
}

function Remove-TrayEntry([string]$name) {
    $entry = $tray[$name]
    $entry.Icon.Visible = $false
    $entry.Icon.Dispose()
    if ($entry.Owned) { $entry.Owned.Dispose() }
    $tray.Remove($name)
}

function Set-TrayIcon($entry, [string]$b64) {
    # $b64 is an .ico with several sizes; pick the one matching the tray at this DPI
    $bytes = [Convert]::FromBase64String($b64)
    $ms = New-Object System.IO.MemoryStream(, $bytes)
    $icon = New-Object System.Drawing.Icon($ms, $iconSize, $iconSize)
    $ms.Dispose()
    $old = $entry.Owned
    $entry.Icon.Icon = $icon
    $entry.Owned = $icon
    if ($old) { $old.Dispose() }
}

function Set-TrayText($entry, [string]$text) {
    # NotifyIcon.Text is limited to 63 characters on .NET Framework
    if ($text.Length -gt 63) { $text = $text.Substring(0, 62) + [char]0x2026 }
    $entry.Icon.Text = $text
}

function Add-MenuText([string]$text, [bool]$bold = $false) {
    $item = New-Object System.Windows.Forms.ToolStripMenuItem($text)
    $item.Enabled = $false
    if ($bold) { $item.Font = New-Object System.Drawing.Font($item.Font, [System.Drawing.FontStyle]::Bold) }
    [void]$menu.Items.Add($item)
}

function Build-Menu($snap) {
    $menu.Items.Clear()
    if ($snap) {
        foreach ($svc in $snap.services) {
            Add-MenuText $svc.name $true
            if ($svc.account) { Add-MenuText ("    " + $svc.account) }
            foreach ($line in $svc.lines) { Add-MenuText ("    " + $line) }
            [void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
        }
    } elseif ($script:lastError) {
        Add-MenuText $script:lastError
        [void]$menu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
    }
    $refresh = New-Object System.Windows.Forms.ToolStripMenuItem($labels.refresh)
    $refresh.add_Click({ Start-Fetch })
    [void]$menu.Items.Add($refresh)
    $quit = New-Object System.Windows.Forms.ToolStripMenuItem($labels.quit)
    $quit.add_Click({ [System.Windows.Forms.Application]::ExitThread() })
    [void]$menu.Items.Add($quit)
    if ($snap) { Add-MenuText ("{0} {1}" -f $labels.updated, $snap.updated) }
}

# ---- fetching runs as a child process; a timer polls it so the UI never blocks
$script:proc = $null
$script:readTask = $null
$script:lastSnap = $null
$script:lastError = $null

function Start-Fetch {
    if ($script:proc) { return }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    if ($Mode -eq "Wsl") {
        $psi.FileName = "wsl.exe"
        # wsl.exe keeps quotes in the -d value literally (-> WSL_E_DISTRO_NOT_FOUND), so leave
        # the distro name bare; arguments after -e are unquoted normally
        $psi.Arguments = "-d $Distro -e python3 `"$Script`" --size $iconSize"
    } else {
        $psi.FileName = $Python
        $psi.Arguments = "`"$Script`" --size $iconSize"
    }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    try {
        $script:proc = [System.Diagnostics.Process]::Start($psi)
        $script:readTask = $script:proc.StandardOutput.ReadToEndAsync()
        $script:fetchStarted = Get-Date
    } catch {
        $script:proc = $null
        Show-Error "Could not start $($psi.FileName): $($_.Exception.Message)"
    }
}

function Show-Error([string]$message) {
    $script:lastError = $message
    foreach ($entry in $tray.Values) { Set-TrayText $entry ("Error: " + $message) }
    Build-Menu $script:lastSnap
}

function Complete-Fetch {
    $output = $script:readTask.Result
    $script:proc.WaitForExit()
    $code = $script:proc.ExitCode
    $script:proc.Dispose()
    $script:proc = $null
    if ($code -ne 0 -or -not $output) {
        # wsl.exe reports its own errors in UTF-16; dropping NULs keeps the ASCII part readable
        $detail = ($output -replace "`0", "").Trim()
        if ($detail.Length -gt 120) { $detail = $detail.Substring(0, 120) }
        Show-Error ("usage_json.py exited with code $code" + $(if ($detail) { ": $detail" } else { "" }))
        return
    }
    try { $snap = $output | ConvertFrom-Json } catch { Show-Error "Bad JSON from usage_json.py"; return }

    $script:lastSnap = $snap
    $script:lastError = $null
    if ($snap.labels) { $script:labels = @{ refresh = $snap.labels.refresh; quit = $snap.labels.quit; updated = $snap.labels.updated } }
    $names = @($snap.services | ForEach-Object { $_.name })
    foreach ($name in @($tray.Keys)) {
        if ($names -notcontains $name) { Remove-TrayEntry $name }
    }
    foreach ($svc in $snap.services) {
        $entry = $tray[$svc.name]
        if (-not $entry) { $entry = New-TrayEntry $svc.name $svc.name }
        Set-TrayIcon $entry $svc.icon
        Set-TrayText $entry $svc.tooltip
    }
    Build-Menu $snap
    foreach ($alert in $snap.alerts) {
        @($tray.Values)[0].Icon.ShowBalloonTip(10000, $alert.title, $alert.body, [System.Windows.Forms.ToolTipIcon]::Warning)
    }
}

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 1000
$script:nextFetch = Get-Date
$timer.add_Tick({
    if ($script:proc -and $script:readTask.IsCompleted) {
        Complete-Fetch
        $script:nextFetch = (Get-Date).AddSeconds($IntervalSec)
    } elseif ($script:proc -and ((Get-Date) - $script:fetchStarted).TotalSeconds -gt 90) {
        try { $script:proc.Kill() } catch {}
        $script:proc = $null
        Show-Error "usage_json.py timed out"
        $script:nextFetch = (Get-Date).AddSeconds($IntervalSec)
    } elseif (-not $script:proc -and (Get-Date) -ge $script:nextFetch) {
        Start-Fetch
    }
})

[void](New-TrayEntry "AI Usage" "AI Usage: loading...")  # placeholder until the first snapshot
Build-Menu $null
$timer.Start()
try {
    [System.Windows.Forms.Application]::Run()
} finally {
    $timer.Stop()
    foreach ($entry in $tray.Values) {
        $entry.Icon.Visible = $false
        $entry.Icon.Dispose()
        if ($entry.Owned) { $entry.Owned.Dispose() }
    }
    $mutex.ReleaseMutex()
}
