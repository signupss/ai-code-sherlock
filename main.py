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
def _build_dynamic_stylesheet(accent: str = "#7AA2F7") -> str:
    """Generate the full dark QSS with a configurable accent color."""
    # Derive slightly lighter/darker shades from the accent
    from PyQt6.QtGui import QColor
    c = QColor(accent)
    h, s, v, _ = c.getHsv()
    lighter = QColor.fromHsv(h, max(0, s - 30), min(255, v + 30)).name()
    darker  = QColor.fromHsv(h, min(255, s + 20), max(0, v - 30)).name()

    return f"""
/* ── Base ──────────────────────────────────────── */
QMainWindow, QDialog, QWidget {{
    background-color: #0E1117;
    color: #CDD6F4;
    font-family: "Segoe UI", "Noto Sans", Arial, sans-serif;
}}
QToolTip {{
    background: #1E2030;
    color: #CDD6F4;
    border: 1px solid #2E3148;
    border-radius: 4px;
    padding: 4px 8px;
}}

/* ── Buttons ────────────────────────────────────── */
QPushButton {{
    background: #1E2030;
    border: 1px solid #2E3148;
    border-radius: 5px;
    padding: 5px 14px;
    color: #CDD6F4;
    min-height: 22px;
}}
QPushButton:hover  {{ background: #2E3148; border-color: {accent}; }}
QPushButton:pressed {{ background: {darker}; }}
QPushButton:disabled {{ color: #3B4261; border-color: #1E2030; }}
QPushButton#primaryBtn {{
    background: {accent};
    border: none;
    color: #0E1117;
    font-weight: bold;
}}
QPushButton#primaryBtn:hover  {{ background: {lighter}; }}
QPushButton#primaryBtn:pressed {{ background: {darker}; }}
QPushButton#successBtn {{
    background: #1A2A1A;
    border: 1px solid #9ECE6A;
    color: #9ECE6A;
}}
QPushButton#successBtn:hover {{ background: #1E351E; }}
QPushButton#dangerBtn {{
    background: #2A0A0A;
    border: 1px solid #F7768E;
    color: #F7768E;
}}
QPushButton#dangerBtn:hover {{ background: #3A1010; }}
QPushButton#iconBtn {{
    background: transparent;
    border: none;
    color: #565f89;
    padding: 2px 6px;
}}
QPushButton#iconBtn:hover {{ background: #1E2030; color: #CDD6F4; }}

/* ── Inputs ─────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background: #131722;
    color: #CDD6F4;
    border: 1px solid #2E3148;
    border-radius: 5px;
    padding: 4px 8px;
    selection-background-color: #2E3148;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {accent};
}}
QSpinBox, QDoubleSpinBox, QComboBox {{
    background: #131722;
    color: #CDD6F4;
    border: 1px solid #2E3148;
    border-radius: 5px;
    padding: 3px 6px;
    min-height: 22px;
}}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {accent};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #565f89;
    margin-right: 4px;
}}
QComboBox QAbstractItemView {{
    background: #1E2030;
    color: #CDD6F4;
    border: 1px solid #2E3148;
    border-radius: 6px;
    selection-background-color: #2E3148;
    outline: none;
}}
QCheckBox {{
    color: #CDD6F4;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid #2E3148;
    background: #131722;
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
}}
QCheckBox::indicator:checked:hover {{ background: {lighter}; }}

/* ── Scroll bars ────────────────────────────────── */
QScrollBar:vertical {{
    background: #0A0D14;
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: #2E3148;
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {accent}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: #0A0D14;
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: #2E3148;
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {accent}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ── Tabs ───────────────────────────────────────── */
QTabWidget::pane {{
    border: none;
    background: #0E1117;
}}
QTabBar {{
    background: #0A0D14;
}}
QTabBar::tab {{
    background: #0A0D14;
    color: #565f89;
    padding: 6px 14px;
    border-bottom: 2px solid transparent;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    color: {accent};
    border-bottom: 2px solid {accent};
    background: #0E1117;
}}
QTabBar::tab:hover:!selected {{ color: #A9B1D6; }}
QTabBar::close-button {{
    subcontrol-position: right;
}}

/* ── Lists & Tables ─────────────────────────────── */
QListWidget, QTreeWidget, QTableWidget {{
    background: #0E1117;
    color: #CDD6F4;
    border: 1px solid #1E2030;
    border-radius: 6px;
    outline: none;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 4px 8px;
    border-radius: 3px;
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: #2E3148;
    color: #CDD6F4;
}}
QListWidget::item:hover, QTreeWidget::item:hover {{
    background: #1E2030;
}}
QHeaderView::section {{
    background: #0A0D14;
    color: #565f89;
    border: none;
    border-bottom: 1px solid #1E2030;
    padding: 5px 8px;
    font-size: 11px;
}}
QTableWidget {{
    gridline-color: #1E2030;
}}
QTableWidget::item:selected {{ background: #2E3148; }}

/* ── Group boxes ────────────────────────────────── */
QGroupBox {{
    border: 1px solid #1E2030;
    border-radius: 8px;
    margin-top: 10px;
    padding: 12px 10px 10px 10px;
    color: #A9B1D6;
    font-weight: bold;
    font-size: 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {accent};
}}

/* ── Splitters ──────────────────────────────────── */
QSplitter::handle {{
    background: #1E2030;
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical  {{ height: 1px; }}

/* ── Menu ───────────────────────────────────────── */
QMenuBar {{
    background: #080B12;
    color: #CDD6F4;
    border-bottom: 1px solid #1E2030;
}}
QMenuBar::item {{ padding: 4px 10px; border-radius: 4px; }}
QMenuBar::item:selected {{ background: #1E2030; color: {accent}; }}
QMenu {{
    background: #1E2030;
    color: #CDD6F4;
    border: 1px solid #2E3148;
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{ padding: 7px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: #2E3148; color: {accent}; }}
QMenu::separator {{ background: #2E3148; height: 1px; margin: 4px 0; }}

/* ── Progress ───────────────────────────────────── */
QProgressBar {{
    background: #1E2030;
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {accent};
    border-radius: 4px;
}}

/* ── Frames ─────────────────────────────────────── */
QFrame#toolbar {{
    background: #080B12;
    border-bottom: 1px solid #1E2030;
}}
QFrame#statusBar {{
    background: #080B12;
    border-top: 1px solid #1E2030;
}}
QFrame#panelHeader {{
    background: #0A0D14;
    border-bottom: 1px solid #1E2030;
}}
QFrame#centerPanel, QFrame#rightPanel {{
    background: #0E1117;
}}
QFrame#inputArea {{
    background: #0A0D14;
    border-top: 1px solid #1E2030;
}}

/* ── Chat bubbles ───────────────────────────────── */
QFrame#userBubble {{
    background: #131722;
    border: 1px solid #1E2030;
    border-radius: 8px;
}}
QFrame#assistantBubble {{
    background: #0D1520;
    border: 1px solid #1A2640;
    border-radius: 8px;
}}
QFrame#systemBubble {{
    background: #0A0D14;
    border: 1px solid #1E2030;
    border-radius: 6px;
}}

/* ── Log view ───────────────────────────────────── */
QPlainTextEdit#logView {{
    background: #080B12;
    color: #A9B1D6;
    border: none;
    font-size: 11px;
}}

/* ── Search bar ─────────────────────────────────── */
QFrame#searchBar {{
    background: #111820;
    border-top: 1px solid #1E2030;
}}

/* ── Section labels ─────────────────────────────── */
QLabel#sectionLabel {{
    color: #565f89;
    font-size: 10px;
    letter-spacing: 1px;
    font-weight: bold;
}}
QLabel#titleLabel {{
    color: #CDD6F4;
    font-size: 14px;
    font-weight: bold;
}}
QLabel#accentLabel {{ color: {accent}; font-size: 12px; }}
QLabel#statusLabel {{ color: #565f89; font-size: 11px; }}

/* ── Settings footer ────────────────────────────── */
QFrame#settingsFooter {{
    background: #0A0D14;
    border-top: 1px solid #1E2030;
}}
"""


