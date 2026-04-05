"""
Browser Module — Полноценный модуль браузерной автоматизации.

Аналог ZennoPoster Browser Actions:
  - Запуск браузера с профилем / прокси
  - Навигация, клики, ввод текста
  - Куки, JS, скриншоты
  - Управление вкладками
  - Настройки браузера (картинки, медиа, JS, Canvas и т.д.)

Поддерживает Selenium (chromedriver) и Playwright (async).
Если ни одна библиотека не установлена — работает в «заглушечном» режиме.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Callable, Any
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QSpinBox, QGroupBox,
    QFormLayout, QTabWidget, QTextEdit, QFileDialog, QMessageBox,
    QDialog, QDialogButtonBox, QScrollArea, QFrame, QListWidget,
    QListWidgetItem, QSplitter, QSizePolicy, QStatusBar,
    QSystemTrayIcon, QMenu,
)
from PyQt6.QtGui import QAction

try:
    from ui.i18n import tr
except ImportError:
    def tr(s): return s

try:
    from ui.theme_manager import get_color
except ImportError:
    def get_color(k):
        return {
            "bg0": "#07080C", "bg1": "#0E1117", "bg2": "#131722", "bg3": "#1A1D2E",
            "bd": "#2E3148", "bd2": "#1E2030",
            "tx0": "#CDD6F4", "tx1": "#A9B1D6", "tx2": "#565f89",
            "ac": "#7AA2F7", "ok": "#9ECE6A", "err": "#F7768E", "warn": "#E0AF68",
        }.get(k, "#CDD6F4")


# ══════════════════════════════════════════════════════════
#  SCREENSHOT WORKER — фоновый захват, не блокирует UI
# ══════════════════════════════════════════════════════════

from PyQt6.QtCore import QRunnable, QThreadPool

class _ScreenshotSignals(QObject):
    done = pyqtSignal(bytes)   # возвращает готовые PNG-байты

class _ScreenshotWorker(QRunnable):
    """Захват + масштабирование скриншота в фоновом потоке."""
    def __init__(self, inst, scale: float = 0.3):
        super().__init__()
        self.inst  = inst
        self.scale = scale
        self.signals = _ScreenshotSignals()
        self.setAutoDelete(True)
        self._pre_captured_b64 = None  # ✅ Предзахваченный скриншот (base64)

    def run(self):
        try:
            png = b""
            
            # ✅ Если есть предзахваченный скриншот — используем его
            if self._pre_captured_b64:
                import base64
                png = base64.b64decode(self._pre_captured_b64)
            else:
                # Fallback: захват в фоновом потоке (только для Playwright)
                if not self.inst or not getattr(self.inst, 'is_running', False):
                    return
                if getattr(self.inst, '_page', None):
                    # Playwright можно вызывать из другого потока
                    import asyncio
                    loop = asyncio.new_event_loop()
                    png = loop.run_until_complete(self.inst._page.screenshot())
                    loop.close()
                # ⚠️ Selenium НЕЛЬЗЯ вызывать из фонового потока — deadlock!
                # Поэтому для Selenium всегда используем _pre_captured_b64
            
            # Масштабирование в фоне
            if png and self.scale < 1.0:
                png = _scale_png_bytes(png, self.scale)
            if png:
                self.signals.done.emit(png)
        except Exception:
            pass


def _scale_png_bytes(png_bytes: bytes, scale: float) -> bytes:
    """Уменьшить PNG (PIL если установлен, иначе возвращаем как есть)."""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(png_bytes))
        new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True, compress_level=6)
        return buf.getvalue()
    except ImportError:
        return png_bytes  # PIL не установлен
    except Exception:
        return png_bytes

# ══════════════════════════════════════════════════════════
#  DATACLASSES
# ══════════════════════════════════════════════════════════

@dataclass
class BrowserProfile:
    """Профиль браузера — набор настроек для конкретного сеанса."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "Новый профиль"
    profile_folder: str = ""          # Путь к папке профиля Chromium/Firefox
    create_if_missing: bool = True    # Создать папку если не существует
    
    # Режим окна
    headless: bool = False              # Headless режим (без окна)
    
    # Отпечатки / эмуляция
    emulate_canvas: bool = True
    emulate_webgl: bool = True
    emulate_audio_context: bool = True
    emulate_client_rects: bool = False

    # Медиа и ресурсы
    load_images: bool = True
    load_media: bool = True
    load_css: bool = True
    load_frames: bool = True
    load_plugins: bool = False        # Flash/Silverlight (legacy)
    enable_javascript: bool = True
    block_ads: bool = False
    block_notifications: bool = True
    block_popups: bool = False

    # Геолокация
    geo_enabled: bool = False
    geo_latitude: float = 0.0
    geo_longitude: float = 0.0
    geo_accuracy: float = 100.0
    geo_altitude: float = 0.0
    geo_altitude_accuracy: float = 50.0
    geo_heading: float = 0.0
    geo_speed: float = 0.0

    # Часовой пояс
    timezone: str = ""                # e.g. "Europe/Kyiv"

    # Разрешение / User-Agent
    window_width: int = 1280
    window_height: int = 900
    user_agent: str = ""

    # Куки
    cookies_json: str = ""            # JSON-куки для импорта при старте

    def to_dict(self) -> dict:
        d = asdict(self)
        # Гарантируем что headless всегда есть
        d['headless'] = getattr(self, 'headless', False)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> BrowserProfile:
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        profile = cls(**valid)
        # Гарантируем что headless инициализирован
        if 'headless' not in valid:
            profile.headless = d.get('headless', False)
        return profile


@dataclass
class BrowserProxy:
    """Настройки прокси для браузера."""
    enabled: bool = False
    protocol: str = "http"            # http, socks4, socks5
    host: str = ""
    port: int = 8080
    login: str = ""
    password: str = ""
    auto_geo: bool = False            # Эмулировать гео/TZ по IP прокси

    @property
    def proxy_string(self) -> str:
        if not self.enabled or not self.host:
            return ""
        auth = f"{self.login}:{self.password}@" if self.login else ""
        return f"{self.protocol}://{auth}{self.host}:{self.port}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> BrowserProxy:
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class BrowserAction:
    """Одно действие браузера (для сниппета BROWSER_ACTION)."""
    action: str = "navigate"          # см. BROWSER_ACTIONS ниже
    target: str = ""                  # URL, selector, JS-код и т.д.
    value: str = ""                   # Значение для ввода/поиска
    variable_out: str = ""            # Переменная для сохранения результата
    timeout: int = 30                 # Таймаут в секундах
    wait_after: float = 0.0           # Пауза после действия (сек.)
    selector_type: str = "css"        # css, xpath, id, name, tag
    frame: str = ""                   # Имя/индекс фрейма (пусто = главный)
    tab_name: str = ""                # Имя вкладки (пусто = текущая)
    # === НОВЫЕ ПОЛЯ для координат и поиска по тексту ===
    coord_x: int = 100                # Координата X для кликов по координатам
    coord_y: int = 100                # Координата Y для кликов по координатам
    search_text: str = ""             # Текст для поиска элемента
    # === НОВОЕ: поддержка плановых шагов ===
    step_number: int = 0              # Номер шага в плане (для логирования)
    step_description: str = ""        # Описание шага от Planner

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> BrowserAction:
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


class BrowserTrayManager(QObject):
    """
    Менеджер системного трея для управления скрытыми окнами браузеров.
    Реализует паттерн Синглтон для работы с несколькими браузерными инстансами.
    """
    _instance: Optional['BrowserTrayManager'] = None
    _initialized = False  # ✅ Флаг инициализации

    def __init__(self, browser_manager=None, parent=None):
        super().__init__(parent)
        # ✅ Предотвращаем повторную инициализацию при получении существующего инстанса
        if BrowserTrayManager._initialized:
            return
            
        self.browser_manager = browser_manager
        BrowserTrayManager._initialized = True
        self._tray = QSystemTrayIcon()  # без parent
        
        # Заглушка для иконки (желательно заменить на реальную иконку приложения)
        icon = QIcon() 
        self._tray.setIcon(icon)
        self._tray.setToolTip("AI Agent Browser - Работает в фоне")

        self._menu = QMenu()
        show_action = QAction("Развернуть браузеры", self)
        show_action.triggered.connect(self.show_all_browsers)
        self._menu.addAction(show_action)
        
        self._menu.addSeparator()
        
        quit_action = QAction("Закрыть все", self)
        quit_action.triggered.connect(self.quit_all)
        self._menu.addAction(quit_action)

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_tray_activated)

        self._managed_windows = []

    @classmethod
    def get_instance(cls, browser_manager=None):
        # ✅ Правильный синглтон — один трей на всё приложение
        if cls._instance is None:
            cls._instance = cls(browser_manager)
        return cls._instance

    def add_window(self, window):
        if window and window not in self._managed_windows:
            # ✅ Фильтр: проверяем уникальность по HWND
            new_hwnd = getattr(window, '_hwnd', None) or getattr(window, 'winId', lambda: None)()
            existing_hwnds = [
                getattr(w, '_hwnd', None) or getattr(w, 'winId', lambda: None)()
                for w in self._managed_windows
            ]
            if new_hwnd not in existing_hwnds:
                self._managed_windows.append(window)
                return True
        return False

    def show_tray(self):
        self._tray.show()

    def hide_tray(self):
        if self._tray:
            self._tray.hide()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_all_browsers()

    def show_all_browsers(self):
        for window in self._managed_windows:
            if window:
                window.showNormal()
                window.activateWindow()
        self.hide_tray()

    def quit_all(self):
        for window in list(self._managed_windows):
            try:
                if window and window.isVisible():
                    window.close()
            except:
                pass

        self._managed_windows.clear()
        self.hide_tray()

        if self.browser_manager:
            try:
                self.browser_manager.close_all()
            except:
                pass

# Все доступные действия браузера
BROWSER_ACTIONS = {
    # Навигация
    "navigate":          ("🌐 Перейти по URL", "target=URL"),
    "navigate_back":     ("◀ Назад", ""),
    "navigate_forward":  ("▶ Вперёд", ""),
    "reload":            ("🔄 Перезагрузить", ""),
    "stop":              ("⏹ Остановить загрузку", ""),
    # Вкладки
    "tab_new":           ("➕ Новая вкладка", "value=имя"),
    "tab_activate":      ("🔀 Активировать вкладку", "target=имя/номер"),
    "tab_close":         ("✖ Закрыть вкладку", "target=имя/номер/текущую"),
    # Элементы
    # Клики
    "click":             ("🖱 Клик по элементу", "target=селектор"),
    "click_js":          ("🖱🟨 Клик через JS", "target=селектор"),
    "click_xy":          ("🖱📍 Клик по координатам", "target=x,y (например: 100,200)"),
    "click_text":        ("🖱🔤 Клик по тексту на странице", "target=текст для поиска"),
    "double_click":      ("🖱🖱 Двойной клик", "target=селектор"),
    "double_click_xy":   ("🖱🖱📍 Двойной клик по координатам", "target=x,y"),
    "right_click":       ("🖱 Правый клик", "target=селектор"),
    "right_click_xy":    ("🖱📍 Правый клик по координатам", "target=x,y"),
    "hover":             ("👆 Наведение мыши", "target=селектор"),
    "hover_xy":          ("👆📍 Наведение по координатам", "target=x,y"),
    "type_text":         ("⌨ Ввести текст", "target=селектор value=текст"),
    "clear_field":       ("🧹 Очистить поле", "target=селектор"),
    "select_option":     ("📋 Выбрать опцию", "target=селектор value=значение"),
    "set_checkbox":      ("☑ Установить чекбокс", "target=селектор value=true/false"),
    "file_upload":       ("📎 Загрузить файл", "target=селектор value=путь"),
    # Получение данных
    "get_text":          ("📄 Получить текст", "target=селектор → variable_out"),
    "get_attr":          ("🏷 Получить атрибут", "target=селектор value=атрибут → variable_out"),
    "get_url":           ("🔗 Получить URL", "→ variable_out"),
    "get_title":         ("📝 Получить заголовок", "→ variable_out"),
    "get_html":          ("🧾 Получить HTML", "target=селектор → variable_out"),
    "count_elements":    ("🔢 Количество элементов", "target=селектор → variable_out"),
    # Ожидание
    "wait_element":      ("⏳ Ждать элемент", "target=селектор"),
    "wait_url":          ("⏳ Ждать URL", "target=паттерн"),
    "wait_text":         ("⏳ Ждать текст", "target=текст"),
    "wait_seconds":      ("⏳ Пауза", "value=секунды"),
    # JS
    "execute_js":        ("🟨 Выполнить JS", "target=код → variable_out"),
    "js_auth":           ("🔐 JS авторизация", "target=логин value=пароль"),
    "js_confirm":        ("✅ JS Confirm", "value=ok/cancel"),
    "js_prompt":         ("💬 JS Prompt", "value=ответ"),
    # Скролл
    "scroll_to":         ("⬇ Скролл к элементу", "target=селектор"),
    "scroll_page":       ("📜 Скролл страницы", "value=px"),
    # Куки
    "cookie_get":        ("🍪 Получить куки", "target=домен → variable_out"),
    "cookie_set":        ("🍪 Установить куку", "target=json"),
    "cookie_clear":      ("🍪🧹 Очистить куки", "target=домен (пусто=все)"),
    # Скриншот
    "screenshot":        ("📸 Скриншот", "value=путь"),
    "screenshot_element":("📸 Скриншот элемента", "target=селектор value=путь"),
    # === Новые действия для BROWSER_AGENT ===
    "get_dom_context":    ("📄 Получить умный DOM-контекст", "→ variable_out (сокращённый DOM + описание)"),
    "smart_action":       ("🧠 Умное действие по DOM", "value=описание_что_сделать (Planner context)"),
    # Прочее
    "close_browser":     ("❌ Закрыть браузер", ""),
    "maximize":          ("⬛ Максимизировать", ""),
    "set_size":          ("📐 Размер окна", "value=1280x900"),
}


# ══════════════════════════════════════════════════════════
#  BROWSER INSTANCE (движок)
# ══════════════════════════════════════════════════════════

