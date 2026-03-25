"""
ThemeManager — builds and applies the full QSS stylesheet dynamically.

Upgrades over v1:
  * QPalette integration — native colors set alongside QSS for zero-flicker
  * Cross-fade animation — screenshot of old state fades out over new (300ms)
  * Cached QSS — same (accent, size, theme) tuple reuses the last generation
  * Efficient repolish — single deferred pass, no double timer hack

Accent color + font size + theme name are injected at runtime.
Supported themes: dark, light, monokai, dracula
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette


# ──────────────────────────────────────────────────────────
#  Theme Palettes
# ──────────────────────────────────────────────────────────

THEMES: dict[str, dict] = {
    "dark": {
        "label":   "🌙 Dark (Tokyo Night)",
        "bg0":     "#07080C",
        "bg1":     "#0E1117",
        "bg2":     "#131722",
        "bg3":     "#1A1D2E",
        "bd":      "#2E3148",
        "bd2":     "#1E2030",
        "tx0":     "#CDD6F4",
        "tx1":     "#A9B1D6",
        "tx2":     "#565f89",
        "tx3":     "#3B4261",
        "sel":     "#2E3148",
        "ok":      "#9ECE6A",
        "warn":    "#E0AF68",
        "err":     "#F7768E",
    },
    "light": {
        "label":   "☀️ Light",
        "bg0":     "#EEF0F5",
        "bg1":     "#F8F9FC",
        "bg2":     "#FFFFFF",
        "bg3":     "#EDF0F7",
        "bd":      "#C8CDE0",
        "bd2":     "#DDE1EF",
        "tx0":     "#1A1D2E",
        "tx1":     "#3B4261",
        "tx2":     "#6B7394",
        "tx3":     "#8B92B8",
        "sel":     "#C5CAE9",
        "ok":      "#2E7D32",
        "warn":    "#E65100",
        "err":     "#C62828",
        "ac":      "#4361C2",
    },
    "monokai": {
        "label":   "🎨 Monokai",
        "bg0":     "#1C1C1C",
        "bg1":     "#272822",
        "bg2":     "#2D2D2D",
        "bg3":     "#363537",
        "bd":      "#49483E",
        "bd2":     "#383830",
        "tx0":     "#F8F8F2",
        "tx1":     "#CFCFC2",
        "tx2":     "#75715E",
        "tx3":     "#49483E",
        "sel":     "#49483E",
        "ok":      "#A6E22E",
        "warn":    "#E6DB74",
        "err":     "#F92672",
    },
    "dracula": {
        "label":   "🧛 Dracula",
        "bg0":     "#1A1A2E",
        "bg1":     "#282A36",
        "bg2":     "#2D2F3F",
        "bg3":     "#383A4A",
        "bd":      "#44475A",
        "bd2":     "#3A3C4E",
        "tx0":     "#F8F8F2",
        "tx1":     "#BFBFBF",
        "tx2":     "#6272A4",
        "tx3":     "#44475A",
        "sel":     "#44475A",
        "ok":      "#50FA7B",
        "warn":    "#F1FA8C",
        "err":     "#FF5555",
    },
}

THEME_NAMES = list(THEMES.keys())


def _shade(hex_color: str, lighten: int = 0, darken: int = 0,
           saturate: int = 0, desaturate: int = 0) -> str:
    c = QColor(hex_color)
    h, s, v, a = c.getHsv()
    s = max(0, min(255, s + saturate - desaturate))
    v = max(0, min(255, v + lighten - darken))
    return QColor.fromHsv(h, s, v, a).name()


# ──────────────────────────────────────────────────────────
#  QSS Cache
# ──────────────────────────────────────────────────────────

_qss_cache: dict[tuple, str] = {}


def build_stylesheet(accent: str = "#7AA2F7", font_size: int = 11,
                     theme: str = "dark") -> str:
    """Return complete QSS. Cached by (accent, font_size, theme) tuple."""
    cache_key = (accent, font_size, theme)
    cached = _qss_cache.get(cache_key)
    if cached is not None:
        return cached

    p = THEMES.get(theme, THEMES["dark"])

    ac    = accent
    ac_l  = _shade(ac, lighten=30, desaturate=20)
    ac_d  = _shade(ac, darken=30, saturate=20)
    ac_dim = _shade(ac, darken=60, desaturate=80)

    bg0, bg1, bg2, bg3 = p["bg0"], p["bg1"], p["bg2"], p["bg3"]
    bd, bd2             = p["bd"],  p["bd2"]
    tx0, tx1, tx2, tx3  = p["tx0"], p["tx1"], p["tx2"], p["tx3"]
    sel                 = p["sel"]

    fs   = font_size
    fs_s = max(8, fs - 1)
    fs_l = fs + 1

    qss = f"""