def _apply_dark_titlebar(window) -> None:
    """Force dark title bar on Windows 10/11."""
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = int(window.winId())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        # Also set caption color to near-black
        DWMWA_CAPTION_COLOR = 35
        bg = ctypes.c_int(0x00120E0E)  # COLORREF: #0E0E12 as BGR
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_CAPTION_COLOR,
            ctypes.byref(bg), ctypes.sizeof(bg)
        )
        DWMWA_TEXT_COLOR = 36
        fg = ctypes.c_int(0x00F4D6CD)  # #CDD6F4 as BGR
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_TEXT_COLOR,
            ctypes.byref(fg), ctypes.sizeof(fg)
        )
    except Exception:
        pass  # silently ignore on unsupported Windows versions


def _apply_accent_caption(window, accent: str) -> None:
    """Set titlebar caption color to match accent on Windows 11."""
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from PyQt6.QtGui import QColor
        c = QColor(accent)
        # Convert to COLORREF (BGR)
        colorref = (c.blue() << 16) | (c.green() << 8) | c.red()
        hwnd = int(window.winId())
        DWMWA_BORDER_COLOR = 34
        bg_c = ctypes.c_int(colorref)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_BORDER_COLOR,
            ctypes.byref(bg_c), ctypes.sizeof(bg_c)
        )
    except Exception:
        pass


