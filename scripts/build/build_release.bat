@echo off
setlocal

set "ROOT=%~dp0..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "PYTHON_EXE=python"
if exist "%ROOT%\.venv\Scripts\python.exe" set "PYTHON_EXE=%ROOT%\.venv\Scripts\python.exe"

set "HAS_ADMIN_UNLOCK_ARG="
call :scan_args %*
if not defined HAS_ADMIN_UNLOCK_ARG if not defined NETCONSOLE_ADMIN_UNLOCK_PASSWORD call :prompt_admin_unlock_password

"%PYTHON_EXE%" -m scripts.build.clean_build_spec --prepare --write-spec
if errorlevel 1 exit /b %ERRORLEVEL%
"%PYTHON_EXE%" -m scripts.build.build_release --backend pyinstaller --build-editions both %*
exit /b %ERRORLEVEL%

:scan_args
if "%~1"=="" exit /b 0
if /i "%~1"=="--admin-unlock-password" (
    set "HAS_ADMIN_UNLOCK_ARG=1"
    exit /b 0
)
set "CURRENT_ARG=%~1"
if /i "%CURRENT_ARG:~0,24%"=="--admin-unlock-password=" (
    set "HAS_ADMIN_UNLOCK_ARG=1"
    exit /b 0
)
shift
goto scan_args

:prompt_admin_unlock_password
echo.
echo Customer admin unlock password is optional.
echo Leave empty to build customer edition without internal unlock.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\build\read_admin_unlock_password.ps1"`) do set "NETCONSOLE_ADMIN_UNLOCK_PASSWORD=%%P"
exit /b 0
