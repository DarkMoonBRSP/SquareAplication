@echo off
chcp 65001 > nul
title ExtremeSquare - Inicializador Automático

echo ========================================================
echo         EXTREMESQUARE - INICIALIZADOR AUTOMÁTICO
echo ========================================================
echo.

:: 1. Verifica se o Python está instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Python não foi encontrado no PATH do sistema!
    echo Por favor, instale o Python e marque a opção 'Add Python to PATH'.
    echo.
    pause
    exit /b
)

:: 2. Cria ambiente virtual venv se ainda não existir
if not exist "venv\Scripts\activate.bat" (
    echo [1/3] Criando ambiente virtual Python (venv)...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERRO] Falha ao criar o ambiente virtual.
        pause
        exit /b
    )
    echo [OK] Ambiente virtual criado com sucesso!
    echo.
)

:: 3. Ativa o ambiente virtual
call venv\Scripts\activate.bat

:: 4. Instala ou atualiza as dependências do requirements.txt
echo [2/3] Verificando e instalando dependências...
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [AVISO] Houve um problema ao verificar pacotes via pip. Tentando continuar...
)
echo [OK] Dependências prontas!
echo.

:: 5. Inicia a aplicação
echo [3/3] Iniciando o servidor ExtremeSquare (Modo Híbrido LAN/VPN)...
echo.
python -c "from managers.network_manager import obter_info_rede; i=obter_info_rede(5000); print('  Local :', i['url_local']); [print('  LAN   :', x['url'], '('+x['interface']+')') for x in i['interfaces_lan']]; [print('  VPN   :', x['url'], '('+x['interface']+')') for x in i['interfaces_vpn']]" 2>nul
echo Pressione CTRL + C para encerrar o servidor.
echo ========================================================
echo.

:: Abre o navegador automaticamente após 2 segundos em segundo plano
start "" /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:5000"

:: Executa a aplicação Flask
python app.py

if %errorlevel% neq 0 (
    echo.
    echo [ERRO] A aplicação foi encerrada com erro.
    pause
)
