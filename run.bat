@echo off
REM ═══════════════════════════════════════════════════════
REM  AI Code Sherlock — Windows Launcher
REM  Двойной клик чтобы запустить
REM ═══════════════════════════════════════════════════════

cd /d "%~dp0"

REM Проверяем Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ══════════════════════════════════════════
    echo  ОШИБКА: Python не найден
    echo ══════════════════════════════════════════
    echo.
    echo Установи Python 3.11+ с python.org
    echo При установке отметь "Add to PATH"
    echo.
    pause
    exit /b 1
)

REM Проверяем PyQt6
python -c "import PyQt6" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ══════════════════════════════════════════
    echo  Устанавливаю зависимости...
    echo ══════════════════════════════════════════
    echo.
    pip install PyQt6 aiohttp aiofiles
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo ОШИБКА: не удалось установить пакеты.
        echo Запусти вручную: pip install PyQt6 aiohttp aiofiles
        pause
        exit /b 1
    )
    echo.
    echo Зависимости установлены!
    echo.
)

REM Запускаем приложение
python main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ══════════════════════════════════════════
    echo  Приложение завершилось с ошибкой.
    echo  Попробуй: python organize.py
    echo  Затем:    python main.py
    echo ══════════════════════════════════════════
    pause
)
