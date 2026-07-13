@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0..\..\..\dist\agent\windows-x64"
set "NETCONSOLE_AGENT_HOME=%LOCALAPPDATA%\NetConsole\Agent"
set "EXE=netconsole-agent-console.exe"
if not exist "%EXE%" (
  echo [ERROR] %EXE% was not found. Run scripts\build_windows.bat first.
  exit /b 1
)
if not exist "%NETCONSOLE_AGENT_HOME%\config.json" (
  echo [ERROR] Copy config.example.json to %NETCONSOLE_AGENT_HOME%\config.json first.
  exit /b 1
)
if not exist "%NETCONSOLE_AGENT_HOME%\targets.json" (
  echo [ERROR] Copy targets.example.json to %NETCONSOLE_AGENT_HOME%\targets.json first.
  exit /b 1
)
echo Open http://127.0.0.1:18080 after startup.
"%EXE%" --console --open -config "%NETCONSOLE_AGENT_HOME%\config.json" -targets "%NETCONSOLE_AGENT_HOME%\targets.json"
endlocal
