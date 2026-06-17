@echo off
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"

set "BUILD_ROOT=%ROOT%build_output"
set "RELEASE_ROOT=%ROOT%release"

echo ==============================
echo NetConsole Build System
echo ROOT: %ROOT%
echo ==============================

echo [1/8] Stop NetConsole.exe
taskkill /F /IM NetConsole.exe >nul 2>nul

echo [2/8] Clean old build output
if exist "%BUILD_ROOT%" rmdir /S /Q "%BUILD_ROOT%"
if exist "%ROOT%build" rmdir /S /Q "%ROOT%build"
if exist "%ROOT%dist" rmdir /S /Q "%ROOT%dist"
if exist "%RELEASE_ROOT%" rmdir /S /Q "%RELEASE_ROOT%"

echo [3/8] Clean __pycache__
for /d /r %%D in (__pycache__) do (
    if exist "%%D" rmdir /S /Q "%%D"
)

echo [4/8] Auto release version, git commit, push and tag
if "%NETCONSOLE_RELEASE_DRY_RUN%"=="1" (
    "%PYTHON_EXE%" release.py --dry-run
) else (
    "%PYTHON_EXE%" release.py
)
if errorlevel 1 goto failed

echo [5/8] Install dependencies
"%PYTHON_EXE%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed

if not exist "%BUILD_ROOT%" mkdir "%BUILD_ROOT%"
"%PYTHON_EXE%" -c "from netconsole.core.version import APP_VERSION; print(APP_VERSION)" > "%BUILD_ROOT%\version.txt"
if errorlevel 1 goto failed
set /p APP_VERSION=<"%BUILD_ROOT%\version.txt"
if "%APP_VERSION%"=="" goto failed

echo [6/8] PyInstaller build

"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --onedir ^
  --windowed ^
  --name NetConsole ^
  --icon "%ROOT%netconsole\ui\icons\love.ico" ^
  --version-file "%ROOT%project\version_info.txt" ^
  --distpath "%BUILD_ROOT%\dist" ^
  --workpath "%BUILD_ROOT%\build" ^
  --specpath "%BUILD_ROOT%\spec" ^
  --add-data "%ROOT%netconsole;netconsole" ^
  main.py

if errorlevel 1 goto failed

echo [7/8] Copy docs/icons
xcopy /E /I /Y "netconsole\docs" "%BUILD_ROOT%\dist\NetConsole\netconsole\docs" >nul
xcopy /E /I /Y "netconsole\ui\icons" "%BUILD_ROOT%\dist\NetConsole\netconsole\ui\icons" >nul

echo [8/8] Create release zip
if not exist "%RELEASE_ROOT%" mkdir "%RELEASE_ROOT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%BUILD_ROOT%\dist\NetConsole\*' -DestinationPath '%RELEASE_ROOT%\NetConsole_%APP_VERSION%.zip' -Force"
if errorlevel 1 goto failed

echo DONE
echo ==============================
echo Output:
echo %BUILD_ROOT%\dist\NetConsole\NetConsole.exe
echo %RELEASE_ROOT%\NetConsole_%APP_VERSION%.zip
echo ==============================
exit /b 0

:failed
echo BUILD FAILED
exit /b 1
