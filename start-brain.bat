@echo off
rem Запуск brain: Telegram-бот + мост с модом. Остановка: Ctrl+C.
chcp 65001 >nul
title Modpack brain
set PYTHONIOENCODING=utf-8
cd /d "%~dp0brain"

if not exist ".env" (
    echo Нет файла brain\.env — скопируй brain\.env.example в brain\.env и заполни.
    pause
    exit /b 1
)

uv run modpack-brain run
if errorlevel 1 (
    echo.
    echo brain завершился с ошибкой, смотри сообщения выше.
    pause
)
