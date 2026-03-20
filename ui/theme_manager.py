"""
ThemeManager — builds and applies the full QSS stylesheet dynamically.
Accent color is injected at runtime; all other colors stay fixed (TokyoNight).
"""
from __future__ import annotations
from PyQt6.QtGui import QColor


def _shade(hex_color: str, lighten: int = 0, darken: int = 0,
           saturate: int = 0, desaturate: int = 0) -> str:
    c = QColor(hex_color)
    h, s, v, a = c.getHsv()
    s = max(0, min(255, s + saturate - desaturate))
    v = max(0, min(255, v + lighten - darken))
    return QColor.fromHsv(h, s, v, a).name()


def build_stylesheet(accent: str = "#7AA2F7", font_size: int = 11) -> str:
    """Return complete QSS for the application with the given accent color."""
    ac  = accent
    ac_l = _shade(ac, lighten=30, desaturate=20)   # lighter accent
    ac_d = _shade(ac, darken=30,  saturate=20)      # darker accent
    ac_dim = _shade(ac, darken=60, desaturate=80)   # very dim, used for borders

    fs   = font_size
    fs_s = max(8, fs - 1)   # small
    fs_l = fs + 1            # large

    return f"""
/* ═══════════════════════════════════════════════════════
   AI Code Sherlock — Dynamic Theme  (auto-generated)
   ═══════════════════════════════════════════════════════ */

/* ── Reset ─────────────────────────────────────────────── */
* {{
    outline: none;
    font-size: {fs}pt;
}}
QMainWindow, QDialog, QWidget {{
    background-color: #0E1117;
    color: #CDD6F4;
}}
QWidget {{
    selection-background-color: #2E3148;
    selection-color: #CDD6F4;
}}

/* ── Named Panels ──────────────────────────────────────── */
QFrame#leftPanel, QFrame#rightPanel {{
    background-color: #131722;
    border: none;
}}
QFrame#centerPanel {{
    background-color: #0E1117;
    border: none;
}}
QFrame#toolbar {{
    background-color: #0A0D14;
    border-bottom: 1px solid #1E2030;
    min-height: 40px;
    max-height: 40px;
    padding: 0 8px;
}}
QFrame#statusBar {{
    background-color: #080B12;
    border-top: 1px solid #1E2030;
    min-height: 22px;
    max-height: 22px;
}}
QFrame#panelHeader {{
    background-color: #0A0D14;
    border-bottom: 1px solid #1E2030;
    min-height: 32px;
    max-height: 32px;
}}
QFrame#inputArea {{
    background-color: #0A0D14;
    border-top: 1px solid #1E2030;
}}
QFrame#settingsFooter {{
    background-color: #0A0D14;
    border-top: 1px solid #1E2030;
}}

/* ── Buttons (base) ────────────────────────────────────── */
QPushButton {{
    background-color: #1A1D2E;
    border: 1px solid #2E3148;
    border-radius: 6px;
    padding: 4px 14px;
    color: #CDD6F4;
    font-size: {fs}pt;
    font-weight: 500;
    min-height: 24px;
}}
QPushButton:hover {{
    background-color: #252840;
    border-color: {ac};
    color: #FFFFFF;
}}
QPushButton:pressed {{
    background-color: {ac_d};
    border-color: {ac_d};
    color: #0E1117;
}}
QPushButton:disabled {{
    color: #3B4261;
    border-color: #1E2030;
    background-color: #0E1117;
}}
QPushButton:checked {{
    background-color: {ac_dim};
    border-color: {ac};
    color: {ac};
}}

/* ── Named button variants ─────────────────────────────── */
QPushButton#primaryBtn {{
    background-color: {ac};
    border-color: {ac};
    color: #0E1117;
    font-weight: bold;
}}
QPushButton#primaryBtn:hover  {{ background-color: {ac_l}; border-color: {ac_l}; }}
QPushButton#primaryBtn:pressed {{ background-color: {ac_d}; border-color: {ac_d}; }}

QPushButton#successBtn {{
    background-color: #1A2A1A;
    border-color: #9ECE6A;
    color: #9ECE6A;
}}
QPushButton#successBtn:hover {{ background-color: #1E351E; color: #B2E07E; }}

QPushButton#dangerBtn {{
    background-color: #2A0A0A;
    border-color: #F7768E;
    color: #F7768E;
}}
QPushButton#dangerBtn:hover {{ background-color: #3D1010; color: #FF9EAE; }}

QPushButton#iconBtn {{
    background-color: transparent;
    border: none;
    color: #565f89;
    padding: 2px 8px;
    font-size: {fs_s}pt;
}}
QPushButton#iconBtn:hover {{ background-color: #1E2030; color: #CDD6F4; border-radius: 4px; }}

QPushButton#toggleBtn {{
    background-color: transparent;
    border: 1px solid #2E3148;
    color: #A9B1D6;
    font-size: {fs_s}pt;
    padding: 3px 10px;
}}
QPushButton#toggleBtn:hover   {{ border-color: {ac}; color: {ac}; }}
QPushButton#toggleBtn:checked {{
    background-color: {ac_dim};
    border-color: {ac};
    color: {ac};
    font-weight: bold;
}}

/* ── Toolbar buttons get brighter labels ───────────────── */
QFrame#toolbar QPushButton {{
    background-color: #1A1D2E;
    border: 1px solid #2E3148;
    border-radius: 5px;
    color: #CDD6F4;
    font-size: {fs_s}pt;
    padding: 3px 10px;
    min-height: 22px;
}}
QFrame#toolbar QPushButton:hover {{
    background-color: #252840;
    border-color: {ac};
    color: #FFFFFF;
}}
QFrame#toolbar QPushButton:checked {{
    background-color: {ac_dim};
    border-color: {ac};
    color: {ac};
}}
QFrame#toolbar QPushButton#dangerBtn {{
    background-color: #2A0A0A;
    border-color: #F7768E;
    color: #F7768E;
}}

/* ── Text inputs ───────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: #131722;
    color: #CDD6F4;
    border: 1px solid #2E3148;
    border-radius: 5px;
    padding: 4px 8px;
    font-size: {fs}pt;
    selection-background-color: #2E3148;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {ac};
}}
QLineEdit::placeholder, QTextEdit::placeholder {{ color: #3B4261; }}

/* ── Spin/Combo ────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: #131722;
    color: #CDD6F4;
    border: 1px solid #2E3148;
    border-radius: 5px;
    padding: 3px 8px;
    font-size: {fs}pt;
    min-height: 22px;
}}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ac}; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: #1E2030;
    border: none;
    width: 16px;
    border-radius: 3px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {ac_dim};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
    background: transparent;
}}
QComboBox::down-arrow {{
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #565f89;
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: #1E2030;
    color: #CDD6F4;
    border: 1px solid {ac};
    border-radius: 6px;
    selection-background-color: #2E3148;
    selection-color: {ac};
    padding: 4px;
    outline: none;
}}
QComboBox QAbstractItemView::item {{ padding: 6px 12px; border-radius: 4px; }}
QComboBox QAbstractItemView::item:hover {{ background-color: #2E3148; }}

/* ── Checkboxes ────────────────────────────────────────── */
QCheckBox {{ color: #CDD6F4; spacing: 8px; font-size: {fs}pt; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid #2E3148;
    background-color: #131722;
}}
QCheckBox::indicator:checked {{
    background-color: {ac};
    border-color: {ac};
    image: none;
}}
QCheckBox::indicator:checked:hover {{ background-color: {ac_l}; }}
QCheckBox::indicator:hover {{ border-color: {ac}; }}

/* ── Scrollbars ────────────────────────────────────────── */
QScrollBar:vertical {{
    background: #0A0D14;
    width: 8px;
    border-radius: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #2E3148;
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {ac}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{
    background: #0A0D14;
    height: 8px;
    border-radius: 4px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: #2E3148;
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {ac}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; border: none; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* ── Tabs ──────────────────────────────────────────────── */
QTabWidget::pane {{ border: none; background: #0E1117; }}
QTabWidget::tab-bar {{ alignment: left; }}
QTabBar {{ background: #0A0D14; }}
QTabBar::tab {{
    background: #0A0D14;
    color: #565f89;
    padding: 6px 14px;
    border-bottom: 2px solid transparent;
    font-size: {fs_s}pt;
    min-width: 60px;
}}
QTabBar::tab:selected {{
    color: {ac};
    border-bottom: 2px solid {ac};
    background: #0E1117;
    font-weight: bold;
}}
QTabBar::tab:hover:!selected {{ color: #A9B1D6; background: #111520; }}
QTabBar::close-button {{ subcontrol-position: right; }}

/* ── Menus (ALL menus get dark style) ─────────────────── */
QMenuBar {{
    background-color: #080B12;
    color: #CDD6F4;
    border-bottom: 1px solid #1E2030;
    font-size: {fs}pt;
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 10px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{ background-color: #1E2030; color: {ac}; }}
QMenuBar::item:pressed  {{ background-color: #2E3148; }}

QMenu {{
    background-color: #131722;
    color: #CDD6F4;
    border: 1px solid #2E3148;
    border-radius: 8px;
    padding: 6px 0;
    font-size: {fs}pt;
}}
QMenu::item {{ padding: 7px 24px 7px 16px; border-radius: 4px; margin: 1px 4px; }}
QMenu::item:selected {{ background-color: #2E3148; color: {ac}; }}
QMenu::item:disabled {{ color: #3B4261; }}
QMenu::separator {{ background-color: #2E3148; height: 1px; margin: 5px 10px; }}
QMenu::indicator {{ width: 14px; height: 14px; margin-left: 6px; }}
QMenu::indicator:checked {{ background-color: {ac}; border-radius: 3px; }}

/* ── Tooltip ───────────────────────────────────────────── */
QToolTip {{
    background-color: #1E2030;
    color: #CDD6F4;
    border: 1px solid {ac};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: {fs_s}pt;
}}

/* ── Lists / Trees / Tables ────────────────────────────── */
QListWidget, QTreeWidget, QTableWidget {{
    background-color: #0E1117;
    color: #CDD6F4;
    border: 1px solid #1E2030;
    border-radius: 6px;
    font-size: {fs}pt;
    outline: none;
    alternate-background-color: #111520;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 4px 8px;
    border-radius: 3px;
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: #2E3148;
    color: {ac};
}}
QListWidget::item:hover:!selected,
QTreeWidget::item:hover:!selected {{ background-color: #1A1D2E; }}
QTreeWidget::branch {{ background: transparent; }}
QHeaderView::section {{
    background-color: #0A0D14;
    color: #565f89;
    border: none;
    border-bottom: 1px solid #1E2030;
    padding: 5px 10px;
    font-size: {fs_s}pt;
}}
QTableWidget {{ gridline-color: #1E2030; }}
QTableWidget::item:selected {{ background-color: #2E3148; color: {ac}; }}

/* ── Group boxes ───────────────────────────────────────── */
QGroupBox {{
    border: 1px solid #1E2030;
    border-radius: 8px;
    margin-top: 12px;
    padding: 14px 10px 10px 10px;
    color: #A9B1D6;
    font-size: {fs}pt;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: {ac};
    font-weight: bold;
}}

/* ── Splitters ─────────────────────────────────────────── */
QSplitter::handle {{ background-color: #1E2030; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical   {{ height: 1px; }}
QSplitter::handle:hover {{ background-color: {ac}; }}

/* ── Progress ──────────────────────────────────────────── */
QProgressBar {{
    background-color: #1E2030;
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background-color: {ac}; border-radius: 4px; }}

/* ── Dialog / Frame specifics ──────────────────────────── */
QFrame#userBubble {{
    background-color: #131722;
    border: 1px solid #1E2030;
    border-radius: 8px;
}}
QFrame#assistantBubble {{
    background-color: #0D1520;
    border: 1px solid #1A2640;
    border-radius: 8px;
}}
QFrame#systemBubble {{
    background-color: #0A0D14;
    border: 1px solid #1E2030;
    border-radius: 6px;
}}
QFrame#searchBar {{
    background-color: #111820;
    border-top: 1px solid #1E2030;
}}
QFrame#editorToolbar {{
    background-color: #0A0D14;
    border-bottom: 1px solid #1E2030;
}}
QFrame#editorStatus {{
    background-color: #0A0D14;
    border-top: 1px solid #1E2030;
}}

/* ── Labels ────────────────────────────────────────────── */
QLabel {{ font-size: {fs}pt; color: #CDD6F4; }}
QLabel#sectionLabel {{
    color: #565f89;
    font-size: {fs_s}pt;
    letter-spacing: 1px;
    font-weight: bold;
}}
QLabel#titleLabel   {{ color: #CDD6F4; font-size: {fs_l}pt; font-weight: bold; }}
QLabel#accentLabel  {{ color: {ac}; font-size: {fs}pt; }}
QLabel#statusLabel  {{ color: #565f89; font-size: {fs_s}pt; }}
QLabel#breadcrumb   {{
    background-color: #080B12;
    color: {ac};
    font-size: {fs_s}pt;
    border-bottom: 1px solid #1E2030;
    padding: 2px 12px;
}}

/* ── Log / plain text views ────────────────────────────── */
QPlainTextEdit#logView {{
    background-color: #080B12;
    color: #A9B1D6;
    border: none;
    font-size: {fs_s}pt;
}}

/* ── Chat input ────────────────────────────────────────── */
QTextEdit#chatInput {{
    background-color: #131722;
    color: #CDD6F4;
    border: 1px solid #2E3148;
    border-radius: 6px;
    font-size: {fs}pt;
}}
QTextEdit#chatInput:focus {{ border-color: {ac}; }}

/* ── Patch card ────────────────────────────────────────── */
QFrame[class="patchCard"] {{
    background-color: #131722;
    border: 1px solid #2E3148;
    border-radius: 6px;
}}
"""


