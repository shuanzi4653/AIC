@echo off
title TianChuang - Local Standby (cloud fallback)
setlocal
set "ROOT=%~dp0"
set "RC=0"

echo.
echo   ============================================================
echo    TianChuang ZhiXun  -  LOCAL STANDBY START
echo    Production mode: prebuilt JAR + Python. No node, no compile.
echo    Use this when the cloud site is unreachable.
echo   ============================================================
echo.

if not exist "%ROOT%scripts\start.ps1" goto nofiles
if not exist "%ROOT%backend-python\.venv\Scripts\python.exe" echo   [warn] python venv missing
if not exist "%ROOT%models\ml-v3-national-vis.json" echo   [warn] model file missing - model axis will be empty
if not exist "%ROOT%data\tianchuang.mv.db" echo   [warn] local database missing - schema will be created on first start
if not exist "%ROOT%data\traffic\nation-network.json" echo   [warn] national network data missing

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\check-powershell.ps1"
if errorlevel 1 goto pserr

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\start.ps1" -OpenBrowser
set "RC=%errorlevel%"
if not "%RC%"=="0" goto failed

echo.
echo   ============================================================
echo    READY  -^>  http://127.0.0.1:8085
echo    Services run in the background. This window can stay open.
echo    To stop: double-click stop.bat
echo   ============================================================
echo.
pause
exit /b 0

:failed
echo.
echo   ============================================================
echo    START FAILED  (exit code %RC%)
echo      1) port 8085 / 8600 busy   -^> run stop.bat
echo      2) JAR missing             -^> run build.bat
echo      3) python venv broken      -^> see docs\deployment.md
echo    Log: .run\start.log
echo   ============================================================
pause
exit /b %RC%

:pserr
echo   Script encoding check failed (UTF-8 BOM required on .ps1 side).
pause
exit /b 1

:nofiles
echo   FAIL: run this launcher from the project root (scripts\start.ps1 not found).
pause
exit /b 1
