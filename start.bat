@echo off
title JD Crypto Bot

:: Create venv if it doesn't exist
if not exist "venv\Scripts\activate.bat" (
    echo [*] Creando entorno virtual...
    python -m venv venv
)

:: Activate venv
call venv\Scripts\activate.bat

:: Install / update dependencies silently
echo [*] Verificando dependencias...
pip install -r requirements.txt -q

:: Check .env exists
if not exist ".env" (
    echo.
    echo [!] ERROR: No se encontro el archivo .env
    echo     Copia .env.example a .env y llena tus credenciales.
    pause
    exit /b 1
)

:: Launch bot
echo [*] Iniciando bot...
echo.
python main.py
pause