_app_ref = None   # weak reference to QApplication
_window_ref = None


def apply_dark_titlebar(widget) -> None:
    """
    Force dark OS title bar on Windows 10/11 via DWMAPI.
    Safe to call on any platform — silently ignored on non-Windows.
    Call from QDialog.showEvent() after super().showEvent(event).
    """
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 11 22H2+), fallback 19
        for attr in (20, 19):
            try:
                value = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
                )
                break
            except Exception:
                continue
        # Dark caption/text colors (Windows 11)
        try:
            DWMWA_CAPTION_COLOR = 35
            bg = ctypes.c_int(0x00170E0E)   # near-black BGR ≈ #0E0E17
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(bg), ctypes.sizeof(bg))
            DWMWA_TEXT_COLOR = 36
            fg = ctypes.c_int(0x00F4D6CD)   # #CDD6F4 BGR
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_TEXT_COLOR, ctypes.byref(fg), ctypes.sizeof(fg))
        except Exception:
            pass
    except Exception:
        pass


def set_app(app) -> None:
    global _app_ref
    _app_ref = app


def set_window(win) -> None:
    global _window_ref
    _window_ref = win


def apply_theme(accent: str = "#7AA2F7", font_size: int = 11) -> None:
    """Apply the dynamic stylesheet to the running QApplication."""
    if _app_ref is None:
        return
    qss = build_stylesheet(accent, font_size)
    _app_ref.setStyleSheet(qss)

    # Force all top-level widgets to repaint
    for w in _app_ref.topLevelWidgets():
        w.update()
        w.repaint()


def apply_font(font_size: int) -> None:
    """Change the global application font size."""
    if _app_ref is None:
        return
    from PyQt6.QtGui import QFont
    f = _app_ref.font()
    f.setPointSize(font_size)
    _app_ref.setFont(f)
