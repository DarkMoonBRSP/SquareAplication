@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title ExtremeSquare 0.2 - Parar Servidor

echo ========================================================
echo    EXTREMESQUARE 0.2 - ENCERRAR SERVIDOR
echo ========================================================
echo.

if not exist "logs\servidor.pid" (
    echo [INFO] Nenhum arquivo logs\servidor.pid encontrado.
    echo O servidor em segundo plano nao esta registrado como ativo.
    pause
    exit /b
)

set /p SRV_PID=<"logs\servidor.pid"
echo Tentando encerrar processo PID %SRV_PID%...

powershell -NoProfile -Command "try { Stop-Process -Id %SRV_PID% -Force -ErrorAction Stop; Write-Host '[OK] Servidor encerrado com sucesso.' } catch { Write-Host '[AVISO] Processo nao encontrado (ja estava encerrado).' }"
del /q "logs\servidor.pid" >nul 2>&1

echo.
pause
