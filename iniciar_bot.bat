@echo off
title Servidor Bot de Discord - Hitoha
cd /d "%~dp0"

echo ==================================================
echo   Iniciando Configuracion del Bot de Discord
echo ==================================================

:: 1. Comprobar si existe el entorno virtual venv
if not exist "venv" (
    echo [Info] No se detecto un entorno virtual. Creando uno nuevo con Python...
    py -m venv venv
    if errorlevel 1 (
        echo [Error] Fallo la creacion del entorno virtual con 'py -m venv'.
        echo Por favor asegurate de tener instalado Python correctamente.
        pause
        exit /b
    )
    echo [Info] Entorno virtual creado exitosamente.
)

:: 2. Activar entorno virtual
echo [Info] Activando entorno virtual...
call venv\Scripts\activate.bat

:: 3. Instalar/Actualizar dependencias
echo [Info] Comprobando e instalando dependencias (requirements.txt)...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo [Error] Hubo un error al instalar las dependencias de Python.
    pause
    exit /b
)

:: 4. Descargar FFmpeg portatil si no existe
echo [Info] Comprobando componentes de FFmpeg...
python download_ffmpeg.py
if errorlevel 1 (
    echo [Advertencia] Hubo un problema al comprobar o descargar FFmpeg.
    echo Si el bot de musica no funciona, asegurate de colocar ffmpeg.exe en esta carpeta manualmente.
)

:: 5. Comprobar si existe el archivo .env configurado
findstr /C:"TU_TOKEN_AQUI" .env > nul
if %errorlevel% == 0 (
    echo ==================================================
    echo [IMPORTANTE] Falta configurar tu Token de Discord!
    echo.
    echo Por favor:
    echo 1. Abre el archivo '.env' en esta carpeta con el Bloc de Notas.
    echo 2. Cambia 'TU_TOKEN_AQUI' por tu Token real de Discord Developer Portal.
    echo 3. Guarda el archivo y vuelve a ejecutar este .bat.
    echo ==================================================
    pause
    exit /b
)

:: 6. Iniciar el bot de Discord
echo [Info] Iniciando el bot de Discord (main.py)...
echo.
python main.py
echo.
echo [Info] El bot se ha detenido.
pause
