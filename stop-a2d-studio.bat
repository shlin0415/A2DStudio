@echo off
setlocal
chcp 65001 >nul

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\a2d-studio-local.ps1" -Action Stop
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" echo A2D Studio stop did not complete. Check the log path printed above.
pause
exit /b %EXIT_CODE%