class BrowserInstance(QObject):
    log_signal = pyqtSignal(str)
    status_changed = pyqtSignal(str)

    def __init__(self, instance_id: str, profile: BrowserProfile,
                 proxy: BrowserProxy, parent=None, launch_for_tray: bool = False):
        super().__init__(parent)
        self.instance_id = instance_id
        self.profile = profile
        self.proxy = proxy
        self._launch_for_tray = launch_for_tray  # ← ДОБАВИТЬ

        self._driver = None
        self._playwright = None
        self._status = "stopped"
        self._driver_lock = threading.Lock()

        # Определяем доступный движок
        self._engine = self._detect_engine()
        
        # Для умного отслеживания изменений (lazy screenshot)
        self._last_dom_hash: str = ""
        self._last_url: str = ""
        self._last_title: str = ""
        self._content_changed: bool = True  # Первый скриншот всегда нужен
        
    def _detect_engine(self) -> str:
        try:
            import selenium
            return "selenium"
        except ImportError:
            pass
        try:
            import playwright
            return "playwright"
        except ImportError:
            pass
        return "stub"

    def _log(self, msg: str):
        self.log_signal.emit(msg)

    # ── Public API ───────────────────────────────────────

    def launch(self) -> bool:
        """Запустить браузер. Возвращает True при успехе."""
        try:
            if self._engine == "selenium":
                return self._launch_selenium()
            elif self._engine == "playwright":
                return self._launch_playwright()
            else:
                self._log("⚠️ Selenium и Playwright не установлены. Работаю в режиме заглушки.")
                self._status = "stub"
                self.status_changed.emit("stub")
                return False
        except Exception as e:
            self._log(f"❌ Ошибка запуска браузера: {e}")
            self._status = "error"
            self.status_changed.emit("error")
            return False

    def execute_action(self, action: BrowserAction) -> Any:
        """Выполнить действие. Возвращает результат или None."""
        if self._engine == "selenium" and self._driver:
            # ═══ Lock для потокобезопасности (UI-поток тоже может обращаться) ═══
            with self._driver_lock:
                return self._selenium_action(action)
        self._log(f"⚠️ Браузер не запущен, действие '{action.action}' пропущено")
        return None

    def close(self):
        """Закрыть браузер."""
        try:
            if self._driver:
                self._driver.quit()
                self._driver = None
            if self._playwright:
                self._playwright.close()
                self._playwright = None
            self._status = "stopped"
            self.status_changed.emit("stopped")
            self._log("🔴 Браузер закрыт")
        except Exception as e:
            self._log(f"⚠️ Ошибка при закрытии: {e}")

    @property
    def is_running(self) -> bool:
        return self._driver is not None or (
            self._playwright is not None and self._status == "running"
        )

    @property
    def current_url(self) -> str:
        try:
            if self._driver:
                return self._driver.current_url
        except Exception:
            pass
        return ""

    @property
    def current_title(self) -> str:
        try:
            if self._driver:
                return self._driver.title
        except Exception:
            pass
        return ""

    # ── Selenium internals ───────────────────────────────

    def _launch_selenium(self) -> bool:
        """Запуск Selenium WebDriver."""
        self._log("🔧 Инициализация Selenium...")
        
        # Проверка импорта
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait, Select
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.action_chains import ActionChains
            self._log("✅ Selenium импортирован")
        except ImportError as e:
            self._log(f"❌ ОШИБКА: Selenium не установлен: {e}")
            self._log("💡 Установите: pip install selenium webdriver-manager")
            return False
        
        opts = Options()

        # Headless режим
        if self.profile.headless:
            opts.add_argument("--headless=new")  # Новый headless режим Chrome
            self._log("👻 Headless режим (без окна)")
        else:
            self._log("🪟 Оконный режим")

        # ═══ КРИТИЧНО: старт вне экрана для трей-режима ═══
        self._log(f"🔍 Проверка _launch_for_tray: {self._launch_for_tray}")
        if self._launch_for_tray:
            opts.add_argument("--start-minimized")
            opts.add_argument("--window-position=-32000,-32000")
            self._log("📌 Старт за пределами экрана (для трей-панели)")
        else:
            self._log(f"   → Обычный старт (_launch_for_tray={self._launch_for_tray})")

        # Профиль
        if self.profile.profile_folder:
            folder = Path(self.profile.profile_folder)
            if self.profile.create_if_missing:
                folder.mkdir(parents=True, exist_ok=True)
            opts.add_argument(f"--user-data-dir={folder}")
            self._log(f"📁 Профиль: {folder}")
        else:
            self._log("📁 Временный профиль (без сохранения)")

        # Окно
        opts.add_argument(f"--window-size={self.profile.window_width},{self.profile.window_height}")

        # Прокси
        if self.proxy.enabled and self.proxy.host:
            opts.add_argument(f"--proxy-server={self.proxy.proxy_string}")

        # User-Agent
        if self.profile.user_agent:
            opts.add_argument(f"--user-agent={self.profile.user_agent}")

        # Уведомления
        if self.profile.block_notifications:
            prefs = {"profile.default_content_setting_values.notifications": 2}
            opts.add_experimental_option("prefs", prefs)

        # Картинки
        if not self.profile.load_images:
            prefs = prefs if 'prefs' in dir() else {}
            prefs["profile.managed_default_content_settings.images"] = 2
            opts.add_experimental_option("prefs", prefs)

        # Геолокация
        if self.profile.geo_enabled:
            opts.add_experimental_option("prefs", {
                "profile.default_content_setting_values.geolocation": 1
            })

        # JavaScript
        if not self.profile.enable_javascript:
            opts.add_experimental_option("prefs", {
                "profile.managed_default_content_settings.javascript": 2
            })

        # Убираем automation banner
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument("--disable-blink-features=AutomationControlled")

        try:
            # Пробуем найти chromedriver в PATH
            self._driver = webdriver.Chrome(options=opts)
        except Exception:
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                self._driver = webdriver.Chrome(
                    service=Service(ChromeDriverManager().install()),
                    options=opts
                )
            except Exception as e:
                raise RuntimeError(f"Не удалось запустить ChromeDriver: {e}")

        # Эмуляция геолокации через JS
        if self.profile.geo_enabled:
            self._driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
                "latitude": self.profile.geo_latitude,
                "longitude": self.profile.geo_longitude,
                "accuracy": self.profile.geo_accuracy,
            })

        # Часовой пояс
        if self.profile.timezone:
            try:
                self._driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {
                    "timezoneId": self.profile.timezone
                })
            except Exception:
                pass

        # Куки из профиля
        if self.profile.cookies_json:
            self._import_cookies_from_json(self.profile.cookies_json)

        self._status = "running"
        self.status_changed.emit("running")
        self._log(f"🌐 Браузер запущен (Selenium) | профиль: {self.profile.name}")
        return True
    
    def check_content_changed(self) -> bool:
        """Быстрая проверка изменений без полного скриншота."""
        if not self.is_running:
            return False
            
        try:
            current_url = self.current_url
            current_title = self.current_title
            
            # Проверяем URL и title (быстро)
            if current_url != self._last_url or current_title != self._last_title:
                self._last_url = current_url
                self._last_title = current_title
                self._content_changed = True
                return True
            
            # Проверяем DOM hash через JS (быстрее скриншота)
            if self._driver:
                # Простой хеш от длины body и первых 100 символов текста
                dom_fingerprint = self._driver.execute_script("""
                    const body = document.body;
                    if (!body) return "no_body";
                    const text = body.innerText || "";
                    return body.childElementCount + ":" + text.length + ":" + text.slice(0, 100);
                """)
                
                if dom_fingerprint != self._last_dom_hash:
                    self._last_dom_hash = dom_fingerprint
                    self._content_changed = True
                    return True
            
            # Изменений нет
            return self._content_changed
            
        except Exception:
            # При ошибке считаем что изменилось (на всякий случай)
            return True

    def mark_content_checked(self):
        """Отметить что текущее состояние проверено."""
        self._content_changed = False
    
    def embed_into_widget(self, parent_widget: QWidget) -> Optional[QWidget]:
        """Встроить окно браузера в Qt-виджет (Windows-only через WinAPI)."""
        import platform
        if platform.system() != 'Windows':
            self._log("⚠️ Встраивание окна поддерживается только на Windows")
            return None
            
        try:
            import ctypes
            from PyQt6.QtWidgets import QWidget, QVBoxLayout
            from PyQt6.QtCore import QTimer
            
            if not self._driver:
                return None
            
            # Проверяем кэш HWND: если мы уже искали это окно, используем его
            browser_hwnd = getattr(self, '_embedded_hwnd', None)
            if not browser_hwnd or not ctypes.windll.user32.IsWindow(browser_hwnd):
                browser_hwnd = getattr(self, '_chrome_hwnd', None)

            if browser_hwnd and ctypes.windll.user32.IsWindow(browser_hwnd):
                self._log(f"♻️ Переиспользуем сохраненный HWND: {browser_hwnd}")
            else:
                # ═══ КРИТИЧНО: получаем PID процесса chromedriver и его детей ═══
                import psutil
                chrome_pids = set()
                
                # Точный способ через Selenium capabilities (решает проблему путаницы окон)
                try:
                    caps = self._driver.capabilities
                    if 'browserProcessId' in caps:
                        main_pid = caps['browserProcessId']
                        chrome_pids.add(main_pid)
                        self._log(f"🎯 Точный PID браузера получен от Selenium: {main_pid}")
                except Exception:
                    pass

                # Резервный способ
                if self._driver.service and self._driver.service.process:
                    driver_pid = self._driver.service.process.pid
                    chrome_pids.add(driver_pid)
                    try:
                        parent = psutil.Process(driver_pid)
                        for child in parent.children(recursive=True):
                            if 'chrome' in child.name().lower() or 'msedge' in child.name().lower():
                                chrome_pids.add(child.pid)
                                self._log(f"🔍 Найден chrome процесс: pid={child.pid}")
                    except Exception as e:
                        self._log(f"⚠️ Ошибка получения дочерних процессов: {e}")
                
                if not chrome_pids:
                    self._log("⚠️ Не найдены chrome процессы")
                    return None
                
                # ═══ КРИТИЧНО: ищем окно ТОЛЬКО по PID наших процессов ═══
                class HwndFinder:
                    def __init__(self, target_pids):
                        self.target_pids = target_pids
                        self.hwnd = None
                        self.found_pid = None
                        self.found_title = None
                    
                    def check_window(self, hwnd):
                        # Проверяем системный класс окна, чтобы игнорировать "Default IME" и прочий скрытый мусор
                        class_buf = ctypes.create_unicode_buffer(256)
                        ctypes.windll.user32.GetClassNameW(hwnd, class_buf, 256)
                        if class_buf.value not in ("Chrome_WidgetWin_1", "Chrome_WidgetWin_0"):
                            return False
                            
                        # Получаем PID окна
                        lpdw_process_id = ctypes.c_ulong()
                        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lpdw_process_id))
                        window_pid = lpdw_process_id.value
                        
                        # Проверяем, что PID окна в нашем списке
                        if window_pid not in self.target_pids:
                            return False
                        
                        # Получаем заголовок
                        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buffer = ctypes.create_unicode_buffer(length + 1)
                            ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
                            title = buffer.value
                            # Исключаем окна без заголовка, devtools и скрытые окна ввода
                            if title and "DevTools" not in title and "Default IME" not in title:
                                self.hwnd = hwnd
                                self.found_pid = window_pid
                                self.found_title = title
                                return True
                        return False
                
                finder = HwndFinder(chrome_pids)
                EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)
                
                def enum_callback(hwnd, extra):
                    if finder.check_window(hwnd):
                        return False  # Нашли — останавливаем
                    return True
                
                # ═══ Несколько попыток с задержкой ═══
                max_attempts = 10
                for attempt in range(max_attempts):
                    ctypes.windll.user32.EnumWindows(EnumWindowsProc(enum_callback), None)
                    if finder.hwnd:
                        break
                    self._log(f"⏳ Попытка {attempt + 1}/{max_attempts} найти окно...")
                    import time
                    time.sleep(0.3)
                
                browser_hwnd = finder.hwnd
                
                if not browser_hwnd:
                    self._log(f"⚠️ Не удалось найти окно браузера для PID: {chrome_pids}")
                    return None
                
                self._chrome_hwnd = browser_hwnd  # Кэшируем глобально
                self._log(f"✅ Найдено окно: hwnd={browser_hwnd}, pid={finder.found_pid}, title='{finder.found_title}'")
            
            # Используем parent_widget напрямую — он уже имеет правильный размер от cell layout
            container = parent_widget
            if container.layout() is None:
                layout = QVBoxLayout(container)
                layout.setContentsMargins(0, 0, 0, 0)
            
            # Получаем реальный размер — parent_widget уже размещён в layout и знает свои размеры
            container_size = container.size()
            # Если size ещё не известен (виджет не показан) — берём sizeHint
            if container_size.width() < 10 or container_size.height() < 10:
                container_size = container.sizeHint()
            
            # WinAPI: SetParent — встраиваем ПЕРЕД изменением стилей
            ctypes.windll.user32.SetParent(browser_hwnd, int(container.winId()))
            
            # ═══ КРИТИЧНО: полностью убираем заголовок, рамки и системное меню ═══
            GWL_STYLE = -16
            GWL_EXSTYLE = -20
            WS_CAPTION = 0x00C00000      # Заголовок
            WS_THICKFRAME = 0x00040000   # Размерная рамка
            WS_MINIMIZEBOX = 0x00020000  # Кнопка минимизации
            WS_MAXIMIZEBOX = 0x00010000  # Кнопка максимизации
            WS_SYSMENU = 0x00080000      # Системное меню
            WS_POPUP = 0x80000000        # Popup окно (без рамок)
            WS_CHILD = 0x40000000        # Дочернее окно
            
            # Получаем текущие стили
            style = ctypes.windll.user32.GetWindowLongW(browser_hwnd, GWL_STYLE)
            ex_style = ctypes.windll.user32.GetWindowLongW(browser_hwnd, GWL_EXSTYLE)
            
            # Убираем все ненужные стили, делаем CHILD + POPUP
            new_style = (style & ~WS_CAPTION & ~WS_THICKFRAME & ~WS_MINIMIZEBOX & 
                        ~WS_MAXIMIZEBOX & ~WS_SYSMENU) | WS_CHILD | WS_POPUP
            
            ctypes.windll.user32.SetWindowLongW(browser_hwnd, GWL_STYLE, new_style)
            
            # Убираем расширенные стили (WS_EX_WINDOWEDGE и т.д.)
            WS_EX_WINDOWEDGE = 0x00000100
            WS_EX_CLIENTEDGE = 0x00000200
            new_ex_style = ex_style & ~WS_EX_WINDOWEDGE & ~WS_EX_CLIENTEDGE
            ctypes.windll.user32.SetWindowLongW(browser_hwnd, GWL_EXSTYLE, new_ex_style)
            
            # ═══ КРИТИЧНО: принудительно устанавливаем размер окна ═══
            # Сначала скрываем окно
            SW_HIDE = 0
            ctypes.windll.user32.ShowWindow(browser_hwnd, SW_HIDE)
            
            # Устанавливаем размер и позицию (0,0 в клиентской области контейнера)
            SWP_FRAMECHANGED = 0x0020    # Применить новые стили
            SWP_NOMOVE = 0x0002          # Не менять позицию (используем 0,0)
            SWP_NOZORDER = 0x0004        # Не менять Z-order
            SWP_NOACTIVATE = 0x0010      # Не активировать
            SWP_SHOWWINDOW = 0x0040      # Показать окно
            
            # Устанавливаем размер равный размеру контейнера
            ctypes.windll.user32.SetWindowPos(
                browser_hwnd, 0,
                0, 0,  # Позиция в клиентской области контейнера
                container_size.width(), container_size.height(),
                SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW
            )
            
            # Ещё раз принудительно показываем и максимизируем
            SW_SHOW = 5
            ctypes.windll.user32.ShowWindow(browser_hwnd, SW_SHOW)
            
            # Обновляем окно
            ctypes.windll.user32.UpdateWindow(browser_hwnd)
            
            self._embedded_hwnd = browser_hwnd
            self._embedded_container = container
            
            # Подключаем обработчик resize
            self._setup_resize_handler(container, browser_hwnd)

            # ✅ При уничтожении контейнера — откреплять Chrome ДО смерти родителя
            # иначе Chrome (WS_CHILD) уничтожается вместе с Qt-виджетом
            def _on_container_destroyed(_inst=self):
                try:
                    if getattr(_inst, '_embedded_hwnd', None):
                        import ctypes
                        hwnd = _inst._embedded_hwnd
                        if ctypes.windll.user32.IsWindow(hwnd):
                            # Убираем WS_CHILD, восстанавливаем нормальный стиль
                            GWL_STYLE = -16
                            WS_CAPTION = 0x00C00000
                            WS_THICKFRAME = 0x00040000
                            WS_CHILD = 0x40000000
                            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
                            ctypes.windll.user32.SetWindowLongW(
                                hwnd, GWL_STYLE,
                                (style & ~WS_CHILD) | WS_CAPTION | WS_THICKFRAME
                            )
                            ctypes.windll.user32.SetParent(hwnd, 0)
                            # Скрываем — в трей, не на экран
                            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
                        _inst._embedded_hwnd = None
                        _inst._embedded_container = None
                except Exception:
                    pass

            self._log(f"🌐 Браузер встроен: hwnd={browser_hwnd}, size={container_size.width()}x{container_size.height()}")
            return container
                
        except Exception as e:
            self._log(f"⚠️ Ошибка встраивания окна: {e}")
            import traceback
            traceback.print_exc()
            
        return None
    
    def _setup_resize_handler(self, container: QWidget, browser_hwnd: int):
        """Подключить обработчик изменения размера контейнера для синхронизации с окном браузера."""
        from PyQt6.QtCore import QObject, pyqtSignal, QTimer
        
        # Создаём фильтр событий для отслеживания resize
        class ResizeFilter(QObject):
            resized = pyqtSignal(int, int)
            
            def eventFilter(self, obj, event):
                from PyQt6.QtCore import QEvent
                if event.type() == QEvent.Type.Resize:
                    self.resized.emit(obj.width(), obj.height())
                return False
        
        self._resize_filter = ResizeFilter(container)
        self._resize_filter.resized.connect(
            lambda w, h: self._on_container_resized(browser_hwnd, w, h)
        )
        container.installEventFilter(self._resize_filter)
        
        # Также таймер для периодической синхронизации (на случай если resize не сработает)
        self._resize_timer = QTimer(container)
        self._resize_timer.timeout.connect(
            lambda: self._on_container_resized(browser_hwnd, container.width(), container.height())
        )
        self._resize_timer.start(100)  # Проверка 10 раз в секунду

        # ✅ Win32-субклассинг: перехватываем WM_DESTROY на контейнере ДО уничтожения
        # WS_CHILD детей — container.destroyed приходит слишком поздно (Chrome уже мёртв)
        try:
            import ctypes
            _WndProc = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_int, ctypes.c_uint, ctypes.c_int, ctypes.c_int)
            _chw     = int(container.winId())
            _old_p   = ctypes.c_void_p(ctypes.windll.user32.GetWindowLongPtrW(_chw, -4))  # GWLP_WNDPROC
            _bref    = [browser_hwnd]
            _iref    = [self]

            @_WndProc
            def _guard(hwnd, msg, wparam, lparam):
                # Проверяем валидность hwnd
                if not ctypes.windll.user32.IsWindow(hwnd):
                    return 0
                
                if msg == 0x0002 and _bref[0]:   # WM_DESTROY — ДО уничтожения детей
                    try:
                        bh = _bref[0];  _bref[0] = 0
                        if ctypes.windll.user32.IsWindow(bh):
                            GWL_STYLE    = -16
                            WS_CHILD     = 0x40000000
                            WS_CAPTION   = 0x00C00000
                            WS_THICKFRAME = 0x00040000
                            st = ctypes.windll.user32.GetWindowLongW(bh, GWL_STYLE)
                            ctypes.windll.user32.SetWindowLongW(
                                bh, GWL_STYLE, (st & ~WS_CHILD) | WS_CAPTION | WS_THICKFRAME)
                            ctypes.windll.user32.SetParent(bh, 0)
                            ctypes.windll.user32.ShowWindow(bh, 0)  # SW_HIDE
                        inst = _iref[0]
                        if inst:
                            inst._embedded_hwnd      = None
                            inst._embedded_container = None
                    except Exception:
                        pass
                    finally:
                        # Всегда вызываем старый proc, даже если наш код упал
                        if _old_p and ctypes.windll.user32.IsWindow(hwnd):
                            try:
                                return ctypes.windll.user32.CallWindowProcW(_old_p, hwnd, msg, wparam, lparam)
                            except Exception:
                                return 0
                        return 0
                
                # Обычная обработка — вызываем старый WndProc с защитой
                if _old_p and ctypes.windll.user32.IsWindow(hwnd):
                    try:
                        return ctypes.windll.user32.CallWindowProcW(_old_p, hwnd, msg, wparam, lparam)
                    except (OSError, ValueError):
                        # Окно уничтожено или _old_p невалиден
                        pass
                return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            ctypes.windll.user32.SetWindowLongPtrW(_chw, -4, _guard)
            self._container_guard_proc = _guard   # держим ссылку — иначе GC удалит callback
            self._container_guard_proc = _guard   # держим ссылку — иначе GC удалит callback
        except Exception as e:
            self._log(f"⚠️ WndProc guard не установлен: {e}")

        self._log("✅ Обработчик resize подключён")
    
    def _on_container_resized(self, browser_hwnd: int, width: int, height: int):
        """Синхронизировать размер окна браузера с контейнером."""
        try:
            import ctypes
            
            # Проверяем, что окно ещё существует
            if not ctypes.windll.user32.IsWindow(browser_hwnd):
                if hasattr(self, '_resize_timer') and self._resize_timer:
                    self._resize_timer.stop()
                return
            
            # ═══ КРИТИЧНО: используем GetClientRect вместо GetWindowRect ═══
            # Получаем размер клиентской области (без рамок)
            client_rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetClientRect(browser_hwnd, ctypes.byref(client_rect))
            current_width = client_rect.right - client_rect.left
            current_height = client_rect.bottom - client_rect.top
            
            # Если размер отличается — корректируем (порог 5 пикселей)
            if abs(current_width - width) > 5 or abs(current_height - height) > 5:
                SWP_FRAMECHANGED = 0x0020
                SWP_NOZORDER = 0x0004
                SWP_NOACTIVATE = 0x0010
                
                # Принудительно устанавливаем новый размер
                ctypes.windll.user32.SetWindowPos(
                    browser_hwnd, 0,
                    0, 0,  # Позиция относительно клиентской области родителя
                    width, height,
                    SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE
                )
                
                # Обновляем окно
                ctypes.windll.user32.UpdateWindow(browser_hwnd)
                
        except Exception as e:
            pass
    
    def unembed(self):
        """Восстановить окно браузера как отдельное."""
        if hasattr(self, '_embedded_hwnd') and self._embedded_hwnd:
            try:
                import ctypes
                GWL_STYLE = -16
                WS_CAPTION = 0x00C00000
                WS_THICKFRAME = 0x00040000
                style = ctypes.windll.user32.GetWindowLongW(self._embedded_hwnd, GWL_STYLE)
                ctypes.windll.user32.SetWindowLongW(self._embedded_hwnd, GWL_STYLE,
                    style | WS_CAPTION | WS_THICKFRAME)
                ctypes.windll.user32.SetParent(self._embedded_hwnd, 0)
                self._log("🌐 Браузер восстановлен как отдельное окно")
            except:
                pass
            self._embedded_hwnd = None
            self._embedded_container = None

    # ── Tray helpers ─────────────────────────────────────

    def _find_chrome_hwnd(self) -> int:
        """Найти HWND главного окна Chrome по PID драйвера."""
        try:
            import ctypes, ctypes.wintypes, psutil
            if not self._driver:
                return 0
                
            # Проверяем кэш HWND
            cached_hwnd = getattr(self, '_chrome_hwnd', None) or getattr(self, '_embedded_hwnd', None)
            if cached_hwnd and ctypes.windll.user32.IsWindow(cached_hwnd):
                return cached_hwnd

            # Собираем только настоящие chrome.exe процессы (как в embed_into_widget)
            chrome_pids = set()
            try:
                caps = self._driver.capabilities
                if 'browserProcessId' in caps:
                    chrome_pids.add(caps['browserProcessId'])
            except Exception:
                pass
                
            if self._driver.service and self._driver.service.process:
                drv_pid = self._driver.service.process.pid
                for child in psutil.Process(drv_pid).children(recursive=True):
                    if 'chrome' in child.name().lower() or 'msedge' in child.name().lower():
                        chrome_pids.add(child.pid)

            if not chrome_pids:
                return 0

            found_hwnd = [0]
            lpdw = ctypes.c_ulong()

            def cb(hwnd, _):
                # Проверяем системный класс окна (отсеиваем Default IME и прочие системные пустышки)
                class_buf = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetClassNameW(hwnd, class_buf, 256)
                if class_buf.value not in ("Chrome_WidgetWin_1", "Chrome_WidgetWin_0"):
                    return True

                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lpdw))
                if lpdw.value not in chrome_pids:
                    return True
                
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    if title and "DevTools" not in title and "Default IME" not in title:
                        found_hwnd[0] = hwnd
                        return False  # нашли — стоп
                return True

            EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)
            ctypes.windll.user32.EnumWindows(EnumProc(cb), None)
            if found_hwnd[0]:
                self._chrome_hwnd = found_hwnd[0]
            return found_hwnd[0]
        except Exception as e:
            self._log(f"⚠️ _find_chrome_hwnd: {e}")
            return 0

    def minimize_window(self) -> bool:
        """Скрыть окно Chrome (убрать в трей — скрыть из taskbar и экрана)."""
        try:
            import ctypes
            hwnd = self._find_chrome_hwnd() or getattr(self, '_chrome_hwnd', 0)
            
            # ✅ Проверяем что HWND валиден
            if hwnd and ctypes.windll.user32.IsWindow(hwnd):
                # ✅ Сначала сохраняем позицию и размер
                if not hasattr(self, '_saved_window_rect'):
                    rect = ctypes.wintypes.RECT()
                    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    self._saved_window_rect = (rect.left, rect.top, 
                                               rect.right - rect.left, 
                                               rect.bottom - rect.top)
                
                # ✅ Скрываем окно (SW_HIDE = 0)
                ctypes.windll.user32.ShowWindow(hwnd, 0)
                self._log(f"✅ Окно {hwnd} скрыто в трей")
                return True
            else:
                self._log(f"⚠️ Невалидный HWND: {hwnd}")
        except Exception as e:
            self._log(f"⚠️ minimize_window: {e}")
        return False

    def show_window(self) -> bool:
        """Показать окно Chrome из скрытого / свёрнутого состояния."""
        try:
            import ctypes
            hwnd = self._find_chrome_hwnd() or getattr(self, '_chrome_hwnd', 0)
            
            if hwnd and ctypes.windll.user32.IsWindow(hwnd):
                # Если окно было встроено — сначала открепляем
                if hasattr(self, '_embedded_hwnd') and self._embedded_hwnd:
                    self.unembed()
                
                SW_SHOW = 5
                SW_RESTORE = 9
                SWP_SHOWWINDOW = 0x0040

                # Перемещаем в видимую область экрана если окно было за пределами
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                x, y = rect.left, rect.top
                w = rect.right - rect.left
                h = rect.bottom - rect.top

                # Если позиция за экраном (старт вне экрана) — сбрасываем на 100,100
                screen_w = ctypes.windll.user32.GetSystemMetrics(0)
                screen_h = ctypes.windll.user32.GetSystemMetrics(1)
                if x < -1000 or y < -1000 or x > screen_w or y > screen_h:
                    x, y = 100, 100

                # Используем сохранённую позицию если есть и она в пределах экрана
                if hasattr(self, '_saved_window_rect'):
                    sx, sy, sw, sh = self._saved_window_rect
                    if -100 <= sx <= screen_w and -100 <= sy <= screen_h:
                        x, y, w, h = sx, sy, sw, sh

                ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, w, h, SWP_SHOWWINDOW)
                ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW)
                ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                
                self._minimized_to_tray = False
                self._log(f"✅ Окно {hwnd} восстановлено из трея")
                return True
            else:
                self._log(f"⚠️ Невозможно показать окно: невалидный HWND {hwnd}")
        except Exception as e:
            self._log(f"⚠️ show_window: {e}")
        return False

    def _launch_playwright(self) -> bool:
        # Синхронный playwright (для простоты интеграции с Qt)
        from playwright.sync_api import sync_playwright
        import threading

        self._pw_ctx = sync_playwright().__enter__()
        launch_opts = {"headless": False}

        if self.proxy.enabled and self.proxy.host:
            pw_proxy = {"server": self.proxy.proxy_string}
            if self.proxy.login:
                pw_proxy["username"] = self.proxy.login
                pw_proxy["password"] = self.proxy.password
            launch_opts["proxy"] = pw_proxy

        browser = self._pw_ctx.chromium.launch(**launch_opts)
        ctx_opts = {}
        if self.profile.profile_folder:
            pass  # playwright использует persistent_context иначе

        if self.profile.geo_enabled:
            ctx_opts["geolocation"] = {
                "latitude": self.profile.geo_latitude,
                "longitude": self.profile.geo_longitude,
                "accuracy": self.profile.geo_accuracy,
            }
            ctx_opts["permissions"] = ["geolocation"]

        if self.profile.timezone:
            ctx_opts["timezone_id"] = self.profile.timezone

        if self.profile.user_agent:
            ctx_opts["user_agent"] = self.profile.user_agent

        self._playwright = browser.new_context(**ctx_opts)
        self._pw_page = self._playwright.new_page()

        self._status = "running"
        self.status_changed.emit("running")
        self._log(f"🌐 Браузер запущен (Playwright) | профиль: {self.profile.name}")
        return True

    def _selenium_action(self, action: BrowserAction) -> Any:
        """Выполнение действий через Selenium."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait, Select
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.action_chains import ActionChains
        import time

        drv = self._driver
        act = action.action
        tgt = action.target
        val = action.value
        tout = action.timeout

        def by_map(sel_type):
            return {
                "css": By.CSS_SELECTOR, "xpath": By.XPATH,
                "id": By.ID, "name": By.NAME, "tag": By.TAG_NAME,
            }.get(sel_type, By.CSS_SELECTOR)

        def find(selector, sel_type="css"):
            by = by_map(sel_type)
            wait = WebDriverWait(drv, tout)
            
            # Если селектор не найден — пробуем альтернативные для Google
            try:
                return wait.until(EC.presence_of_element_located((by, selector)))
            except Exception as e:
                # Fallback для Google поиска
                if "q" in selector or "search" in selector.lower():
                    try:
                        # Пробуем разные варианты селекторов Google
                        for alt_selector in [
                            'textarea[name="q"]',
                            'input[name="q"]',
                            '[aria-label="Найти"]',
                            '[aria-label="Search"]',
                            'form[role="search"] input',
                            'form[role="search"] textarea',
                            'input[type="text"]',
                        ]:
                            try:
                                return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, alt_selector)))
                            except:
                                continue
                    except:
                        pass
                raise e

        result = None
        try:
            # Навигация
            if act == "navigate":
                url = (tgt or "").strip()
                if url and not url.startswith(("http://", "https://", "file://", "about:", "data:", "chrome://")):
                    url = "https://" + url
                drv.get(url)
            elif act == "navigate_back":
                drv.back()
            elif act == "navigate_forward":
                drv.forward()
            elif act == "reload":
                drv.refresh()
            elif act == "stop":
                drv.execute_script("window.stop();")

            # Вкладки
            elif act == "tab_new":
                drv.execute_script("window.open('', arguments[0]);", val or "new_tab")
                drv.switch_to.window(drv.window_handles[-1])
            elif act == "tab_activate":
                try:
                    idx = int(tgt)
                    drv.switch_to.window(drv.window_handles[idx])
                except (ValueError, IndexError):
                    for handle in drv.window_handles:
                        drv.switch_to.window(handle)
                        if tgt.lower() in drv.title.lower():
                            break
            elif act == "tab_close":
                if tgt == "current" or not tgt:
                    drv.close()
                    if drv.window_handles:
                        drv.switch_to.window(drv.window_handles[-1])

            # Клики
            elif act in ("click", "click_js"):
                self._log(f"🖱 Клик по элементу: {tgt[:60]} (тип: {action.selector_type})")
                try:
                    el = find(tgt, action.selector_type)
                    
                    # Получаем координаты ДО клика для верификации
                    location_before = el.location
                    size = el.size
                    center_x = location_before['x'] + size['width'] // 2
                    center_y = location_before['y'] + size['height'] // 2
                    
                    # Помечаем элемент для верификации
                    el_id = drv.execute_script("return arguments[0].setAttribute('data-ai-verify', 'target'); arguments[0].getAttribute('data-ai-id') || ''", el)
                    
                    if act == "click_js":
                        drv.execute_script("arguments[0].click();", el)
                    else:
                        el.click()
                    
                    # Верификация: проверяем что элемент на месте
                    try:
                        import time
                        time.sleep(0.1)
                        location_after = el.location
                        dx = abs(location_after['x'] - location_before['x'])
                        dy = abs(location_after['y'] - location_before['y'])
                        if dx > 10 or dy > 10:
                            self._log(f"⚠️ Элемент сдвинулся после клика: Δx={dx}, Δy={dy}")
                        else:
                            self._log(f"✅ Клик выполнен, элемент стабилен ({center_x}, {center_y})")
                    except:
                        self._log("✅ Клик выполнен (верификация недоступна)")
                        
                except Exception as e:
                    self._log(f"❌ Ошибка клика по элементу '{tgt[:30]}': {e}")
                    raise

            elif act == "click_xy":
                # ═══ ИСПРАВЛЕНИЕ: click_xy вынесен как отдельный elif ═══
                x, y = 0, 0
                if tgt and ',' in str(tgt):
                    try:
                        coords = str(tgt).replace(" ", "").split(",")
                        x, y = int(coords[0]), int(coords[1])
                    except (ValueError, IndexError):
                        pass
                if x <= 0 or y <= 0:
                    try:
                        x = int(getattr(action, 'coord_x', 0))
                        y = int(getattr(action, 'coord_y', 0))
                    except (ValueError, TypeError):
                        pass
                if x <= 0 or y <= 0:
                    self._log(f"❌ click_xy: невалидные координаты ({x}, {y})")
                    raise ValueError(f"Invalid coordinates for click_xy: ({x}, {y})")
                self._log(f"🖱 Клик по координатам: ({x}, {y})")
                ActionChains(drv).move_by_offset(x, y).click().perform()
                ActionChains(drv).move_by_offset(-x, -y).perform()

            elif act == "click_text":
                # Клик по тексту: ищем элемент содержащий текст
                # Текст берём из отдельного поля search_text или из target
                search_text = getattr(action, 'search_text', '') or tgt or ''
                if not search_text:
                    self._log("⚠️ click_text: не указан текст для поиска")
                    return None
                self._log(f"🔤 Поиск элемента по тексту: '{search_text[:50]}...'")
                # Экранируем кавычки в тексте для XPath
                safe_text = search_text.replace("'", "&apos;").replace('"', '&quot;')
                xpath = f"//*[contains(text(), '{safe_text}')]"
                try:
                    el = WebDriverWait(drv, tout).until(
                        EC.presence_of_element_located((By.XPATH, xpath))
                    )
                    self._log(f"✅ Элемент найден, выполняю клик")
                    el.click()
                except Exception as e:
                    self._log(f"❌ Элемент с текстом '{search_text[:30]}' не найден: {e}")
                    raise
            elif act == "double_click":
                el = find(tgt, action.selector_type)
                ActionChains(drv).double_click(el).perform()
            elif act == "double_click_xy":
                x, y = 100, 100
                if tgt and ',' in str(tgt):
                    try:
                        coords = str(tgt).replace(" ", "").split(",")
                        x, y = int(coords[0]), int(coords[1])
                    except (ValueError, IndexError):
                        pass
                else:
                    try:
                        x = int(getattr(action, 'coord_x', 100))
                        y = int(getattr(action, 'coord_y', 100))
                    except (ValueError, TypeError):
                        pass
                self._log(f"🖱🖱 Двойной клик по координатам: ({x}, {y})")
                ActionChains(drv).move_by_offset(x, y).double_click().perform()
                ActionChains(drv).move_by_offset(-x, -y).perform()
            elif act == "right_click":
                el = find(tgt, action.selector_type)
                ActionChains(drv).context_click(el).perform()
            elif act == "right_click_xy":
                x, y = 100, 100
                if tgt and ',' in str(tgt):
                    try:
                        coords = str(tgt).replace(" ", "").split(",")
                        x, y = int(coords[0]), int(coords[1])
                    except (ValueError, IndexError):
                        pass
                else:
                    try:
                        x = int(getattr(action, 'coord_x', 100))
                        y = int(getattr(action, 'coord_y', 100))
                    except (ValueError, TypeError):
                        pass
                self._log(f"🖱 Правый клик по координатам: ({x}, {y})")
                ActionChains(drv).move_by_offset(x, y).context_click().perform()
                ActionChains(drv).move_by_offset(-x, -y).perform()
            elif act == "hover":
                el = find(tgt, action.selector_type)
                ActionChains(drv).move_to_element(el).perform()
            elif act == "hover_xy":
                x, y = 100, 100
                if tgt and ',' in str(tgt):
                    try:
                        coords = str(tgt).replace(" ", "").split(",")
                        x, y = int(coords[0]), int(coords[1])
                    except (ValueError, IndexError):
                        pass
                else:
                    try:
                        x = int(getattr(action, 'coord_x', 100))
                        y = int(getattr(action, 'coord_y', 100))
                    except (ValueError, TypeError):
                        pass
                self._log(f"👆 Наведение по координатам: ({x}, {y})")
                ActionChains(drv).move_by_offset(x, y).perform()
                # Не возвращаем курсор — hover должен оставаться

            # Ввод
            elif act == "type_text":
                el = None
                x, y = None, None
                
                # === ШАГ 1: Определяем координаты ===
                # Сначала пробуем распарсить target как "x,y"
                if tgt and ',' in str(tgt):
                    try:
                        coords = str(tgt).replace(" ", "").split(",")
                        x, y = int(coords[0]), int(coords[1])
                        if x <= 0 or y <= 0:
                            x, y = None, None
                    except (ValueError, IndexError):
                        x, y = None, None
                
                # Fallback на отдельные поля coord_x/coord_y
                if x is None:
                    try:
                        x = int(getattr(action, 'coord_x', 0))
                        y = int(getattr(action, 'coord_y', 0))
                        if x <= 0 or y <= 0:
                            x, y = None, None
                    except (ValueError, TypeError):
                        x, y = None, None
                
                # === ШАГ 2: Если есть координаты — кликаем и вводим через ActionChains ===
                if x is not None and y is not None:
                    self._log(f"  🖱 Клик по координатам ({x}, {y}) и ввод текста")
                    try:
                        # Клик + ввод через ActionChains — надёжнее чем find_element
                        actions = ActionChains(drv)
                        actions.move_by_offset(x, y).click()
                        actions.pause(0.1)  # небольшая пауза для фокуса
                        actions.send_keys(val)
                        actions.perform()
                        # Возвращаем курсор
                        ActionChains(drv).move_by_offset(-x, -y).perform()
                        self._log(f"  ✅ Текст введён через ActionChains: {val[:50]}...")
                        result = val  # УСПЕХ — возвращаем результат
                        # Пропускаем стандартную логику — она ниже в elif, не вызываем её
                    except Exception as e:
                        self._log(f"  ⚠️ ActionChains не сработал: {e}, пробуем стандартный путь")
                        # Продолжаем к стандартной логике
                
                # === ШАГ 3: Стандартная логика — поиск по селектору ===
                try:
                    el = find(tgt, action.selector_type)
                except Exception:
                    pass
                
                # Если не нашли — ищем поле ввода по умолчанию
                if not el:
                    try:
                        el = drv.find_element(By.CSS_SELECTOR, 
                            'input[type="text"], input[type="search"], textarea, [role="searchbox"], '
                            'input[name="q"], textarea[name="q"], #search, [name="q"]')
                        self._log(f"  🔍 Найдено поле ввода по умолчанию: {el.tag_name if el else "none"}")
                    except Exception:
                        pass
                
                if not el:
                    raise Exception(f"Не удалось найти поле ввода для: {tgt}")
                
                # === ШАГ 4: Ввод текста с защитой от ошибок ===
                try:
                    # Прокручиваем к элементу
                    drv.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                    import time
                    time.sleep(0.2)
                    
                    # Клик для фокуса
                    el.click()
                    time.sleep(0.1)
                    
                    # Очистка с защитой
                    try:
                        el.clear()
                    except Exception as e:
                        self._log(f"  ⚠️ clear() не сработал: {e}, используем Ctrl+A")
                        # Альтернативная очистка
                        el.send_keys(u'\ue009' + 'a')  # Ctrl+A
                        el.send_keys(u'\ue017')  # DELETE
                    
                    # Ввод текста
                    el.send_keys(val)
                    self._log(f"  ✅ Введён текст: {val[:50]}...")
                    
                except Exception as e:
                    self._log(f"  ❌ Ошибка ввода: {e}")
                    # Последняя попытка — через JavaScript
                    try:
                        drv.execute_script("arguments[0].value = arguments[1];", el, val)
                        drv.execute_script("arguments[0].dispatchEvent(new Event('input', {bubbles: true}));", el)
                        drv.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", el)
                        self._log(f"  ✅ Текст введён через JavaScript: {val[:50]}...")
                    except Exception as js_e:
                        raise Exception(f"Ввод текста не удался: {e}, JS fallback: {js_e}")
            elif act == "clear_field":
                el = find(tgt, action.selector_type)
                el.clear()
            elif act == "select_option":
                el = find(tgt, action.selector_type)
                Select(el).select_by_visible_text(val)
            elif act == "set_checkbox":
                el = find(tgt, action.selector_type)
                checked = val.lower() in ("true", "1", "yes", "да")
                if el.is_selected() != checked:
                    el.click()
            elif act == "file_upload":
                el = find(tgt, action.selector_type)
                el.send_keys(val)

            # Получение данных
            elif act == "get_text":
                el = find(tgt, action.selector_type)
                result = el.text
            elif act == "get_attr":
                el = find(tgt, action.selector_type)
                result = el.get_attribute(val)
            elif act == "get_url":
                result = drv.current_url
            elif act == "get_title":
                result = drv.title
            elif act == "get_html":
                if tgt:
                    el = find(tgt, action.selector_type)
                    result = el.get_attribute("outerHTML")
                else:
                    result = drv.page_source
            elif act == "count_elements":
                from selenium.webdriver.common.by import By
                elements = drv.find_elements(by_map(action.selector_type), tgt)
                result = len(elements)

            # Ожидание
            elif act == "wait_element":
                find(tgt, action.selector_type)
            elif act == "wait_url":
                WebDriverWait(drv, tout).until(
                    lambda d: tgt.lower() in d.current_url.lower()
                )
            elif act == "wait_text":
                WebDriverWait(drv, tout).until(
                    EC.text_to_be_present_in_element(
                        (by_map(action.selector_type), tgt), val
                    )
                )
            elif act == "wait_seconds":
                time.sleep(float(val) if val else 1.0)

            # JavaScript
            elif act == "execute_js":
                result = drv.execute_script(tgt)
            elif act == "js_auth":
                drv.execute_script(
                    "window.promptCredentials = function() { return [arguments[0], arguments[1]]; }",
                    tgt, val
                )
            elif act == "js_confirm":
                drv.execute_script(
                    f"window.confirm = function() {{ return {'true' if val != 'cancel' else 'false'}; }}"
                )
            elif act == "js_prompt":
                drv.execute_script(
                    f"window.prompt = function() {{ return '{val}'; }}"
                )

            # Скролл
            elif act == "scroll_to":
                el = find(tgt, action.selector_type)
                drv.execute_script("arguments[0].scrollIntoView(true);", el)
            elif act == "scroll_page":
                drv.execute_script(f"window.scrollBy(0, {val or 500});")

            # Куки
            elif act == "cookie_get":
                cookies = drv.get_cookies()
                if tgt:
                    cookies = [c for c in cookies if tgt in c.get("domain", "")]
                result = json.dumps(cookies, ensure_ascii=False)
            elif act == "cookie_set":
                cookies = json.loads(tgt)
                if isinstance(cookies, list):
                    for c in cookies:
                        try:
                            drv.add_cookie(c)
                        except Exception:
                            pass
                elif isinstance(cookies, dict):
                    drv.add_cookie(cookies)
            elif act == "cookie_clear":
                if tgt:
                    all_cookies = drv.get_cookies()
                    for c in all_cookies:
                        if tgt in c.get("domain", ""):
                            drv.delete_cookie(c["name"])
                else:
                    drv.delete_all_cookies()

            # Скриншот
            elif act == "screenshot":
                path = val or "screenshot.png"
                drv.save_screenshot(path)
                result = path
            elif act == "screenshot_element":
                el = find(tgt, action.selector_type)
                path = val or "screenshot_el.png"
                el.screenshot(path)
                result = path

            # Окно
            elif act == "close_browser":
                self.close()
            elif act == "maximize":
                drv.maximize_window()
            elif act == "set_size":
                parts = val.split("x") if "x" in val else val.split(",")
                w, h = int(parts[0]), int(parts[1]) if len(parts) > 1 else 900
                drv.set_window_size(w, h)

            # Пауза после действия
            if action.wait_after > 0:
                import time
                time.sleep(action.wait_after)

        except Exception as e:
            self._log(f"⚠️ Ошибка действия '{act}': {e}")
            result = None

        return result

    def _playwright_action(self, action: BrowserAction) -> Any:
        """Аналог для Playwright (упрощённый)."""
        page = getattr(self, "_pw_page", None)
        if not page:
            return None
        act = action.action
        tgt = action.target
        try:
            if act == "navigate":
                page.goto(tgt, timeout=action.timeout * 1000)
            elif act == "click":
                page.click(tgt)
            elif act == "click_xy":
                # Координаты из отдельных полей или из target
                x = getattr(action, 'coord_x', 100)
                y = getattr(action, 'coord_y', 100)
                if ',' in str(tgt):
                    coords = str(tgt).replace(" ", "").split(",")
                    x, y = int(coords[0]), int(coords[1])
                page.mouse.click(x, y)
            elif act == "click_text":
                # Playwright: клик по тексту через get_by_text
                search_text = getattr(action, 'search_text', '') or tgt
                page.get_by_text(search_text).click()
            elif act == "double_click":
                page.dblclick(tgt)
            elif act == "double_click_xy":
                coords = tgt.replace(" ", "").split(",")
                x, y = int(coords[0]), int(coords[1])
                page.mouse.dblclick(x, y)
            elif act == "right_click":
                page.click(tgt, button="right")
            elif act == "right_click_xy":
                coords = tgt.replace(" ", "").split(",")
                x, y = int(coords[0]), int(coords[1])
                page.mouse.click(x, y, button="right")
            elif act == "hover":
                page.hover(tgt)
            elif act == "hover_xy":
                coords = tgt.replace(" ", "").split(",")
                x, y = int(coords[0]), int(coords[1])
                page.mouse.move(x, y)
            elif act == "type_text":
                page.fill(tgt, action.value)
            elif act == "get_text":
                return page.text_content(tgt)
            elif act == "get_url":
                return page.url
            elif act == "execute_js":
                return page.evaluate(tgt)
            elif act == "screenshot":
                page.screenshot(path=action.value or "screenshot.png")
            elif act == "close_browser":
                self.close()
        except Exception as e:
            self._log(f"⚠️ Playwright: ошибка '{act}': {e}")
        return None
    
    def get_smart_dom_context(self, max_tokens: int = 8000) -> dict:
        """Сокращённый DOM + описание страницы + скриншот (если нужно)."""
        if not self._driver:
            return {"error": "Браузер не запущен"}
        
        try:
            # 1. Получаем полный DOM
            dom = self._driver.execute_script("return document.documentElement.outerHTML")
            
            # 2. Умное сокращение (убираем скрипты, стили, комментарии, скрытые элементы)
            dom = self._driver.execute_script("""
                return document.documentElement.outerHTML
                    .replace(/<script[^>]*>.*?<\\/script>/gis, '')
                    .replace(/<style[^>]*>.*?<\\/style>/gis, '')
                    .replace(/<!--.*?-->/gs, '')
                    .replace(/\\s+/g, ' ')
                    .slice(0, 120000);
            """)
            
            # 3. Скриншот (base64) — только если нужен для верификации
            screenshot_b64 = None
            try:
                screenshot_b64 = self._driver.get_screenshot_as_base64()
            except:
                pass
            
            # 4. Краткое описание страницы (title + meta + visible text)
            page_info = self._driver.execute_script("""
                return {
                    title: document.title,
                    url: location.href,
                    visibleText: document.body ? document.body.innerText.trim().slice(0, 2000) : ''
                };
            """)
            
            return {
                "success": True,
                "url": page_info["url"],
                "title": page_info["title"],
                "dom_summary": dom[:max_tokens],
                "visible_text": page_info["visibleText"],
                "screenshot_base64": screenshot_b64,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"error": str(e)}
    
    def _import_cookies_from_json(self, cookies_json: str):
        """Импорт куки из JSON-строки."""
        if not self._driver:
            return
        try:
            cookies = json.loads(cookies_json)
            if isinstance(cookies, list):
                for c in cookies:
                    try:
                        self._driver.add_cookie(c)
                    except Exception:
                        pass
        except Exception as e:
            self._log(f"⚠️ Ошибка импорта куки: {e}")
            
    # ─── DOM extraction ───────────────────────────────────────────────────────

    def get_dom_compressed(self, max_tokens: int = 2000) -> str:
        """
        Извлечь DOM текущей страницы и сжать до max_tokens примерно (~4 символа = 1 токен).
        Убирает скрипты, стили, svg, мета-теги. Оставляет текст, alt, placeholder, aria-label,
        href, id, name — всё что нужно AI для понимания структуры страницы.
        """
        max_chars = max_tokens * 4
        raw_html = ""

        try:
            if self._driver:  # Selenium
                raw_html = self._driver.page_source or ""
            elif self._page:  # Playwright
                import asyncio
                raw_html = asyncio.get_event_loop().run_until_complete(
                    self._page.content()
                ) or ""
        except Exception as e:
            return f"[DOM extraction error: {e}]"

        # --- Минимальный парсинг без внешних зависимостей ---
        import re
        # Удаляем <script>, <style>, <svg>, <meta>, <link>
        for tag in ("script", "style", "svg", "meta", "link", "noscript"):
            raw_html = re.sub(
                rf"<{tag}[\s>].*?</{tag}>", "", raw_html,
                flags=re.DOTALL | re.IGNORECASE
            )
            raw_html = re.sub(
                rf"<{tag}[^>]*/?>", "", raw_html, flags=re.IGNORECASE
            )

        # Оставляем только нужные атрибуты в тегах
        def _clean_tag(m: re.Match) -> str:
            tag_text = m.group(0)
            # Оставляем: id, name, class (первые 30 символов), href, placeholder,
            # aria-label, alt, type, value, role
            keep = re.findall(
                r'\b(id|name|href|placeholder|aria-label|alt|type|value|role|class)'
                r'=["\']([^"\']{0,60})["\']',
                tag_text, re.IGNORECASE
            )
            tag_name = re.match(r"<(\w+)", tag_text)
            if not tag_name:
                return ""
            attrs = " ".join(f'{k}="{v}"' for k, v in keep)
            return f"<{tag_name.group(1)} {attrs}>" if attrs else f"<{tag_name.group(1)}>"

        raw_html = re.sub(r"<[a-zA-Z][^>]{10,}>", _clean_tag, raw_html)

        # Убираем пустые строки и лишние пробелы
        lines = [ln.strip() for ln in raw_html.splitlines() if ln.strip()]
        compressed = "\n".join(lines)

        if len(compressed) > max_chars:
            compressed = compressed[:max_chars] + "\n...[DOM TRUNCATED]"

        return compressed
    
    def get_interactive_elements(self, max_elements: int = 50) -> list[dict]:
        """
        Получить список интерактивных видимых элементов с координатами.
        Только элементы которые можно кликнуть, ввести текст, выбрать.
        """
        result = self.collect_dom_for_ai(max_elements=max_elements)
        return result.get("interactive", [])

    def collect_dom_for_ai(self, max_elements: int = 200) -> dict:
        """
        Полная коллекция DOM для AI-агента (аналог ZP AiDomMapper + AiDomPreprocessor).
        Собирает ВСЕ элементы страницы включая Shadow DOM, затем фильтрует для AI.
        Возвращает dict: {meta, elements, interactive, dom_text}.
        """
        if not self._driver:
            return {"meta": {}, "elements": [], "interactive": [], "dom_text": ""}

        # ── Шаг 1: Сбор полного DOM через JS ──────────────────────────
        JS_COLLECT = """