/* AI Code Sherlock — Dynamic Theme: {theme} */

* {{ outline: none; font-size: {fs}pt; }}

QMainWindow, QDialog, QWidget {{
    background-color: {bg1};
    color: {tx0};
}}
QWidget {{ selection-background-color: {sel}; selection-color: {tx0}; }}

/* ── Named Panels ──────────────────────────────────────── */
QFrame#leftPanel, QFrame#rightPanel {{
    background-color: {bg2};
    border: none;
}}
QFrame#centerPanel {{
    background-color: {bg1};
    border: none;
}}
QFrame#toolbar {{
    background-color: {bg0};
    border-bottom: 1px solid {bd2};
    min-height: 40px; max-height: 40px;
    padding: 0 8px;
}}
QFrame#titleBar {{
    background-color: {bg0};
    border-bottom: 1px solid {bd2};
    min-height: 44px; max-height: 44px;
}}
QFrame#statusBar {{
    background-color: {bg0};
    border-top: 1px solid {bd2};
    min-height: 22px; max-height: 22px;
}}
QFrame#panelHeader {{
    background-color: {bg0};
    border-bottom: 1px solid {bd2};
    min-height: 32px; max-height: 32px;
}}
QFrame#inputArea {{
    background-color: {bg0};
    border-top: 1px solid {bd2};
}}
QFrame#settingsFooter {{
    background-color: {bg0};
    border-top: 1px solid {bd2};
}}

/* ── Buttons ───────────────────────────────────────────── */
QPushButton {{
    background-color: {bg3};
    border: 1px solid {bd};
    border-radius: 6px;
    padding: 4px 14px;
    color: {tx0};
    font-size: {fs}pt;
    font-weight: 500;
    min-height: 24px;
}}
QPushButton:hover {{
    background-color: {sel};
    border-color: {ac};
    color: {tx0};
}}
QPushButton:pressed {{ background-color: {ac_d}; border-color: {ac_d}; color: {bg1}; }}
QPushButton:disabled {{ color: {tx3}; border-color: {bd2}; background-color: {bg1}; }}
QPushButton:checked {{ background-color: {ac_dim}; border-color: {ac}; color: {ac}; }}

QPushButton#primaryBtn {{
    background-color: {ac};
    border-color: {ac};
    color: {"#FFFFFF" if theme in ("dark", "monokai", "dracula") else "#1A1D2E"};
    font-weight: bold;
}}
QPushButton#primaryBtn:hover  {{ background-color: {ac_l}; border-color: {ac_l}; }}
QPushButton#primaryBtn:pressed {{ background-color: {ac_d}; border-color: {ac_d}; }}

QPushButton#successBtn {{
    background-color: transparent;
    border-color: {p["ok"]};
    color: {p["ok"]};
}}
QPushButton#successBtn:hover {{ background-color: {sel}; }}

QPushButton#dangerBtn {{
    background-color: transparent;
    border-color: {p["err"]};
    color: {p["err"]};
}}
QPushButton#dangerBtn:hover {{ background-color: {sel}; }}

QPushButton#iconBtn {{
    background-color: transparent;
    border: none;
    color: {tx2};
    padding: 2px 8px;
    font-size: {fs_s}pt;
}}
QPushButton#iconBtn:hover {{ background-color: {sel}; color: {tx0}; border-radius: 4px; }}

QPushButton#toggleBtn {{
    background-color: transparent;
    border: 1px solid {bd};
    color: {tx1};
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

/* Toolbar buttons */
QFrame#toolbar QPushButton {{
    background-color: {bg3};
    border: 1px solid {bd};
    border-radius: 5px;
    color: {tx0};
    font-size: {fs_s}pt;
    padding: 3px 10px;
    min-height: 22px;
}}
QFrame#toolbar QPushButton:hover {{ background-color: {sel}; border-color: {ac}; }}
QFrame#toolbar QPushButton:checked {{ background-color: {ac_dim}; border-color: {ac}; color: {ac}; }}
QFrame#toolbar QPushButton#dangerBtn {{ border-color: {p["err"]}; color: {p["err"]}; }}

