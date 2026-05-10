@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Sincronizar Datos Google Ads

echo.
echo ================================================
echo   Sincronizando datos de Google Ads
echo ================================================
echo.

"%~dp0venv\Scripts\python.exe" google_sync.py %*

echo.
pause
