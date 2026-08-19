@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
for %%I in ("%~dp0..\..\..") do set "REPO_ROOT=%%~fI"
set "BUILD_ROOT=%NETCONSOLE_AGENT_BUILD_ROOT%"
if not defined BUILD_ROOT set "BUILD_ROOT=%~dp0..\..\..\dist\agent\.build-windows-x64\mr_collector"
if exist "%BUILD_ROOT%" rmdir /s /q "%BUILD_ROOT%"
mkdir "%BUILD_ROOT%" || exit /b 1
set "PYINSTALLER_CONFIG_DIR=%BUILD_ROOT%\pyinstaller-cache"
set "PYTHON_EXE=%REPO_ROOT%\.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" -m PyInstaller --version >nul 2>nul
  if not errorlevel 1 goto pyinstaller_module
)
where pyinstaller >nul 2>nul
if not errorlevel 1 goto pyinstaller_executable
echo [ERROR] PyInstaller not found in the project .venv or PATH. Install requirements-build.txt first.
exit /b 1

:pyinstaller_module
"%PYTHON_EXE%" -m PyInstaller --clean --onefile --name netconsole-mr-collector --distpath "%BUILD_ROOT%\dist" --workpath "%BUILD_ROOT%\work" --specpath "%BUILD_ROOT%\spec" collector_cli.py || exit /b 1
goto build_complete

:pyinstaller_executable
pyinstaller --clean --onefile --name netconsole-mr-collector --distpath "%BUILD_ROOT%\dist" --workpath "%BUILD_ROOT%\work" --specpath "%BUILD_ROOT%\spec" collector_cli.py || exit /b 1

:build_complete
echo Built: %BUILD_ROOT%\dist\netconsole-mr-collector.exe
endlocal
