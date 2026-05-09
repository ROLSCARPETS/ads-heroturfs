@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Sincronizar Datos Meta Ads

echo.
echo ================================================
echo   Sincronizando datos de Meta Ads
echo ================================================
echo.

"%~dp0venv\Scripts\python.exe" meta_sync.py

echo.
pause
