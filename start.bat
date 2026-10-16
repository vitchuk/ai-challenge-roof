@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo [setup] creating virtual environment ...
    py -m venv .venv
)

call ".venv\Scripts\activate.bat"

echo [setup] installing backend dependencies ...
python -m pip install --disable-pip-version-check -q -r server\requirements.txt

if not exist "client\node_modules" (
    echo [setup] installing client dependencies ...
    pushd client
    call npm install
    popd
)

if not exist "tools\github-mcp-server.exe" (
    echo [setup] downloading GitHub MCP Server ...
    powershell -NoProfile -ExecutionPolicy Bypass -File setup_mcp.ps1
)

echo [run] starting application ...
python scripts\dev.py
