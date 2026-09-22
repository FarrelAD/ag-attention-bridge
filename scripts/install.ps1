# Install Ag Attention Bridge globally for Antigravity on Windows
# Requires no administrator privileges.
[CmdletBinding()]
param(
    [switch]$NoStartup,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

Write-Host "=== Installing Ag Attention Bridge on Windows for Antigravity ===" -ForegroundColor Cyan

# 1. Locate Python executable
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$VenvPythonw = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"

if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
    $PythonwExe = $VenvPythonw
    Write-Host "- Using virtualenv Python: $PythonExe" -ForegroundColor Green
} else {
    $PythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $PythonCmd) {
        Write-Error "Python 3.11+ was not found on PATH or in .venv. Please install Python first."
        exit 1
    }
    $PythonExe = $PythonCmd.Source
    $PythonwExe = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
    Write-Host "- Using system Python: $PythonExe" -ForegroundColor Green
}

# 2. Setup user bin directory in %LOCALAPPDATA%\ag-attention-bridge\bin
$LocalAppDir = Join-Path $env:LOCALAPPDATA "ag-attention-bridge"
$BinDir = Join-Path $LocalAppDir "bin"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
Write-Host "- Created user binary directory: $BinDir"

# Generate launcher shims in user bin directory
$HookAdapterCmd = Join-Path $BinDir "ag-hook-adapter.cmd"
$BridgeCmd = Join-Path $BinDir "ag-attention-bridge.cmd"

$HookAdapterContent = @"
@echo off
setlocal
set AG_ATTENTION_SYNTHETIC_FALLBACK=1
"$PythonExe" -m ag_attention_bridge.hooks.adapter %*
"@

$BridgeContent = @"
@echo off
setlocal
start "" "$PythonwExe" -m ag_attention_bridge.app %*
"@

[System.IO.File]::WriteAllText($HookAdapterCmd, $HookAdapterContent)
[System.IO.File]::WriteAllText($BridgeCmd, $BridgeContent)

Write-Host "  -> ag-hook-adapter.cmd deployed" -ForegroundColor Green
Write-Host "  -> ag-attention-bridge.cmd deployed" -ForegroundColor Green

# 3. Add to User PATH if not present
$UserPath = [Environment]::GetEnvironmentVariable("PATH", [EnvironmentVariableTarget]::User)
$Paths = ($UserPath -split ";") | Where-Object { $_ -ne "" }
if ($Paths -notcontains $BinDir) {
    Write-Host "- Adding $BinDir to User PATH..." -ForegroundColor Yellow
    $NewUserPath = "$UserPath;$BinDir"
    [Environment]::SetEnvironmentVariable("PATH", $NewUserPath, [EnvironmentVariableTarget]::User)
    $env:PATH = "$env:PATH;$BinDir"
    Write-Host "  -> PATH updated successfully" -ForegroundColor Green
} else {
    Write-Host "- $BinDir is already in User PATH"
}

# 4. Configure %USERPROFILE%\.gemini\config\hooks.json
$GeminiConfigDir = Join-Path $env:USERPROFILE ".gemini\config"
$HooksJsonPath = Join-Path $GeminiConfigDir "hooks.json"
New-Item -ItemType Directory -Force -Path $GeminiConfigDir | Out-Null

if (Test-Path $HooksJsonPath) {
    Copy-Item $HooksJsonPath "$HooksJsonPath.bak" -Force
    Write-Host "- Backed up existing hooks.json to hooks.json.bak"
}

# Safely merge hooks using native PowerShell JSON cmdlets
$Config = @{}
if (Test-Path $HooksJsonPath) {
    try {
        $Config = Get-Content -Raw -Path $HooksJsonPath -Encoding utf8 | ConvertFrom-Json
    } catch {
        $Config = @{}
    }
}

$BridgeHooks = @{
    PreToolUse = @(
        @{
            matcher = "ask_question|ask_permission"
            hooks   = @(
                @{
                    type    = "command"
                    command = "`"$HookAdapterCmd`" --event PreToolUse"
                    timeout = 30
                }
            )
        }
    )
    PreInvocation = @(
        @{
            type    = "command"
            command = "`"$HookAdapterCmd`" --event PreInvocation"
            timeout = 15
        }
    )
    PostInvocation = @(
        @{
            type    = "command"
            command = "`"$HookAdapterCmd`" --event PostInvocation"
            timeout = 15
        }
    )
    Stop = @(
        @{
            type    = "command"
            command = "`"$HookAdapterCmd`" --event Stop"
            timeout = 15
        }
    )
}

if ($Config.PSObject.Properties.Match("ag-attention-bridge").Count -gt 0) {
    $Config."ag-attention-bridge" = $BridgeHooks
} else {
    $Config | Add-Member -NotePropertyName "ag-attention-bridge" -NotePropertyValue $BridgeHooks -Force
}

$UpdatedJson = $Config | ConvertTo-Json -Depth 10
Set-Content -Path $HooksJsonPath -Value $UpdatedJson -Encoding utf8
Write-Host "- Successfully updated $HooksJsonPath" -ForegroundColor Green

# 5. Optional Windows Startup Autostart Shortcut
if (-not $NoStartup) {
    try {
        $WshShell = New-Object -ComObject WScript.Shell
        $StartupDir = [Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)
        $ShortcutPath = Join-Path $StartupDir "Ag Attention Bridge.lnk"
        $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $PythonwExe
        $Shortcut.Arguments = "-m ag_attention_bridge.app"
        $Shortcut.WorkingDirectory = $RepoRoot
        $Shortcut.WindowStyle = 7  # Minimized
        $Shortcut.Description = "Ag Attention Bridge Daemon"
        $Shortcut.Save()
        Write-Host "- Created Startup shortcut in $ShortcutPath" -ForegroundColor Green
    } catch {
        Write-Host "- Note: Could not create startup shortcut: $_" -ForegroundColor DarkGray
    }
}

# 6. Launch daemon in background
if (-not $NoStart) {
    Write-Host "- Starting Ag Attention Bridge daemon in background..." -ForegroundColor Cyan
    # Stop existing instance if running
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -like "*ag_attention_bridge.app*"
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

    Start-Process -FilePath $PythonwExe -ArgumentList "-m ag_attention_bridge.app" -WorkingDirectory $RepoRoot
    Start-Sleep -Milliseconds 500
    Write-Host "  -> Daemon started in background (Notification area tray icon active)" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Ag Attention Bridge Windows Installation Complete! ===" -ForegroundColor Cyan
Write-Host "Installed Executable: $BridgeCmd"
Write-Host "Hook Adapter:         $HookAdapterCmd"
Write-Host "Hooks File:           $HooksJsonPath"
Write-Host ""
