@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Sincronizar Datos HubSpot

echo.
echo ================================================
echo   Sincronizando datos de HubSpot CRM
echo   (contactos, deals, pipelines, asociaciones)
echo ================================================
echo.

"%~dp0venv\Scripts\python.exe" hubspot_sync.py %*

echo.
pause
