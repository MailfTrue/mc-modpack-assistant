@echo off
rem Ручной запуск brain (Telegram-бот + мост), когда его не запускает сервер
rem (brain.autostart=false в config/modpack-bridge.json). При автозапуске этот файл не нужен.
rem Остановка: Ctrl+C.
chcp 65001 >nul
title Modpack brain
set PYTHONIOENCODING=utf-8
cd /d "%~dp0brain"

if not exist ".env" (
    echo Нет файла brain\.env — скопируй brain\.env.example в brain\.env и укажи SERVER_DIR.
    pause
    exit /b 1
)

uv run modpack-brain run
if errorlevel 1 (
    echo.
    echo brain завершился с ошибкой, смотри сообщения выше.
    pause
)
