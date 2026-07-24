@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%\..\..\..") do set "REPO_ROOT=%%~fI"
set "DELIVERY=%REPO_ROOT%\dist\agent\windows-x64"
set "CONFIG_TEMPLATE=%REPO_ROOT%\apps\agent\resources\config\config.example.json"
set "TARGETS_TEMPLATE=%REPO_ROOT%\apps\agent\resources\config\targets.example.json"
if not defined NETCONSOLE_DATA_ROOT set "NETCONSOLE_DATA_ROOT=D:\NetConsoleData"
if not defined NETCONSOLE_AGENT_HOME set "NETCONSOLE_AGENT_HOME=%NETCONSOLE_DATA_ROOT%\agents\local"
set "EXE=netconsole-agent-console.exe"
if not exist "%DELIVERY%\%EXE%" (
  echo [ERROR] %EXE% was not found. Run scripts\build_windows.bat first.
  exit /b 1
)
if not exist "%NETCONSOLE_AGENT_HOME%" mkdir "%NETCONSOLE_AGENT_HOME%"
if not exist "%NETCONSOLE_AGENT_HOME%" (
  echo [ERROR] Cannot create Agent runtime directory: %NETCONSOLE_AGENT_HOME%
  exit /b 1
)
if not exist "%NETCONSOLE_AGENT_HOME%\config.json" (
  if not exist "%CONFIG_TEMPLATE%" (
    echo [ERROR] Config template was not found: %CONFIG_TEMPLATE%
    exit /b 1
  )
  copy /y "%CONFIG_TEMPLATE%" "%NETCONSOLE_AGENT_HOME%\config.json" >nul
  if errorlevel 1 (
    echo [ERROR] Cannot initialize %NETCONSOLE_AGENT_HOME%\config.json
    exit /b 1
  )
  echo [INIT] Created %NETCONSOLE_AGENT_HOME%\config.json from config.example.json
)
if not exist "%NETCONSOLE_AGENT_HOME%\targets.json" (
  if not exist "%TARGETS_TEMPLATE%" (
    echo [ERROR] Targets template was not found: %TARGETS_TEMPLATE%
    exit /b 1
  )
  copy /y "%TARGETS_TEMPLATE%" "%NETCONSOLE_AGENT_HOME%\targets.json" >nul
  if errorlevel 1 (
    echo [ERROR] Cannot initialize %NETCONSOLE_AGENT_HOME%\targets.json
    exit /b 1
  )
  echo [INIT] Created %NETCONSOLE_AGENT_HOME%\targets.json from targets.example.json
)
echo [INFO] Edit these files for real MR / iperf targets if needed: %NETCONSOLE_AGENT_HOME%
cd /d "%DELIVERY%"
echo Open http://127.0.0.1:18080 after startup.
"%EXE%" --console --open -config "%NETCONSOLE_AGENT_HOME%\config.json" -targets "%NETCONSOLE_AGENT_HOME%\targets.json"
endlocal
