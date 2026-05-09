@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Dashboard Meta Ads Heroturfs

echo.
echo ================================================
echo   Dashboard Meta Ads Heroturfs
echo   URL: http://127.0.0.1:5001
echo ================================================
echo.
echo Iniciando servidor Flask y abriendo navegador...
echo Para detener el servidor: cierra esta ventana o pulsa Ctrl+C
echo.

REM Lanzar el navegador en 3 segundos (en paralelo, ventana minimizada)
start "" /min cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:5001"

REM Lanzar Flask en esta consola (asi se ven los logs)
"%~dp0venv\Scripts\python.exe" app.py

REM Si Flask se para inesperadamente, dejar la ventana abierta para ver el error
echo.
echo El servidor se ha detenido.
pause
