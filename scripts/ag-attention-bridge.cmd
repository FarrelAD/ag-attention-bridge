@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."

if exist "%REPO_ROOT%\.venv\Scripts\pythonw.exe" (
    start "" "%REPO_ROOT%\.venv\Scripts\pythonw.exe" -m ag_attention_bridge.app %*
) else (
    start "" pythonw -m ag_attention_bridge.app %*
)
