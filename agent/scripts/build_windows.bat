@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."
set "ROOT=%CD%"
set "DELIVERY=dist\netconsole-agent-windows-x64"
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
if exist "dist" rmdir /s /q "dist"
mkdir "dist" || exit /b 1
mkdir "%DELIVERY%" || exit /b 1
set "CGO_ENABLED=0"
set "GOOS=windows"
set "GOARCH=amd64"

echo [1/7] Building Python MR Collector if possible...
if exist "%ROOT%\mr_collector_py\build_windows.bat" (
  pushd "%ROOT%\mr_collector_py"
  call "build_windows.bat"
  if errorlevel 1 (
    popd
    cd /d "%ROOT%"
    echo [WARN] MR Collector build failed; put netconsole-mr-collector.exe manually.
  ) else (
    popd
    cd /d "%ROOT%"
  )
)

echo [2/7] Running go mod tidy...
"%GO_EXE%" mod tidy || exit /b 1
echo [3/7] Running tests...
"%GO_EXE%" test ./... || exit /b 1
echo [4/7] Building console exe...
"%GO_EXE%" build -trimpath -ldflags "-s -w -X main.version=%VERSION%" -o "dist\netconsole-agent-console.exe" .\cmd\netconsole-agent || exit /b 1
echo [5/7] Building GUI tray exe...
"%GO_EXE%" build -trimpath -ldflags "-s -w -H=windowsgui -X main.version=%VERSION%" -o "dist\netconsole-agent.exe" .\cmd\netconsole-agent || exit /b 1

echo [6/7] Preparing delivery directory...
copy /y "dist\netconsole-agent.exe" "%DELIVERY%\netconsole-agent.exe" >nul || exit /b 1
copy /y "dist\netconsole-agent-console.exe" "%DELIVERY%\netconsole-agent-console.exe" >nul || exit /b 1
copy /y "config.json" "%DELIVERY%\config.json" >nul || exit /b 1
copy /y "targets.json" "%DELIVERY%\targets.json" >nul || exit /b 1
copy /y "README.md" "%DELIVERY%\README.md" >nul || exit /b 1
mkdir "%DELIVERY%\data" 2>nul
mkdir "%DELIVERY%\logs" 2>nul
mkdir "%DELIVERY%\packages" 2>nul
mkdir "%DELIVERY%\tools\windows-x64" 2>nul
for %%T in (iperf3 fping mr_collector) do if exist "tools\windows-x64\%%T" xcopy /e /i /y "tools\windows-x64\%%T" "%DELIVERY%\tools\windows-x64\%%T\" >nul

> "%DELIVERY%\start_agent.bat" (
  echo @echo off
  echo cd /d "%%~dp0"
  echo start "" "netconsole-agent.exe" --open
)
> "%DELIVERY%\start_console.bat" (
  echo @echo off
  echo cd /d "%%~dp0"
  echo "netconsole-agent-console.exe" --console --open
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
echo [7/7] Build complete: %ROOT%\%DELIVERY%
endlocal
