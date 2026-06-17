@echo off
setlocal enabledelayedexpansion

REM =============================
REM Force project root
REM =============================
set "ROOT=%~dp0"
cd /d "%ROOT%project"

set "PROJECT_ROOT=%CD%"

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"

set "BUILD_ROOT=%PROJECT_ROOT%\build_output"
set "RELEASE_ROOT=%PROJECT_ROOT%\release"

echo ==============================
echo NetConsole Build System
echo PROJECT_ROOT: %PROJECT_ROOT%
echo ==============================

REM =============================
REM Stop running process
REM =============================
echo [1/8] Stop NetConsole.exe
taskkill /F /IM NetConsole.exe >nul 2>nul

REM =============================
REM Clean outputs (ONLY inside project)
REM =============================
echo [2/8] Clean build artifacts

if exist "%BUILD_ROOT%" rmdir /S /Q "%BUILD_ROOT%"
if exist "%PROJECT_ROOT%\build" rmdir /S /Q "%PROJECT_ROOT%\build"
if exist "%PROJECT_ROOT%\dist" rmdir /S /Q "%PROJECT_ROOT%\dist"
if exist "%RELEASE_ROOT%" rmdir /S /Q "%RELEASE_ROOT%"

REM =============================
REM Clean cache
REM =============================
echo [3/8] Clean __pycache__
for /d /r %%D in (__pycache__) do (
    if exist "%%D" rmdir /S /Q "%%D"
)

REM =============================
REM Release version step
REM =============================
echo [4/8] Auto release (git + version)
if "%NETCONSOLE_RELEASE_DRY_RUN%"=="1" (
    "%PYTHON_EXE%" release.py --dry-run
) else (
    "%PYTHON_EXE%" release.py
)

if errorlevel 1 goto failed

REM =============================
REM Install deps
REM =============================
echo [5/8] Install dependencies
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto failed

REM =============================
REM Prepare build folder
REM =============================
if not exist "%BUILD_ROOT%" mkdir "%BUILD_ROOT%"

REM =============================
REM Get version
REM =============================
for /f %%i in ('"%PYTHON_EXE%" -c "from netconsole.core.version import APP_VERSION; print(APP_VERSION)"') do set APP_VERSION=%%i

echo Version: %APP_VERSION%

REM =============================
REM PyInstaller build (IMPORTANT FIX)
REM =============================
echo [6/8] PyInstaller build

"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onedir ^
  --windowed ^
  --name NetConsole ^
  --icon "%PROJECT_ROOT%\netconsole\ui\icons\love.ico" ^
  --distpath "%BUILD_ROOT%\dist" ^
  --workpath "%BUILD_ROOT%\build" ^
  --specpath "%BUILD_ROOT%\spec" ^
  --add-data "%PROJECT_ROOT%\netconsole;netconsole" ^
  main.py

if errorlevel 1 goto failed

REM =============================
REM Copy resources
REM =============================
echo [7/8] Copy resources

xcopy /E /I /Y "%PROJECT_ROOT%\netconsole\docs" "%BUILD_ROOT%\dist\NetConsole\netconsole\docs" >nul
xcopy /E /I /Y "%PROJECT_ROOT%\netconsole\ui\icons" "%BUILD_ROOT%\dist\NetConsole\netconsole\ui\icons" >nul

REM =============================
REM Create release zip
REM =============================
echo [8/8] Create release package

if not exist "%RELEASE_ROOT%" mkdir "%RELEASE_ROOT%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
"Compress-Archive -Path '%BUILD_ROOT%\dist\NetConsole\*' -DestinationPath '%RELEASE_ROOT%\NetConsole_%APP_VERSION%.zip' -Force"

if errorlevel 1 goto failed

echo ==============================
echo BUILD SUCCESS
echo EXE: %BUILD_ROOT%\dist\NetConsole\NetConsole.exe
echo ZIP: %RELEASE_ROOT%\NetConsole_%APP_VERSION%.zip
echo ==============================
exit /b 0

:failed
echo BUILD FAILED
exit /b 1