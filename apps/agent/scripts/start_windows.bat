@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0..\dist\netconsole-agent-windows-x64"
set "EXE=netconsole-agent-console.exe"
if not exist "%EXE%" (
  echo [ERROR] %EXE% was not found. Run scripts\build_windows.bat first.
  exit /b 1
)
echo Open http://127.0.0.1:18080 after startup.
"%EXE%" --console --open -config "config.json" -targets "targets.json"
endlocal
