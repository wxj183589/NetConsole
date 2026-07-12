@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
if not exist "go.mod" (
  echo [ERROR] The current directory is not the NetConsole Agent root. Cleanup cancelled.
  exit /b 1
)
for %%D in ("data\tasks" "logs" "packages") do (
  if exist "%%~D" rmdir /s /q "%%~D"
  mkdir "%%~D"
)
echo Agent tasks, logs and packages were cleaned. Configuration files were preserved.
endlocal