/* ── Text inputs ───────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {bg2};
    color: {tx0};
    border: 1px solid {bd};
    border-radius: 5px;
    padding: 4px 8px;
    font-size: {fs}pt;
    selection-background-color: {sel};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {ac}; }}

/* ── Spin/Combo ────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {bg2};
    color: {tx0};
    border: 1px solid {bd};
    border-radius: 5px;
    padding: 3px 8px;
    font-size: {fs}pt;
    min-height: 22px;
}}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ac}; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: {sel}; border: none; width: 16px; border-radius: 3px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {ac_dim};
}}
QComboBox::drop-down {{ border: none; width: 22px; background: transparent; }}
QComboBox::down-arrow {{
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {tx2};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {bg2};
    color: {tx0};
    border: 1px solid {ac};
    border-radius: 6px;
    selection-background-color: {sel};
    selection-color: {ac};
    padding: 4px;
    outline: none;
}}

/* ── Checkboxes ────────────────────────────────────────── */
QCheckBox {{ color: {tx0}; spacing: 8px; font-size: {fs}pt; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid {bd};
    background-color: {bg2};
}}
QCheckBox::indicator:checked {{ background-color: {ac}; border-color: {ac}; }}
QCheckBox::indicator:checked:hover {{ background-color: {ac_l}; }}
QCheckBox::indicator:hover {{ border-color: {ac}; }}

/* ── Scrollbars ────────────────────────────────────────── */
QScrollBar:vertical {{ background: {bg0}; width: 8px; border-radius: 4px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {bd}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {ac}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{ background: {bg0}; height: 8px; border-radius: 4px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {bd}; border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {ac}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; border: none; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* ── Tabs ──────────────────────────────────────────────── */
QTabWidget::pane {{ border: none; background: {bg1}; }}
QTabWidget::tab-bar {{ alignment: left; }}
QTabBar {{ background: {bg0}; }}
QTabBar::tab {{
    background: {bg0};
    color: {tx2};
    padding: 6px 14px;
    border-bottom: 2px solid transparent;
    font-size: {fs_s}pt;
    min-width: 60px;
}}
QTabBar::tab:selected {{ color: {ac}; border-bottom: 2px solid {ac}; background: {bg1}; font-weight: bold; }}
QTabBar::tab:hover:!selected {{ color: {tx1}; background: {bg2}; }}

/* ── Menus ─────────────────────────────────────────────── */
QMenuBar {{ background-color: {bg0}; color: {tx0}; border-bottom: 1px solid {bd2}; font-size: {fs}pt; }}
QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 4px; }}
QMenuBar::item:selected {{ background-color: {sel}; color: {ac}; }}
QMenu {{
    background-color: {bg2};
    color: {tx0};
    border: 1px solid {bd};
    border-radius: 8px;
    padding: 6px 0;
    font-size: {fs}pt;
}}
QMenu::item {{ padding: 7px 24px 7px 16px; border-radius: 4px; margin: 1px 4px; }}
QMenu::item:selected {{ background-color: {sel}; color: {ac}; }}
QMenu::item:disabled {{ color: {tx3}; }}
QMenu::separator {{ background-color: {bd}; height: 1px; margin: 5px 10px; }}

/* ── Tooltip ───────────────────────────────────────────── */
QToolTip {{
    background-color: {bg2};
    color: {tx0};
    border: 1px solid {ac};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: {fs_s}pt;
}}

/* ── Lists / Trees / Tables ────────────────────────────── */
QListWidget, QTreeWidget, QTableWidget {{
    background-color: {bg1};
    color: {tx0};
    border: 1px solid {bd2};
    border-radius: 6px;
    font-size: {fs}pt;
    outline: none;
    alternate-background-color: {bg2};
}}
QListWidget::item, QTreeWidget::item {{ padding: 4px 8px; border-radius: 3px; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background-color: {sel}; color: {ac}; }}
QListWidget::item:hover:!selected,
QTreeWidget::item:hover:!selected {{ background-color: {bg3}; }}
QTreeWidget::branch {{ background: transparent; }}
QHeaderView::section {{
    background-color: {bg0};
    color: {tx2};
    border: none;
    border-bottom: 1px solid {bd2};
    padding: 5px 10px;
    font-size: {fs_s}pt;
}}
QTableWidget {{ gridline-color: {bd2}; }}
QTableWidget::item:selected {{ background-color: {sel}; color: {ac}; }}

/* ── Group boxes ───────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {bd2};
    border-radius: 8px;
    margin-top: 12px;
    padding: 14px 10px 10px 10px;
    color: {tx1};
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
QSplitter::handle {{ background-color: {bd2}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical   {{ height: 1px; }}
QSplitter::handle:hover {{ background-color: {ac}; }}

/* ── Progress ──────────────────────────────────────────── */
QProgressBar {{
    background-color: {bd2};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background-color: {ac}; border-radius: 4px; }}

/* ── Chat bubbles ──────────────────────────────────────── */
QFrame#userBubble {{ background-color: {bg2}; border: 1px solid {bd2}; border-radius: 8px; }}
QFrame#assistantBubble {{ background-color: {bg3}; border: 1px solid {bd}; border-radius: 8px; }}
QFrame#systemBubble {{ background-color: {bg1}; border: 1px solid {bd2}; border-radius: 6px; }}
QFrame#errorBubble {{ background-color: {bg1}; border: 1px solid {p["err"]}44; border-radius: 6px; }}

/* ── Editor chrome ─────────────────────────────────────── */
QFrame#searchBar {{ background-color: {bg2}; border-top: 1px solid {bd2}; }}
QFrame#editorToolbar {{ background-color: {bg0}; border-bottom: 1px solid {bd2}; }}
QFrame#editorToolbar QPushButton {{
    background: transparent; border: none; color: {tx2};
    padding: 2px 8px; font-size: {fs_s}pt; border-radius: 3px;
}}
QFrame#editorToolbar QPushButton:hover {{ background: {bd2}; color: {tx0}; }}
QFrame#editorStatus {{ background-color: {bg0}; border-top: 1px solid {bd2}; }}
QFrame#editorStatus QLabel {{
    color: {tx3}; font-size: {fs_s}pt;
    font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
}}

