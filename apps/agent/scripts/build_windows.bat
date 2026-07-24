@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."
set "ROOT=%CD%"
for %%I in ("%ROOT%\..\..") do set "REPO_ROOT=%%~fI"
set "AGENT_DIST_ROOT=%REPO_ROOT%\dist\agent"
set "BUILD_ROOT=%AGENT_DIST_ROOT%\.build-windows-x64"
set "DELIVERY=%AGENT_DIST_ROOT%\windows-x64"
set "GO_EXE=go"
where go >nul 2>nul
if not errorlevel 1 goto go_found
if exist "D:\Program Files\Go\bin\go.exe" (
  set "GO_EXE=D:\Program Files\Go\bin\go.exe"
  goto go_found
)
echo [ERROR] Go 1.26.5 was not found in PATH or D:\Program Files\Go\bin.
exit /b 1

:go_found
set "VERSION=0.2.0-win-agent"
set "TOOL_SOURCE=%REPO_ROOT%\resources\tools\windows-x64"
set "TOOL_GUARD=%REPO_ROOT%\scripts\build\validate_runtime_tools.ps1"
if not exist "%TOOL_GUARD%" (
  echo [ERROR] Runtime tool validation script is missing: %TOOL_GUARD%
  exit /b 1
)
echo [PRECHECK] Validating versioned runtime tools from local resources...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TOOL_GUARD%" -ToolRoot "%TOOL_SOURCE%"
if errorlevel 1 exit /b 1
if exist "%DELIVERY%" rmdir /s /q "%DELIVERY%"
if exist "%BUILD_ROOT%" rmdir /s /q "%BUILD_ROOT%"
mkdir "%BUILD_ROOT%" || exit /b 1
mkdir "%DELIVERY%" || exit /b 1
set "CGO_ENABLED=0"
set "GOOS=windows"
set "GOARCH=amd64"

echo [1/7] Building Python MR Collector...
if not exist "%ROOT%\mr_collector_py\build_windows.bat" (
  echo [ERROR] MR Collector build script is missing.
  exit /b 1
)
set "NETCONSOLE_AGENT_BUILD_ROOT=%BUILD_ROOT%\mr_collector"
pushd "%ROOT%\mr_collector_py"
call "build_windows.bat"
if errorlevel 1 (
  popd
  cd /d "%ROOT%"
  echo [ERROR] MR Collector build failed; Agent delivery cannot be completed.
  exit /b 1
)
popd
cd /d "%ROOT%"
if not exist "%BUILD_ROOT%\mr_collector\dist\netconsole-mr-collector.exe" (
  echo [ERROR] MR Collector output is missing after a successful build.
  exit /b 1
)

echo [2/7] Running go mod tidy...
"%GO_EXE%" mod tidy || exit /b 1
echo [3/7] Running tests...
"%GO_EXE%" test ./... || exit /b 1
echo [4/7] Building console exe...
"%GO_EXE%" build -trimpath -ldflags "-s -w -X main.version=%VERSION%" -o "%BUILD_ROOT%\netconsole-agent-console.exe" .\cmd\netconsole-agent || exit /b 1
echo [5/7] Building GUI tray exe...
"%GO_EXE%" build -trimpath -ldflags "-s -w -H=windowsgui -X main.version=%VERSION%" -o "%BUILD_ROOT%\netconsole-agent.exe" .\cmd\netconsole-agent || exit /b 1

echo [6/7] Preparing delivery directory...
copy /y "%BUILD_ROOT%\netconsole-agent.exe" "%DELIVERY%\netconsole-agent.exe" >nul || exit /b 1
copy /y "%BUILD_ROOT%\netconsole-agent-console.exe" "%DELIVERY%\netconsole-agent-console.exe" >nul || exit /b 1
copy /y "%ROOT%\resources\config\config.example.json" "%DELIVERY%\config.example.json" >nul || exit /b 1
copy /y "%ROOT%\resources\config\targets.example.json" "%DELIVERY%\targets.example.json" >nul || exit /b 1
copy /y "README.md" "%DELIVERY%\README.md" >nul || exit /b 1
mkdir "%DELIVERY%\tools\windows-x64" 2>nul
for %%T in (iperf3 fping) do (
  if not exist "%TOOL_SOURCE%\%%T" (
    echo [ERROR] Runtime tool source is missing: %TOOL_SOURCE%\%%T
    exit /b 1
  )
  xcopy /e /i /y "%TOOL_SOURCE%\%%T" "%DELIVERY%\tools\windows-x64\%%T\" >nul || exit /b 1
)
echo [VERIFY] Validating copied runtime tools in delivery...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TOOL_GUARD%" -ToolRoot "%DELIVERY%\tools\windows-x64"
if errorlevel 1 exit /b 1
mkdir "%DELIVERY%\tools\windows-x64\mr_collector" 2>nul
copy /y "%BUILD_ROOT%\mr_collector\dist\netconsole-mr-collector.exe" "%DELIVERY%\tools\windows-x64\mr_collector\netconsole-mr-collector.exe" >nul || exit /b 1

