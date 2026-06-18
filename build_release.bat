@echo off
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "PROJECT_ROOT=%ROOT%\project"
cd /d "%ROOT%"

set "PYTHON_EXE=python"
if exist "%ROOT%\.venv\Scripts\python.exe" set "PYTHON_EXE=%ROOT%\.venv\Scripts\python.exe"

set "BUILD_ROOT=%PROJECT_ROOT%\build"
set "DIST_ROOT=%PROJECT_ROOT%\dist"
set "SPEC_ROOT=%PROJECT_ROOT%\spec"
set "RELEASE_ROOT=%PROJECT_ROOT%\release"

echo ==============================
echo NetConsole Build System
echo ROOT: %ROOT%
echo ==============================

echo [1/8] Stop NetConsole.exe
taskkill /F /IM NetConsole.exe >nul 2>nul

echo [2/8] Clean old build output
if exist "%BUILD_ROOT%" rmdir /S /Q "%BUILD_ROOT%"
if exist "%DIST_ROOT%" rmdir /S /Q "%DIST_ROOT%"
if exist "%SPEC_ROOT%" rmdir /S /Q "%SPEC_ROOT%"
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
if not exist "%PROJECT_ROOT%" mkdir "%PROJECT_ROOT%"
cd /d "%PROJECT_ROOT%"

"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --onedir ^
  --windowed ^
  --name NetConsole ^
  --icon "%ROOT%\netconsole\ui\icons\love.ico" ^
  --version-file "%ROOT%\project\version_info.txt" ^
  --distpath "%DIST_ROOT%" ^
  --workpath "%BUILD_ROOT%" ^
  --specpath "%SPEC_ROOT%" ^
  --contents-directory "_internal" ^
  --exclude-module tests ^
  --exclude-module docs ^
  --exclude-module project ^
  --add-data "%ROOT%\netconsole\ui\icons;assets\ui\icons" ^
  --add-data "%ROOT%\netconsole\docs\changelog.md;assets\docs" ^
  "%ROOT%\main.py"

if errorlevel 1 goto failed

echo [7/8] Verify clean dist
cd /d "%ROOT%"
if exist "%DIST_ROOT%\NetConsole\netconsole" goto failed
if exist "%DIST_ROOT%\NetConsole\tests" goto failed
if exist "%DIST_ROOT%\NetConsole\docs" goto failed
if exist "%DIST_ROOT%\NetConsole\project" goto failed
powershell -NoProfile -ExecutionPolicy Bypass -Command "$allowed = @('NetConsole.exe', '_internal'); $unexpected = Get-ChildItem -LiteralPath '%DIST_ROOT%\NetConsole' -Force | Where-Object { $allowed -notcontains $_.Name }; if ($unexpected) { $unexpected | ForEach-Object { Write-Host ('Unexpected dist item: ' + $_.FullName) }; exit 1 }"
if errorlevel 1 goto failed

echo [8/8] Create release zip
if not exist "%RELEASE_ROOT%" mkdir "%RELEASE_ROOT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%DIST_ROOT%\NetConsole\*' -DestinationPath '%RELEASE_ROOT%\NetConsole_%APP_VERSION%.zip' -Force"
if errorlevel 1 goto failed

echo DONE
echo ==============================
echo Output:
echo %DIST_ROOT%\NetConsole\NetConsole.exe
echo %RELEASE_ROOT%\NetConsole_%APP_VERSION%.zip
echo ==============================
exit /b 0

:failed
echo BUILD FAILED
exit /b 1