/* ── Labels ────────────────────────────────────────────── */
QLabel {{ font-size: {fs}pt; color: {tx0}; }}
QLabel#sectionLabel {{ color: {tx2}; font-size: {fs_s}pt; letter-spacing: 1px; font-weight: bold; }}
QLabel#titleLabel   {{ color: {tx0}; font-size: {fs_l}pt; font-weight: bold; }}
QLabel#accentLabel  {{ color: {ac}; font-size: {fs}pt; }}
QLabel#statusLabel  {{ color: {tx2}; font-size: {fs_s}pt; }}
QLabel#breadcrumb {{
    background-color: {bg0}; color: {ac}; font-size: {fs_s}pt;
    border-bottom: 1px solid {bd2}; padding: 2px 12px;
}}

/* ── Log / plain text views ────────────────────────────── */
QPlainTextEdit#logView {{
    background-color: {bg0};
    color: {tx1};
    border: none;
    font-size: {fs_s}pt;
}}

/* ── Chat input ────────────────────────────────────────── */
QTextEdit#chatInput {{
    background-color: {bg2};
    color: {tx0};
    border: 1px solid {bd};
    border-radius: 6px;
    font-size: {fs}pt;
}}
QTextEdit#chatInput:focus {{ border-color: {ac}; }}

/* ── Diff viewers ──────────────────────────────────────── */
QTextEdit#diffSearch, QPlainTextEdit#diffSearch {{
    background-color: {bg2}; color: {p["err"]}; border-radius: 4px;
    padding: 8px; border: 1px solid {p["err"]}33;
}}
QTextEdit#diffReplace, QPlainTextEdit#diffReplace {{
    background-color: {bg2}; color: {p["ok"]}; border-radius: 4px;
    padding: 8px; border: 1px solid {p["ok"]}33;
}}

/* ── Patch card ────────────────────────────────────────── */
QFrame#patchCard {{
    background-color: {bg3};
    border: 1px solid {bd};
    border-radius: 6px;
}}