(function() {
    try {
        // Ждём body если его ещё нет
        if (!document.body) {
            // Пробуем document.documentElement как fallback
            var root = document.documentElement;
            if (!root) return {error: "No document.documentElement", meta: {}, elements: []};
        }
        var body = document.body || document.documentElement;

        var IGNORE = new Set(['SCRIPT','STYLE','NOSCRIPT','META','HEAD','LINK',
                              'PATH','DEFS','SVG','BR','WBR','TEMPLATE']);
        var ITAGS  = new Set(['A','BUTTON','INPUT','SELECT','TEXTAREA',
                              'DETAILS','SUMMARY','LABEL','OPTION','OPTGROUP']);
        var IROLES = new Set(['button','link','menuitem','tab','checkbox','radio',
                              'switch','combobox','listbox','option','treeitem',
                              'slider','spinbutton','searchbox','textbox','gridcell']);

        var elements = [];
        var idCounter = 0;

        function safeStr(v, max) {
            if (!v) return '';
            var s = String(v).replace(/\\s+/g, ' ').trim();
            return s.length ? s.substring(0, max || 300) : '';
        }

        function getRect(el) {
            try {
                var r = el.getBoundingClientRect();
                return {
                    x:  Math.round(r.left   + window.scrollX),
                    y:  Math.round(r.top    + window.scrollY),
                    w:  Math.round(r.width),
                    h:  Math.round(r.height),
                    cx: Math.round(r.left   + window.scrollX + r.width  / 2),
                    cy: Math.round(r.top    + window.scrollY + r.height / 2)
                };
            } catch(e) { return {x:0,y:0,w:0,h:0,cx:0,cy:0}; }
        }

        function traverse(el, depth, shadowDepth) {
            if (!el || el.nodeType !== 1) return;
            var tag = (el.tagName || '').toUpperCase();
            if (IGNORE.has(tag)) return;
            if (el.id && el.id.startsWith('zp_')) return;

            var rect = getRect(el);
            var role = el.getAttribute('role') || '';
            var type = el.getAttribute('type') || '';
            var isI  = ITAGS.has(tag) || IROLES.has(role)
                    || el.getAttribute('onclick') != null
                    || el.getAttribute('tabindex') != null
                    || el.contentEditable === 'true';
            var isImg = (tag === 'IMG' || tag === 'PICTURE' || tag === 'CANVAS');

            var obj = {
                id:   ++idCounter,
                tag:  tag.toLowerCase(),
                x: rect.x, y: rect.y, w: rect.w, h: rect.h,
                cx: rect.cx, cy: rect.cy,
                visible: (rect.w > 0 && rect.h > 0)
            };
            if (isI)   obj.interactive = true;
            if (isImg) obj.isImage     = true;
            if (shadowDepth > 0) obj.shadowDepth = shadowDepth;

            var text = safeStr(el.innerText || el.textContent, 300);
            if (text) obj.text = text;

            if (el.id)                        obj.elId        = el.id;
            if (el.name)                      obj.name        = el.name;
            if (el.className && typeof el.className === 'string')
                                              obj.cls         = safeStr(el.className, 100);
            if (el.href)                      obj.href        = safeStr(el.href, 200);
            if (el.src)                       obj.src         = safeStr(el.src, 200);
            if (el.placeholder)               obj.ph          = safeStr(el.placeholder, 150);
            if (el.value !== undefined && el.value !== '')
                                              obj.value       = safeStr(String(el.value), 150);
            if (el.disabled)                  obj.disabled    = true;
            if (el.checked !== undefined)     obj.checked     = el.checked;
            if (role)                         obj.role        = role;
            if (type)                         obj.type        = type;

            var al = el.getAttribute('aria-label');
            var ae = el.getAttribute('aria-expanded');
            if (al) obj.ariaLabel    = safeStr(al, 150);
            if (ae) obj.ariaExpanded = ae;

            if (isI) {
                try { obj.outerHtml = el.outerHTML.substring(0, 300); } catch(e) {}
            }

            elements.push(obj);

            // Light DOM
            if (el.children) {
                for (var i = 0; i < el.children.length; i++)
                    traverse(el.children[i], depth + 1, shadowDepth);
            }
            // Shadow DOM
            if (el.shadowRoot && el.shadowRoot.children) {
                for (var i = 0; i < el.shadowRoot.children.length; i++)
                    traverse(el.shadowRoot.children[i], depth + 1, shadowDepth + 1);
            }
        }

        traverse(body, 0, 0);

        var meta = {
            url:       window.location.href,
            title:     document.title,
            scrollX:   window.scrollX,
            scrollY:   window.scrollY,
            viewportW: window.innerWidth,
            viewportH: window.innerHeight,
            pageW:     document.documentElement.scrollWidth,
            pageH:     document.documentElement.scrollHeight,
            total:     elements.length
        };

        // Отладка: если элементов 0, проверим что вообще есть в DOM
        if (elements.length === 0) {
            try {
                meta.bodyExists = !!document.body;
                meta.bodyChildrenCount = document.body ? document.body.children.length : 0;
                meta.htmlLength = document.documentElement ? document.documentElement.outerHTML.length : 0;
                meta.bodyHTMLLength = document.body ? document.body.innerHTML.length : 0;
                meta.url = location.href;
            } catch(e) {}
        }
        
        return {meta: meta, elements: elements};
    } catch(e) {
        return {error: e.message, meta: {}, elements: []};
    }
})();
"""
        try:
            raw = self._driver.execute_script(JS_COLLECT) or {}
            # Отладочный вывод если DOM пустой
            if raw and raw.get("meta", {}).get("total", 0) == 0:
                meta = raw.get("meta", {})
                self._log(f"  🔍 Отладка DOM: bodyExists={meta.get('bodyExists')}, "
                         f"bodyChildren={meta.get('bodyChildrenCount')}, "
                         f"htmlLen={meta.get('htmlLength')}, "
                         f"bodyHTMLLen={meta.get('bodyHTMLLength')}, "
                         f"url={meta.get('url', 'unknown')}")
        except Exception as e:
            self._log(f"⚠️ collect_dom_for_ai JS error: {e}")
            return {"meta": {}, "elements": [], "interactive": [], "dom_text": ""}
        
        # Если JS вернул 0 элементов — пробуем fallback через Selenium напрямую
        if not raw or raw.get("meta", {}).get("total", 0) == 0:
            self._log("  🔄 Fallback: пробуем Selenium find_elements...")
            try:
                from selenium.webdriver.common.by import By
                all_tags = ["a", "button", "input", "select", "textarea", 
                           "div", "span", "p", "h1", "h2", "h3", "h4", "h5", "h6",
                           "label", "form", "ul", "ol", "li", "table", "tr", "td",
                           "img", "iframe", "nav", "header", "footer", "main", "section",
                           "article", "aside", "details", "dialog", "figure", "figcaption"]
                fallback_elements = []
                for tag in all_tags:
                    try:
                        found = self._driver.find_elements(By.TAG_NAME, tag)
                        for el in found[:200]:  # увеличили лимит
                            try:
                                rect = el.rect
                                fallback_elements.append({
                                    "id": len(fallback_elements) + 1,
                                    "tag": tag,
                                    "x": int(rect.get("x", 0)), 
                                    "y": int(rect.get("y", 0)),
                                    "w": int(rect.get("width", 0)), 
                                    "h": int(rect.get("height", 0)),
                                    "cx": int(rect.get("x", 0) + rect.get("width", 0) / 2),
                                    "cy": int(rect.get("y", 0) + rect.get("height", 0) / 2),
                                    "visible": rect.get("width", 0) > 0 and rect.get("height", 0) > 0,
                                    "interactive": tag in ["a", "button", "input", "select", "textarea"],
                                    "text": (el.text or "")[:100] if hasattr(el, "text") else ""
                                })
                            except:
                                pass
                    except:
                        pass
                if fallback_elements:
                    self._log(f"  ✅ Fallback нашёл {len(fallback_elements)} элементов")
                    # Инициализируем raw правильно
                    raw = {
                        "elements": fallback_elements,
                        "meta": {
                            "total": len(fallback_elements),
                            "url": self._driver.current_url if self._driver else "",
                            "title": self._driver.title if self._driver else ""
                        }
                    }
                else:
                    self._log("  ❌ Fallback тоже не нашёл элементов")
                    raw = {"elements": [], "meta": {"total": 0}}
            except Exception as e:
                self._log(f"  ⚠️ Fallback error: {e}")
                raw = {"elements": [], "meta": {"total": 0}}
        
        if "error" in raw:
            self._log(f"⚠️ collect_dom_for_ai: {raw['error']}")

        meta     = raw.get("meta", {})
        all_els  = raw.get("elements", [])

        # ── Шаг 2: Фильтрация и сжатие (аналог AiDomPreprocessor) ──────
        interactive: list[dict] = []
        filtered:    list[dict] = []
        M = 30  # минимальный размер для контейнеров

        # Собираем ID интерактивных элементов (даже если visible=False — они могут быть кликабельны)
        interactive_ids: set = {e["id"] for e in all_els if e.get("interactive")}
        
        # Логируем статистику для отладки (один раз!)
        total_visible = sum(1 for e in all_els if e.get("visible"))
        total_interactive = len(interactive_ids)
        self._log(f"  📊 DOM статистика: всего={len(all_els)}, видимых={total_visible}, интерактивных={total_interactive}")

        # === ДЕДУПЛИКАЦИЯ: отслеживаем уникальные координаты ===
        seen_coords: set[tuple[int, int]] = set()
        coord_tolerance = 5  # пикселей — считаем одной точкой
        
        def has_valid_coords(el: dict) -> bool:
            """Проверить что координаты валидны (не нулевые и не слишком близко к краю)."""
            cx, cy = el.get("cx", 0), el.get("cy", 0)
            # Отбрасываем нулевые или почти нулевые координаты
            if cx <= 5 or cy <= 5:
                return False
            return True
        
        def is_duplicate_coords(el: dict) -> bool:
            """Проверить что координаты уже встречались (с допуском)."""
            cx, cy = el.get("cx", 0), el.get("cy", 0)
            
            # Округляем до сетки tolerance
            grid_x = cx // coord_tolerance
            grid_y = cy // coord_tolerance
            key = (grid_x, grid_y)
            
            if key in seen_coords:
                return True
            seen_coords.add(key)
            return False
            
            # Округляем до сетки tolerance
            grid_x = cx // coord_tolerance
            grid_y = cy // coord_tolerance
            key = (grid_x, grid_y)
            
            if key in seen_coords:
                return True
            seen_coords.add(key)
            return False
        
        for el in all_els:
            w, h = el.get("w", 0), el.get("h", 0)
            is_interactive = el.get("interactive", False)
            tag = el.get("tag", "")
            
            # === ФИЛЬТР 0: Координаты ===
            if not has_valid_coords(el):
                continue  # нулевые координаты — не кликабельно
            
            # === ФИЛЬТР 1: Размеры ===
            if not is_interactive and (w <= 2 or h <= 2):
                continue  # слишком маленькие элементы — мусор
            if w < 0 or h < 0:
                continue
            
            # === ФИЛЬТР 2: Только видимые на экране ===
            cx, cy = el.get("cx", 0), el.get("cy", 0)
            viewport_w = meta.get("viewportW", 1280)
            viewport_h = meta.get("viewportH", 900)
            
            # Элемент должен быть в пределах viewport + небольшой отступ
            margin = 100
            if not (-margin <= cx <= viewport_w + margin and -margin <= cy <= viewport_h + margin):
                continue  # вне экрана — не нужен
            
            # === ФИЛЬТР 3: Интерактивные — с дедупликацией ===
            if is_interactive:
                # Пропускаем дубликаты координат
                if is_duplicate_coords(el):
                    continue
                
                compact = self._compact_el(el)
                
                # Дополнительный фильтр: интерактивный без текста/placeholder/aria — возможно мусор
                has_meaning = (
                    compact.get("text") or 
                    compact.get("ph") or 
                    compact.get("ariaLabel") or
                    compact.get("value") or
                    compact.get("href") or
                    compact.get("elId") or
                    compact.get("name")
                )
                if not has_meaning and tag in ("div", "span", "section"):
                    continue  # пустые контейнеры — пропускаем
                
                filtered.append(compact)
                interactive.append(compact)
                continue
            
            # === ФИЛЬТР 4: Не-интерактивные — только важные ===
            if el.get("id") in interactive_ids:
                continue  # дочерний интерактивного — пропускаем
            
            # Только крупные изображения
            if tag in ("img", "picture", "canvas") and w >= 32 and h >= 32:
                filtered.append(self._compact_el(el))
                continue
            
            # Заголовки — всегда важны
            if tag in ("h1", "h2", "h3"):
                filtered.append(self._compact_el(el))
                continue
            
            # Крупные контейнеры (но не слишком много)
            if tag in ("div", "section", "main", "form", "nav", "header", "footer", "article") \
                    and w >= 100 and h >= 100 and len(filtered) < max_elements // 2:
                filtered.append(self._compact_el(el))
                continue
            
            # Параграфы с текстом (но не все подряд)
            if tag in ("p", "span") and el.get("text") and len(filtered) < max_elements // 3:
                # Ограничиваем количество текстовых блоков
                filtered.append(self._compact_el(el))
                continue

            if el.get("id") in interactive_ids:
                continue  # дочерний интерактивного

            if el.get("isImage") and el.get("w", 0) >= 16 and el.get("h", 0) >= 16:
                filtered.append(self._compact_el(el))
                continue

            if tag in ("h1", "h2", "h3", "h4"):
                filtered.append(self._compact_el(el))
                continue

            if tag in ("div", "section", "main", "form", "nav", "header", "footer") \
                    and el.get("w", 0) >= M and el.get("h", 0) >= M:
                filtered.append(self._compact_el(el))
                continue

        # Ограничиваем количество
        filtered    = filtered[:max_elements]
        interactive = interactive[:max_elements]

        # ── Шаг 3: Текстовое представление для промпта ─────────────────
        lines = [
            f"URL:{meta.get('url', '?')[:60]}",
            f"Title:{meta.get('title', '?')[:50]}",
            f"Viewport:{meta.get('viewportW', 0)}x{meta.get('viewportH', 0)}",
            f"Elements:{len(all_els)}→{len(filtered)}(i:{len(interactive)})",
            "",
            "===INTERACTIVE:cx,cy|tag|text/ph/aria===",
        ]
        
        # Сортируем интерактивные по важности (сверху-вниз, слева-направо)
        interactive_sorted = sorted(interactive, key=lambda e: (e.get("cy", 0), e.get("cx", 0)))
        
        for el in interactive_sorted[:50]:  # хард-лимит 50 интерактивных
            parts = []
            cx, cy = el.get("cx", 0), el.get("cy", 0)
            parts.append(f"{cx},{cy}")
            
            tag = el.get("tag", "")
            if el.get("interactive"):
                parts.append(f"{tag}*")  # * = интерактивный
            else:
                parts.append(tag)
            
            # Текстовое описание — компактно
            desc_parts = []
            if el.get("t"):  
                t = el["t"].replace("|", "/").replace("\n", " ")  # эскейпим разделители
                desc_parts.append(f'"{t}"')
            if el.get("ph"):  
                desc_parts.append(f"ph:{el['ph']}")
            if el.get("aria"):  
                desc_parts.append(f"a:{el['aria']}")
            if el.get("name"):
                desc_parts.append(f"n:{el['name']}")
            if el.get("type") and el["type"] not in ("text", "button"):
                desc_parts.append(f"t:{el['type']}")
            if el.get("href"):
                h = el["href"][:25]
                desc_parts.append(f"→{h}")
            
            if desc_parts:
                parts.append("|".join(desc_parts))
            
            lines.append(" ".join(parts))
        
        # Не-интерактивные — только если есть место и они важные
        other = [e for e in filtered if not e.get("interactive")]
        if other and len(lines) < 80:
            lines.append("")
            lines.append("===OTHER:h1-h3,img,form===")
            for el in other[:20]:  # максимум 20 других
                tag = el.get("tag", "")
                if tag not in ("h1", "h2", "h3", "img", "form", "nav"):
                    continue
                cx, cy = el.get("cx", 0), el.get("cy", 0)
                t = el.get("t", "")[:30]
                lines.append(f"{cx},{cy}|{tag}|{t}")

        if len(filtered) > len(interactive):
            lines += ["", "=== OTHER VISIBLE ELEMENTS ==="]
            for el in filtered:
                if el.get("interactive"):
                    continue
                desc = f"[{el['id']}] {el['tag']} ({el.get('x', 0)},{el.get('y', 0)}) {el.get('w', 0)}x{el.get('h', 0)}"
                if el.get("text"):  desc += f" | {el['text'][:80]}"
                lines.append(desc)

        dom_text = "\n".join(lines)

        return {
            "meta":        meta,
            "elements":    filtered,
            "interactive": interactive,
            "dom_text":    dom_text,
        }

    def _compact_el(self, el: dict) -> dict:
        """Компактный словарь элемента для AI — только критически важное."""
        c = {}
        
        # 0. ID — обязательно для ссылок на элемент
        c["id"] = el.get("id", 0)
        
        # 1. Координаты центра — самое главное для кликов
        cx, cy = el.get("cx", 0), el.get("cy", 0)
        if cx > 0 or cy > 0:
            c["cx"] = cx
            c["cy"] = cy
        
        # 2. Тег и интерактивность
        tag = el.get("tag", "")
        c["tag"] = tag
        if el.get("interactive"):
            c["i"] = True  # сокращаем для компактности
        
        # 3. Размеры (только если крупный)
        w, h = el.get("w", 0), el.get("h", 0)
        if w > 50 or h > 50:
            c["w"] = w
            c["h"] = h
        
        # 4. Текстовое содержимое — сильно обрезаем
        text = el.get("text", "").strip()
        if text:
            # Для кнопок/ссылок — больше текста, для div — меньше
            limit = 40 if tag in ("button", "a", "label", "span") else 25
            c["t"] = text[:limit]  # "t" вместо "text"
        
        # 5. Placeholder/aria-label — ключевые для поиска полей ввода
        ph = el.get("ph", "").strip()
        if ph:
            c["ph"] = ph[:30]
        
        aria = el.get("ariaLabel", "").strip()
        if aria:
            c["aria"] = aria[:30]
        
        # 6. Value — для input/select
        val = el.get("value", "").strip()
        if val and len(val) < 50:
            c["val"] = val[:30]
        
        # 7. ID/name — для идентификации
        el_id = el.get("elId", "")
        if el_id:
            c["id"] = el_id[:20]
        
        name = el.get("name", "")
        if name:
            c["name"] = name[:20]
        
        # 8. Href — только для ссылок
        if tag == "a":
            href = el.get("href", "")
            if href and not href.startswith("javascript"):
                c["href"] = href[:40]
        
        # 9. Type — для input
        typ = el.get("type", "")
        if typ and tag == "input":
            c["type"] = typ
        
        # 10. Role — если отличается от тега
        role = el.get("role", "")
        if role and role != tag:
            c["role"] = role
        
        # 11. Состояния — только если true
        if el.get("disabled"):
            c["dis"] = True
        if el.get("checked"):
            c["chk"] = True
        
        return c
        
    def get_element_at_position(self, x: int, y: int) -> dict | None:
        """Получить элемент по координатам (для верификации клика)."""
        if not self._driver:
            return None
            
        try:
            return self._driver.execute_script("""
                const el = document.elementFromPoint(arguments[0], arguments[1]);
                if (!el) return null;
                
                const rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName.toLowerCase(),
                    text: (el.textContent || '').trim().slice(0, 50),
                    x: Math.round(rect.left + rect.width / 2),
                    y: Math.round(rect.top + rect.height / 2),
                    dataAiId: el.getAttribute('data-ai-id') || ''
                };
            """, x, y)
        except Exception as e:
            self._log(f"⚠️ Ошибка get_element_at_position: {e}")
            return None
    
    def verify_click_position(self, target_x: int, target_y: int, 
                              expected_element_id: str = "",
                              tolerance: int = 5) -> tuple[bool, str]:
        """
        Верификация что клик попал туда куда нужно.
        Возвращает (успех, сообщение)
        """
        # Проверяем что по координатам есть элемент
        element_at_pos = self.get_element_at_position(target_x, target_y)
        
        if not element_at_pos:
            return False, f"Нет элемента по координатам ({target_x}, {target_y})"
        
        # Если передан ID ожидаемого элемента — проверяем совпадение
        if expected_element_id and element_at_pos.get('dataAiId') != expected_element_id:
            return False, (f"Клик попал не в тот элемент: ожидался {expected_element_id}, "
                          f"получен {element_at_pos.get('dataAiId', 'unknown')} "
                          f"(тег: {element_at_pos.get('tag')}, текст: {element_at_pos.get('text', 'пусто')})")
        
        # Проверяем что элемент не сдвинулся (сравниваем с записанной позицией)
        if expected_element_id:
            current_pos = self._driver.execute_script("""
                const el = document.querySelector('[data-ai-id="' + arguments[0] + '"]');
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {
                    x: Math.round(rect.left + rect.width / 2),
                    y: Math.round(rect.top + rect.height / 2)
                };
            """, expected_element_id)
            
            if current_pos:
                dx = abs(current_pos['x'] - target_x)
                dy = abs(current_pos['y'] - target_y)
                
                if dx > tolerance or dy > tolerance:
                    return False, (f"Элемент сдвинулся! Ожидалось ({target_x}, {target_y}), "
                                  f"текущая позиция ({current_pos['x']}, {current_pos['y']}), "
                                  f"сдвиг ({dx}, {dy})")
        
        return True, f"✅ Клик верифицирован: {element_at_pos.get('tag')} '{element_at_pos.get('text', '')[:30]}'"
    
    def get_screenshot_base64(self, scale: float = 1.0) -> str:
        """Получить скриншот как base64 PNG (потокобезопасно)."""
        try:
            png = b""
            if self._driver:
                # ═══ Блокировка чтобы не конфликтовать с рабочими потоками ═══
                acquired = self._driver_lock.acquire(timeout=2)
                if not acquired:
                    return ""  # Драйвер занят — пропускаем скриншот
                try:
                    import base64
                    png = self._driver.get_screenshot_as_png()
                finally:
                    self._driver_lock.release()
            elif self._page:
                import asyncio, base64
                png = asyncio.get_event_loop().run_until_complete(self._page.screenshot())
            if not png:
                return ""
            if scale < 1.0:
                png = _scale_png_bytes(png, scale)
            return base64.b64encode(png).decode()
        except Exception:
            return ""

    def _scale_png(self, png_bytes: bytes, scale: float) -> bytes:
        """Обёртка для обратной совместимости."""
        return _scale_png_bytes(png_bytes, scale)

    def compare_screenshots(self, before_b64: str, after_b64: str,
                             threshold: float = 0.05) -> tuple[bool, float]:
        """
        Сравнить два скриншота (base64 PNG). 
        Возвращает (изменилось, доля_изменённых_пикселей).
        Работает без PIL — через простое побайтное сравнение.
        """
        try:
            import base64
            b_bytes = base64.b64decode(before_b64)
            a_bytes = base64.b64decode(after_b64)
            min_len = min(len(b_bytes), len(a_bytes))
            if min_len == 0:
                return False, 0.0
            diff = sum(1 for x, y in zip(b_bytes[:min_len], a_bytes[:min_len]) if x != y)
            ratio = diff / min_len
            return ratio >= threshold, ratio
        except Exception:
            return False, 0.0


# ══════════════════════════════════════════════════════════
#  BROWSER MANAGER (синглтон)
# ══════════════════════════════════════════════════════════

class BrowserManager(QObject):
    """
    Менеджер браузерных инстансов.
    Синглтон — один на всё приложение.
    """
    instance_launched = pyqtSignal(str)   # instance_id
    instance_closed = pyqtSignal(str)     # instance_id
    log_signal = pyqtSignal(str)

    _instance: Optional[BrowserManager] = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._instances: dict[str, BrowserInstance] = {}

    @classmethod
    def get(cls) -> BrowserManager:
        if cls._instance is None:
            cls._instance = BrowserManager()
        return cls._instance

    def launch(self, profile: BrowserProfile,
               proxy: BrowserProxy,
               embed_target: Optional[QWidget] = None,
               start_in_tray: bool = False) -> Optional[BrowserInstance]:
        """Запустить новый инстанс браузера."""
        iid = str(uuid.uuid4())[:8]
        self.log_signal.emit(f"🔧 Создание инстанса {iid}...")
        
        # Определяем режим запуска ДО создания инстанса
        _launch_for_tray = start_in_tray and not embed_target and not profile.headless
        
        if _launch_for_tray:
            self.log_signal.emit("📌 Режим трей-панели: старт за пределами экрана")
        else:
            self.log_signal.emit(f"   → Обычный старт (трей отменён: start_in_tray={start_in_tray}, embed={embed_target is not None}, headless={profile.headless})")

        # Создание инстанса перенесено СЮДА, после блока if-else
        inst = BrowserInstance(iid, profile, proxy, launch_for_tray=_launch_for_tray)
        inst.log_signal.connect(self.log_signal)
        # Флаг _launch_for_tray теперь передаётся через profile.headless или отдельный параметр конструктора
        
        self.log_signal.emit(f"🚀 Запуск движка (headless={profile.headless})...")
        if inst.launch():
            self._instances[iid] = inst
            self.log_signal.emit(f"✅ Движок запущен, ID: {iid}")
            inst._launched_with_tray = not bool(embed_target)
            
            if embed_target:
                self.log_signal.emit("⏳ Автовстраивание через 500мс...")
                QTimer.singleShot(500, lambda: self._try_embed(inst, embed_target))
            else:
                self.log_signal.emit("⏳ Скрытие окна в трей (ожидание появления)...")
                QTimer.singleShot(500, lambda: self._try_minimize_to_tray(inst))
                
            self.instance_launched.emit(iid)
            self.log_signal.emit(f"✅ Инстанс {iid} полностью готов ({profile.name})")
            
            tray = BrowserTrayManager.get(self)
            if tray:
                tray.refresh()
                tray.notify("🌐 Браузер запущен",
                            f"[{iid}] {profile.name}\nДважды кликните на иконке трея чтобы показать")
            return inst
        else:
            self.log_signal.emit(f"❌ Не удалось запустить инстанс {iid}")
            return None

    def _try_minimize_to_tray(self, inst: BrowserInstance, attempt: int = 1):
        """Попытаться скрыть окно в трей с повторными попытками (ожидаем появления окна)."""
        max_attempts = 10
        if not inst.is_running or inst.profile.headless:
            return
            
        # inst.minimize_window() возвращает True только когда находит HWND и успешно скрывает его
        if inst.minimize_window():
            self.log_signal.emit(f"✅ Браузер [{inst.instance_id}] успешно скрыт в трей")
        elif attempt < max_attempts:
            QTimer.singleShot(500, lambda: self._try_minimize_to_tray(inst, attempt + 1))
        else:
            self.log_signal.emit(f"⚠️ Не удалось скрыть браузер [{inst.instance_id}] в трей после {max_attempts} попыток")

    def _try_minimize_to_tray(self, inst: BrowserInstance, attempt: int = 1):
        """Отложенное скрытие окна браузера в трей."""
        # ═══ Если стартовали за пределами экрана — просто показываем в трее ═══
        if getattr(inst, '_launch_for_tray', False):
            self.log_signal.emit(f"✅ Браузер [{inst.instance_id}] уже стартовал невидимым (трей-режим)")
            inst._minimized_to_tray = True
            
            # Окно уже за пределами экрана (-32000,-32000) — только SW_HIDE, без show_window
            inst.minimize_window()
            
            tray = BrowserTrayManager.get(self)
            if tray:
                tray.refresh()

            # Принудительно перерисовываем все Qt-окна после скрытия Chrome,
            # иначе WM_ERASEBKGND от Windows оставляет пустой артефакт в конструкторе
            from PyQt6.QtWidgets import QApplication
            QTimer.singleShot(150, lambda: [
                w.update() for w in QApplication.topLevelWidgets() if w.isVisible()
            ])
            return
        
        # Fallback: старая логика для случаев без флага
        max_attempts = 20
        
        # ✅ Проверяем что инстанс всё ещё существует и запущен
        if not inst or not inst.is_running or inst.profile.headless:
            return
        
        # ✅ Проверяем что инстанс всё ещё в нашем менеджере
        if inst.instance_id not in self._instances:
            return

        # ✅ Если браузер уже встроен в виджет — сворачивать в трей не нужно
        if getattr(inst, '_embedded_hwnd', None):
            return
        
        if inst.minimize_window():
            self.log_signal.emit(f"✅ Браузер [{inst.instance_id}] успешно скрыт в трей")
            # ✅ Сохраняем флаг что окно в трее
            inst._minimized_to_tray = True
        elif attempt < max_attempts:
            # ✅ Проверяем условия перед повторной попыткой
            if inst.is_running and inst.instance_id in self._instances:
                QTimer.singleShot(500, lambda: self._try_minimize_to_tray(inst, attempt + 1))
        else:
            self.log_signal.emit(f"⚠️ Не удалось скрыть браузер [{inst.instance_id}] в трей")

    def _try_embed(self, inst: BrowserInstance, target: QWidget, attempt: int = 1):
        """Попытаться встроить браузер с повторными попытками."""
        max_attempts = 5
        self.log_signal.emit(f"⬇️ Попытка встраивания {attempt}/{max_attempts}...")
        
        if not inst.is_running:
            self.log_signal.emit("⚠️ Инстанс не запущен, отмена встраивания")
            return
        
        # Очищаем placeholder перед встраиванием
        if hasattr(target, 'layout') and target.layout():
            while target.layout().count():
                item = target.layout().takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
        
        embedded = inst.embed_into_widget(target)
        if embedded:
            self.log_signal.emit("✅ Встраивание успешно!")
        elif attempt < max_attempts:
            self.log_signal.emit(f"⏳ Не удалось, повтор через 500мс...")
            # Повторная попытка через 500мс
            QTimer.singleShot(500, lambda: self._try_embed(inst, target, attempt + 1))
        else:
            self.log_signal.emit("❌ Встраивание не удалось после всех попыток")

    def get_instance(self, iid: str) -> Optional[BrowserInstance]:
        return self._instances.get(iid)

    def all_instances(self) -> dict[str, BrowserInstance]:
        return dict(self._instances)

    def close_instance(self, iid: str):
        inst = self._instances.pop(iid, None)
        if inst:
            # ✅ Убираем из трея перед закрытием
            tray = BrowserTrayManager.get()
            if tray and hasattr(tray, '_managed_windows'):
                # Удаляем окно из управления треем
                inst._minimized_to_tray = False
                # Показываем окно перед закрытием, чтобы оно не зависло скрытым
                if hasattr(inst, 'show_window'):
                    inst.show_window()
            inst.close()
            self.instance_closed.emit(iid)
        
        # ✅ Обновляем трей после закрытия
        tray = BrowserTrayManager.get()
        if tray:
            tray.refresh()

    def close_all(self):
        for iid in list(self._instances.keys()):
            self.close_instance(iid)


# ══════════════════════════════════════════════════════════
#  BROWSER TRAY MANAGER
# ══════════════════════════════════════════════════════════

# ПОСЛЕ
class BrowserTrayManager(QObject):
    """
    Системный трей для управления несколькими браузерными инстансами.
    Синглтон — создаётся при первом запуске браузера.
    """
    _instance: Optional['BrowserTrayManager'] = None

    def __init__(self, browser_manager: 'BrowserManager', parent=None):
        super().__init__(parent)
        self._bms: list = [browser_manager]   # список менеджеров всех проектов
        self._tray: Optional[QSystemTrayIcon] = None
        self._setup_tray()

    @classmethod
    def get(cls, browser_manager: Optional['BrowserManager'] = None) -> Optional['BrowserTrayManager']:
        if cls._instance is None and browser_manager is not None:
            cls._instance = BrowserTrayManager(browser_manager)
        elif cls._instance is not None and browser_manager is not None:
            # регистрируем менеджер нового проекта, не ломая старые
            if browser_manager not in cls._instance._bms:
                cls._instance._bms.append(browser_manager)
        return cls._instance

    @classmethod
    def get_instance(cls, browser_manager=None):
        """Псевдоним для совместимости с вызовами из BrowserManager."""
        return cls.get(browser_manager)

    def _make_icon(self) -> 'QIcon':
        """Нарисовать иконку глобуса 16×16."""
        from PyQt6.QtGui import QPainter, QBrush, QPen, QIcon, QPixmap, QColor
        px = QPixmap(16, 16)
        px.fill(QColor(0, 0, 0, 0))
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor("#43AEFF")))
        p.setPen(QPen(QColor("#1A6BBF"), 1))
        p.drawEllipse(1, 1, 14, 14)
        p.setPen(QPen(QColor("#FFFFFF"), 1))
        p.drawLine(1, 8, 15, 8)          # горизонталь
        p.drawArc(4, 1, 8, 14, 0, 5760)  # меридиан
        p.end()
        return QIcon(px)

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(self._make_icon())
        self._tray.setToolTip("🌐 Браузеры — нет запущенных")
        self._tray.activated.connect(self._on_activated)
        self._rebuild_menu()
        self._tray.show()

    _MENU_STYLE = """
        QMenu {
            background: #0E1117;
            color: #CDD6F4;
            border: 1px solid #2E3148;
            border-radius: 8px;
            padding: 4px 0;
            font-size: 12px;
        }
        QMenu::item {
            padding: 6px 22px 6px 14px;
            border-radius: 4px;
            min-width: 220px;
        }
        QMenu::item:selected { background: #1A1D2E; color: #7AA2F7; }
        QMenu::item:disabled { color: #565f89; }
        QMenu::separator { height: 1px; background: #2E3148; margin: 3px 10px; }
    """

    def _rebuild_menu(self):
        if not self._tray:
            return
        menu = QMenu()
        menu.setStyleSheet(self._MENU_STYLE)
        instances = {}
        for bm in self._bms:
            instances.update(bm.all_instances())

        if not instances:
            a = menu.addAction("🌐  Нет запущенных браузеров")
            a.setEnabled(False)
        else:
            hdr = menu.addAction(f"🌐  Браузеры   ({len(instances)} запущено)")
            hdr.setEnabled(False)
            menu.addSeparator()

            for iid, inst in instances.items():
                status = "🟢" if inst.is_running else "🔴"
                url_short = (inst.current_url[:40] + "…") if len(inst.current_url) > 40 else (inst.current_url or "—")
                sub = menu.addMenu(f"{status}  [{iid}]  {inst.profile.name}")
                sub.setStyleSheet(self._MENU_STYLE)

                url_act = sub.addAction(f"   {url_short}")
                url_act.setEnabled(False)
                sub.addSeparator()

                act_show = sub.addAction("👁  Показать окно")
                act_show.triggered.connect(lambda _checked, i=inst: i.show_window())

                act_min = sub.addAction("📌  Свернуть")
                act_min.triggered.connect(lambda _checked, i=inst: i.minimize_window())

                sub.addSeparator()

                act_close = sub.addAction("✖  Закрыть браузер")
                act_close.triggered.connect(lambda _checked, i=iid: self._close_one(i))

        menu.addSeparator()
        act_grid = menu.addAction("🔲  Сводка всех браузеров")
        act_grid.triggered.connect(self._open_global_grid)
        act_all_show = menu.addAction("👁  Показать все")
        act_all_show.triggered.connect(self._show_all)
        act_all_hide = menu.addAction("📌  Скрыть все в трей")
        act_all_hide.triggered.connect(self._hide_all)
        act_all_close = menu.addAction("✖  Закрыть все")
        act_all_close.triggered.connect(self._close_all)
        menu.addSeparator()
        act_hide_tray = menu.addAction("⏻  Убрать иконку из трея")
        act_hide_tray.triggered.connect(self.hide_tray)

        self._tray.setContextMenu(menu)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        self._rebuild_menu()
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_all()

    def _show_all(self):
        for bm in self._bms:
            for inst in bm.all_instances().values():
                inst.show_window()

    def _close_one(self, iid: str):
        for bm in self._bms:
            if bm.get_instance(iid):
                bm.close_instance(iid)
                break
        self.refresh()

    def _close_all(self):
        for bm in self._bms:
            bm.close_all()
        self.refresh()

    def _hide_all(self):
        for bm in self._bms:
            for inst in bm.all_instances().values():
                inst.minimize_window()
                inst._minimized_to_tray = True
        self.refresh()

    def _open_global_grid(self):
        """Открыть окно сводки всех инстансов."""
        all_instances = {}
        for bm in self._bms:
            all_instances.update(bm.all_instances())
        dlg = GlobalBrowserGridDialog(all_instances, self._bms)
        dlg.exec()

    def notify(self, title: str, msg: str):
        if self._tray:
            self._tray.showMessage(title, msg,
                QSystemTrayIcon.MessageIcon.Information, 3000)

    def refresh(self):
        """Вызывать при запуске/закрытии инстанса."""
        self._rebuild_menu()
        if self._tray:
            n = sum(len(bm.all_instances()) for bm in self._bms)
            tip = f"🌐 Браузеры: {n} запущено" if n else "🌐 Браузеры: нет запущенных"
            self._tray.setToolTip(tip)

    def hide_tray(self):
        if self._tray:
            self._tray.hide()


# ══════════════════════════════════════════════════════════
#  GLOBAL BROWSER GRID DIALOG — сводка всех инстансов
# ══════════════════════════════════════════════════════════

class GlobalBrowserGridDialog(QDialog):
    """Красивое окно-сетка всех открытых браузерных инстансов по всем проектам."""

    _CARD_W = 420
    _CARD_H = 310
    _THUMB_H = 160

    def __init__(self, instances: dict, bms: list, parent=None):
        super().__init__(parent)
        self._instances = instances
        self._bms = bms
        self._card_widgets: dict[str, QFrame] = {}   # iid → card
        self.setWindowTitle("🌐 Все открытые браузеры")
        self.resize(1100, 680)
        self.setMinimumSize(700, 460)
        bg0  = get_color("bg0")
        bg1  = get_color("bg1")
        bg3  = get_color("bg3")
        bd   = get_color("bd")
        tx0  = get_color("tx0")
        ac   = get_color("ac")
        ok   = get_color("ok")
        err  = get_color("err")
        warn = get_color("warn")
        self.setStyleSheet(f"""
            QDialog {{ background: {bg0}; color: {tx0}; }}
            QLabel  {{ color: {tx0}; }}
            QLineEdit {{
                background: {bg1}; color: {tx0};
                border: 1px solid {bd}; border-radius: 5px;
                padding: 3px 7px; font-size: 11px;
            }}
            QPushButton {{
                background: {bg3}; color: {tx0};
                border: 1px solid {bd}; border-radius: 6px;
                padding: 4px 11px; font-size: 11px;
            }}
            QPushButton:hover  {{ background: {bd}; color: {ac}; border-color: {ac}; }}
            QPushButton:pressed{{ background: {bg1}; }}
            QPushButton#act    {{ background: {bg1}; color: {ok}; border-color: {ok}; }}
            QPushButton#act:hover{{ color: #b8e08a; }}
            QPushButton#warn   {{ background: {bg1}; color: {warn}; border-color: {warn}; }}
            QPushButton#warn:hover{{ background: {bg3}; }}
            QPushButton#danger {{ background: {bg1}; color: {err}; border-color: {err}; }}
            QPushButton#danger:hover{{ background: {bg3}; }}
            QPushButton#sm {{
                padding: 3px 8px; font-size: 10px;
                border-radius: 4px; min-width: 0;
            }}
            QFrame#card {{
                background: {bg1};
                border: 1px solid {bd};
                border-radius: 12px;
            }}
            QFrame#card:hover {{ border-color: {ac}; }}
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{
                background: {bg0}; width: 7px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {bd}; border-radius: 3px; min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {ac}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
        """)
        self._build_ui()
        # Авто-обновление каждые 4 секунды
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._live_refresh)
        self._refresh_timer.start(4000)

    def closeEvent(self, event):
        self._refresh_timer.stop()
        super().closeEvent(event)

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # ── Шапка ──────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        self._lbl_count = QLabel()
        self._lbl_count.setStyleSheet("font-size: 16px; font-weight: bold; color: #CDD6F4;")
        self._update_count_label()
        hdr.addWidget(self._lbl_count)
        hdr.addSpacing(12)

        # Поиск / фильтр
        self._fld_search = QLineEdit()
        self._fld_search.setPlaceholderText("🔍 Фильтр по ID, профилю, URL…")
        self._fld_search.setFixedWidth(240)
        self._fld_search.textChanged.connect(self._populate_grid)
        hdr.addWidget(self._fld_search)
        hdr.addStretch()

        # Кнопки «все»
        for txt, obj, slot in [
            ("👁 Показать все",  "",       self._show_all),
            ("📌 Скрыть все",    "",       self._hide_all),
            ("🔄 Обновить скрины","warn",  self._refresh_all_screens),
            ("✖ Закрыть все",   "danger", self._close_all),
        ]:
            b = QPushButton(txt)
            if obj:
                b.setObjectName(obj)
            b.clicked.connect(slot)
            hdr.addWidget(b)

        root.addLayout(hdr)

        # ── Разделитель ────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2E3148;")
        root.addWidget(sep)

        # ── Скролл-сетка ───────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._grid = QVBoxLayout(self._container)
        self._grid.setSpacing(12)
        self._grid.setContentsMargins(0, 4, 0, 4)
        self._populate_grid()
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, stretch=1)

        # ── Статусбар ──────────────────────────────────────
        self._lbl_status = QLabel("● Авто-обновление каждые 4 сек")
        self._lbl_status.setStyleSheet("font-size: 10px; color: #565f89; padding: 2px 0;")
        footer = QHBoxLayout()
        footer.addWidget(self._lbl_status)
        footer.addStretch()
        btn_ok = QPushButton("Закрыть")
        btn_ok.clicked.connect(self.accept)
        footer.addWidget(btn_ok)
        root.addLayout(footer)

    # ── Наполнение сетки ──────────────────────────────────

    def _filtered_instances(self) -> dict:
        q = self._fld_search.text().strip().lower() if hasattr(self, '_fld_search') else ""
        if not q:
            return self._instances
        return {
            iid: inst for iid, inst in self._instances.items()
            if q in iid.lower()
            or q in inst.profile.name.lower()
            or q in (inst.current_url or "").lower()
        }

    def _update_count_label(self):
        n = len(self._instances)
        running = sum(1 for i in self._instances.values() if i.is_running)
        self._lbl_count.setText(
            f"🌐 Браузеров: <b>{n}</b>  <span style='color:#9ECE6A;'>▶ {running} активных</span>"
        )

    def _populate_grid(self):
        # Чистим старые карточки
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.layout():
                while item.layout().count():
                    c = item.layout().takeAt(0)
                    if c.widget():
                        c.widget().deleteLater()
            elif item.widget():
                item.widget().deleteLater()
        self._card_widgets.clear()

        filtered = self._filtered_instances()
        self._update_count_label()

        if not filtered:
            lbl = QLabel("Нет браузеров" if not self._instances else "Ничего не найдено")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #565f89; font-size: 14px; padding: 60px;")
            self._grid.addWidget(lbl)
            self._grid.addStretch()
            return

        COLS = 3
        row_layout = None
        for idx, (iid, inst) in enumerate(filtered.items()):
            if idx % COLS == 0:
                row_layout = QHBoxLayout()
                row_layout.setSpacing(12)
                self._grid.addLayout(row_layout)
            card = self._make_card(iid, inst)
            self._card_widgets[iid] = card
            row_layout.addWidget(card)

        # Добить пустышками чтобы карточки не растягивались
        remainder = len(filtered) % COLS
        if remainder and row_layout:
            for _ in range(COLS - remainder):
                spacer = QWidget()
                spacer.setFixedSize(self._CARD_W, self._CARD_H)
                spacer.setStyleSheet("background: transparent;")
                row_layout.addWidget(spacer)

        self._grid.addStretch()

    def _make_card(self, iid: str, inst) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setFixedSize(self._CARD_W, self._CARD_H)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        # ── Строка 1: статус-дот + ID + профиль + [закрыть] ──
        top = QHBoxLayout()
        top.setSpacing(6)
        is_running = inst.is_running
        is_hidden  = getattr(inst, '_minimized_to_tray', False)
        dot_color  = "#9ECE6A" if is_running else "#F7768E"
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {dot_color}; font-size: 14px;")
        dot.setFixedWidth(16)
        top.addWidget(dot)

        lbl_name = QLabel(f"<b>[{iid}]</b> {inst.profile.name}")
        lbl_name.setStyleSheet("font-size: 11px;")
        top.addWidget(lbl_name, stretch=1)

        badge_color = "#2A2A40" if not is_hidden else "#1A1A1A"
        badge_text  = "👁 видим" if not is_hidden else "📌 в трее"
        badge = QLabel(badge_text)
        badge.setStyleSheet(
            f"background:{badge_color}; color:#A9B1D6; border:1px solid #2E3148;"
            f"border-radius:4px; font-size:9px; padding:1px 5px;"
        )
        top.addWidget(badge)

        btn_x = QPushButton("✕")
        btn_x.setObjectName("danger sm")
        btn_x.setFixedSize(22, 22)
        btn_x.setToolTip("Закрыть браузер")
        btn_x.clicked.connect(lambda _, i=iid: self._close_one(i))
        top.addWidget(btn_x)
        lay.addLayout(top)

        # ── Превью (скриншот) ──────────────────────────────
        lbl_thumb = QLabel()
        lbl_thumb.setFixedSize(self._CARD_W - 20, self._THUMB_H)
        lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_thumb.setStyleSheet(
            "background: #07080C; border: 1px solid #1E2030; border-radius: 6px;"
        )
        lbl_thumb.setProperty("_iid", iid)
        lay.addWidget(lbl_thumb)
        # Загрузить скриншот асинхронно
        self._load_thumb(inst, lbl_thumb)

        # ── URL ────────────────────────────────────────────
        url = inst.current_url or "—"
        url_short = (url[:55] + "…") if len(url) > 55 else url
        lbl_url = QLabel(f"<span style='color:#565f89; font-size:10px;'>{url_short}</span>")
        lbl_url.setWordWrap(False)
        lbl_url.setToolTip(url)
        lay.addWidget(lbl_url)

        # ── Кнопки действий ────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(5)

        btn_show = QPushButton("👁 Показать")
        btn_show.setObjectName("act")
        btn_show.setFixedHeight(26)
        btn_show.clicked.connect(lambda _, i=inst: self._show_one(i))

        btn_hide = QPushButton("📌 В трей")
        btn_hide.setFixedHeight(26)
        btn_hide.clicked.connect(lambda _, i=inst: self._hide_one(i))

        btn_reload = QPushButton("🔄")
        btn_reload.setToolTip("Перезагрузить страницу")
        btn_reload.setFixedSize(28, 26)
        btn_reload.setObjectName("warn")
        btn_reload.clicked.connect(lambda _, i=inst: self._reload_one(i))

        btn_screen = QPushButton("📸")
        btn_screen.setToolTip("Обновить скриншот")
        btn_screen.setFixedSize(28, 26)
        btn_screen.clicked.connect(lambda _, i=inst, lbl=lbl_thumb: self._load_thumb(i, lbl))

        row1.addWidget(btn_show)
        row1.addWidget(btn_hide)
        row1.addStretch()
        row1.addWidget(btn_reload)
        row1.addWidget(btn_screen)
        lay.addLayout(row1)

        # ── Навигация ──────────────────────────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(5)
        nav_fld = QLineEdit()
        nav_fld.setPlaceholderText("https://…  (Enter — перейти)")
        nav_fld.setFixedHeight(24)
        nav_fld.returnPressed.connect(
            lambda i=inst, f=nav_fld: self._navigate_one(i, f.text())
        )
        btn_go = QPushButton("▶")
        btn_go.setFixedSize(28, 24)
        btn_go.setObjectName("act")
        btn_go.setToolTip("Перейти по URL")
        btn_go.clicked.connect(
            lambda _, i=inst, f=nav_fld: self._navigate_one(i, f.text())
        )
        row2.addWidget(nav_fld, stretch=1)
        row2.addWidget(btn_go)
        lay.addLayout(row2)

        return card

    # ── Утилиты ───────────────────────────────────────────

    def _load_thumb(self, inst, lbl: QLabel):
        """Захватить скриншот и показать в QLabel (потокобезопасно)."""
        try:
            if not inst or not inst.is_running:
                lbl.setText("⛔ не запущен")
                return
            # ═══ Только через get_screenshot_base64 (он использует _driver_lock) ═══
            b64 = inst.get_screenshot_base64(scale=0.28) if hasattr(inst, 'get_screenshot_base64') else None
            # НЕ обращаемся к inst._driver напрямую — это вызывает deadlock
            # с рабочими потоками которые тоже используют драйвер
            if b64:
                import base64 as _b64
                raw = _b64.b64decode(b64)
                raw = _scale_png_bytes(raw, 0.28)
                pix = QPixmap()
                pix.loadFromData(raw)
                if not pix.isNull():
                    pix = pix.scaled(
                        lbl.width(), lbl.height(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    lbl.setPixmap(pix)
                    return
        except Exception:
            pass
        lbl.setText("📷 нет превью")

    def _live_refresh(self):
        """Лёгкое обновление: только URL-метки и статус-точки в существующих карточках."""
        changed = False
        # Добавить/удалить карточки если изменился состав инстансов
        for bm in self._bms:
            for iid, inst in bm.all_instances().items():
                if iid not in self._instances:
                    self._instances[iid] = inst
                    changed = True
        dead = [iid for iid in self._instances if not any(
            bm.get_instance(iid) for bm in self._bms
        )]
        for iid in dead:
            self._instances.pop(iid, None)
            changed = True
        if changed:
            self._populate_grid()
            return
        self._update_count_label()
        self._lbl_status.setText(
            f"● Обновлено: {datetime.now().strftime('%H:%M:%S')}"
        )

    # ── Действия ──────────────────────────────────────────

    def _navigate_one(self, inst, url: str):
        url = url.strip()
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            if getattr(inst, '_driver', None):
                # ═══ Lock чтобы не конфликтовать с рабочими потоками ═══
                acquired = inst._driver_lock.acquire(timeout=3)
                if not acquired:
                    return
                try:
                    inst._driver.get(url)
                finally:
                    inst._driver_lock.release()
        except Exception:
            pass

    def _reload_one(self, inst):
        try:
            if getattr(inst, '_driver', None):
                acquired = inst._driver_lock.acquire(timeout=3)
                if not acquired:
                    return
                try:
                    inst._driver.refresh()
                finally:
                    inst._driver_lock.release()
        except Exception:
            pass

    def _refresh_all_screens(self):
        """Обновить скриншоты всех карточек."""
        for iid, card in self._card_widgets.items():
            inst = self._instances.get(iid)
            if not inst:
                continue
            # Найти QLabel с превью внутри карточки
            for child in card.findChildren(QLabel):
                if child.property("_iid") == iid:
                    self._load_thumb(inst, child)
                    break

    def _show_one(self, inst):
        inst.show_window()
        inst._minimized_to_tray = False
        self._populate_grid()

    def _hide_one(self, inst):
        inst.minimize_window()
        inst._minimized_to_tray = True
        self._populate_grid()

    def _close_one(self, iid: str):
        for bm in self._bms:
            if bm.get_instance(iid):
                bm.close_instance(iid)
                break
        self._instances.pop(iid, None)
        self._populate_grid()

    def _show_all(self):
        for inst in self._instances.values():
            inst.show_window()
            inst._minimized_to_tray = False
        self._populate_grid()

    def _hide_all(self):
        for inst in self._instances.values():
            inst.minimize_window()
            inst._minimized_to_tray = True
        self._populate_grid()

    def _close_all(self):
        for bm in self._bms:
            bm.close_all()
        self._instances.clear()
        self._populate_grid()

# ══════════════════════════════════════════════════════════
#  PROFILE MANAGER (загрузка/сохранение профилей)
# ══════════════════════════════════════════════════════════

class BrowserProfileManager:
    """Загрузка и сохранение профилей браузера на диск."""
    PROFILES_DIR = ".sherlock_versions/browser_profiles"

    def __init__(self, project_root: str = ""):
        self._root = Path(project_root) if project_root else Path.cwd()
        self._profiles: dict[str, BrowserProfile] = {}
        self._load_all()

    def _profiles_file(self) -> Path:
        return self._root / self.PROFILES_DIR / "profiles.json"

    def _load_all(self):
        f = self._profiles_file()
        if not f.exists():
            return
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for d in data:
                p = BrowserProfile.from_dict(d)
                self._profiles[p.id] = p
        except Exception as e:
            print(f"BrowserProfileManager load error: {e}")

    def save_all(self):
        f = self._profiles_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        data = [p.to_dict() for p in self._profiles.values()]
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def all_profiles(self) -> list[BrowserProfile]:
        return list(self._profiles.values())

    def get(self, pid: str) -> Optional[BrowserProfile]:
        return self._profiles.get(pid)

    def add_or_update(self, profile: BrowserProfile):
        self._profiles[profile.id] = profile
        self.save_all()

    def remove(self, pid: str):
        self._profiles.pop(pid, None)
        self.save_all()

    def set_root(self, root: str):
        self._root = Path(root)
        self._profiles.clear()
        self._load_all()


# ══════════════════════════════════════════════════════════
#  UI: BROWSER LAUNCH DIALOG
# ══════════════════════════════════════════════════════════

class BrowserLaunchDialog(QDialog):
    """
    Диалог запуска браузера.
    Позволяет выбрать/создать профиль и настроить прокси.
    """

    def __init__(self, profile_manager: BrowserProfileManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌐 Запуск браузера")
        self.resize(680, 540)
        self._pm = profile_manager
        self._selected_profile: Optional[BrowserProfile] = None
        self._proxy = BrowserProxy()
        self._build_ui()
        self._refresh_profiles()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # ── Вкладка «Профиль» ─────────────────────────────
        profile_tab = QWidget()
        pt_layout = QVBoxLayout(profile_tab)

        # Список профилей
        top_row = QHBoxLayout()
        self._lst_profiles = QListWidget()
        self._lst_profiles.currentRowChanged.connect(self._on_profile_selected)
        top_row.addWidget(self._lst_profiles, stretch=1)

        btn_col = QVBoxLayout()
        btn_new = QPushButton("➕ Создать")
        btn_new.clicked.connect(self._new_profile)
        btn_del = QPushButton("🗑 Удалить")
        btn_del.clicked.connect(self._delete_profile)
        btn_save = QPushButton("💾 Сохранить")
        btn_save.clicked.connect(self._save_profile)
        btn_col.addWidget(btn_new)
        btn_col.addWidget(btn_del)
        btn_col.addWidget(btn_save)
        btn_col.addStretch()
        top_row.addLayout(btn_col)
        pt_layout.addLayout(top_row, stretch=1)

        # Поля профиля
        form = QFormLayout()
        self._fld_pname = QLineEdit()
        form.addRow("Имя профиля:", self._fld_pname)

        folder_row = QHBoxLayout()
        self._fld_pfolder = QLineEdit()
        self._fld_pfolder.setPlaceholderText("Путь к папке профиля...")
        btn_browse = QPushButton("Обзор...")
        btn_browse.clicked.connect(self._browse_profile_folder)
        folder_row.addWidget(self._fld_pfolder)
        folder_row.addWidget(btn_browse)
        form.addRow("Папка профиля:", folder_row)

        self._chk_create_folder = QCheckBox("Создать папку, если не существует")
        self._chk_create_folder.setChecked(True)
        form.addRow("", self._chk_create_folder)

        self._fld_useragent = QLineEdit()
        self._fld_useragent.setPlaceholderText("Оставьте пустым для авто")
        form.addRow("User-Agent:", self._fld_useragent)

        size_row = QHBoxLayout()
        self._spn_w = QSpinBox()
        self._spn_w.setRange(800, 3840)
        self._spn_w.setValue(1280)
        self._spn_h = QSpinBox()
        self._spn_h.setRange(600, 2160)
        self._spn_h.setValue(900)
        size_row.addWidget(QLabel("Ш:"))
        size_row.addWidget(self._spn_w)
        size_row.addWidget(QLabel("В:"))
        size_row.addWidget(self._spn_h)
        form.addRow("Разрешение:", size_row)

        self._fld_timezone = QLineEdit()
        self._fld_timezone.setPlaceholderText("e.g. Europe/Kyiv")
        form.addRow("Часовой пояс:", self._fld_timezone)

        pt_layout.addLayout(form)
        tabs.addTab(profile_tab, "👤 Профиль")

        # ── Вкладка «Настройки» ───────────────────────────
        settings_tab = QWidget()
        st_layout = QFormLayout(settings_tab)

        self._chk_images = QCheckBox("Загружать картинки")
        self._chk_images.setChecked(True)
        st_layout.addRow(self._chk_images)

        self._chk_media = QCheckBox("Загружать медиа (video/audio)")
        self._chk_media.setChecked(True)
        st_layout.addRow(self._chk_media)

        self._chk_css = QCheckBox("Загружать CSS стили")
        self._chk_css.setChecked(True)
        st_layout.addRow(self._chk_css)

        self._chk_frames = QCheckBox("Загружать фреймы")
        self._chk_frames.setChecked(True)
        st_layout.addRow(self._chk_frames)

        self._chk_js = QCheckBox("Включить JavaScript")
        self._chk_js.setChecked(True)
        st_layout.addRow(self._chk_js)

        self._chk_notif = QCheckBox("Блокировать уведомления браузера")
        self._chk_notif.setChecked(True)
        st_layout.addRow(self._chk_notif)

        self._chk_popups = QCheckBox("Блокировать всплывающие окна")
        st_layout.addRow(self._chk_popups)

        self._chk_canvas = QCheckBox("Эмулировать Canvas/WebGL")
        self._chk_canvas.setChecked(True)
        st_layout.addRow(self._chk_canvas)

        self._chk_audio = QCheckBox("Эмулировать AudioContext")
        self._chk_audio.setChecked(True)
        st_layout.addRow(self._chk_audio)

        tabs.addTab(settings_tab, "⚙️ Настройки")

        # ── Вкладка «Геолокация» ──────────────────────────
        geo_tab = QWidget()
        geo_layout = QFormLayout(geo_tab)

        self._chk_geo = QCheckBox("Включить эмуляцию геолокации")
        geo_layout.addRow(self._chk_geo)

        self._spn_lat = QSpinBox()
        self._spn_lat.setRange(-90, 90)
        geo_layout.addRow("Широта (°):", self._spn_lat)

        self._spn_lon = QSpinBox()
        self._spn_lon.setRange(-180, 180)
        geo_layout.addRow("Долгота (°):", self._spn_lon)

        self._spn_acc = QSpinBox()
        self._spn_acc.setRange(1, 10000)
        self._spn_acc.setValue(100)
        geo_layout.addRow("Точность (м):", self._spn_acc)

        tabs.addTab(geo_tab, "🌍 Геолокация")

        # ── Вкладка «Прокси» ──────────────────────────────
        proxy_tab = QWidget()
        px_layout = QFormLayout(proxy_tab)

        self._chk_proxy = QCheckBox("Использовать прокси")
        px_layout.addRow(self._chk_proxy)

        self._cmb_proto = QComboBox()
        self._cmb_proto.addItems(["http", "socks4", "socks5"])
        px_layout.addRow("Протокол:", self._cmb_proto)

        proxy_addr = QHBoxLayout()
        self._fld_proxy_host = QLineEdit()
        self._fld_proxy_host.setPlaceholderText("IP или домен")
        self._spn_proxy_port = QSpinBox()
        self._spn_proxy_port.setRange(1, 65535)
        self._spn_proxy_port.setValue(8080)
        proxy_addr.addWidget(self._fld_proxy_host)
        proxy_addr.addWidget(QLabel(":"))
        proxy_addr.addWidget(self._spn_proxy_port)
        px_layout.addRow("Адрес:", proxy_addr)

        self._fld_proxy_login = QLineEdit()
        self._fld_proxy_login.setPlaceholderText("Логин (если нужен)")
        px_layout.addRow("Логин:", self._fld_proxy_login)

        self._fld_proxy_pass = QLineEdit()
        self._fld_proxy_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._fld_proxy_pass.setPlaceholderText("Пароль")
        px_layout.addRow("Пароль:", self._fld_proxy_pass)

        self._chk_auto_geo = QCheckBox("Эмулировать Гео/TZ по IP прокси")
        px_layout.addRow(self._chk_auto_geo)

        tabs.addTab(proxy_tab, "🔒 Прокси")

        layout.addWidget(tabs)

        # Кнопки диалога
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("🚀 Запустить браузер")
        layout.addWidget(btns)

        self._apply_styles()

    def _apply_styles(self):
        self.setStyleSheet(f"""
            QDialog {{ background: {get_color('bg1')}; color: {get_color('tx0')}; }}
            QLabel {{ color: {get_color('tx1')}; }}
            QLineEdit, QSpinBox, QComboBox {{
                background: {get_color('bg2')}; color: {get_color('tx0')};
                border: 1px solid {get_color('bd')}; border-radius: 4px; padding: 3px;
            }}
            QPushButton {{
                background: {get_color('bg3')}; color: {get_color('tx0')};
                border: 1px solid {get_color('bd')}; border-radius: 4px; padding: 5px 10px;
            }}
            QPushButton:hover {{ background: {get_color('ac')}; color: #000; }}
            QListWidget {{
                background: {get_color('bg2')}; color: {get_color('tx0')};
                border: 1px solid {get_color('bd')}; border-radius: 4px;
            }}
            QListWidget::item:selected {{ background: {get_color('ac')}; color: #000; }}
            QTabWidget::pane {{ border: 1px solid {get_color('bd')}; }}
            QTabBar::tab {{
                background: {get_color('bg2')}; color: {get_color('tx1')};
                padding: 5px 12px; border-radius: 4px 4px 0 0;
            }}
            QTabBar::tab:selected {{ background: {get_color('bg3')}; color: {get_color('tx0')}; }}
        """)

    def _refresh_profiles(self):
        self._lst_profiles.clear()
        for p in self._pm.all_profiles():
            item = QListWidgetItem(f"👤 {p.name}")
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            self._lst_profiles.addItem(item)

    def _on_profile_selected(self, row: int):
        item = self._lst_profiles.item(row)
        if not item:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        p = self._pm.get(pid)
        if p:
            self._selected_profile = p
            self._load_profile_to_ui(p)

    def _load_profile_to_ui(self, p: BrowserProfile):
        self._fld_pname.setText(p.name)
        self._fld_pfolder.setText(p.profile_folder)
        self._chk_create_folder.setChecked(p.create_if_missing)
        self._fld_useragent.setText(p.user_agent)
        self._spn_w.setValue(p.window_width)
        self._spn_h.setValue(p.window_height)
        self._fld_timezone.setText(p.timezone)
        self._chk_images.setChecked(p.load_images)
        self._chk_media.setChecked(p.load_media)
        self._chk_css.setChecked(p.load_css)
        self._chk_frames.setChecked(p.load_frames)
        self._chk_js.setChecked(p.enable_javascript)
        self._chk_notif.setChecked(p.block_notifications)
        self._chk_popups.setChecked(p.block_popups)
        self._chk_canvas.setChecked(p.emulate_canvas)
        self._chk_audio.setChecked(p.emulate_audio_context)
        self._chk_geo.setChecked(p.geo_enabled)
        self._spn_lat.setValue(int(p.geo_latitude))
        self._spn_lon.setValue(int(p.geo_longitude))
        self._spn_acc.setValue(int(p.geo_accuracy))

    def _collect_profile_from_ui(self) -> BrowserProfile:
        p = self._selected_profile or BrowserProfile()
        p.name = self._fld_pname.text().strip() or "Профиль"
        p.profile_folder = self._fld_pfolder.text().strip()
        p.create_if_missing = self._chk_create_folder.isChecked()
        p.user_agent = self._fld_useragent.text().strip()
        p.window_width = self._spn_w.value()
        p.window_height = self._spn_h.value()
        p.timezone = self._fld_timezone.text().strip()
        p.load_images = self._chk_images.isChecked()
        p.load_media = self._chk_media.isChecked()
        p.load_css = self._chk_css.isChecked()
        p.load_frames = self._chk_frames.isChecked()
        p.enable_javascript = self._chk_js.isChecked()
        p.block_notifications = self._chk_notif.isChecked()
        p.block_popups = self._chk_popups.isChecked()
        p.emulate_canvas = self._chk_canvas.isChecked()
        p.emulate_audio_context = self._chk_audio.isChecked()
        p.geo_enabled = self._chk_geo.isChecked()
        p.geo_latitude = float(self._spn_lat.value())
        p.geo_longitude = float(self._spn_lon.value())
        p.geo_accuracy = float(self._spn_acc.value())
        return p

    def _collect_proxy_from_ui(self) -> BrowserProxy:
        return BrowserProxy(
            enabled=self._chk_proxy.isChecked(),
            protocol=self._cmb_proto.currentText(),
            host=self._fld_proxy_host.text().strip(),
            port=self._spn_proxy_port.value(),
            login=self._fld_proxy_login.text().strip(),
            password=self._fld_proxy_pass.text(),
            auto_geo=self._chk_auto_geo.isChecked(),
        )

    def _browse_profile_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выбрать папку профиля")
        if folder:
            self._fld_pfolder.setText(folder)

    def _new_profile(self):
        p = BrowserProfile(name=f"Профиль {len(self._pm.all_profiles()) + 1}")
        self._pm.add_or_update(p)
        self._refresh_profiles()
        # Выделяем новый
        for i in range(self._lst_profiles.count()):
            if self._lst_profiles.item(i).data(Qt.ItemDataRole.UserRole) == p.id:
                self._lst_profiles.setCurrentRow(i)
                break

    def _delete_profile(self):
        item = self._lst_profiles.currentItem()
        if item:
            pid = item.data(Qt.ItemDataRole.UserRole)
            self._pm.remove(pid)
            self._refresh_profiles()
            self._selected_profile = None

    def _save_profile(self):
        p = self._collect_profile_from_ui()
        self._pm.add_or_update(p)
        self._refresh_profiles()

    def _on_ok(self):
        self._selected_profile = self._collect_profile_from_ui()
        self._proxy = self._collect_proxy_from_ui()
        self.accept()

    def get_result(self) -> tuple[BrowserProfile, BrowserProxy]:
        return self._selected_profile or BrowserProfile(), self._proxy


# ══════════════════════════════════════════════════════════
#  UI: BROWSER INSTANCE PANEL (боковая панель)
# ══════════════════════════════════════════════════════════

class BrowserInstancePanel(QWidget):
    """
    Панель управления запущенными браузерными инстансами.
    Добавляется в боковой таб Agent Constructor.
    """
    action_requested = pyqtSignal(str, object)   # instance_id, BrowserAction

    def __init__(self, manager: BrowserManager, parent=None):
        super().__init__(parent)
        self._manager = manager
        self._build_ui()
        manager.instance_launched.connect(self._refresh)
        manager.instance_closed.connect(self._refresh)

    def set_manager(self, manager: BrowserManager) -> None:
        """Переключить менеджер при смене активного проекта."""
        if self._manager is manager:
            return
        # Отключаем сигналы старого менеджера
        try:
            self._manager.instance_launched.disconnect(self._refresh)
            self._manager.instance_closed.disconnect(self._refresh)
        except Exception:
            pass
        self._manager = manager
        # Подключаем сигналы нового менеджера
        manager.instance_launched.connect(self._refresh)
        manager.instance_closed.connect(self._refresh)
        self._refresh()
    
    def _log(self, msg: str):
        """Логирование через сигнал менеджера."""
        if self._manager:
            self._manager.log_signal.emit(msg)
    
    def _toggle_embed(self):
        """Скрыть/показать окно браузера (thumbnail остается на месте)."""
        inst = self._get_selected_instance()
        if not inst:
            QMessageBox.warning(self, "Нет выбора", "Выберите инстанс из списка")
            return
            
        # Проверяем, скрыто ли окно в трей
        is_hidden = getattr(inst, '_minimized_to_tray', False) or getattr(inst, '_embedded_hwnd', None) is not None
        
        if is_hidden:
            # Показываем окно (открепляем)
            inst.show_window()
            inst._minimized_to_tray = False
            self._log(f"👁 Окно браузера {inst.instance_id} показано")
        else:
            # Скрываем окно в трей (thumbnail продолжает обновляться)
            inst.minimize_window()
            inst._minimized_to_tray = True
            self._log(f"📌 Окно браузера {inst.instance_id} скрыто в трей")
        
        self._update_embed_button()

    def _get_selected_instance(self) -> Optional[BrowserInstance]:
        """Получить выбранный инстанс браузера."""
        item = self._lst.currentItem()
        if not item:
            return None
        iid = item.data(Qt.ItemDataRole.UserRole)
        return self._manager.get_instance(iid)

    def _refresh(self, *_):
        self._lst.clear()
        alive_ids = set(self._manager.all_instances().keys())

        # Удалить ячейки закрытых браузеров
        for iid in list(self._cells.keys()):
            if iid not in alive_ids:
                self._remove_cell(iid)

        for iid, inst in self._manager.all_instances().items():
            status_icon = "🟢" if inst.is_running else "🔴"
            item = QListWidgetItem(f"{status_icon} [{iid}] {inst.profile.name}")
            item.setData(Qt.ItemDataRole.UserRole, iid)
            self._lst.addItem(item)

            # Автовстраивание новых инстансов (задержка чтобы окно успело появиться)
            if inst.is_running and iid not in self._cells:
                QTimer.singleShot(900, lambda i=inst: self._auto_embed_if_needed(i))

        self._update_embed_button()
    
    def _auto_embed_if_needed(self, inst: BrowserInstance, do_embed: bool = False):
        """Создать ячейку в сетке и опционально встроить окно браузера."""
        if not inst.is_running:
            return
        if inst.instance_id in self._cells:
            return   # уже есть

        # Убираем placeholder если он ещё есть
        if self._browser_placeholder.parent() is not None:
            self._browser_placeholder.setParent(None)

        # Определяем позицию в сетке
        idx = len(self._cells)
        row = idx // self._COLS
        col = idx % self._COLS

        iid = inst.instance_id

        # Создаём ячейку-контейнер фиксированного размера
        cell = QWidget()
        cell.setFixedSize(self._CELL_W, self._CELL_H)
        cell.setStyleSheet(
            f"background: {get_color('bg1')};"
            f"border: 1px solid {get_color('bd')};"
            f"border-radius: 6px;"
        )
        cell_layout = QVBoxLayout(cell)
        cell_layout.setContentsMargins(0, 0, 0, 0)
        cell_layout.setSpacing(0)

        # Заголовок ячейки
        hdr = QLabel(f"🌐 [{iid}]  {inst.profile.name}")
        hdr.setFixedHeight(22)
        hdr.setStyleSheet(
            f"background: {get_color('bg3')}; color: {get_color('tx1')};"
            f"font-size: 10px; padding: 0 6px;"
            f"border-radius: 6px 6px 0 0;"
        )
        cell_layout.addWidget(hdr)

        # QLabel для отображения скриншота
        thumb_lbl = QLabel()
        thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_lbl.setStyleSheet("background: #000;")
        cell_layout.addWidget(thumb_lbl, stretch=1)

        self._grid_layout.addWidget(cell, row, col)
        self._cells[iid] = cell

        # Функция обновления скриншота — масштабирует с сохранением пропорций
        def _refresh_screenshot(label=thumb_lbl, instance=inst):
            if not instance.is_running:
                return
            try:
                b64 = instance.get_screenshot_base64()
                if not b64:
                    return
                import base64 as _b64
                data = _b64.b64decode(b64)
                pix = QPixmap()
                pix.loadFromData(data)
                if not pix.isNull():
                    available_w = label.width()  if label.width()  > 10 else self._CELL_W
                    available_h = label.height() if label.height() > 10 else self._CELL_H - 22
                    scaled = pix.scaled(
                        available_w, available_h,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    label.setPixmap(scaled)
            except Exception:
                pass

        # Умный таймер: проверяем изменения часто, скриншотим только при нужде
        timer = QTimer(cell)
        
        def _smart_refresh():
            if not inst.is_running:
                return
            
            # Проверяем изменения через инстанс
            if inst.check_content_changed():
                # Только при изменении делаем скриншот
                _refresh_screenshot()
                inst.mark_content_checked()
        
        timer.timeout.connect(_smart_refresh)
        timer.start(1000)  # Проверка каждую секунду
        self._cell_timers[iid] = timer

        # Первый скриншот сразу (с небольшой задержкой чтобы браузер загрузился)
        QTimer.singleShot(1200, _refresh_screenshot)

        self._update_embed_button()
        
        # Если запрошено встраивание окна — делаем это с задержкой для отрисовки
        if do_embed:
            QTimer.singleShot(400, lambda: self._embed_into_cell(inst, cell))
    
    def _embed_into_cell(self, inst: BrowserInstance, cell: QWidget):
        """Встроить окно браузера в ячейку сетки."""
        try:
            # Встраиваем окно
            result = inst.embed_into_widget(cell)
            if result:
                self._log(f"✅ Браузер {inst.instance_id} встроен в панель")
                # Обновляем кнопку после успешного встраивания
                self._update_embed_button()
            else:
                self._log(f"⚠️ Не удалось встроить браузер {inst.instance_id}")
        except Exception as e:
            self._log(f"❌ Ошибка встраивания: {e}")
        
    def _remove_cell(self, iid: str):
        """Убрать ячейку конкретного инстанса из сетки и перестроить сетку."""
        # Останавливаем таймер скриншота
        timer = self._cell_timers.pop(iid, None)
        if timer:
            timer.stop()
        cell = self._cells.pop(iid, None)
        if cell:
            cell.setParent(None)
        # Перестраиваем все оставшиеся ячейки
        remaining = list(self._cells.values())
        for w in remaining:
            self._grid_layout.removeWidget(w)
        for idx, w in enumerate(remaining):
            self._grid_layout.addWidget(w, idx // self._COLS, idx % self._COLS)
        # Если пусто — вернуть placeholder
        if not self._cells:
            self._grid_layout.addWidget(
                self._browser_placeholder, 0, 0, 1, self._COLS
            )

    def _clear_browser_container(self):
        """Очистить всю сетку (legacy, оставлен для совместимости)."""
        for iid in list(self._cells.keys()):
            self._remove_cell(iid)
    
    def _update_embed_button(self):
        """Обновить состояние кнопки встраивания."""
        inst = self._get_selected_instance()
        if inst is not None and inst.is_running:
            self._btn_embed.setEnabled(True)
            # Проверяем, скрыто ли окно (в трее)
            is_hidden = getattr(inst, '_minimized_to_tray', False) or getattr(inst, '_embedded_hwnd', None) is not None
            if is_hidden:
                self._btn_embed.setText("⬆️ Открепить окно")
            else:
                self._btn_embed.setText("⬇️ Встроить в панель")
        else:
            self._btn_embed.setEnabled(False)
            self._btn_embed.setText("⬇️ Встроить в панель")
    
    def _build_ui(self):
        self._embed_target = None  # будет установлен после создания контейнера
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        hdr = QLabel("🌐 Браузерные инстансы")
        hdr.setStyleSheet(f"color: {get_color('tx0')}; font-weight: bold; font-size: 12px;")
        layout.addWidget(hdr)

        self._lst = QListWidget()
        self._lst.setStyleSheet(f"""
            QListWidget {{
                background: {get_color('bg2')};
                color: {get_color('tx0')};
                border: 1px solid {get_color('bd')};
                border-radius: 4px;
            }}
            QListWidget::item:selected {{ background: {get_color('ac')}; color: #000; }}
        """)
        self._lst.itemSelectionChanged.connect(self._update_embed_button)
        layout.addWidget(self._lst)

        btn_row = QHBoxLayout()
        btn_close = QPushButton("✖ Закрыть")
        btn_close.clicked.connect(self._close_selected)
        btn_info = QPushButton("ℹ Инфо")
        btn_info.clicked.connect(self._show_info)
        btn_all = QPushButton("🔲 Все браузеры")
        btn_all.setToolTip("Сводка всех запущенных браузеров во всех открытых проектах")
        btn_all.clicked.connect(self._open_global_grid)
        btn_row.addWidget(btn_info)
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        # ── Прокручиваемая сетка браузеров ───────────────────────────
        self._COLS      = 2          # колонок в сетке
        self._CELL_W    = 480        # ширина одной ячейки px
        self._CELL_H    = 320        # высота одной ячейки px
        self._cells: dict[str, QWidget] = {}   # iid → ячейка
        self._cell_timers: dict[str, QTimer] = {}  # iid → таймер скриншота

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {get_color('bg0')};
                border: 1px solid {get_color('bd')};
                border-radius: 6px;
            }}
            QScrollBar:vertical {{
                background: {get_color('bg2')};
                width: 8px; border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {get_color('bd')}; border-radius: 4px; min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {get_color('ac')}; }}
            QScrollBar:horizontal {{
                background: {get_color('bg2')};
                height: 8px; border-radius: 4px;
            }}
            QScrollBar::handle:horizontal {{
                background: {get_color('bd')}; border-radius: 4px; min-width: 20px;
            }}
            QScrollBar::handle:horizontal:hover {{ background: {get_color('ac')}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
        """)

        # Внутренний виджет сетки
        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet(f"background: {get_color('bg0')};")
        from PyQt6.QtWidgets import QGridLayout
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(6, 6, 6, 6)
        self._grid_layout.setSpacing(6)
        self._scroll.setWidget(self._grid_widget)

        # Placeholder (показывается пока нет браузеров)
        self._browser_placeholder = QLabel(
            "🌐 Нет запущенных браузеров\n\nЗапустите сниппет Browser Launch\nили нажмите «Тест запуска»"
        )
        self._browser_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._browser_placeholder.setStyleSheet(
            f"color: {get_color('tx2')}; font-size: 12px; padding: 40px;"
        )
        self._grid_layout.addWidget(self._browser_placeholder, 0, 0, 1, self._COLS)

        layout.addWidget(self._scroll, stretch=1)
        self._embed_target = None   # embed происходит поячеечно, не через единый target
        
        # Кнопка встраивания/открепления
        btn_row = QHBoxLayout()
        self._btn_embed = QPushButton("⬇️ Встроить в панель")
        self._btn_embed.clicked.connect(self._toggle_embed)
        self._btn_embed.setEnabled(False)
        btn_row.addWidget(self._btn_embed)
        layout.addLayout(btn_row)
        
        # Статус URL
        self._lbl_url = QLabel("URL: —")
        self._lbl_url.setStyleSheet(f"color: {get_color('tx2')}; font-size: 10px;")
        self._lbl_url.setWordWrap(True)
        layout.addWidget(self._lbl_url)

        # Таймер обновления URL
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_url)
        self._timer.start(2000)

    def apply_theme(self):
        """Обновить стили при смене темы."""
        self._lst.setStyleSheet(f"""
            QListWidget {{
                background: {get_color('bg2')};
                color: {get_color('tx0')};
                border: 1px solid {get_color('bd')};
                border-radius: 4px;
            }}
            QListWidget::item:selected {{ background: {get_color('ac')}; color: #000; }}
        """)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {get_color('bg0')};
                border: 1px solid {get_color('bd')};
                border-radius: 6px;
            }}
            QScrollBar:vertical {{
                background: {get_color('bg2')};
                width: 8px; border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {get_color('bd')}; border-radius: 4px; min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {get_color('ac')}; }}
            QScrollBar:horizontal {{
                background: {get_color('bg2')};
                height: 8px; border-radius: 4px;
            }}
            QScrollBar::handle:horizontal {{
                background: {get_color('bd')}; border-radius: 4px; min-width: 20px;
            }}
            QScrollBar::handle:horizontal:hover {{ background: {get_color('ac')}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
        """)
        self._grid_widget.setStyleSheet(f"background: {get_color('bg0')};")
        self._browser_placeholder.setStyleSheet(
            f"color: {get_color('tx2')}; font-size: 12px; padding: 40px;"
        )
        self._lbl_url.setStyleSheet(f"color: {get_color('tx2')}; font-size: 10px;")
        # Обновляем ячейки с браузерами
        for iid, cell in self._cells.items():
            cell.setStyleSheet(
                f"background: {get_color('bg1')};"
                f"border: 1px solid {get_color('bd')};"
                f"border-radius: 6px;"
            )
        self.update()

    def _close_selected(self):
        item = self._lst.currentItem()
        if item:
            iid = item.data(Qt.ItemDataRole.UserRole)
            self._manager.close_instance(iid)
    
    def _open_global_grid(self):
        """Открыть глобальную сводку всех инстансов из всех открытых проектов."""
        tray = BrowserTrayManager.get()
        if tray:
            tray._open_global_grid()
        else:
            # Fallback — показываем только текущий менеджер
            all_instances = self._manager.all_instances()
            dlg = GlobalBrowserGridDialog(all_instances, [self._manager], self)
            dlg.exec()
    
    def _show_info(self):
        item = self._lst.currentItem()
        if not item:
            return
        iid = item.data(Qt.ItemDataRole.UserRole)
        inst = self._manager.get_instance(iid)
        if inst:
            msg = (f"ID: {iid}\n"
                   f"Профиль: {inst.profile.name}\n"
                   f"Движок: {inst._engine}\n"
                   f"URL: {inst.current_url}\n"
                   f"Заголовок: {inst.current_title}")
            QMessageBox.information(self, "Инстанс браузера", msg)

    def _update_url(self):
        item = self._lst.currentItem()
        if item:
            iid = item.data(Qt.ItemDataRole.UserRole)
            inst = self._manager.get_instance(iid)
            if inst and inst.is_running:
                url = inst.current_url
                self._lbl_url.setText(f"URL: {url[:80]}..." if len(url) > 80 else f"URL: {url}")


# ══════════════════════════════════════════════════════════
#  UI: SNIPPET CONFIG WIDGET для BROWSER_ACTION
# ══════════════════════════════════════════════════════════

class BrowserActionWidget(QWidget):
    """
    Виджет конфигурации сниппета BROWSER_ACTION.
    Встраивается в панель свойств AgentConstructor.
    """
    changed = pyqtSignal()

    def __init__(self, manager: BrowserManager, parent=None):
        super().__init__(parent)
        self._manager = manager
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()

        # Инстанс
        self._cmb_instance = QComboBox()
        self._cmb_instance.addItem("— из контекста проекта (browser_instance_id) —", None)
        form.addRow("Инстанс:", self._cmb_instance)

        # Действие
        self._cmb_action = QComboBox()
        for action_id, (label, hint) in BROWSER_ACTIONS.items():
            self._cmb_action.addItem(label, action_id)
        self._cmb_action.currentIndexChanged.connect(self._update_hints)
        form.addRow("Действие:", self._cmb_action)

        # Целевой элемент
        self._fld_target = QLineEdit()
        self._fld_target.setPlaceholderText("Селектор / URL / JS-код...")
        form.addRow("Цель:", self._fld_target)

        # Тип селектора
        self._cmb_sel_type = QComboBox()
        self._cmb_sel_type.addItems(["css", "xpath", "id", "name", "tag"])
        form.addRow("Тип селектора:", self._cmb_sel_type)

        # Значение
        self._fld_value = QLineEdit()
        self._fld_value.setPlaceholderText("Значение для ввода/параметр...")
        form.addRow("Значение:", self._fld_value)

        # Переменная для результата
        self._fld_var_out = QLineEdit()
        self._fld_var_out.setPlaceholderText("{variable_name}")
        form.addRow("Результат →:", self._fld_var_out)

        # Таймаут
        self._spn_timeout = QSpinBox()
        self._spn_timeout.setRange(1, 600)
        self._spn_timeout.setValue(30)
        form.addRow("Таймаут (с):", self._spn_timeout)

        # Пауза после
        self._spn_wait = QSpinBox()
        self._spn_wait.setRange(0, 60)
        self._spn_wait.setValue(0)
        form.addRow("Пауза после (с):", self._spn_wait)

        layout.addLayout(form)

        # Подсказка
        self._lbl_hint = QLabel()
        self._lbl_hint.setStyleSheet(f"color: {get_color('tx2')}; font-size: 10px; font-style: italic;")
        self._lbl_hint.setWordWrap(True)
        layout.addWidget(self._lbl_hint)

        layout.addStretch()
        self._update_hints()

    def _update_hints(self):
        action_id = self._cmb_action.currentData()
        if action_id and action_id in BROWSER_ACTIONS:
            _, hint = BROWSER_ACTIONS[action_id]
            self._lbl_hint.setText(hint)

    def refresh_instances(self):
        self._cmb_instance.clear()
        self._cmb_instance.addItem("— первый доступный —", None)
        for iid, inst in self._manager.all_instances().items():
            self._cmb_instance.addItem(
                f"[{iid}] {inst.profile.name}", iid
            )

    def get_config(self) -> dict:
        return {
            "instance_id": self._cmb_instance.currentData(),  # None = брать из context["browser_instance_id"]
            "action": self._cmb_action.currentData() or "navigate",
            "target": self._fld_target.text(),
            "value": self._fld_value.text(),
            "variable_out": self._fld_var_out.text(),
            "timeout": self._spn_timeout.value(),
            "wait_after": float(self._spn_wait.value()),
            "selector_type": self._cmb_sel_type.currentText(),
        }

    def set_config(self, cfg: dict):
        if not cfg:
            return
        # Action
        for i in range(self._cmb_action.count()):
            if self._cmb_action.itemData(i) == cfg.get("action", "navigate"):
                self._cmb_action.setCurrentIndex(i)
                break
        self._fld_target.setText(cfg.get("target", ""))
        self._fld_value.setText(cfg.get("value", ""))
        self._fld_var_out.setText(cfg.get("variable_out", ""))
        self._spn_timeout.setValue(cfg.get("timeout", 30))
        self._spn_wait.setValue(int(cfg.get("wait_after", 0)))
        sel_idx = self._cmb_sel_type.findText(cfg.get("selector_type", "css"))
        self._cmb_sel_type.setCurrentIndex(max(0, sel_idx))


# ══════════════════════════════════════════════════════════
#  UI: BROWSER LAUNCH SNIPPET WIDGET
# ══════════════════════════════════════════════════════════

class BrowserLaunchWidget(QWidget):
    """
    Виджет конфигурации сниппета BROWSER_LAUNCH.
    Позволяет задать профиль, прокси и аргументы прямо в ноде.
    """
    changed = pyqtSignal()

    def __init__(self, profile_manager: BrowserProfileManager,
                 manager: BrowserManager, parent=None):
        super().__init__(parent)
        self._pm = profile_manager
        self._manager = manager
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()

        # Выбор профиля
        profile_row = QHBoxLayout()
        self._cmb_profile = QComboBox()
        self._refresh_profiles()
        btn_manage = QPushButton("⚙")
        btn_manage.setFixedWidth(28)
        btn_manage.setToolTip("Управление профилями")
        btn_manage.clicked.connect(self._open_profile_dialog)
        profile_row.addWidget(self._cmb_profile)
        profile_row.addWidget(btn_manage)
        form.addRow("Профиль:", profile_row)

        # Папка профиля (быстрый ввод)
        folder_row = QHBoxLayout()
        self._fld_folder = QLineEdit()
        self._fld_folder.setPlaceholderText("Путь к папке профиля (переопределяет профиль)...")
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(28)
        btn_browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(self._fld_folder)
        folder_row.addWidget(btn_browse)
        form.addRow("Папка профиля:", folder_row)

        self._chk_create = QCheckBox("Создать если не существует")
        self._chk_create.setChecked(True)
        form.addRow("", self._chk_create)

        # Прокси
        self._chk_proxy = QCheckBox("Использовать прокси")
        form.addRow(self._chk_proxy)

        proxy_row = QHBoxLayout()
        self._cmb_proto = QComboBox()
        self._cmb_proto.addItems(["http", "socks4", "socks5"])
        self._fld_proxy = QLineEdit()
        self._fld_proxy.setPlaceholderText("login:pass@host:port  или  host:port")
        proxy_row.addWidget(self._cmb_proto)
        proxy_row.addWidget(self._fld_proxy)
        form.addRow("Прокси:", proxy_row)

        # Переменная результата (instance_id)
        self._fld_iid_var = QLineEdit()
        self._fld_iid_var.setPlaceholderText("{browser_instance_id}")
        form.addRow("ID инстанса →:", self._fld_iid_var)

        # Режим запуска окна
        self._cmb_window_mode = QComboBox()
        self._cmb_window_mode.addItem("📌 Встроить в панель браузеров", "embed_panel")
        self._cmb_window_mode.addItem("🖥 Показать на рабочем столе", "desktop")
        self._cmb_window_mode.addItem("👻 Headless (без окна)", "headless")
        form.addRow("Режим окна:", self._cmb_window_mode)

        layout.addLayout(form)

        # Кнопка быстрого теста
        btn_test = QPushButton("🧪 Тест запуска (здесь и сейчас)")
        btn_test.clicked.connect(self._quick_launch)
        layout.addWidget(btn_test)

        layout.addStretch()

    def _refresh_profiles(self):
        self._cmb_profile.clear()
        self._cmb_profile.addItem("— не выбран —", None)
        for p in self._pm.all_profiles():
            self._cmb_profile.addItem(f"👤 {p.name}", p.id)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выбрать папку профиля")
        if folder:
            self._fld_folder.setText(folder)

    def _open_profile_dialog(self):
        dlg = BrowserLaunchDialog(self._pm, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            profile, proxy = dlg.get_result()
            self._pm.add_or_update(profile)
            self._refresh_profiles()
            # Выбираем только что созданный профиль
            for i in range(self._cmb_profile.count()):
                if self._cmb_profile.itemData(i) == profile.id:
                    self._cmb_profile.setCurrentIndex(i)
                    break
            self.changed.emit()

    def _quick_launch(self):
        """Запустить браузер прямо сейчас для теста."""
        cfg = self.get_config()
        profile = self._pm.get(cfg.get("profile_id") or "") or BrowserProfile()
        if cfg.get("profile_folder"):
            profile.profile_folder = cfg["profile_folder"]
            profile.create_if_missing = cfg.get("create_if_missing", True)

        proxy = BrowserProxy()
        if cfg.get("proxy_enabled"):
            proxy.enabled = True
            proxy.protocol = cfg.get("proxy_protocol", "http")
            raw = cfg.get("proxy_string", "")
            # Парсим host:port или login:pass@host:port
            if "@" in raw:
                auth, addr = raw.rsplit("@", 1)
                if ":" in auth:
                    proxy.login, proxy.password = auth.split(":", 1)
            else:
                addr = raw
            if ":" in addr:
                h, p_str = addr.rsplit(":", 1)
                proxy.host = h
                try:
                    proxy.port = int(p_str)
                except ValueError:
                    pass

        inst = self._manager.launch(profile, proxy)
        if inst:
            QMessageBox.information(self, "Браузер запущен",
                                    f"✅ Браузер запущен!\nID: {inst.instance_id}")
        else:
            QMessageBox.warning(self, "Ошибка",
                                "❌ Не удалось запустить браузер.\n"
                                "Убедитесь что установлен selenium:\n"
                                "pip install selenium webdriver-manager")

    def get_config(self) -> dict:
        mode = self._cmb_window_mode.currentData() if hasattr(self, '_cmb_window_mode') else "embed_panel"
        return {
            "profile_id": self._cmb_profile.currentData(),
            "profile_folder": self._fld_folder.text().strip(),
            "create_if_missing": self._chk_create.isChecked(),
            "proxy_enabled": self._chk_proxy.isChecked(),
            "proxy_protocol": self._cmb_proto.currentText(),
            "proxy_string": self._fld_proxy.text().strip(),
            "instance_id_var": self._fld_iid_var.text().strip(),
            "window_mode": mode,
            "auto_embed": mode == "embed_panel",
            "start_in_tray": mode == "embed_panel",
            "headless": mode == "headless",
        }

    def set_config(self, cfg: dict):
        if not cfg:
            return
        pid = cfg.get("profile_id")
        if pid:
            for i in range(self._cmb_profile.count()):
                if self._cmb_profile.itemData(i) == pid:
                    self._cmb_profile.setCurrentIndex(i)
                    break
        self._fld_folder.setText(cfg.get("profile_folder", ""))
        self._chk_create.setChecked(cfg.get("create_if_missing", True))
        self._chk_proxy.setChecked(cfg.get("proxy_enabled", False))
        proto_idx = self._cmb_proto.findText(cfg.get("proxy_protocol", "http"))
        self._cmb_proto.setCurrentIndex(max(0, proto_idx))
        self._fld_proxy.setText(cfg.get("proxy_string", ""))
        self._fld_iid_var.setText(cfg.get("instance_id_var", ""))
        if hasattr(self, '_cmb_window_mode'):
            mode = cfg.get("window_mode", "embed_panel")
            idx = self._cmb_window_mode.findData(mode)
            self._cmb_window_mode.setCurrentIndex(max(0, idx))


# ══════════════════════════════════════════════════════════
#  BROWSER TRAY MINIATURE  (ZennoPoster-style)
# ══════════════════════════════════════════════════════════

class BrowserTrayMiniature(QWidget):
    """
    Умная миниатюра браузера — скриншот только при изменении контента.
    Проверяет DOM/URL/title каждую секунду, скриншотит только при изменениях.
    """
    open_requested = pyqtSignal(str)   # instance_id

    THUMB_W = 240
    THUMB_H = 160
    
    # Интервал проверки изменений (быстрый), не скриншота
    CHECK_INTERVAL: int = 1000   # мс — проверяем каждую секунду
    DEFAULT_SCALE:    float = 0.3  # 30% от оригинала

    def __init__(self, instance_id: str, label: str = "", parent=None):
        super().__init__(parent)
        self.instance_id = instance_id
        self._label = label or instance_id[:8]
        self._pixmap: QPixmap | None = None
        self._manager: Optional["BrowserManager"] = None

        self.setFixedSize(self.THUMB_W, self.THUMB_H + 28)
        self.setToolTip(f"Браузер: {self._label}\nКлик — открыть")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            BrowserTrayMiniature {{
                background: {get_color('bg1')};
                border: 1px solid {get_color('bd')};
                border-radius: 6px;
            }}
        """)

        # Флаги состояния
        self._screenshot_busy = False
        self._pending_screenshot = False  # Нужен скриншот но заняты
        
        # Таймер проверки изменений (лёгкий, каждую секунду)
        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._check_for_changes)
        self._check_timer.start(self.CHECK_INTERVAL)

    def set_manager(self, manager: "BrowserManager"):
        """Привязать к менеджеру для получения скриншотов."""
        self._manager = manager

    def _check_for_changes(self):
        """Быстрая проверка изменений — не блокирует UI."""
        if not self._manager:
            return
            
        inst = self._manager.get_instance(self.instance_id)
        if not inst or not inst.is_running:
            return
        
        # Проверяем изменения (быстро, без скриншота)
        if inst.check_content_changed():
            # Контент изменился — ставим в очередь на скриншот
            self._pending_screenshot = True
            self._try_screenshot()

    def _try_screenshot(self):
        """Попытаться сделать скриншот если не заняты."""
        if self._screenshot_busy or not self._pending_screenshot:
            return
            
        inst = self._manager.get_instance(self.instance_id)
        if not inst or not inst.is_running:
            return
        
        self._screenshot_busy = True
        self._pending_screenshot = False
        
        # Делаем скриншот в фоновом потоке
        scale = getattr(BrowserTrayMiniature, 'DEFAULT_SCALE', 0.3)
        worker = _ScreenshotWorker(inst, scale=scale)
        worker.signals.done.connect(self._on_screenshot_ready)
        worker.signals.done.connect(lambda _: setattr(self, '_screenshot_busy', False))
        QThreadPool.globalInstance().start(worker)

    def _on_screenshot_ready(self, png_bytes: bytes):
        """Скриншот готов — обновляем картинку."""
        try:
            pix = QPixmap()
            pix.loadFromData(png_bytes)
            if not pix.isNull():
                self._pixmap = pix.scaled(
                    self.THUMB_W, self.THUMB_H,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.update()
                
                # Отмечаем что проверили
                inst = self._manager.get_instance(self.instance_id) if self._manager else None
                if inst:
                    inst.mark_content_checked()
        except Exception:
            pass
        
        # Если накопились изменения пока делали скриншот — делаем ещё один
        if self._pending_screenshot:
            QTimer.singleShot(100, self._try_screenshot)
        
    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor, QFont
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        from PyQt6.QtGui import QColor
        # Фон
        painter.fillRect(self.rect(), QColor(get_color("bg1")))

        # Скриншот или индикатор загрузки
        if self._pixmap:
            x = (self.THUMB_W - self._pixmap.width()) // 2
            painter.drawPixmap(x, 0, self._pixmap)
            
                # Индикатор что нужен новый скриншот
            if self._pending_screenshot and not self._screenshot_busy:
                painter.setBrush(QColor(255, 165, 0, 180))  # Оранжевый
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(self.THUMB_W - 12, 4, 8, 8)
        else:
            painter.setPen(QColor(get_color("tx2")))
            painter.drawText(
                QRectF(0, 0, self.THUMB_W, self.THUMB_H),
                Qt.AlignmentFlag.AlignCenter,
                "⏳ Ожидание изменений..."
            )

        # Подпись
        painter.fillRect(
            0, self.THUMB_H, self.THUMB_W, 28,
            QColor(get_color("bg2"))
        )
        painter.setPen(QColor(get_color("tx1")))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        # Добавляем точку статуса
        status_dot = "🟢" if not self._pending_screenshot else "🟡"
        painter.drawText(
            QRectF(4, self.THUMB_H + 2, self.THUMB_W - 8, 24),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            f"{status_dot} {self._label}"
        )
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self.instance_id)

    def apply_theme(self):
        """Обновить стили при смене темы."""
        self.setStyleSheet(f"""
            BrowserTrayMiniature {{
                background: {get_color('bg1')};
                border: 1px solid {get_color('bd')};
                border-radius: 6px;
            }}
        """)
        self.update()


class BrowserTrayPanel(QWidget):
    """
    Панель трея — горизонтальная полоса с миниатюрами всех браузеров проекта.
    Кнопка «→ Трей» на каждом инстансе отправляет его сюда.
    """
    def __init__(self, manager: "BrowserManager", parent=None):
        super().__init__(parent)
        self._manager = manager
        self._thumbs: dict[str, BrowserTrayMiniature] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        self._layout = layout
        self.setFixedHeight(BrowserTrayMiniature.THUMB_H + 28 + 12)
        self.setStyleSheet(f"background: {get_color('bg0')};")

    def add_instance(self, instance_id: str, label: str = ""):
        if instance_id in self._thumbs:
            return
        thumb = BrowserTrayMiniature(instance_id, label, self)
        thumb.set_manager(self._manager)
        thumb.open_requested.connect(self._on_open)
        self._layout.addWidget(thumb)
        self._thumbs[instance_id] = thumb

    def remove_instance(self, instance_id: str):
        if instance_id in self._thumbs:
            thumb = self._thumbs.pop(instance_id)
            self._layout.removeWidget(thumb)
            thumb.deleteLater()

    def _on_open(self, instance_id: str):
        inst = self._manager.get_instance(instance_id)
        if inst:
            inst._launched_with_tray = False
            inst.show_window()
        self.remove_instance(instance_id)

    def apply_theme(self):
        """Обновить стили трей-панели и всех миниатюр при смене темы."""
        self.setStyleSheet(f"background: {get_color('bg0')};")
        for thumb in self._thumbs.values():
            thumb.apply_theme()

class ProjectBrowserManager:
    """
    Менеджер браузеров для одного проекта.
    Оборачивает BrowserManager и добавляет project_id-изоляцию.
    Каждый проект имеет свой независимый набор инстансов.
    """
    def __init__(self, project_id: str, base_manager: "BrowserManager | None" = None):
        self.project_id = project_id
        self._manager: BrowserManager = base_manager or BrowserManager.get()
        # ID инстансов принадлежащих ЭТОМУ проекту
        self._owned_ids: set[str] = set()

    def launch(self, profile: BrowserProfile, proxy: BrowserProxy | None = None,
               embed_target=None, start_in_tray: bool = False) -> "BrowserInstance | None":
        inst = self._manager.launch(profile, proxy, embed_target=embed_target, start_in_tray=start_in_tray)
        if inst:
            self._owned_ids.add(inst.instance_id)
        return inst

    def get_instance(self, iid: str) -> "BrowserInstance | None":
        # Возвращаем только если инстанс принадлежит этому проекту
        if iid in self._owned_ids:
            return self._manager.get_instance(iid)
        return None

    def all_instances(self) -> dict:
        return {
            iid: inst
            for iid, inst in self._manager.all_instances().items()
            if iid in self._owned_ids
        }

    def close(self, iid: str):
        if iid in self._owned_ids:
            self._manager.close(iid)
            self._owned_ids.discard(iid)

    def close_all(self):
        for iid in list(self._owned_ids):
            self._manager.close_instance(iid)
        self._owned_ids.clear()

    def close_instance(self, iid: str):
        """Алиас close() — совместимость с BrowserManager API."""
        if iid in self._owned_ids:
            self._manager.close_instance(iid)
            self._owned_ids.discard(iid)

    def get_instance(self, iid: str) -> "BrowserInstance | None":
        """Получить инстанс по ID если он принадлежит этому проекту."""
        if iid in self._owned_ids:
            return self._manager.get_instance(iid)
        return None

    def first_instance_id(self) -> str | None:
        for iid in self._owned_ids:
            inst = self._manager.get_instance(iid)
            if inst and inst.is_running:
                return iid
        return None

# ══════════════════════════════════════════════════════════
#  RUNTIME EXECUTION HELPERS
# ══════════════════════════════════════════════════════════

def execute_browser_launch_snippet(cfg: dict, context: dict,
                                   profile_manager: BrowserProfileManager,
                                   manager: BrowserManager,
                                   logger: Callable[[str], None],
                                   embed_target: Optional[Any] = None,
                                   project_browser_manager=None) -> dict:
    """
    Выполнить сниппет BROWSER_LAUNCH.
    Возвращает обновлённый context.
    """
    logger("🔧 Начало запуска браузера...")
    logger(f"📋 Конфиг: { {k:v for k,v in cfg.items() if not k.startswith('_')} }")
    
    # Создаём профиль из конфига сниппета
    profile = BrowserProfile()
    profile.name = "Snippet Profile"
    
    # Папка профиля
    profile_folder = cfg.get("profile_folder", "")
    if profile_folder:
        # Подставляем переменные контекста
        for k, v in context.items():
            profile_folder = profile_folder.replace(f"{{{k}}}", str(v))
        # ═══ Изоляция профиля для каждого потока ═══
        thread_num = context.get("_thread_num", "")
        if thread_num and str(thread_num) != "1":
            # Каждый поток получает СВОЙ подкаталог профиля
            import os
            profile_folder = os.path.join(profile_folder, f"thread_{thread_num}")
            logger(f"🔀 Поток #{thread_num}: изолированный профиль")
        profile.profile_folder = profile_folder
        logger(f"📁 Папка профиля: {profile_folder}")
    else:
        # ═══ Если папка пуста — подхватить из Browser Profile Op ═══
        _loaded = context.get("_browser_profile_path", "")
        if _loaded:
            profile.profile_folder = _loaded
            logger(f"📁 Подхвачен профиль из контекста: {_loaded}")
    profile.create_if_missing = cfg.get("create_if_missing", True)
    
    # Параметры окна
    profile.headless = cfg.get("headless", False)
    
    # ═══ Если браузер без профиля и без auto_embed — скорее всего промежуточный ═══
    # Помечаем как "тихий" чтобы минимизировать визуальное мелькание
    _is_intermediate = (not cfg.get("profile_folder", "").strip() and 
                        not cfg.get("auto_embed", False) and
                        not cfg.get("instance_id_var", "").strip())
    if _is_intermediate:
        logger("🔇 Промежуточный браузер (без профиля, без embed) — минимальный режим")
    
    # Стартовый URL
    start_url = cfg.get("start_url", "").strip()
    
    try:
        profile.window_width = int(cfg.get("window_width", 1280))
        profile.window_height = int(cfg.get("window_height", 900))
    except (ValueError, TypeError):
        profile.window_width = 1280
        profile.window_height = 900
    logger(f"🪟 Размер окна: {profile.window_width}x{profile.window_height}")
    
    # User-Agent
    user_agent = cfg.get("user_agent", "")
    if user_agent:
        for k, v in context.items():
            user_agent = user_agent.replace(f"{{{k}}}", str(v))
        profile.user_agent = user_agent
        logger(f"🎭 User-Agent: {user_agent[:50]}...")

    # Прокси
    proxy = BrowserProxy()
    if cfg.get("proxy_enabled"):
        proxy.enabled = True
        proxy.protocol = cfg.get("proxy_protocol", "http")
        raw = cfg.get("proxy_string", "")
        # Поддержка переменных из контекста
        for k, v in context.items():
            raw = raw.replace(f"{{{k}}}", str(v))
        logger(f"🔒 Прокси строка: {raw[:30]}...")
        if "@" in raw:
            auth, addr = raw.rsplit("@", 1)
            if ":" in auth:
                proxy.login, proxy.password = auth.split(":", 1)
        else:
            addr = raw
        if addr and ":" in addr:
            h, p_str = addr.rsplit(":", 1)
            proxy.host = h
            try:
                proxy.port = int(p_str)
            except ValueError:
                pass
        logger(f"🔒 Прокси: {proxy.protocol}://{proxy.host}:{proxy.port}")

    # ═══ Автозакрытие предыдущего браузера этого потока ═══
    # Если в контексте уже есть browser_instance_id от предыдущего BROWSER_LAUNCH,
    # и новый launch создаст ДРУГОЙ браузер — закрываем старый чтобы не было сирот
    _prev_iid = context.get("browser_instance_id", "")
    if _prev_iid:
        _prev_inst = None
        if project_browser_manager:
            _prev_inst = project_browser_manager.get_instance(_prev_iid)
        if not _prev_inst:
            _prev_inst = manager.get_instance(_prev_iid)
        if _prev_inst and _prev_inst.is_running:
            # Проверяем: новый браузер будет другим? (другой профиль или пустой профиль)
            _prev_profile = getattr(_prev_inst.profile, 'profile_folder', '')
            _new_profile = profile.profile_folder or ''
            if _prev_profile != _new_profile:
                logger(f"♻️ Закрываем предыдущий браузер {_prev_iid} (смена профиля)")
                try:
                    if project_browser_manager:
                        project_browser_manager.close_instance(_prev_iid)
                    else:
                        manager.close_instance(_prev_iid)
                except Exception as e:
                    logger(f"⚠️ Не удалось закрыть предыдущий: {e}")
                context.pop("browser_instance_id", None)
    
    # Запускаем! — сначала проверяем: нет ли уже запущенного с тем же профилем
    logger("🚀 Запуск браузера...")
    existing_inst = None
    if profile.profile_folder:
        # Проверяем ВСЕ инстансы: и проектные, и глобальные (для многопоточности)
        _pools = []
        if project_browser_manager:
            _pools.append(project_browser_manager.all_instances())
        _pools.append(manager.all_instances())
        
        _checked_ids = set()
        for _pool in _pools:
            for _iid, _inst in _pool.items():
                if _iid in _checked_ids:
                    continue
                _checked_ids.add(_iid)
                if _inst.is_running and _inst.profile.profile_folder == profile.profile_folder:
                    existing_inst = _inst
                    # ═══ Регистрируем в project_browser_manager если ещё не там ═══
                    if project_browser_manager and _iid not in project_browser_manager._owned_ids:
                        project_browser_manager._owned_ids.add(_iid)
                    logger(f"♻️ Браузер с профилем '{profile.profile_folder}' уже запущен "
                           f"(ID: {_iid}), переиспользуем — новый НЕ запускаем")
                    break
            if existing_inst:
                break
    try:
        # ═══ Определяем режим запуска ═══
        # auto_embed=True → стартуем скрытым, BrowserInstancePanel сам подхватит через instance_launched
        # start_in_tray → явный трей без встраивания
        # иначе → обычный запуск на рабочем столе
        explicit_tray = cfg.get("start_in_tray", False)
        auto_embed = cfg.get("auto_embed", False)
        # auto_embed и промежуточный браузер тоже стартуют за пределами экрана
        start_in_tray = explicit_tray or auto_embed or _is_intermediate
        
        if start_in_tray:
            logger(f"📌 Режим трей-панели: explicit={explicit_tray}, auto_embed={auto_embed}")
        
        if existing_inst:
            inst = existing_inst
        elif project_browser_manager:
            inst = project_browser_manager.launch(profile, proxy, 
                                                  embed_target=embed_target,
                                                  start_in_tray=start_in_tray)
        else:
            inst = manager.launch(profile, proxy, 
                                  embed_target=embed_target,
                                  start_in_tray=start_in_tray)
        if inst:
            iid = inst.instance_id
            if existing_inst:
                logger(f"✅ Используется существующий браузер, ID: {iid}")
            else:
                logger(f"✅ Браузер успешно запущен! ID: {iid}")
            var_name = cfg.get("instance_id_var", "").strip("{}")
            if var_name:
                context[var_name] = iid
                logger(f"💾 ID сохранён в переменную: {var_name}")
            # Всегда сохраняем в стандартную переменную для совместимости
            context["browser_instance_id"] = iid
            logger(f"💾 ID также сохранён в переменную: browser_instance_id")
            # Без embed_target — панель BrowserInstancePanel автовстроит через сигнал instance_launched
            # Автоматический переход если указан start_url
            if inst._driver:
                if start_url:
                    try:
                        logger(f"🌐 Переход на стартовый URL: {start_url}")
                        inst._driver.get(start_url)
                        import time
                        time.sleep(1.0)
                        logger(f"  ✅ Перешли на: {inst._driver.current_url}")
                    except Exception as e:
                        logger(f"  ⚠️ Не удалось перейти: {e}")
                elif inst._driver.current_url in ("about:blank", "chrome://new-tab-page/", "data:,"):
                    try:
                        logger("🌐 Автоматический переход на google.com...")
                        inst._driver.get("https://www.google.com")
                        import time
                        time.sleep(1.0)
                        logger(f"  ✅ Перешли на: {inst._driver.current_url}")
                    except Exception as e:
                        logger(f"  ⚠️ Не удалось перейти: {e}")

            # auto_embed: панель уже добавила карточку через instance_launched → _auto_embed_if_needed
            # Дополнительно скрываем окно браузера через 2 сек после запуска (HWND точно уже есть)
            if auto_embed and not explicit_tray:
                def _delayed_hide(i=inst):
                    import time
                    time.sleep(2.0)
                    if i.is_running:
                        hidden = i.minimize_window()
                        if hidden:
                            i._minimized_to_tray = True
                            logger(f"📌 Окно браузера {i.instance_id} скрыто (auto_embed)")
                        else:
                            logger(f"⚠️ Не удалось скрыть окно {i.instance_id} — HWND не найден")
                import threading
                threading.Thread(target=_delayed_hide, daemon=True).start()

            # Автовстраивание если запрошено и есть куда
            if cfg.get("auto_embed") and embed_target:
                logger("⬇️ Автовстраивание окна...")
                # Даём время окну создаться
                import time
                time.sleep(1.0)
                embedded = inst.embed_into_widget(embed_target)
                if embedded:
                    logger("✅ Окно встроено в панель")
                else:
                    logger("⚠️ Не удалось встроить окно")
        else:
            logger("❌ ОШИБКА: Браузер не запустился (launch вернул None)")
            logger("💡 Проверьте: 1) Установлен Chrome 2) pip install selenium webdriver-manager")
    except Exception as e:
        logger(f"❌ ОШИБКА запуска браузера: {e}")
        import traceback
        logger(f"🔍 Трейс: {traceback.format_exc()[:500]}")

    return context


def execute_browser_action_snippet(cfg: dict, context: dict,
                                   manager: BrowserManager,
                                   logger: Callable[[str], None],
                                   project_browser_manager=None) -> dict:
    """
    Выполнить сниппет BROWSER_ACTION.
    Возвращает обновлённый context.
    """
    # ─── Определяем instance_id, раскрывая переменные контекста ───────────
    iid = cfg.get("instance_id") or ""

    # Раскрываем {variable_name} → значение из контекста
    if iid:
        if iid.startswith("{") and iid.endswith("}"):
            iid = context.get(iid.strip("{}"), iid)
        else:
            for k, v in context.items():
                iid = iid.replace(f"{{{k}}}", str(v))
        iid = iid.strip("{} \t")

    if not iid:
        iid = context.get("browser_instance_id", "")

    # Если несколько браузеров открыто — предупреждаем о неоднозначности
    if not iid and project_browser_manager:
        owned = project_browser_manager.all_instances()
        count = len(owned)
        if count == 1:
            iid = project_browser_manager.first_instance_id()
        elif count > 1:
            logger(
                f"⚠️ Открыто {count} браузеров, instance_id не задан. "
                f"Добавьте поле 'ID инстанса' в действие с переменной из BROWSER_LAUNCH."
            )
            iid = project_browser_manager.first_instance_id()

    if not iid:
        instances = manager.all_instances()
        iid = next(iter(instances), None)

    # ─── Получаем инстанс ─────────────────────────────────────────────────
    inst = None
    if iid:
        if project_browser_manager:
            inst = project_browser_manager.get_instance(iid)
        if not inst:
            inst = manager.get_instance(iid)
    if not inst or not inst.is_running:
        logger(f"⚠️ Браузер не запущен (instance_id='{iid}'). "
               f"Убедитесь что BROWSER_LAUNCH выполнен и переменная с ID передана корректно.")
        return context

    # Подставляем переменные из контекста в target и value
    def resolve(s: str) -> str:
        for k, v in context.items():
            s = s.replace(f"{{{k}}}", str(v))
        return s

    # Получаем координаты из отдельных полей или формируем из них target
    coord_x = cfg.get("coord_x", "")
    coord_y = cfg.get("coord_y", "")
    search_text = cfg.get("search_text", "")
    
    # Формируем target для координатных действий: "x,y"
    target = cfg.get("target", "")
    action_type = cfg.get("action", "navigate")
    if action_type in ("click_xy", "double_click_xy", "right_click_xy", "hover_xy"):
        # Если target пустой, формируем из coord_x/coord_y
        if not target and coord_x and coord_y:
            target = f"{coord_x},{coord_y}"
        # Если coord_x/coord_y пустые, но target есть — используем target
    
    # Формируем target для поиска по тексту
    if action_type == "click_text" and not target and search_text:
        target = search_text

    action = BrowserAction(
        action=action_type,
        target=resolve(target),
        value=resolve(cfg.get("value", "")),
        variable_out=cfg.get("variable_out", ""),
        timeout=cfg.get("timeout", 30),
        wait_after=cfg.get("wait_after", 0.0),
        selector_type=cfg.get("selector_type", "css"),
        # Передаём координаты и search_text для надёжности
        coord_x=int(coord_x) if str(coord_x).isdigit() else 100,
        coord_y=int(coord_y) if str(coord_y).isdigit() else 100,
        search_text=resolve(search_text),
    )

    result = inst.execute_action(action)
    logger(f"🌐 {cfg.get('action', '?')}: {action.target[:60]}")

    # Сохраняем результат в контекст
    var_out = action.variable_out.strip("{}")
    if var_out and result is not None:
        context[var_out] = result

    return context

def execute_browser_screenshot_snippet(cfg: dict, context: dict,
                                       manager,
                                       logger: Callable[[str], None],
                                       project_browser_manager=None) -> dict:
    """
    Сниппет BROWSER_SCREENSHOT — делает скриншот страницы и сохраняет
    base64-строку в переменную контекста.
    """
    iid = cfg.get("instance_id", "").strip("{} ")
    if not iid:
        iid = context.get("browser_instance_id", "")
    if not iid and project_browser_manager:
        iid = project_browser_manager.first_instance_id() or ""

    inst = None
    if iid:
        inst = (project_browser_manager.get_instance(iid) if project_browser_manager
                else manager.get_instance(iid))
    if not inst:
        for _iid, _i in (project_browser_manager.all_instances() if project_browser_manager
                         else manager.all_instances()).items():
            if _i.is_running:
                inst = _i
                break

    if not inst or not inst.is_running:
        logger("❌ BROWSER_SCREENSHOT: браузер не найден")
        return context

    save_path = cfg.get("save_path", "").strip()
    var_out   = cfg.get("variable_out", "").strip("{} ")

    try:
        b64 = inst.get_screenshot_base64()
        if not b64 and getattr(inst, "_driver", None):
            import base64 as _b64
            b64 = _b64.b64encode(inst._driver.get_screenshot_as_png()).decode()

        if b64:
            if var_out:
                context[var_out] = b64
                logger(f"📸 Скриншот сохранён в переменную: {var_out} ({len(b64)} байт b64)")
            if save_path:
                # Подставляем переменные
                for k, v in context.items():
                    save_path = save_path.replace(f"{{{k}}}", str(v))
                import base64 as _b64, pathlib
                pathlib.Path(save_path).write_bytes(_b64.b64decode(b64))
                logger(f"📸 Скриншот сохранён в файл: {save_path}")
        else:
            logger("⚠️ BROWSER_SCREENSHOT: пустой скриншот")
    except Exception as e:
        logger(f"❌ BROWSER_SCREENSHOT: {e}")

    return context    

class BrowserClickImageWidget(QWidget):
    """
    Виджет конфигурации сниппета BROWSER_CLICK_IMAGE.
    Показывает скриншот текущего браузера, позволяет выделить регион-шаблон.
    """
    changed = pyqtSignal()

    def __init__(self, manager: "BrowserManager", parent=None):
        super().__init__(parent)
        self._manager = manager
        self._template_b64: str = ""   # base64 PNG шаблона
        self._screenshot_b64: str = "" # base64 PNG полного скриншота
        self._sel_start = None
        self._sel_end   = None
        self._pixmap    = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # ── Кнопка «Сделать скриншот браузера» ──
        btn_row = QHBoxLayout()
        self._btn_grab = QPushButton("📸 Сделать скриншот браузера")
        self._btn_grab.clicked.connect(self._grab_screenshot)
        btn_row.addWidget(self._btn_grab)

        self._lbl_status = QLabel("Нет шаблона")
        self._lbl_status.setStyleSheet("color:#E0AF68; font-size:10px;")
        btn_row.addWidget(self._lbl_status)
        btn_row.addStretch()

        btn_clear = QPushButton("🗑")
        btn_clear.setFixedWidth(28)
        btn_clear.setToolTip("Очистить шаблон")
        btn_clear.clicked.connect(self._clear_template)
        btn_row.addWidget(btn_clear)
        lay.addLayout(btn_row)

        # ── Инструкция ──
        hint = QLabel("После скриншота: зажмите мышь на картинке и выделите нужную область →")
        hint.setStyleSheet("color:#565f89; font-size:10px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # ── Canvas для отображения и выделения ──
        self._canvas = _ScreenshotCanvas(self)
        self._canvas.setMinimumHeight(240)
        self._canvas.region_selected.connect(self._on_region_selected)
        lay.addWidget(self._canvas, stretch=1)

        # ── Превью выбранного шаблона ──
        prev_row = QHBoxLayout()
        prev_lbl = QLabel("Шаблон:")
        prev_lbl.setStyleSheet("color:#A9B1D6; font-size:10px;")
        prev_row.addWidget(prev_lbl)
        self._lbl_preview = QLabel()
        self._lbl_preview.setFixedSize(80, 50)
        self._lbl_preview.setStyleSheet(
            "background:#07080C; border:1px solid #2E3148; border-radius:4px;")
        self._lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_row.addWidget(self._lbl_preview)
        prev_row.addStretch()
        lay.addLayout(prev_row)

    def _grab_screenshot(self):
        """Взять скриншот из выбранного (по instance_id) или первого доступного браузера через Selenium."""
        # ═══ ИСПРАВЛЕНИЕ: собираем инстансы из project_browser_manager + глобального ═══
        all_inst = {}
        pbm = getattr(self, '_project_browser_manager', None)
        if pbm:
            all_inst.update(pbm.all_instances())
        all_inst.update(self._manager.all_instances())
        
        # Ищем по заданному instance_id из конфига
        inst = None
        cfg_iid = getattr(self, '_cfg_instance_id', '') or ''
        if cfg_iid:
            inst = all_inst.get(cfg_iid)
        if not inst:
            inst = next((i for i in all_inst.values() if i.is_running), None)
        
        if not inst:
            QMessageBox.warning(self, "Браузер не запущен",
                                "Сначала запустите браузер (BROWSER_LAUNCH).")
            return
        
        # ═══ ИСПРАВЛЕНИЕ: скриншот ТОЛЬКО через Selenium (внутри браузера) ═══
        b64 = None
        drv = getattr(inst, '_driver', None)
        if drv:
            try:
                b64 = drv.get_screenshot_as_base64()
            except Exception:
                pass
        # Фолбэк на старый метод только если Selenium не смог
        if not b64:
            b64 = inst.get_screenshot_base64()
        if not b64:
            QMessageBox.warning(self, "Ошибка", "Не удалось сделать скриншот.")
            return
        self._screenshot_b64 = b64
        import base64
        raw = base64.b64decode(b64)
        pix = QPixmap()
        pix.loadFromData(raw)
        self._canvas.set_pixmap(pix)
        self._lbl_status.setText("Выделите область мышью ↓")

    def _on_region_selected(self, rect: "QRectF"):
        """Вырезаем выделенную область из полного скриншота."""
        if not self._screenshot_b64:
            return
        try:
            import base64, io
            raw = base64.b64decode(self._screenshot_b64)
            pix = QPixmap()
            pix.loadFromData(raw)
            # Масштабируем rect под оригинальный размер (canvas может быть меньше)
            sx = pix.width()  / max(1, self._canvas.width())
            sy = pix.height() / max(1, self._canvas.height())
            x  = int(rect.x()      * sx)
            y  = int(rect.y()      * sy)
            w  = int(rect.width()  * sx)
            h  = int(rect.height() * sy)
            if w < 4 or h < 4:
                return
            cropped = pix.copy(x, y, w, h)
            # Сохраняем как base64 PNG
            ba = __import__('PyQt6.QtCore', fromlist=['QByteArray']).QByteArray()
            buf = __import__('PyQt6.QtCore', fromlist=['QBuffer']).QBuffer(ba)
            buf.open(__import__('PyQt6.QtCore', fromlist=['QIODevice']).QIODevice.OpenModeFlag.WriteOnly)
            cropped.save(buf, "PNG")
            self._template_b64 = bytes(ba.toBase64()).decode()
            # Показываем превью
            prev = cropped.scaled(80, 50,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self._lbl_preview.setPixmap(prev)
            self._lbl_status.setText(f"✅ Шаблон: {w}×{h} px")
            self.changed.emit()
        except Exception as e:
            self._lbl_status.setText(f"Ошибка: {e}")

    def _clear_template(self):
        self._template_b64 = ""
        self._lbl_preview.clear()
        self._lbl_preview.setText("—")
        self._lbl_status.setText("Нет шаблона")
        self.changed.emit()

    def get_config(self) -> dict:
        return {"template_image": self._template_b64}

    def set_config(self, cfg: dict):
        self._template_b64 = cfg.get("template_image", "")
        self._cfg_instance_id = cfg.get("instance_id", "")
        self._cfg_instance_id = cfg.get("instance_id", "")
        if self._template_b64:
            try:
                import base64
                raw = base64.b64decode(self._template_b64)
                pix = QPixmap()
                pix.loadFromData(raw)
                prev = pix.scaled(80, 50,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                self._lbl_preview.setPixmap(prev)
                self._lbl_status.setText("✅ Шаблон загружен")
            except Exception:
                pass


class _ScreenshotCanvas(QWidget):
    """Canvas с поддержкой выделения региона мышью."""
    from PyQt6.QtCore import pyqtSignal
    region_selected = pyqtSignal(object)  # QRectF

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap   = None
        self._sel_start = None
        self._sel_end   = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMinimumSize(320, 200)
        self.setStyleSheet("background:#07080C; border:1px solid #2E3148; border-radius:4px;")

    def set_pixmap(self, pix: QPixmap):
        self._pixmap = pix
        self._sel_start = self._sel_end = None
        self.update()

    def paintEvent(self, ev):
        from PyQt6.QtGui import QPainter, QPen, QColor
        p = QPainter(self)
        if self._pixmap:
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, scaled)
        else:
            p.fillRect(self.rect(), QColor("#07080C"))
            p.setPen(QColor("#565f89"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Нажмите «Сделать скриншот браузера»")
        if self._sel_start and self._sel_end:
            r = QRectF(self._sel_start, self._sel_end).normalized()
            p.setPen(QPen(QColor("#7AA2F7"), 2, Qt.PenStyle.DashLine))
            p.setBrush(QColor(122, 162, 247, 40))
            p.drawRect(r)
        p.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._sel_start = ev.position()
            self._sel_end   = ev.position()
            self.update()

    def mouseMoveEvent(self, ev):
        if self._sel_start and (ev.buttons() & Qt.MouseButton.LeftButton):
            self._sel_end = ev.position()
            self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self._sel_start:
            self._sel_end = ev.position()
            r = QRectF(self._sel_start, self._sel_end).normalized()
            self.region_selected.emit(r)
            self.update()


def execute_browser_click_image_snippet(
        cfg: dict, context: dict,
        manager: "BrowserManager",
        logger,
        project_browser_manager=None) -> dict:
    """
    Сниппет BROWSER_CLICK_IMAGE:
    ищет шаблон (base64 PNG) на скриншоте браузера и кликает по центру совпадения.
    Использует OpenCV если доступен, иначе — PIL.
    """
    iid = cfg.get("instance_id", "").strip("{} ")
    if not iid:
        iid = context.get("browser_instance_id", "")
    inst = None
    if iid:
        if project_browser_manager:
            inst = project_browser_manager.get_instance(iid)
        if not inst:
            inst = manager.get_instance(iid)
    if not inst:
        # fallback — первый доступный
        for i in (project_browser_manager.all_instances() if project_browser_manager
                  else manager.all_instances()).values():
            if i.is_running:
                inst = i
                break
    if not inst or not inst.is_running:
        logger("❌ BROWSER_CLICK_IMAGE: нет активного браузера")
        return context

    template_b64 = cfg.get("template_image", "")
    if not template_b64:
        logger("⚠️ BROWSER_CLICK_IMAGE: шаблон не задан — откройте настройки сниппета и выберите область")
        return context

    threshold    = cfg.get("threshold", 80) / 100.0
    click_type   = cfg.get("click_type", "click")
    wait_timeout = int(cfg.get("wait_timeout", 10))
    variable_out = cfg.get("variable_out", "").strip("{} ")

    import base64, time

    def _find_and_click() -> tuple[bool, int, int]:
        """Делает скриншот браузера, ищет шаблон, возвращает (found, cx, cy)."""
        page_b64 = inst.get_screenshot_base64()
        if not page_b64:
            return False, 0, 0

        page_bytes = base64.b64decode(page_b64)
        tmpl_bytes = base64.b64decode(template_b64)

        # ── Попытка через OpenCV ──────────────────────────────────────
        try:
            import cv2, numpy as np
            page_arr = np.frombuffer(page_bytes, np.uint8)
            tmpl_arr = np.frombuffer(tmpl_bytes, np.uint8)
            page_img = cv2.imdecode(page_arr, cv2.IMREAD_COLOR)
            tmpl_img = cv2.imdecode(tmpl_arr, cv2.IMREAD_COLOR)
            if page_img is None or tmpl_img is None:
                raise ValueError("decode failed")
            res = cv2.matchTemplate(page_img, tmpl_img, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val >= threshold:
                h, w = tmpl_img.shape[:2]
                cx = max_loc[0] + w // 2
                cy = max_loc[1] + h // 2
                return True, cx, cy
            return False, 0, 0
        except ImportError:
            pass

        # ── Fallback через PIL ────────────────────────────────────────
        try:
            from PIL import Image
            import io, numpy as np
            page_img = np.array(Image.open(io.BytesIO(page_bytes)).convert("RGB"))
            tmpl_img = np.array(Image.open(io.BytesIO(tmpl_bytes)).convert("RGB"))
            ph, pw = page_img.shape[:2]
            th, tw = tmpl_img.shape[:2]
            if th > ph or tw > pw:
                return False, 0, 0
            # Простой sliding-window match (медленно, но без OpenCV)
            best_score = 0.0
            best_loc   = (0, 0)
            for y in range(0, ph - th, 4):
                for x in range(0, pw - tw, 4):
                    patch = page_img[y:y+th, x:x+tw]
                    diff  = np.abs(patch.astype(int) - tmpl_img.astype(int))
                    score = 1.0 - diff.mean() / 255.0
                    if score > best_score:
                        best_score = score
                        best_loc   = (x, y)
            if best_score >= threshold:
                cx = best_loc[0] + tw // 2
                cy = best_loc[1] + th // 2
                return True, cx, cy
            return False, 0, 0
        except ImportError:
            logger("⚠️ Установите opencv-python или Pillow: pip install opencv-python")
            return False, 0, 0

    # ── Поиск с опциональным ожиданием ──────────────────────────────
    deadline = time.time() + (wait_timeout if wait_timeout > 0 else 0)
    found, cx, cy = False, 0, 0
    attempts = 0
    while True:
        found, cx, cy = _find_and_click()
        attempts += 1
        if found:
            break
        if wait_timeout <= 0 or time.time() > deadline:
            break
        time.sleep(0.5)

    if not found:
        logger(f"⚠️ BROWSER_CLICK_IMAGE: шаблон не найден (попыток: {attempts}, порог: {threshold:.0%})")
        return context

    logger(f"✅ BROWSER_CLICK_IMAGE: найдено ({cx}, {cy}), выполняю {click_type}")

    action = BrowserAction(
        action=click_type + "_xy" if not click_type.endswith("_xy") else click_type,
        target=f"{cx},{cy}",
    )
    inst.execute_action(action)

    if variable_out:
        context[variable_out] = f"{cx},{cy}"

    return context

def execute_browser_agent_node(
    node,
    context: dict,
    project_browser_manager: "ProjectBrowserManager",
    planner_output: str,
    model_provider,
    logger,
    call_model_func=None,  # ← новый параметр
) -> dict:
    import asyncio
    from concurrent.futures import TimeoutError as FutureTimeoutError
    """
    Выполнить BROWSER_AGENT:
    ...
    """
    # Определяем инстанс браузера
    iid_var = getattr(node, "browser_instance_var", "").strip("{}")
    iid = context.get(iid_var) if iid_var else None
    
    # Если не указана переменная — пробуем получить из стандартной
    if not iid:
        iid = context.get("browser_instance_id")
    
    logger(f"[DEBUG] execute_browser_agent_node: ищу iid={iid}, context keys={list(context.keys())}")
    
    # Пробуем получить инстанс
    inst = None
    if iid and project_browser_manager:
        inst = project_browser_manager.get_instance(iid)
    
    # Fallback: любой активный инстанс проекта
    if not inst and project_browser_manager:
        all_inst = project_browser_manager.all_instances()
        for iid_candidate, inst_candidate in all_inst.items():
            if getattr(inst_candidate, 'is_running', False):
                inst = inst_candidate
                iid = iid_candidate
                break
    
    # Последний fallback: глобальный BrowserManager
    if not inst:
        try:
            from constructor.browser_module import BrowserManager
            bm = BrowserManager.get()
            # Ищем по ID из контекста
            if iid:
                inst = bm.get_instance(iid)
            # Или первый доступный
            if not inst:
                for iid_candidate, inst_candidate in bm.all_instances().items():
                    if getattr(inst_candidate, 'is_running', False):
                        inst = inst_candidate
                        iid = iid_candidate
                        break
        except Exception:
            pass

    if not inst or not getattr(inst, 'is_running', False):
        # Последний fallback: ищем в глобальном BrowserManager
        try:
            bm = BrowserManager.get()
            for iid_candidate, inst_candidate in bm.all_instances().items():
                if getattr(inst_candidate, 'is_running', False):
                    inst = inst_candidate
                    iid = iid_candidate
                    logger(f"[DEBUG] BROWSER_AGENT: fallback на глобальный инстанс {iid}")
                    break
        except Exception as e:
            logger(f"[DEBUG] BROWSER_AGENT: fallback не сработал: {e}")
        
        if not inst or not getattr(inst, 'is_running', False):
            logger("⚠️ BROWSER_AGENT: нет активного браузера для проекта")
            raise RuntimeError("No active browser instance for BROWSER_AGENT")

    cfg = getattr(node, "snippet_config", {}) or {}
    dom_max_elements    = int(cfg.get("dom_max_elements",    150))
    ai_timeout_sec      = int(cfg.get("ai_timeout_sec",      120))
    max_actions         = int(cfg.get("max_actions",          10))
    do_screenshot       = bool(cfg.get("screenshot_verify",  False))
    diff_threshold      = float(cfg.get("screenshot_diff_threshold", 5)) / 100.0
    scroll_before_scan  = bool(cfg.get("scroll_before_scan", False))
    action_wait_sec     = float(cfg.get("action_wait_sec",    1))
    variable_out        = str(cfg.get("variable_out",         "")).strip("{}")

    # Backwards compat
    node.dom_max_elements = dom_max_elements
    node.ai_timeout_sec   = ai_timeout_sec
    node.screenshot_verify = do_screenshot
    node.screenshot_diff_threshold = diff_threshold

    # --- 1. Снимок ДО (опционально) ---
    before_b64 = inst.get_screenshot_base64() if do_screenshot else ""

    # --- 2. Интерактивные элементы с координатами ---
    # Скролл перед сканированием (для lazy-load)
    if scroll_before_scan and inst._driver:
        try:
            inst._driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
            import time; time.sleep(0.8)
        except Exception:
            pass

    # Ждём загрузки страницы перед сканированием
    logger("🌐 BROWSER_AGENT: ожидание загрузки страницы...")
    try:
        if inst._driver:
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            # Проверяем URL
            current_url = inst._driver.current_url
            logger(f"  🔗 Текущий URL: {current_url}")
            # Если about:blank — страница не загружена
            if current_url in ("about:blank", "data:,"):
                logger("  ⚠️ Страница не загружена (about:blank)! Нужен navigate перед Browser Agent")
            WebDriverWait(inst._driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            # Дополнительная пауза для рендеринга JS-фреймворков
            import time
            time.sleep(0.5)
            # Проверяем что body появился
            body_exists = inst._driver.execute_script("return !!document.body")
            logger(f"  📄 document.body exists: {body_exists}")
            logger("  ✅ Страница загружена")
    except Exception as e:
        logger(f"  ⚠️ Таймаут ожидания загрузки: {e}")

    # Проверяем URL перед сканированием
    current_url = ""
    try:
        if inst._driver:
            current_url = inst._driver.current_url
            logger(f"  🔗 Текущий URL перед сканированием: {current_url}")
            if current_url in ("about:blank", "chrome://new-tab-page/", "data:,"):
                logger("  ⚠️ Браузер на пустой странице! Добавьте Browser Action → navigate перед Browser Agent")
    except:
        pass
    
    logger("🌐 BROWSER_AGENT: сканирование DOM страницы...")
    dom_max = getattr(node, "dom_max_elements", 150)
    dom_result = inst.collect_dom_for_ai(max_elements=dom_max)
    interactive_elements = dom_result.get("interactive", [])
    dom_str = dom_result.get("dom_text", "")
    total_elements = dom_result.get("meta", {}).get("total", 0)
    logger(f"  📋 DOM: {total_elements} элементов всего, "
           f"{len(interactive_elements)} интерактивных")
    
    # Fallback: если DOM пустой — пробуем ещё раз с задержкой
    if total_elements == 0 and inst._driver:
        logger("  ⏳ DOM пустой, повторная попытка через 2 сек...")
        import time
        time.sleep(2.0)
        dom_result = inst.collect_dom_for_ai(max_elements=dom_max)
        interactive_elements = dom_result.get("interactive", [])
        dom_str = dom_result.get("dom_text", "")
        total_elements = dom_result.get("meta", {}).get("total", 0)
        logger(f"  📋 DOM повторно: {total_elements} элементов, "
               f"{len(interactive_elements)} интерактивных")
    # === ОБРАБОТКА ПЛАНА ОТ PLANNER ===
    # Planner может вернуть многострочный план — разбираем его на шаги
    planner_raw = str(planner_output) if planner_output else ""
    
    # Если план содержит нумерацию (1., 2., -, •) — разбиваем на шаги
    import re
    plan_steps = []
    
    # Ищем нумерованные или маркированные пункты
    numbered = re.findall(r'(?:^|\n)\s*(?:\d+[.):]\s*|-\s+|\*\s+|•\s+)([^\n]+)', planner_raw)
    if numbered:
        plan_steps = [s.strip() for s in numbered if s.strip()]
    
    # Если не нашли структуру — используем как есть, но разбиваем по предложениям
    if not plan_steps and len(planner_raw) > 100:
        # Разбиваем по точкам, но осторожно (не разрываем URL)
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-ZА-Я])', planner_raw)
        plan_steps = [s.strip() for s in sentences if len(s.strip()) > 10]
    
    # Если всё ещё пусто — используем оригинал
    if not plan_steps:
        plan_steps = [planner_raw]
    
    # Формируем структурированный план для AI
    structured_plan = "ПЛАН ДЕЙСТВИЙ:\n"
    for i, step in enumerate(plan_steps[:15], 1):  # макс 15 шагов
        structured_plan += f"{i}. {step}\n"
    structured_plan += f"\nВыполни ВСЕ шаги по порядку. Максимум действий: {max_actions}\n"
    
    # Заменяем planner_output на структурированный план
    planner_output = structured_plan
    
    # --- 3. Промпт ---
    system = getattr(node, "system_prompt", "") or (
        "Ты — браузерный агент. Получаешь задачу и список элементов страницы.\n"
        "Формат: 'cx,cy|tag*|\"текст\"|ph:placeholder|a:aria-label|n:name|t:type|→href'\n"
        "* после tag = интерактивный (кликабельный)\n"
        "cx,cy = координаты ЦЕНТРА элемента для клика — используй ТОЛЬКО их!\n\n"
        "ПРАВИЛА:\n"
        "1. click_xy: клик по cx,cy — основной способ взаимодействия\n"
        "2. type_text: target='cx,cy' (координаты поля ввода), value='текст'\n"
        "3. Для поиска: найди поле с ph: или a: содержащим 'поиск/search/find' → клик → ввод\n"
        "4. Кнопки подтверждения обычно рядом с полем ввода (ниже или справа)\n"
        "5. После navigate подожди 2 сек (wait_seconds)\n\n"
        "Отвечай ТОЛЬКО JSON-массивом:\n"
        '[{"action":"click_xy","target":"400,200"},{"action":"type_text","target":"400,200","value":"текст"}]'
        "Отвечай ТОЛЬКО JSON-списком действий:\n"
        '[\n'
        '  {"action":"click_xy","target":"100,200"},\n'
        '  {"action":"type_text","target":"input[name=\\"q\\"]","value":"текст"},\n'
        '  {"action":"navigate","target":"https://example.com"},\n'
        '  {"action":"wait_seconds","value":"2"}\n'
        ']\n\n'
        "ДОСТУПНЫЕ action:\n"
        "- click_xy — клик по координатам (x,y) из DOM. ИСПОЛЬЗУЙ ЭТО по умолчанию для кликов!\n"
        "- click — клик по CSS-селектору (только если точно знаешь селектор)\n"
        "- double_click_xy — двойной клик по координатам\n"
        "- right_click_xy — правый клик по координатам\n"
        "- hover_xy — наведение на координаты\n"
        "- type_text — ввод текста. ФОРМАТ: target='x,y' (координаты) ИЛИ target='CSS-селектор'. value=текст\n"
        "  ПРИМЕР: {'action':'type_text','target':'500,300','value':'CodesSherlock'} — сначала кликнет по координатам, потом введёт текст\n"
        "- clear_field — очистить поле\n"
        "- get_text — получить текст элемента\n"
        "- navigate — переход по URL\n"
        "- wait_seconds — пауза в секундах (value='2')\n"
        "- scroll_page — прокрутка (value='500' пикселей)\n\n"
        "ПРАВИЛА:\n"
        "1. Для кликов ВСЕГДА используй click_xy с координатами из (cx,cy) — они надежнее селекторов\n"
        "2. Если элемент не найден — попробуй ближайшие координаты ±10 пикселей\n"
        "3. После navigate подожди 2 секунды (wait_seconds)\n"
        "4. Для поиска используй click_xy на поле ввода, затем type_text, затем клик по кнопке\n"
        "5. Не используй ID вроде [4] как селекторы — они не работают!"
    )

    user_prompt = (
        f"## Задача от Planner:\n{planner_output}\n\n"
        f"## URL: {current_url}\n\n"
        f"## DOM страницы (сжатый):\n{dom_str}\n\n"
        f"Сформируй список из не более {max_actions} действий для выполнения задачи."
    )

    ai_timeout = getattr(node, "ai_timeout_sec", 120)
    logger(f"🤖 BROWSER_AGENT: запрос к AI (таймаут {ai_timeout}с)...")
    try:
        from core.models import ChatMessage, MessageRole
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=system),
            ChatMessage(role=MessageRole.USER, content=user_prompt),
        ]

        # Всегда запускаем в отдельном потоке с собственным event loop —
        # избегаем deadlock при вызове из asyncio-контекста
        import concurrent.futures as _cf

        def _run_ai_sync():
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
            try:
                if call_model_func:
                    return _loop.run_until_complete(call_model_func(messages))
                else:
                    async def _stream():
                        chunks = []
                        async for chunk in model_provider.stream(messages):
                            chunks.append(chunk)
                        return "".join(chunks)
                    return _loop.run_until_complete(_stream())
            finally:
                _loop.close()

        with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
            _fut = _ex.submit(_run_ai_sync)
            try:
                response_text = _fut.result(timeout=ai_timeout)
            except _cf.TimeoutError:
                logger(f"  ⏱ Таймаут ожидания ответа от AI ({ai_timeout} сек)")
                raise RuntimeError(f"AI response timeout after {ai_timeout} seconds")

    except Exception as e:
        logger(f"❌ BROWSER_AGENT: ошибка AI: {e}")
        import traceback
        logger(f"🔍 Трейс: {traceback.format_exc()[:500]}")
        return context

    logger(f"📋 BROWSER_AGENT: получен ответ ({len(response_text)} символов)")

    # --- 4. Парсим и выполняем действия ---
    import re, json as _json
    actions_data = []
    
    # Очистка от markdown-оберток
    clean_response = response_text.strip()
    if clean_response.startswith("```"):
        # Убираем ```json и ```
        clean_response = re.sub(r'^```(?:json)?\s*', '', clean_response)
        clean_response = re.sub(r'\s*```$', '', clean_response)
    
    # Способ 1: Прямой JSON-парсинг всего ответа
    try:
        parsed = _json.loads(clean_response)
        if isinstance(parsed, list):
            actions_data = parsed
            logger(f"  ✅ Парсинг: JSON-список, {len(actions_data)} действий")
        elif isinstance(parsed, dict):
            # Одиночное действие или обертка
            if "action" in parsed or "tool" in parsed:
                actions_data = [parsed]
                logger(f"  ✅ Парсинг: одиночное действие")
            elif "actions" in parsed and isinstance(parsed["actions"], list):
                actions_data = parsed["actions"]
                logger(f"  ✅ Парсинг: вложенный список actions, {len(actions_data)}")
    except _json.JSONDecodeError:
        pass
    
    # Способ 2: Поиск JSON-массива в тексте
    if not actions_data:
        array_match = re.search(r'\[\s*\{.*?\}\s*\]', clean_response, re.DOTALL)
        if array_match:
            try:
                actions_data = _json.loads(array_match.group(0))
                logger(f"  ✅ Парсинг: JSON из текста, {len(actions_data)} действий")
            except:
                pass
    
    # Способ 3: Поиск JSON-объектов по одному (для многострочного вывода)
    if not actions_data:
        objects = re.findall(r'\{[^{}]*"action"[^{}]*\}', clean_response)
        if objects:
            actions_data = []
            for obj_str in objects:
                try:
                    obj = _json.loads(obj_str)
                    if "action" in obj or "tool" in obj:
                        actions_data.append(obj)
                except:
                    pass
            if actions_data:
                logger(f"  ✅ Парсинг: найдено {len(actions_data)} JSON-объектов")
    
    # Способ 4: Текстовый парсинг (fallback для не-JSON ответов)
    if not actions_data:
        logger("  🔄 Текстовый парсинг...")
        text_lower = clean_response.lower()
        
        # Навигация
        url_match = re.search(r'https?://[^\s"\'<>]+', clean_response)
        if url_match and ("перейди" in text_lower or "navigate" in text_lower or "открой" in text_lower):
            actions_data.append({"action": "navigate", "target": url_match.group(0)})
        
        # Клики по координатам (ищем числа в скобках или рядом)
        coord_matches = re.findall(r'\(?(\d{2,4})\s*[,;]\s*(\d{2,4})\)?', clean_response)
        for x, y in coord_matches[:3]:  # максимум 3 клика
            actions_data.append({"action": "click_xy", "target": f"{x},{y}"})
        
        # Поиск и ввод текста
        if "найди" in text_lower or "поиск" in text_lower or "введи" in text_lower:
            # Ищем текст в кавычках
            quoted = re.findall(r'["\']([^"\']{3,50})["\']', clean_response)
            for text in quoted[:2]:
                actions_data.append({"action": "type_text", "target": "input[type=\"text\"], input[name=\"q\"], #search, [name=\"q\"]", "value": text})
                actions_data.append({"action": "wait_seconds", "value": "1"})
        
        # Ожидание
        wait_match = re.search(r'подожди\s+(\d+)|wait\s+(\d+)', text_lower)
        if wait_match:
            sec = wait_match.group(1) or wait_match.group(2)
            actions_data.append({"action": "wait_seconds", "value": sec})
        
        if actions_data:
            logger(f"  ✅ Текстовый парсинг: {len(actions_data)} действий")

    if not actions_data:
        logger("⚠️ BROWSER_AGENT: AI не вернул список действий")
        context["browser_agent_raw"] = response_text
        return context

    executed_count = 0
    for i, act_cfg in enumerate(actions_data):
        if not isinstance(act_cfg, dict):
            logger(f"  ⚠️ Пропускаем не-объект: {act_cfg}")
            continue
        
        # === НОРМАЛИЗАЦИЯ: приводим разные форматы к единому виду ===
        normalized = {}
        
        # Копируем все ключи в нижний регистр
        for k, v in act_cfg.items():
            normalized[k.lower()] = v
        
        # Поддержка tool вместо action
        if "tool" in normalized and "action" not in normalized:
            normalized["action"] = normalized["tool"]
        
        # Поддержка params для сложных действий
        if "params" in normalized and isinstance(normalized["params"], dict):
            p = normalized["params"]
            if "url" in p:
                normalized["target"] = p["url"]
                normalized["action"] = "navigate"
            if "selector" in p:
                normalized["target"] = p["selector"]
            if "text" in p or "command" in p:
                normalized["value"] = p.get("text") or p.get("command", "")
            if "x" in p and "y" in p:
                normalized["target"] = f"{p['x']},{p['y']}"
                if normalized.get("action") == "click":
                    normalized["action"] = "click_xy"
            if "duration" in p or "seconds" in p:
                normalized["value"] = str(p.get("duration") or p.get("seconds", "1"))
                normalized["action"] = "wait_seconds"
        
        # Извлекаем значения
        action_type = normalized.get("action", "navigate")
        target = str(normalized.get("target", "")).strip()
        value = str(normalized.get("value", "")).strip()
        
        # === КОНВЕРТАЦИЯ: type_text с координатами ===
        if action_type == "type_text" and target:
            # Если target выглядит как координаты "123,456" — оставляем как есть (type_text теперь поддерживает это)
            coord_pattern = r'^\(?(\d{2,4})\s*[,;]\s*(\d{2,4})\)?$'
            if re.match(coord_pattern, target):
                logger(f"  🔄 type_text с координатами: клик ({target}) затем ввод текста")
        
        # === КОНВЕРТАЦИЯ: click → click_xy если target выглядит как координаты ===
        if action_type == "click" and target:
            # Проверяем формат "123,456" или "(123, 456)"
            coord_pattern = r'^\(?(\d{2,4})\s*[,;]\s*(\d{2,4})\)?$'
            coord_match = re.match(coord_pattern, target)
            if coord_match:
                action_type = "click_xy"
                target = f"{coord_match.group(1)},{coord_match.group(2)}"
                logger(f"  🔄 Автоконвертация: click → click_xy ({target})")
        
        # === КОНВЕРТАЦИЯ: click по [id] → click_xy с поиском координат ===
        if action_type in ("click", "click_js") and target.startswith('[') and ']' in target:
            # Извлекаем ID вида [4]
            id_match = re.match(r'\[(\d+)\]', target)
            if id_match:
                el_id = int(id_match.group(1))
                # Ищем элемент с таким ID в interactive_elements
                found_el = None
                for el in interactive_elements:
                    if el.get("id") == el_id:
                        found_el = el
                        break
                if found_el:
                    cx, cy = found_el.get("cx", 0), found_el.get("cy", 0)
                    if cx > 0 and cy > 0:
                        action_type = "click_xy"
                        target = f"{cx},{cy}"
                        logger(f"  🔄 Конвертация: [{el_id}] → click_xy ({target}) — {found_el.get('text', '')[:30]}")
                    else:
                        logger(f"  ⚠️ Элемент [{el_id}] найден, но координаты нулевые")
                else:
                    logger(f"  ⚠️ Элемент [{el_id}] не найден в DOM")
        
        # Очистка URL
        if action_type == "navigate" and target:
            target = target.strip('"\'<> ')
        
        # === ВЫПОЛНЕНИЕ ===
        action = BrowserAction(
            action=action_type,
            target=target,
            value=value,
            variable_out=str(normalized.get("variable_out", "")).strip("{}"),
            timeout=int(normalized.get("timeout", 15)),
            wait_after=float(normalized.get("wait_after", 0.5)),
            selector_type=normalized.get("selector_type", "css"),
        )
        
        logger(f"  [{i+1}/{len(actions_data)}] {action.action}: {action.target[:60] if action.target else '(пусто)'}")
        if action.value:
            logger(f"      value: {action.value[:40]}...")
        
        try:
            result = inst.execute_action(action)
            executed_count += 1
            
            # Сохраняем результат
            var_out = action.variable_out
            if var_out and result is not None:
                context[var_out] = result
            
            # Пауза между действиями для стабильности
            if i < len(actions_data) - 1 and action_wait_sec > 0:
                import time
                time.sleep(action_wait_sec)
                
        except Exception as e:
            logger(f"  ❌ Ошибка действия {action.action}: {e}")
            # Продолжаем со следующего действия, не прерываем весь план
            continue
    
    logger(f"✅ Выполнено {executed_count}/{len(actions_data)} действий")
    # --- 5. Скриншот ПОСЛЕ + diff ---
    if do_screenshot and before_b64:
        after_b64 = inst.get_screenshot_base64()
        changed, ratio = inst.compare_screenshots(before_b64, after_b64, diff_threshold)
        context["browser_agent_screenshot_changed"] = changed
        context["browser_agent_screenshot_diff"] = round(ratio, 4)
        logger(
            f"📸 BROWSER_AGENT: пиксельная верификация — "
            f"{'✅ изменение обнаружено' if changed else '⚠️ изменений нет'} "
            f"(diff={ratio:.2%})"
        )

    context["browser_agent_actions_count"] = len(actions_data)
    return context
    
    
# ══════════════════════════════════════════════════════════════
#  ProgramInstancePanel — вкладка открытых программ (аналог BrowserInstancePanel)
# ══════════════════════════════════════════════════════════════
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QLabel, QGroupBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QImage
import ctypes, base64, io

class ProgramTrayMiniature(QWidget):
    """Миниатюра одной открытой программы — аналог BrowserTrayMiniature."""

    def __init__(self, instance_key: str, entry: dict, runtime_ref, parent=None):
        super().__init__(parent)
        self.instance_key = instance_key  # строковый ключ, например "notepad.exe_0"
        self.pid = entry.get('pid', 0)    # числовой PID только для WinAPI
        self.entry = entry
        self._runtime = runtime_ref
        self._build_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_screenshot)
        self._refresh_timer.start(2000)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Заголовок: имя программы или ключ экземпляра
        name = self.entry.get('name') or self.instance_key
        self._lbl_title = QLabel(f"🖥 {name}")
        self._lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_title.setStyleSheet("font-weight:bold;font-size:11px;")
        self._lbl_title.setToolTip(f"Key: {self.instance_key}\nPID: {self.pid}")
        layout.addWidget(self._lbl_title)

        self._lbl_screen = QLabel()
        self._lbl_screen.setFixedSize(200, 130)
        self._lbl_screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_screen.setStyleSheet(
            f"background:{get_color('bg2')};border:1px solid {get_color('bd')};")
        layout.addWidget(self._lbl_screen)

        btn_row = QHBoxLayout()
        btn_show = QPushButton(tr("👁 Показать"))
        btn_show.clicked.connect(self._show_window)
        btn_hide = QPushButton(tr("🙈 Скрыть"))
        btn_hide.clicked.connect(self._hide_window)
        btn_close = QPushButton(tr("✖ Закрыть"))
        btn_close.clicked.connect(self._close_window)
        btn_row.addWidget(btn_show)
        btn_row.addWidget(btn_hide)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self.setStyleSheet(
            f"QWidget{{background:{get_color('bg1')};border-radius:6px;}}"
            f"QLabel{{color:{get_color('tx0')};}}"
            f"QPushButton{{background:{get_color('bg2')};color:{get_color('tx0')};"
            f"border:1px solid {get_color('bd')};border-radius:3px;padding:2px 6px;}}"
            f"QPushButton:hover{{background:{get_color('bg3')};}}"
        )
        self.setFixedWidth(220)

    def _get_hwnd(self) -> int:
        return self.entry.get('hwnd', 0)

    def _refresh_screenshot(self):
        hwnd = self._get_hwnd()
        if not hwnd:
            return
        try:
            import win32gui, win32ui, win32con
            left, top, right, bot = win32gui.GetWindowRect(hwnd)
            w, h = right - left, bot - top
            if w <= 0 or h <= 0:
                return
            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(bmp)
            ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)
            bmpinfo = bmp.GetInfo()
            bmpstr = bmp.GetBitmapBits(True)
            img = QImage(bmpstr, bmpinfo['bmWidth'], bmpinfo['bmHeight'], QImage.Format.Format_ARGB32)
            pix = QPixmap.fromImage(img).scaled(200, 130, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)
            self._lbl_screen.setPixmap(pix)
            win32gui.DeleteObject(bmp.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            self._lbl_screen.setText("📸 нет скриншота")

    def _show_window(self):
        hwnd = self._get_hwnd()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
            ctypes.windll.user32.MoveWindow(hwnd, 100, 100,
                                             self.entry.get('win_w', 800),
                                             self.entry.get('win_h', 600), True)
            ctypes.windll.user32.SetForegroundWindow(hwnd)

    def _hide_window(self):
        hwnd = self._get_hwnd()
        if hwnd:
            ox = self.entry.get('offscreen_x', 20000)
            oy = self.entry.get('offscreen_y', 20000)
            ctypes.windll.user32.MoveWindow(hwnd, ox, oy,
                                             self.entry.get('win_w', 800),
                                             self.entry.get('win_h', 600), True)

    def _close_window(self):
        """Закрыть окно программы и удалить миниатюру из трея."""
        hwnd = self._get_hwnd()
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        
        # Убираем из реестра и из трея немедленно по строковому ключу
        panel = getattr(self, '_panel_ref', None)
        if panel:
            panel._remove_program(self.instance_key)
        
        # Дополнительная очистка из всех возможных мест хранения
        try:
            panel = self.parent().parent()  # ProgramInstancePanel
            mw = panel._main_window
            for attr in ('_runtime_thread', '_runtime'):
                rt = getattr(mw, attr, None)
                if rt and hasattr(rt, '_context'):
                    rt._context.get('_open_programs', {}).pop(self.instance_key, None)
            tab = mw._current_project_tab() if hasattr(mw, '_current_project_tab') else None
            if tab:
                for a in ('_last_runtime', '_runtime', '_runtime_thread'):
                    rt3 = getattr(tab, a, None)
                    if rt3 and hasattr(rt3, '_context'):
                        rt3._context.get('_open_programs', {}).pop(self.instance_key, None)
                getattr(tab, '_last_open_programs', {}).pop(self.instance_key, None)
            getattr(mw, '_last_open_programs', {}).pop(self.instance_key, None)
        except Exception:
            pass
        
        # Немедленно убираем миниатюру из UI
        try:
            panel = self.parent().parent()
            if hasattr(panel, '_miniatures') and self.instance_key in panel._miniatures:
                panel._miniatures.pop(self.instance_key)
                panel._flow.removeWidget(self)
                self.deleteLater()
        except Exception:
            pass

class ProgramInstancePanel(QWidget):
    """Панель управления открытыми программами — аналог BrowserInstancePanel."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self._miniatures: dict[str, ProgramTrayMiniature] = {}  # <-- строковые ключи
        self._build_ui()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._refresh)
        self._poll_timer.start(1500)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # ── Заголовок ──
        hdr = QHBoxLayout()
        lbl_title = QLabel(tr("🖥 Открытые программы"))
        lbl_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #FF9E64;")
        hdr.addWidget(lbl_title)
        hdr.addStretch()
        btn_refresh = QPushButton(tr("🔄 Обновить"))
        btn_refresh.setFixedHeight(26)
        btn_refresh.setStyleSheet(
            f"QPushButton {{ background: {get_color('bg2')}; color: #7AA2F7;"
            f" border: 1px solid #7AA2F7; border-radius: 4px; padding: 0 8px; font-size: 11px; }}"
            f"QPushButton:hover {{ background: #7AA2F7; color: #000; }}")
        btn_refresh.clicked.connect(self._refresh)
        hdr.addWidget(btn_refresh)
        layout.addLayout(hdr)

        # ── Подсказка ──
        self._lbl_empty = QLabel(
            tr("Нет открытых программ.\n"
               "Используйте сниппет 🖥 Program Open\n"
               "с опцией «Скрыть за экран» для управления программами здесь.")
        )
        self._lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_empty.setStyleSheet(
            f"color: {get_color('tx2')}; font-size: 11px; padding: 20px;"
            f" border: 1px dashed {get_color('bd')}; border-radius: 6px;")
        self._lbl_empty.setWordWrap(True)
        layout.addWidget(self._lbl_empty)

        # ── Скролл с миниатюрами ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._flow = QHBoxLayout(self._container)
        self._flow.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._flow.setSpacing(10)
        self._flow.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(self._container)
        layout.addWidget(scroll)
    
    def apply_theme(self):
        """Обновить цвета по текущей теме."""
        self._build_ui_styles()

    def _build_ui_styles(self):
        if hasattr(self, '_lbl_empty'):
            self._lbl_empty.setStyleSheet(
                f"color: {get_color('tx2')}; font-size: 11px; padding: 20px;"
                f" border: 1px dashed {get_color('bd')}; border-radius: 6px;")
        for mini in self._miniatures.values():
            mini.setStyleSheet(
                f"QWidget{{background:{get_color('bg1')};border-radius:6px;}}"
                f"QLabel{{color:{get_color('tx0')};}}"
                f"QPushButton{{background:{get_color('bg2')};color:{get_color('tx0')};"
                f"border:1px solid {get_color('bd')};border-radius:3px;padding:2px 6px;}}"
                f"QPushButton:hover{{background:{get_color('bg3')};}}"
            )
    
    def _get_open_programs(self) -> dict:
        """Получить реестр открытых программ из активного runtime или сохранённого состояния."""
        try:
            mw = self._main_window
            # Вариант 1: живой runtime_thread
            rt = getattr(mw, '_runtime_thread', None)
            if rt and hasattr(rt, '_context'):
                progs = rt._context.get('_open_programs', {})
                if progs:
                    return progs
            # Вариант 2: WorkflowRuntimeEngine
            rt2 = getattr(mw, '_runtime', None)
            if rt2 and hasattr(rt2, '_context'):
                progs = rt2._context.get('_open_programs', {})
                if progs:
                    return progs
            # Вариант 3: из project tab (живой или сохранённый)
            tab = mw._current_project_tab()
            if tab:
                for attr in ('_last_runtime', '_runtime', '_runtime_thread'):
                    rt3 = getattr(tab, attr, None)
                    if rt3 and hasattr(rt3, '_context'):
                        progs = rt3._context.get('_open_programs', {})
                        if progs:
                            return progs
                # Вариант 4: сохранённые программы после завершения workflow
                saved = getattr(tab, '_last_open_programs', {})
                if saved:
                    return saved
            # Вариант 5: сохранённые на главном окне
            saved_mw = getattr(mw, '_last_open_programs', {})
            if saved_mw:
                return saved_mw
        except Exception:
            pass
        return {}

    def _remove_program(self, instance_key: str):
        """Удалить программу из реестра и убрать миниатюру из трея по строковому ключу."""
        # Удаляем из всех возможных мест хранения
        try:
            mw = self._main_window
            for attr in ('_runtime_thread', '_runtime'):
                rt = getattr(mw, attr, None)
                if rt and hasattr(rt, '_context'):
                    rt._context.get('_open_programs', {}).pop(instance_key, None)
            tab = mw._current_project_tab() if hasattr(mw, '_current_project_tab') else None
            if tab:
                for a in ('_last_runtime', '_runtime', '_runtime_thread'):
                    rt3 = getattr(tab, a, None)
                    if rt3 and hasattr(rt3, '_context'):
                        rt3._context.get('_open_programs', {}).pop(instance_key, None)
                getattr(tab, '_last_open_programs', {}).pop(instance_key, None)
            getattr(mw, '_last_open_programs', {}).pop(instance_key, None)
        except Exception:
            pass
        
        # Убираем виджет из UI
        if instance_key in self._miniatures:
            w = self._miniatures.pop(instance_key)
            self._flow.removeWidget(w)
            w.deleteLater()
        
        has_programs = len(self._miniatures) > 0
        self._lbl_empty.setVisible(not has_programs)
        self._container.setVisible(has_programs)

    def _refresh(self):
        """Обновить список миниатюр; автоматически убирает завершённые процессы."""
        import ctypes as _ct

        def _pid_alive(pid: int) -> bool:
            try:
                h = _ct.windll.kernel32.OpenProcess(0x100000, False, pid)
                if not h:
                    return False
                ret = _ct.windll.kernel32.WaitForSingleObject(h, 0)
                _ct.windll.kernel32.CloseHandle(h)
                return ret == 0x102   # WAIT_TIMEOUT = процесс жив
            except Exception:
                return False

        programs = self._get_open_programs()

        # ── Находим мёртвые PID и чистим все хранилища ───────────────────────
        dead_keys: set[str] = set()
        for key, entry in list(programs.items()):
            pid = int(entry.get('pid', 0) or 0)
            if pid and not _pid_alive(pid):
                dead_keys.add(key)

        if dead_keys:
            mw = self._main_window
            # runtime context
            for _attr in ('_runtime_thread', '_runtime'):
                _rt = getattr(mw, _attr, None)
                if _rt and hasattr(_rt, '_context'):
                    for dk in dead_keys:
                        _rt._context.get('_open_programs', {}).pop(dk, None)
            # tab storage
            try:
                _tab = mw._current_project_tab() if hasattr(mw, '_current_project_tab') else None
                if _tab:
                    for _a in ('_last_runtime', '_runtime', '_runtime_thread'):
                        _rt3 = getattr(_tab, _a, None)
                        if _rt3 and hasattr(_rt3, '_context'):
                            for dk in dead_keys:
                                _rt3._context.get('_open_programs', {}).pop(dk, None)
                    _lop = getattr(_tab, '_last_open_programs', {})
                    for dk in dead_keys:
                        _lop.pop(dk, None)
            except Exception:
                pass
            # main window storage
            for dk in dead_keys:
                getattr(mw, '_last_open_programs', {}).pop(dk, None)
            # workflow metadata
            try:
                _wf = getattr(mw, '_workflow', None)
                if _wf and isinstance(getattr(_wf, 'metadata', None), dict):
                    _meta = _wf.metadata.get('_open_programs_meta', {})
                    for dk in dead_keys:
                        _meta.pop(dk, None)
            except Exception:
                pass

        # ── Актуальный набор живых ключей ─────────────────────────────────────
        current_keys = set(programs.keys()) - dead_keys
        shown_keys   = set(self._miniatures.keys())

        # Убираем из UI то, чего нет среди живых
        for key in shown_keys - current_keys:
            w = self._miniatures.pop(key)
            self._flow.removeWidget(w)
            w.deleteLater()

        # Добавляем новые / обновляем существующие
        for key in current_keys:
            entry = programs[key]
            if key not in self._miniatures:
                mini = ProgramTrayMiniature(key, entry, None, self._container)
                mini._panel_ref = self
                self._miniatures[key] = mini
                self._flow.addWidget(mini)
            else:
                self._miniatures[key].entry = entry
                self._miniatures[key].pid   = entry.get('pid')

        has_programs = len(self._miniatures) > 0
        self._lbl_empty.setVisible(not has_programs)
        self._container.setVisible(has_programs)