> "%DELIVERY%\init_agent_config.bat" (
  echo @echo off
  echo setlocal EnableExtensions
  echo chcp 65001 ^>nul
  echo if not defined NETCONSOLE_DATA_ROOT set "NETCONSOLE_DATA_ROOT=D:\NetConsoleData"
  echo if not defined NETCONSOLE_AGENT_HOME set "NETCONSOLE_AGENT_HOME=%%NETCONSOLE_DATA_ROOT%%\agents\local"
  echo if not exist "%%NETCONSOLE_AGENT_HOME%%" mkdir "%%NETCONSOLE_AGENT_HOME%%"
  echo if exist "%%NETCONSOLE_AGENT_HOME%%" goto agent_home_ready
  echo echo [ERROR] Cannot create Agent runtime directory: %%NETCONSOLE_AGENT_HOME%%
  echo exit /b 1
  echo :agent_home_ready
  echo if exist "%%NETCONSOLE_AGENT_HOME%%\config.json" goto config_ready
  echo if exist "%%~dp0config.example.json" goto config_template_ready
  echo echo [ERROR] Config template was not found: %%~dp0config.example.json
  echo exit /b 1
  echo :config_template_ready
  echo copy /y "%%~dp0config.example.json" "%%NETCONSOLE_AGENT_HOME%%\config.json" ^>nul
  echo if errorlevel 1 goto config_copy_failed
  echo echo [INIT] Created %%NETCONSOLE_AGENT_HOME%%\config.json from config.example.json
  echo :config_ready
  echo if exist "%%NETCONSOLE_AGENT_HOME%%\targets.json" goto targets_ready
  echo if exist "%%~dp0targets.example.json" goto targets_template_ready
  echo echo [ERROR] Targets template was not found: %%~dp0targets.example.json
  echo exit /b 1
  echo :targets_template_ready
  echo copy /y "%%~dp0targets.example.json" "%%NETCONSOLE_AGENT_HOME%%\targets.json" ^>nul
  echo if errorlevel 1 goto targets_copy_failed
  echo echo [INIT] Created %%NETCONSOLE_AGENT_HOME%%\targets.json from targets.example.json
  echo :targets_ready
  echo echo [INFO] Edit these files for real MR / iperf targets if needed: %%NETCONSOLE_AGENT_HOME%%
  echo exit /b 0
  echo :config_copy_failed
  echo echo [ERROR] Cannot initialize %%NETCONSOLE_AGENT_HOME%%\config.json
  echo exit /b 1
  echo :targets_copy_failed
  echo echo [ERROR] Cannot initialize %%NETCONSOLE_AGENT_HOME%%\targets.json
  echo exit /b 1
)
> "%DELIVERY%\start_agent.bat" (
  echo @echo off
  echo setlocal EnableExtensions
  echo chcp 65001 ^>nul
  echo cd /d "%%~dp0"
  echo if not defined NETCONSOLE_DATA_ROOT set "NETCONSOLE_DATA_ROOT=D:\NetConsoleData"
  echo if not defined NETCONSOLE_AGENT_HOME set "NETCONSOLE_AGENT_HOME=%%NETCONSOLE_DATA_ROOT%%\agents\local"
  echo call "%%~dp0init_agent_config.bat"
  echo if errorlevel 1 exit /b 1
  echo start "" "netconsole-agent.exe" --open --config "%%NETCONSOLE_AGENT_HOME%%\config.json" --targets "%%NETCONSOLE_AGENT_HOME%%\targets.json"
)
> "%DELIVERY%\start_console.bat" (
  echo @echo off
  echo setlocal EnableExtensions
  echo chcp 65001 ^>nul
  echo cd /d "%%~dp0"
  echo if not defined NETCONSOLE_DATA_ROOT set "NETCONSOLE_DATA_ROOT=D:\NetConsoleData"
  echo if not defined NETCONSOLE_AGENT_HOME set "NETCONSOLE_AGENT_HOME=%%NETCONSOLE_DATA_ROOT%%\agents\local"
  echo call "%%~dp0init_agent_config.bat"
  echo if errorlevel 1 exit /b 1
  echo "netconsole-agent-console.exe" --console --open --config "%%NETCONSOLE_AGENT_HOME%%\config.json" --targets "%%NETCONSOLE_AGENT_HOME%%\targets.json"
  echo pause
)
> "%DELIVERY%\check_win_compat.bat" (
  echo @echo off
  echo cd /d "%%~dp0"
  echo echo [1] Agent version
  echo netconsole-agent-console.exe --version
  echo echo [2] MR collector
  echo if exist "tools\windows-x64\mr_collector\netconsole-mr-collector.exe" tools\windows-x64\mr_collector\netconsole-mr-collector.exe --version
  echo echo [3] iperf3
  echo if exist "tools\windows-x64\iperf3\iperf3.exe" tools\windows-x64\iperf3\iperf3.exe --version
  echo echo [4] fping
  echo if exist "tools\windows-x64\fping\fping.exe" tools\windows-x64\fping\fping.exe --version
  echo pause
)
> "%DELIVERY%\stop_hint.txt" echo 退出 Agent 请使用托盘菜单“退出”；控制台版可按 Ctrl+C。
echo [7/7] Build complete: %DELIVERY%
endlocal
