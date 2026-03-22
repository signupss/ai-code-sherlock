"""
ThemeManager — builds and applies the full QSS stylesheet dynamically.
Accent color + font size + theme name are injected at runtime.
Supported themes: dark, light, monokai, dracula
"""
from __future__ import annotations
from PyQt6.QtGui import QColor


# ──────────────────────────────────────────────────────────
#  Theme Palettes
# ──────────────────────────────────────────────────────────

THEMES: dict[str, dict] = {
    "dark": {
        "label":   "🌙 Dark (Tokyo Night)",
        "bg0":     "#07080C",   # deepest background
        "bg1":     "#0E1117",   # main background
        "bg2":     "#131722",   # panel / input background
        "bg3":     "#1A1D2E",   # button / card background
        "bd":      "#2E3148",   # border
        "bd2":     "#1E2030",   # subtle border
        "tx0":     "#CDD6F4",   # primary text
        "tx1":     "#A9B1D6",   # secondary text
        "tx2":     "#565f89",   # muted text
        "tx3":     "#3B4261",   # very muted / disabled
        "sel":     "#2E3148",   # selection bg
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
        "tx0":     "#1A1D2E",   # near-black  — primary text
        "tx1":     "#3B4261",   # dark grey   — secondary text
        "tx2":     "#6B7394",   # medium grey — muted/hint text
        "tx3":     "#8B92B8",   # legible grey— disabled / status (was too light)
        "sel":     "#C5CAE9",
        "ok":      "#2E7D32",
        "warn":    "#E65100",
        "err":     "#C62828",
        "ac":      "#4361C2",   # deep blue accent for light theme
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


def build_stylesheet(accent: str = "#7AA2F7", font_size: int = 11,
                     theme: str = "dark") -> str:
    """Return complete QSS for the application with given accent, font, and theme."""
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

    return f"""
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
QFrame#searchBar {{ background-color: {bg2}; border-top: 1px solid {bd2}; }}
QFrame#editorToolbar {{ background-color: {bg0}; border-bottom: 1px solid {bd2}; }}
QFrame#editorToolbar QPushButton {{
    background: transparent; border: none; color: {tx2};
    padding: 2px 8px; font-size: {fs_s}pt; border-radius: 3px;
}}
QFrame#editorToolbar QPushButton:hover {{ background: {bd2}; color: {tx0}; }}
QFrame#editorStatus  {{ background-color: {bg0}; border-top: 1px solid {bd2}; }}
QFrame#editorStatus QLabel {{
    color: {tx3}; font-size: {fs_s}pt;
    font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
}}

/* ── Breadcrumb ────────────────────────────────────────── */
QLabel#breadcrumb {{
    background-color: {bg0};
    color: {ac};
    font-size: {fs_s}pt;
    padding: 2px 12px;
    border-bottom: 1px solid {bd2};
    font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
}}

/* ── Labels ────────────────────────────────────────────── */
QLabel {{ font-size: {fs}pt; color: {tx0}; }}
QLabel#sectionLabel {{ color: {tx2}; font-size: {fs_s}pt; letter-spacing: 1px; font-weight: bold; }}
QLabel#titleLabel   {{ color: {tx0}; font-size: {fs_l}pt; font-weight: bold; }}
QLabel#accentLabel  {{ color: {ac}; font-size: {fs}pt; }}
QLabel#statusLabel  {{ color: {tx2}; font-size: {fs_s}pt; }}

/* ── Log / plain text ──────────────────────────────────── */
QPlainTextEdit#logView {{
    background-color: {bg1};
    color: {tx1};
    border: none;
    font-size: {fs}pt;
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
QTextEdit#diffSearch {{
    background-color: {bg2};
    color: {p["err"]};
    border-radius: 4px;
    padding: 8px;
    border: 1px solid {p["err"]}33;
}}
QTextEdit#diffReplace {{
    background-color: {bg2};
    color: {p["ok"]};
    border-radius: 4px;
    padding: 8px;
    border: 1px solid {p["ok"]}33;
}}

/* ── Patch card ─────────────────────────────────────────── */
QFrame#patchCard {{
    background-color: {bg3};
    border: 1px solid {bd};
    border-radius: 6px;
}}
"""
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
QFrame#editorToolbar QPushButton {{
    background: transparent; border: none; color: #565f89;
    padding: 2px 8px; font-size: {fs_s}pt; border-radius: 3px;
}}
QFrame#editorToolbar QPushButton:hover {{ background: #1E2030; color: #CDD6F4; }}
QFrame#editorStatus {{
    background-color: #0A0D14;
    border-top: 1px solid #1E2030;
}}
QFrame#editorStatus QLabel {{
    color: #3B4261;
    font-size: {fs_s}pt;
    font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
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


_app_ref = None
_window_ref = None

# ── Current palette state (updated on every apply_theme call) ──────────────
_current_palette: dict = THEMES["dark"]
_current_accent:  str  = "#7AA2F7"
_current_theme:   str  = "dark"
_refresh_callbacks: list = []   # list[Callable[[], None]]


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
    """Return the current theme name (dark/light/monokai/dracula)."""
    return _current_theme


def register_theme_refresh(callback) -> None:
    """
    Register a callable to be invoked after every apply_theme() call.
    Use this in widgets that have inline stylesheets to refresh their colors.
    """
    if callback not in _refresh_callbacks:
        _refresh_callbacks.append(callback)


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


def apply_theme(accent: str = "#7AA2F7", font_size: int = 11, theme: str = "dark") -> None:
    """Apply the dynamic stylesheet to the running QApplication."""
    global _current_palette, _current_accent, _current_theme

    _current_theme   = theme
    _current_accent  = accent
    _current_palette = THEMES.get(theme, THEMES["dark"])

    if _app_ref is None:
        return
    qss = build_stylesheet(accent, font_size, theme)
    _app_ref.setStyleSheet(qss)

    # First pass — immediate repaint of top-level windows
    for w in _app_ref.topLevelWidgets():
        w.update()
        w.repaint()

    # Second pass — deferred full unpolish/polish after Qt flushes paint events
    def _deferred_repolish():
        try:
            for w in _app_ref.allWidgets():
                try:
                    w.style().unpolish(w)
                    w.style().polish(w)
                    w.update()
                except Exception:
                    pass
            # Third pass — force repaint after polish
            for w in _app_ref.topLevelWidgets():
                w.repaint()
        except Exception:
            pass

    from PyQt6.QtCore import QTimer
    QTimer.singleShot(0,   _deferred_repolish)   # after current event loop tick
    QTimer.singleShot(100, _deferred_repolish)   # after 100ms — catches lazy widgets

    # Notify all registered widgets to refresh their inline styles
    dead = []
    for cb in _refresh_callbacks:
        try:
            cb()
        except Exception:
            dead.append(cb)
    for cb in dead:
        _refresh_callbacks.remove(cb)


def apply_font(font_size: int) -> None:
    """Change the global application font size."""
    if _app_ref is None:
        return
    from PyQt6.QtGui import QFont
    f = _app_ref.font()
    f.setPointSize(font_size)
    _app_ref.setFont(f)
