@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
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
if not exist "bin\windows-x64" mkdir "bin\windows-x64"
set "CGO_ENABLED=0"
set "GOOS=windows"
set "GOARCH=amd64"
echo [1/3] Downloading Go modules...
"%GO_EXE%" mod download || exit /b 1
echo [2/3] Running tests...
"%GO_EXE%" test ./... || exit /b 1
echo [3/3] Building netconsole-agent.exe...
"%GO_EXE%" build -trimpath -ldflags "-s -w" -o "bin\windows-x64\netconsole-agent.exe" .\cmd\netconsole-agent || exit /b 1
echo Build complete: %CD%\bin\windows-x64\netconsole-agent.exe
endlocal
