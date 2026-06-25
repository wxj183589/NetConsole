@echo off
setlocal

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "PYTHON_EXE=%ROOT%\.venv\Scripts\python.exe"

cd /d "%ROOT%"

if not exist "%PYTHON_EXE%" (
    echo BUILD FAILED
    echo Missing virtual environment Python:
    echo %PYTHON_EXE%
    exit /b 1
)

"%PYTHON_EXE%" "%ROOT%\project\build_nuitka_release.py" %*
exit /b %ERRORLEVEL%
