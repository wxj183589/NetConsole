@echo off
setlocal
chcp 65001 >nul
set "AGENT_DATA_ROOT=%LOCALAPPDATA%\NetConsole\Agent"
if not exist "%AGENT_DATA_ROOT%" (
  echo [ERROR] Agent data root was not found: %AGENT_DATA_ROOT%
  exit /b 1
)
for %%D in ("%AGENT_DATA_ROOT%\data\tasks" "%AGENT_DATA_ROOT%\logs" "%AGENT_DATA_ROOT%\packages" "%AGENT_DATA_ROOT%\tmp" "%AGENT_DATA_ROOT%\runtime") do (
  if exist "%%~D" rmdir /s /q "%%~D"
  mkdir "%%~D"
)
echo Agent tasks, logs, packages, tmp and runtime files were cleaned from %AGENT_DATA_ROOT%. Configuration files were preserved.
endlocal
