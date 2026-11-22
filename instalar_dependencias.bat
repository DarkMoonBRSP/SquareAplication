@echo off
chcp 65001 > nul
title Instalador de Dependências - ExtremeSquare

echo ========================================================
echo      INSTALAÇÃO DE DEPENDÊNCIAS - EXTREMESQUARE
echo ========================================================
echo.

:: Verifica se o Python está acessível
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Python não foi encontrado no sistema!
    echo Certifique-se de que o Python está instalado e marcado no PATH do Windows.
    echo.
    pause
    exit /b
)

echo Atualizando o pip...
python -m pip install --upgrade pip

echo.
echo Instalando pacotes listados no requirements.txt...
pip install -r requirements.txt

echo.
if %errorlevel% equ 0 (
    echo ========================================================
    echo  [SUCESSO] Todas as dependências foram instaladas com êxito!
    echo ========================================================
) else (
    echo ========================================================
    echo  [ERRO] Ocorreu uma falha durante a instalação.
    echo ========================================================
)

echo.
pause