/* ── Dialog buttons ────────────────────────────────────── */
QDialogButtonBox QPushButton {{ min-width: 80px; }}
"""

    _qss_cache[cache_key] = qss
    # Keep cache bounded
    if len(_qss_cache) > 20:
        oldest = next(iter(_qss_cache))
        del _qss_cache[oldest]
    return qss


# ──────────────────────────────────────────────────────────
#  Module State
# ──────────────────────────────────────────────────────────

_app_ref = None
_window_ref = None
_current_palette: dict = THEMES["dark"]
_current_accent:  str  = "#7AA2F7"
_current_theme:   str  = "dark"
_refresh_callbacks: list = []


# ──────────────────────────────────────────────────────────
#  Public Accessors
# ──────────────────────────────────────────────────────────

def get_palette() -> dict:
    """Return the currently active palette dict."""
    return _current_palette


def get_color(key: str) -> str:
    """
    Return a color from the current palette by key.
    Keys: bg0 bg1 bg2 bg3  bd bd2  tx0 tx1 tx2 tx3  sel  ok warn err
    Special: ac (accent)
    """
    if key == "ac":
        return _current_accent
    return _current_palette.get(key, "#CDD6F4")


def get_theme() -> str:
    """Return the current theme name."""
    return _current_theme


def register_theme_refresh(callback) -> None:
    """Register a callable invoked after every apply_theme()."""
    if callback not in _refresh_callbacks:
        _refresh_callbacks.append(callback)


# ──────────────────────────────────────────────────────────
#  QPalette Builder
# ──────────────────────────────────────────────────────────

def _build_qpalette(p: dict, accent: str) -> QPalette:
    """
    Build a QPalette from theme dict + accent.
    This sets native Qt colors so widgets that don't use QSS
    still get correct colors (eliminates flicker on theme switch).
    """
    pal = QPalette()
    c = QColor

    pal.setColor(QPalette.ColorRole.Window,          c(p["bg1"]))
    pal.setColor(QPalette.ColorRole.WindowText,      c(p["tx0"]))
    pal.setColor(QPalette.ColorRole.Base,            c(p["bg2"]))
    pal.setColor(QPalette.ColorRole.AlternateBase,   c(p["bg3"]))
    pal.setColor(QPalette.ColorRole.Text,            c(p["tx0"]))
    pal.setColor(QPalette.ColorRole.BrightText,      c(p["tx0"]))
    pal.setColor(QPalette.ColorRole.Button,          c(p["bg3"]))
    pal.setColor(QPalette.ColorRole.ButtonText,      c(p["tx0"]))
    pal.setColor(QPalette.ColorRole.Highlight,       c(accent))
    pal.setColor(QPalette.ColorRole.HighlightedText, c("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ToolTipBase,     c(p["bg2"]))
    pal.setColor(QPalette.ColorRole.ToolTipText,     c(p["tx0"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, c(p["tx3"]))
    pal.setColor(QPalette.ColorRole.Link,            c(accent))
    pal.setColor(QPalette.ColorRole.LinkVisited,     c(p.get("ac", accent)))

    # Disabled group
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, c(p["tx3"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,       c(p["tx3"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, c(p["tx3"]))

    return pal


# ──────────────────────────────────────────────────────────
#  Cross-Fade Overlay
# ──────────────────────────────────────────────────────────

class _CrossFadeOverlay:
    """
    Creates a temporary QLabel overlay with a screenshot of the old state,
    then fades it out over 300ms revealing the new theme underneath.
    """

    _overlay = None

    @classmethod
    def start(cls, window) -> None:
        """Capture current state and prepare overlay."""
        if window is None:
            return
        try:
            from PyQt6.QtWidgets import QLabel
            from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
            from PyQt6.QtGui import QPixmap

            # Grab screenshot of current window
            pixmap = window.grab()
            if pixmap.isNull():
                return

            # Create overlay label
            overlay = QLabel(window)
            overlay.setPixmap(pixmap)
            overlay.setGeometry(window.rect())
            overlay.setAttribute(
                __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
            overlay.show()
            overlay.raise_()

            # Store ref to keep alive during animation
            cls._overlay = overlay

        except Exception:
            cls._overlay = None

    @classmethod
    def fade_out(cls, duration_ms: int = 300) -> None:
        """Fade out the overlay, then destroy it."""
        if cls._overlay is None:
            return
        try:
            from PyQt6.QtWidgets import QGraphicsOpacityEffect
            from PyQt6.QtCore import QPropertyAnimation, QEasingCurve

            effect = QGraphicsOpacityEffect(cls._overlay)
            cls._overlay.setGraphicsEffect(effect)

            anim = QPropertyAnimation(effect, b"opacity")
            anim.setDuration(duration_ms)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)

            def _cleanup():
                try:
                    if cls._overlay is not None:
                        cls._overlay.hide()
                        cls._overlay.deleteLater()
                except Exception:
                    pass
                cls._overlay = None

            anim.finished.connect(_cleanup)
            # Store anim on overlay to prevent GC
            cls._overlay._fade_anim = anim
            anim.start()

        except Exception:
            # Fallback: just remove overlay
            try:
                if cls._overlay is not None:
                    cls._overlay.hide()
                    cls._overlay.deleteLater()
            except Exception:
                pass
            cls._overlay = None


# ──────────────────────────────────────────────────────────
#  Dark Title Bar (Windows)
# ──────────────────────────────────────────────────────────

def apply_dark_titlebar(widget) -> None:
    """
    Force dark OS title bar on Windows 10/11 via DWMAPI.
    Safe on all platforms — silently ignored on non-Windows.
    """
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        for attr in (20, 19):
            try:
                value = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
                )
                break
            except Exception:
                continue
        try:
            bg = ctypes.c_int(0x00170E0E)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(bg), ctypes.sizeof(bg))
            fg = ctypes.c_int(0x00F4D6CD)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(fg), ctypes.sizeof(fg))
        except Exception:
            pass
    except Exception:
        pass


# ──────────────────────────────────────────────────────────
#  Application-level API
# ──────────────────────────────────────────────────────────

def set_app(app) -> None:
    global _app_ref
    _app_ref = app


def set_window(win) -> None:
    global _window_ref
    _window_ref = win


def apply_theme(accent: str = "#7AA2F7", font_size: int = 11,
                theme: str = "dark", animate: bool = True) -> None:
    """
    Apply the dynamic stylesheet to the running QApplication.

    Steps:
      1. Capture screenshot overlay (cross-fade source)
      2. Set QPalette natively (prevents white flash)
      3. Apply QSS
      4. Single deferred repolish pass
      5. Fade out the overlay (300ms)
      6. Notify registered refresh callbacks
    """
    global _current_palette, _current_accent, _current_theme

    _current_theme   = theme
    _current_accent  = accent
    _current_palette = THEMES.get(theme, THEMES["dark"])

    if _app_ref is None:
        return

    # 1. Capture overlay before any visual change
    if animate and _window_ref is not None:
        _CrossFadeOverlay.start(_window_ref)

    # 2. Set QPalette natively — this prevents the white flash
    #    that occurs when QSS is applied before palette is set
    qpal = _build_qpalette(_current_palette, accent)
    _app_ref.setPalette(qpal)

    # 3. Apply QSS
    qss = build_stylesheet(accent, font_size, theme)
    _app_ref.setStyleSheet(qss)

    # 4. Single deferred repolish — after Qt processes the QSS
    #    CRITICAL: Skip QPlainTextEdit / QTextEdit — repolishing them
    #    destroys their document state, syntax highlighting, and cursor.
    #    Those widgets handle their own theming via register_theme_refresh.
    def _deferred_repolish():
        try:
            from PyQt6.QtWidgets import QPlainTextEdit, QTextEdit, QScrollBar
            _skip_types = (QPlainTextEdit, QTextEdit)
            for w in _app_ref.allWidgets():
                try:
                    if isinstance(w, _skip_types):
                        # Обновляем только скроллбары редактора, не сам редактор
                        v_bar = w.verticalScrollBar()
                        h_bar = w.horizontalScrollBar()
                        for bar in (v_bar, h_bar):
                            if bar:
                                bar.style().unpolish(bar)
                                bar.style().polish(bar)
                                bar.update()
                        w.update()
                        continue
                    w.style().unpolish(w)
                    w.style().polish(w)
                    w.update()
                except Exception:
                    pass
        except Exception:
            pass

        # 5. Start cross-fade after repolish completes
        if animate:
            _CrossFadeOverlay.fade_out(300)

        # 6. Notify registered widgets to refresh inline styles
        #    (this is where CodeEditor._apply_editor_theme gets called)
        _notify_refresh_callbacks()

    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0, _deferred_repolish)


def _notify_refresh_callbacks() -> None:
    """Call all registered refresh callbacks, removing dead ones."""
    dead = []
    for cb in _refresh_callbacks:
        try:
            cb()
        except Exception:
            dead.append(cb)
    for cb in dead:
        try:
            _refresh_callbacks.remove(cb)
        except ValueError:
            pass


def apply_font(font_size: int) -> None:
    """Change the global application font size."""
    if _app_ref is None:
        return
    from PyQt6.QtGui import QFont
    f = _app_ref.font()
    f.setPointSize(font_size)
    _app_ref.setFont(f)
