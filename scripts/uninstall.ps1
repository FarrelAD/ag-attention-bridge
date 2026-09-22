# Uninstall Ag Attention Bridge from Windows and Antigravity
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

Write-Host "=== Uninstalling Ag Attention Bridge from Windows ===" -ForegroundColor Cyan

# 1. Stop running daemon
Write-Host "- Stopping running daemon processes..." -ForegroundColor Cyan
Get-Process -Name "pythonw", "python" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like "*ag_attention_bridge.app*"
} | Stop-Process -Force -ErrorAction SilentlyContinue

# 2. Remove hooks from %USERPROFILE%\.gemini\config\hooks.json
$GeminiConfigDir = Join-Path $env:USERPROFILE ".gemini\config"
$HooksJsonPath = Join-Path $GeminiConfigDir "hooks.json"

if (Test-Path $HooksJsonPath) {
    try {
        $Content = Get-Content -Raw -Path $HooksJsonPath -Encoding utf8 | ConvertFrom-Json
        if ($Content.PSObject.Properties.Match("ag-attention-bridge").Count -gt 0) {
            $Content.PSObject.Properties.Remove("ag-attention-bridge")
            $UpdatedJson = $Content | ConvertTo-Json -Depth 10
            Set-Content -Path $HooksJsonPath -Value $UpdatedJson -Encoding utf8
            Write-Host "- Removed ag-attention-bridge from $HooksJsonPath" -ForegroundColor Green
        } else {
            Write-Host "- ag-attention-bridge not present in $HooksJsonPath"
        }
    } catch {
        Write-Host "- Warning: could not parse hooks.json: $_" -ForegroundColor Yellow
    }
}

# 3. Remove Windows Startup shortcut
$StartupDir = [Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)
$ShortcutPath = Join-Path $StartupDir "Ag Attention Bridge.lnk"
if (Test-Path $ShortcutPath) {
    Remove-Item -Path $ShortcutPath -Force
    Write-Host "- Removed Startup shortcut: $ShortcutPath" -ForegroundColor Green
}

# 4. Remove binaries from %LOCALAPPDATA%\ag-attention-bridge\bin
$LocalAppDir = Join-Path $env:LOCALAPPDATA "ag-attention-bridge"
$BinDir = Join-Path $LocalAppDir "bin"
if (Test-Path $BinDir) {
    Remove-Item -Path $BinDir -Recurse -Force
    Write-Host "- Removed binary directory: $BinDir" -ForegroundColor Green
}

# 5. Remove from User PATH
$UserPath = [Environment]::GetEnvironmentVariable("PATH", [EnvironmentVariableTarget]::User)
if ($UserPath) {
    $Paths = ($UserPath -split ";") | Where-Object { $_ -ne "" -and $_ -ne $BinDir }
    $NewUserPath = $Paths -join ";"
    [Environment]::SetEnvironmentVariable("PATH", $NewUserPath, [EnvironmentVariableTarget]::User)
    Write-Host "- Cleaned User PATH" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Ag Attention Bridge Uninstallation Complete ===" -ForegroundColor Cyan
