@echo off
REM Developer quality check script for Windows

echo ==^> Running Ruff check...
ruff check src tests
if errorlevel 1 exit /b %errorlevel%

echo ==^> Running Ruff format check...
ruff format --check src tests
if errorlevel 1 exit /b %errorlevel%

echo ==^> Running Mypy type checker...
mypy src
if errorlevel 1 exit /b %errorlevel%

echo ==^> Running Pytest with coverage...
pytest --cov=ag_attention_bridge --cov-report=term-missing
if errorlevel 1 exit /b %errorlevel%

echo ==^> All checks passed!
