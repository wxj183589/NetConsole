@echo off
setlocal

chcp 65001 >nul
set "PROJECT_ROOT=%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%scripts\build\package_local.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" (
    echo 打包完成。
) else (
    echo 打包失败，请查看上方错误和日志。
)

pause
exit /b %EXIT_CODE%
