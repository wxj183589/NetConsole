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
echo Built: %~dp0dist\netconsole-mr-collector.exe
endlocal
