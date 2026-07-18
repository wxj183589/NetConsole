@echo off
setlocal

set "ROOT=%~dp0..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "PYTHON_EXE=python"
if exist "%ROOT%\.venv\Scripts\python.exe" set "PYTHON_EXE=%ROOT%\.venv\Scripts\python.exe"

"%PYTHON_EXE%" -m scripts.build.clean_build_spec --prepare --write-spec
if errorlevel 1 exit /b %ERRORLEVEL%
"%PYTHON_EXE%" -m scripts.build.build_release --backend pyinstaller %*
exit /b %ERRORLEVEL%
