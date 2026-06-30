@echo off
setlocal

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "PYTHON_EXE=python"
if exist "%ROOT%\.venv\Scripts\python.exe" set "PYTHON_EXE=%ROOT%\.venv\Scripts\python.exe"

"%PYTHON_EXE%" "%ROOT%\clean_build_spec.py" --prepare --write-spec
if errorlevel 1 exit /b %ERRORLEVEL%
"%PYTHON_EXE%" "%ROOT%\project\build_release.py" --backend pyinstaller --build-editions both %*
exit /b %ERRORLEVEL%
