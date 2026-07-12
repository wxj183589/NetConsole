@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
set "EXE=bin\windows-x64\netconsole-agent.exe"
if not exist "%EXE%" (
  echo [ERROR] %EXE% was not found. Run scripts\build_windows.bat first.
  exit /b 1
)
echo Open http://127.0.0.1:18080 after startup.
"%EXE%" -config "config.json" -targets "targets.json"
endlocal
