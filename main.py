"""
AI Code Sherlock — Entry point
Работает в двух режимах:
  1. Правильная структура (после organize.py): core/, ui/, services/ ...
  2. Плоская папка (все .py в одном месте): запускает organize.py автоматически
"""
import sys
import os
import traceback
import subprocess
from pathlib import Path

# ── Путь к папке проекта ─────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent

# ── Определяем режим: структурированный или плоский ──────────────────────────
_STRUCTURED = (_ROOT / "ui" / "main_window.py").exists()
_FLAT       = (_ROOT / "main_window.py").exists()

if not _STRUCTURED and not _FLAT:
    print("ОШИБКА: Не найдены файлы проекта рядом с main.py")
    print(f"Ожидалось в: {_ROOT}")
    input("Нажми Enter...")
    sys.exit(1)

# ── Если плоский режим → запустить organize.py ───────────────────────────────
if not _STRUCTURED and _FLAT:
    org = _ROOT / "organize.py"
    if org.exists():
        print("="*55)
        print("  AI Code Sherlock — первый запуск")
        print("="*55)
        print()
        print("Файлы лежат в плоской папке.")
        print("Автоматически создаю правильную структуру...")
        print()
        result = subprocess.run(
            [sys.executable, str(org)],
            cwd=str(_ROOT)
        )
        if result.returncode != 0:
            print("organize.py завершился с ошибкой.")
            input("Нажми Enter...")
            sys.exit(1)
        # Перезапускаем main.py после реорганизации
        print("Перезапуск...")
        os.execv(sys.executable, [sys.executable, __file__] + sys.argv[1:])
    else:
        print("ОШИБКА: organize.py не найден.")
        print("Скачай файл organize.py из проекта.")
        input("Нажми Enter...")
        sys.exit(1)

# ── Структура правильная → добавляем root в sys.path ─────────────────────────
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Импорты PyQt6 ─────────────────────────────────────────────────────────────
try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtGui import QFont
except ImportError:
    print("="*55)
    print("ОШИБКА: PyQt6 не установлен")
    print("="*55)
    print()
    print("Установи зависимости:")
    print()
    print("    pip install PyQt6 aiohttp aiofiles")
    print()
    input("Нажми Enter...")
    sys.exit(1)

# ── Импорт главного окна ──────────────────────────────────────────────────────
try:
    from ui.main_window import MainWindow
except ImportError as e:
    print(f"ОШИБКА импорта: {e}")
    print(f"sys.path: {sys.path[:3]}")
    print()
    print("Попробуй запустить organize.py заново:")
    print("    python organize.py")
    input("Нажми Enter...")
    sys.exit(1)


# ── Загрузка темы ─────────────────────────────────────────────────────────────
def load_stylesheet(app: QApplication) -> None:
    qss = _ROOT / "ui" / "styles" / "dark_theme.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))
    else:
        # Fallback minimal dark style
        app.setStyleSheet("""
            QMainWindow, QWidget { background-color: #0E1117; color: #CDD6F4; }
            QPushButton { background: #1E2030; border: 1px solid #2E3148;
                          border-radius: 5px; padding: 5px 12px; color: #CDD6F4; }
            QPushButton:hover { background: #2E3148; }
            QTextEdit, QPlainTextEdit { background: #131722; color: #CDD6F4;
                                        border: 1px solid #2E3148; }
        """)


# ── Обработчик необработанных исключений ─────────────────────────────────────
def setup_exception_handler(window: "MainWindow") -> None:
    def handle(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            window._logger.error(msg, source="UncaughtException")
        except Exception:
            pass
        QMessageBox.critical(
            window, "Критическая ошибка",
            f"Необработанное исключение:\n\n{exc_value}\n\n"
            "Подробности в панели Логи."
        )
    sys.excepthook = handle


# ── Точка входа ───────────────────────────────────────────────────────────────
def main():
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

    app = QApplication(sys.argv)
    app.setApplicationName("AI Code Sherlock")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("Sherlock")
    app.setStyle("Fusion")

    font = QFont()
    font.setFamilies(["JetBrains Mono", "Cascadia Code", "Consolas", "Courier New"])
    font.setPointSize(11)
    app.setFont(font)

    load_stylesheet(app)

    window = MainWindow()
    setup_exception_handler(window)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
