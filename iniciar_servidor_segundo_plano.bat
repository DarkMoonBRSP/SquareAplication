@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title ExtremeSquare 0.2 - Segundo Plano (LAN/VPN)

echo ========================================================
echo    EXTREMESQUARE 0.2 - INICIAR EM SEGUNDO PLANO
echo ========================================================
echo.

if not exist "logs" mkdir logs

:: Se ja existir PID ativo, avisa e encerra
if exist "logs\servidor.pid" (
    set /p OLD_PID=<"logs\servidor.pid"
    powershell -NoProfile -Command "if (Get-Process -Id '%OLD_PID%' -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
    if %errorlevel% equ 0 (
        echo [AVISO] O servidor ja parece estar rodando em segundo plano (PID %OLD_PID%).
        echo Use parar_servidor.bat antes de iniciar novamente.
        pause
        exit /b
    ) else (
        del /q "logs\servidor.pid" >nul 2>&1
    )
)

:: Escolhe Python do venv se existir, senao do sistema (preferindo pythonw sem janela)
set "PY_CMD=pythonw"
if exist "venv\Scripts\pythonw.exe" (
    set "PY_CMD=%~dp0venv\Scripts\pythonw.exe"
) else (
    where pythonw >nul 2>&1
    if %errorlevel% neq 0 (
        if exist "venv\Scripts\python.exe" (
            set "PY_CMD=%~dp0venv\Scripts\python.exe"
        ) else (
            set "PY_CMD=python"
        )
    )
)

echo [1/2] Subindo servidor em segundo plano usando: %PY_CMD%
powershell -NoProfile -Command "$p = Start-Process -FilePath '%PY_CMD%' -ArgumentList 'app.py' -WorkingDirectory '%~dp0' -WindowStyle Hidden -RedirectStandardOutput '%~dp0logs\servidor.log' -RedirectStandardError '%~dp0logs\servidor_erro.log' -PassThru; Set-Content -Path '%~dp0logs\servidor.pid' -Value $p.Id -Encoding Ascii"

if not exist "logs\servidor.pid" (
    echo [ERRO] Nao foi possivel iniciar o servidor em segundo plano.
    pause
    exit /b 1
)

set /p NEW_PID=<"logs\servidor.pid"
echo [2/2] Servidor iniciado em segundo plano (PID: %NEW_PID%).
echo.
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "from managers.network_manager import obter_info_rede; i=obter_info_rede(5000); print('  Acesso Local :', i['url_local']); [print('  Acesso LAN   :', x['url'], '('+x['interface']+')') for x in i['interfaces_lan']]; [print('  Acesso VPN   :', x['url'], '('+x['interface']+')') for x in i['interfaces_vpn']]; print('  ESP32 POST   :', i['endpoint_telemetria'])" 2>nul
) else (
    python -c "from managers.network_manager import obter_info_rede; i=obter_info_rede(5000); print('  Acesso Local :', i['url_local']); [print('  Acesso LAN   :', x['url'], '('+x['interface']+')') for x in i['interfaces_lan']]; [print('  Acesso VPN   :', x['url'], '('+x['interface']+')') for x in i['interfaces_vpn']]; print('  ESP32 POST   :', i['endpoint_telemetria'])" 2>nul
)
echo.
echo Logs em: logs\servidor.log
echo Para encerrar o servidor, execute: parar_servidor.bat
echo ========================================================
timeout /t 4 >nul
