@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where pyinstaller >nul 2>nul
if errorlevel 1 (
  echo [ERROR] PyInstaller not found. Install with: pip install pyinstaller netmiko paramiko cryptography
  exit /b 1
)
pyinstaller --clean --onefile --name netconsole-mr-collector collector_cli.py || exit /b 1
mkdir "..\tools\windows-x64\mr_collector" 2>nul
copy /y "dist\netconsole-mr-collector.exe" "..\tools\windows-x64\mr_collector\netconsole-mr-collector.exe" >nul || exit /b 1
echo Built: ..\tools\windows-x64\mr_collector\netconsole-mr-collector.exe
endlocal