def _make_app_icon(accent: str = "#7AA2F7"):
    """Generate a programmatic SVG icon for the app."""
    from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QPen, QFont
    from PyQt6.QtCore import Qt, QRect
    px = QPixmap(64, 64)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Background circle
    p.setBrush(QBrush(QColor("#0E1117")))
    p.setPen(QPen(QColor(accent), 3))
    p.drawRoundedRect(4, 4, 56, 56, 12, 12)
    # Magnifying glass body
    p.setPen(QPen(QColor(accent), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.GlobalColor.transparent)
    p.drawEllipse(14, 10, 26, 26)
    # Magnifying glass handle
    p.drawLine(37, 34, 50, 47)
    # AI "spark" dot in center
    p.setBrush(QBrush(QColor(accent)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(24, 20, 6, 6)
    p.end()
    return QIcon(px)


def load_stylesheet(app, accent: str = "#7AA2F7") -> None:
    qss_path = _ROOT / "ui" / "styles" / "dark_theme.qss"
    if qss_path.exists():
        base = qss_path.read_text(encoding="utf-8")
        # Patch accent color in existing QSS
        import re
        base = re.sub(r"#7AA2F7", accent, base)
        app.setStyleSheet(base)
    else:
        app.setStyleSheet(_build_dynamic_stylesheet(accent))


def apply_settings_to_app(app, settings) -> None:
    """Apply font size and accent from settings to the running app."""
    font = app.font()
    font.setPointSize(getattr(settings, "ui_font_size", 11))
    app.setFont(font)
    accent = getattr(settings, "accent_color", "#7AA2F7")
    load_stylesheet(app, accent)


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

    # ── Load persisted settings ──────────────────────────────
    try:
        from services.settings_manager import SettingsManager
        saved = SettingsManager().load()
        accent    = getattr(saved, "accent_color", "#7AA2F7")
        font_size = getattr(saved, "ui_font_size", 11)
        language  = getattr(saved, "language", "ru")
        theme     = getattr(saved, "theme", "dark")
    except Exception:
        accent = "#7AA2F7"; font_size = 11; language = "ru"; theme = "dark"

    # ── Apply global font ────────────────────────────────────
    base_font = QFont()
    base_font.setFamilies(["Segoe UI", "Noto Sans", "Arial"])
    base_font.setPointSize(font_size)
    app.setFont(base_font)

    # ── Register ThemeManager ────────────────────────────────
    from ui.theme_manager import set_app, apply_theme, apply_font
    set_app(app)
    apply_theme(accent, font_size, theme)

    # ── Set language ─────────────────────────────────────────
    from ui.i18n import set_language
    set_language(language)

    # ── Icon ─────────────────────────────────────────────────
    app.setWindowIcon(_make_app_icon(accent))

    # ── Create main window ───────────────────────────────────
    window = MainWindow()
    from ui.theme_manager import set_window
    set_window(window)

    # ── Dark OS titlebar ─────────────────────────────────────
    _apply_dark_titlebar(window)
    _apply_accent_caption(window, accent)

    # ── Live settings reload ─────────────────────────────────
    def _on_settings_changed(s):
        new_accent = getattr(s, "accent_color", "#7AA2F7")
        new_size   = getattr(s, "ui_font_size", 11)
        new_theme  = getattr(s, "theme", "dark")
        new_lang   = getattr(s, "language", "ru")
        apply_font(new_size)
        apply_theme(new_accent, new_size, new_theme)
        app.setWindowIcon(_make_app_icon(new_accent))
        _apply_dark_titlebar(window)
        _apply_accent_caption(window, new_accent)
        # Apply language change
        from ui.i18n import set_language, retranslate_widget
        set_language(new_lang)
        retranslate_widget(window)
        # Deferred second repaint — ensures scroll areas and chat bubbles repaint
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(80, lambda: [
            w.update() for w in app.allWidgets() if w.isVisible()
        ])
        QTimer.singleShot(150, window.repaint)

    try:
        window.settings_changed.connect(_on_settings_changed)
    except Exception:
        pass

    setup_exception_handler(window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
