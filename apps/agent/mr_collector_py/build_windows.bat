@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "BUILD_ROOT=%NETCONSOLE_AGENT_BUILD_ROOT%"
if not defined BUILD_ROOT set "BUILD_ROOT=%~dp0..\..\..\dist\agent\.build-windows-x64\mr_collector"
if exist "%BUILD_ROOT%" rmdir /s /q "%BUILD_ROOT%"
mkdir "%BUILD_ROOT%" || exit /b 1
where pyinstaller >nul 2>nul
if errorlevel 1 (
  echo [ERROR] PyInstaller not found. Install with: pip install pyinstaller netmiko paramiko cryptography
  exit /b 1
)
pyinstaller --clean --onefile --name netconsole-mr-collector --distpath "%BUILD_ROOT%\dist" --workpath "%BUILD_ROOT%\work" --specpath "%BUILD_ROOT%\spec" collector_cli.py || exit /b 1
echo Built: %BUILD_ROOT%\dist\netconsole-mr-collector.exe
endlocal
