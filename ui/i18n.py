"""
i18n.py — Advanced Internationalization for AI Code Sherlock.

Features:
  * Instant language switching (no restart needed)
  * Russian pluralization (1 патч / 2 патча / 5 патчей)
  * English pluralization (1 patch / 2 patches)
  * Deep recursive widget walker — retranslates text, tooltips,
    placeholders, QComboBox items, QListWidget items, QTabWidget tabs
  * Missing-key detection — untranslated keys get a mark prefix in UI
    and are logged for developer review
  * Listener system — widgets register callbacks for live updates

Usage:
    from ui.i18n import tr, tr_plural, set_language, get_language

    set_language("en")
    print(tr("Новый проект"))                      # -> "New Project"
    print(tr_plural(3, "файл", "файла", "файлов")) # -> "3 files"
    print(tr_plural(5, "файл"))                     # -> "5 файлов" (ru) / "5 files" (en)

Supported: "ru" (default, identity), "en"
"""
from __future__ import annotations

import sys
import threading
from typing import Callable

_current_lang: str = "ru"
_lock = threading.Lock()
_listeners: list[Callable] = []

# Track missing keys for developer debugging
_missing_keys: set[str] = set()
_missing_key_marker: str = "\u26a0\ufe0f "  # prepended to untranslated strings
_debug_missing: bool = False                  # set True to print missing keys to stderr


# =====================================================================
#  Pluralization Engine
# =====================================================================

def _ru_plural_idx(n: int) -> int:
    """
    Russian pluralization index.
    0 -> "1 файл"   1 -> "2 файла"   2 -> "5 файлов"
    """
    abs_n = abs(n)
    mod10, mod100 = abs_n % 10, abs_n % 100
    if mod10 == 1 and mod100 != 11:
        return 0
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return 1
    return 2

def _en_plural_idx(n: int) -> int:
    return 0 if abs(n) == 1 else 1


# Plural forms table
# Key = Russian base form, value = {"ru": (form1, form2_4, form5+), "en": (sing, plur)}
_PLURAL_FORMS: dict[str, dict[str, tuple]] = {
    "патч":              {"ru": ("патч", "патча", "патчей"),             "en": ("patch", "patches")},
    "патч(ей)":          {"ru": ("патч", "патча", "патчей"),             "en": ("patch", "patches")},
    "файл":              {"ru": ("файл", "файла", "файлов"),             "en": ("file", "files")},
    "файл(ов)":          {"ru": ("файл", "файла", "файлов"),             "en": ("file", "files")},
    "строка":            {"ru": ("строка", "строки", "строк"),           "en": ("line", "lines")},
    "строк":             {"ru": ("строка", "строки", "строк"),           "en": ("line", "lines")},
    "версия":            {"ru": ("версия", "версии", "версий"),          "en": ("version", "versions")},
    "версий":            {"ru": ("версия", "версии", "версий"),          "en": ("version", "versions")},
    "итерация":          {"ru": ("итерация", "итерации", "итераций"),    "en": ("iteration", "iterations")},
    "модель":            {"ru": ("модель", "модели", "моделей"),         "en": ("model", "models")},
    "токен":             {"ru": ("токен", "токена", "токенов"),          "en": ("token", "tokens")},
    "токенов":           {"ru": ("токен", "токена", "токенов"),          "en": ("token", "tokens")},
    "секунда":           {"ru": ("секунда", "секунды", "секунд"),        "en": ("second", "seconds")},
    "ошибка":            {"ru": ("ошибка", "ошибки", "ошибок"),          "en": ("error", "errors")},
    "ошибок":            {"ru": ("ошибка", "ошибки", "ошибок"),          "en": ("error", "errors")},
    "скрипт":            {"ru": ("скрипт", "скрипта", "скриптов"),       "en": ("script", "scripts")},
    "событие":           {"ru": ("событие", "события", "событий"),        "en": ("event", "events")},
    "вкладка":           {"ru": ("вкладка", "вкладки", "вкладок"),       "en": ("tab", "tabs")},
    "попытка":           {"ru": ("попытка", "попытки", "попыток"),       "en": ("attempt", "attempts")},
    "вариант":           {"ru": ("вариант", "варианта", "вариантов"),    "en": ("variant", "variants")},
    "неудача":           {"ru": ("неудача", "неудачи", "неудач"),        "en": ("failure", "failures")},
    "файл для патчинга": {"ru": ("файл для патчинга", "файла для патчинга", "файлов для патчинга"),
                          "en": ("patch target file", "patch target files")},
}


_RU_TO_EN: dict[str, str] = {
    "⚡ Pipeline":                   "⚡ Pipeline",
    "патч(ей)":                      "patch(es)",
    # ── Toolbar ──────────────────────────────────────────────
    "📋 Новый проект":       "📋 New Project",
    "📁 Открыть проект":     "📁 Open Project",
    "📄 Файл":               "📄 File",
    "💾 Сохранить":          "💾 Save",
    "🔍 Шерлок":             "🔍 Sherlock",
    "📋 Логи→AI":            "📋 Logs→AI",
    "🆕 Новый":              "🆕 New",
    "⏪ История":            "⏪ History",
    "🗂 Карта ошибок":       "🗂 Error Map",
    "⚡ Pipeline":           "⚡ Pipeline",
    "▶ Запустить скрипт":    "▶ Run Script",
    "📥 Логи":               "📥 Logs",
    "○ Сигнал":              "○ Signal",
    "⟳ Обработка...":       "⟳ Processing...",
    "■ Стоп":                "■ Stop",
    # ── Tab labels ───────────────────────────────────────────
    "💬 Диалог":             "💬 Chat",
    "📋 Логи":               "📋 Logs",
    "📦 Контекст":           "📦 Context",
    "📡 Сигналы":            "📡 Signals",
    "⚡ Авто-запуск":        "⚡ Auto-run",
    "КОД":                   "CODE",
    "ПАТЧИ AI":              "AI PATCHES",
    "ПРОВОДНИК":             "EXPLORER",
    # ── Input area ───────────────────────────────────────────
    "Активный файл":         "Active File",
    "Логи ошибок":           "Error Logs",
    "Весь проект (скелет)":  "Full Project (skeleton)",
    "Стратегия:":            "Strategy:",
    "Вариантов:":            "Variants:",
    "🤝 Консенсус":          "🤝 Consensus",
    "⚙ Модели":              "⚙ Models",
    "✏ Свои":                "✏ Custom",
    "▶ Отправить  Ctrl+↵":   "▶ Send  Ctrl+↵",
    "Задай вопрос или опиши изменение...  (Ctrl+Enter — отправить)":
        "Ask a question or describe the change...  (Ctrl+Enter — send)",
    # ── Patches panel ────────────────────────────────────────
    "0 патчей":              "0 patches",
    "✓ Все":                 "✓ All",
    "🔍\n\nПатчей нет\nОтправь запрос AI":
        "🔍\n\nNo patches\nSend an AI request",
    # ── Context tab ──────────────────────────────────────────
    "КОНТЕКСТ AI":           "AI CONTEXT",
    "↺ Обновить":            "↺ Refresh",
    "Контекст не построен":  "Context not built",
    "Открой файл и отправь запрос для построения контекста...":
        "Open a file and send a request to build context...",
    # ── Signals tab ──────────────────────────────────────────
    "МОНИТОРИНГ СИГНАЛОВ":  "SIGNAL MONITOR",
    "○ Остановлен":          "○ Stopped",
    "▶ Запустить":           "▶ Start",
    "■ Стоп":                "■ Stop",
    "События файловых сигналов появятся здесь...":
        "File signal events will appear here...",
    "Событий: 0":            "Events: 0",
    # ── Status bar ───────────────────────────────────────────
    "нет модели":            "no model",
    "Готов":                 "Ready",
    "Обработка...":          "Processing...",
    "Сжимаю контекст...":    "Compressing context...",
    "Генерирую ответ...":    "Generating response...",
    # ── Script runner / Logs tab interactive stdin ────────────
    "Ввод для запущенного скрипта... (Enter — отправить)":
        "Input for running script... (Enter — send)",
    "Отправить ввод скрипту":     "Send input to script",
    "Выполняю":                   "Running",
    "⏹ Операция остановлена":     "⏹ Operation stopped",
    # ── Auto-run panel sub-tabs ───────────────────────────────
    "📡 Лайв-лог":           "📡 Live Log",
    "🤖 AI анализ":          "🤖 AI Analysis",
    "✂️ Патчи":              "✂️ Patches",
    "📤 Промпт":             "📤 Prompt",
    "🤖 Ответ AI":           "🤖 AI Response",
    # ── Auto-run panel placeholder texts ─────────────────────
    "Промпт появится здесь когда AI начнёт анализ...":
        "Prompt will appear here when AI begins analysis...",
    "Ответ AI появится здесь после анализа...":
        "AI response will appear here after analysis...",
    "Применённые патчи появятся здесь...":
        "Applied patches will appear here...",
    # ── File tree ────────────────────────────────────────────
    "Поиск файлов...":       "Search files...",
    "Папка не открыта":      "No folder open",
    "📄  Открыть в редакторе":    "📄  Open in editor",
    "🔍  Отправить в AI":         "🔍  Send to AI",
    "📋  Копировать путь":         "📋  Copy path",
    "🗂  Показать в проводнике":   "🗂  Show in Explorer",
    "📂  Раскрыть":                "📂  Expand",
    "📌 Переключить закладку":     "📌 Toggle bookmark",
    "Очистить закладки":           "Clear bookmarks",
    "⊕ Развернуть всё":            "⊕ Expand all",
    "⊖ Свернуть всё":              "⊖ Collapse all",
    # ── Constructor / Agent Builder ───────────────────────────
    "🤖 Конструктор AI-агентов — AI Code Sherlock": "🤖 AI Agent Constructor — AI Code Sherlock",
    "📄 Новый":                      "📄 New",
    "📁 Рабочая папка:":             "📁 Working folder:",
    "Выберите папку для создания файлов...": "Select a folder to create files...",
    "Обзор...":                      "Browse...",
    "Создать новую подпапку с датой-временем в текущей рабочей папке":
        "Create a new dated subfolder in the current working folder",
    "Сохранить путь рабочей папки в проект workflow":
        "Save working folder path to workflow project",
    "📂 Открыть":                    "📂 Open",
    "⚡ Запуск":                     "⚡ Launch",
    "📊 Менеджер":                   "📊 Manager",
    "Менеджер проектов — управление всеми проектами\nЗапуск, остановка, расписание, потоки":
        "Project manager — manage all projects\nLaunch, stop, schedule, threads",
    # ── Lists / Tables inline panel ─────────────────────────
    "📋 Списки / Таблицы":           "📋 Lists / Tables",
    "📋 Списки / Таблицы  ▼":        "📋 Lists / Tables  ▼",
    "📋 Списки / Таблицы  ▲":        "📋 Lists / Tables  ▲",
    "➕ Список":                      "➕ List",
    "➕ Таблица":                     "➕ Table",
    "➕ База данных":                 "➕ Database",
    "➕ Настройки":                   "➕ Settings",
    # ── Debug / Run panel ────────────────────────────────────
    "⚡⚡ Все проекты":               "⚡⚡ All Projects",
    "Запустить отладку сразу на всех открытых вкладках.\nЛКМ — с начала каждого проекта\nПКМ — подменю: с начала / от текущего узла":
        "Run debugging on all open tabs at once.\nLMB — from the start of each project\nRMB — submenu: from start / from current node",
    "⛔ Стоп все":                    "⛔ Stop All",
    "Остановить выполнение на всех открытых вкладках":
        "Stop execution on all open tabs",
    "▶ Старт":                       "▶ Start",
    "F5 — Запуск с начала":          "F5 — Run from beginning",
    "▶| От выбранного":              "▶| From selected",
    "F6 — Запуск от выбранного сниппета до конца":
        "F6 — Run from selected snippet to end",
    "☑ Только выбранные":            "☑ Selected only",
    "F7 — Выполнить только выделенные сниппеты":
        "F7 — Execute only highlighted snippets",
    "⏭ По шагам":                    "⏭ Step-by-step",
    "F8 — Запуск в пошаговом режиме (пауза перед каждым)":
        "F8 — Run in step mode (pause before each)",
    "⏭ Шаг (F10)":                   "⏭ Step (F10)",
    "⏩ Продолжить":                  "⏩ Continue",
    "⏹ Стоп":                        "⏹ Stop",
    # ── Constructor log messages ─────────────────────────────
    "СТАРТ":                          "START",
    "Новый проект создан":            "New project created",
    "Добавлен агент:":                "Agent added:",
    "Связь:":                         "Connection:",
    "↩️ Нечего отменять":             "↩️ Nothing to undo",
    "↪️ Нечего повторять":            "↪️ Nothing to redo",
    "🗑️ Удалено:":                    "🗑️ Deleted:",
    "агентов":                        "agents",
    "связей":                         "connections",
    "Открыт:":                        "Opened:",
    "Сохранён:":                      "Saved:",
    "ВЫКЛ":                           "OFF",
    "ВКЛ":                            "ON",
    "🎬 Анимация выполнения:":        "🎬 Execution animation:",
    "▶| Запуск от:":                  "▶| Running from:",
    "☑ Только выбранные:":            "☑ Selected only:",
    "↩️ Восстановлен полный workflow": "↩️ Full workflow restored",
    "⏭ Пошаговый режим":              "⏭ Step-by-step mode",
    "⚠ Проект":                       "⚠ Project",
    "уже выполняется, пропускаем":    "already running, skipping",
    "⚡ Запущено":                     "⚡ Started",
    "проектов":                       "projects",
    "от текущей позиции":             "from current position",
    "с начала":                       "from the beginning",
    "⏹ Все проекты остановлены":      "⏹ All projects stopped",
    "✅ Стартовое действие":           "✅ Entry point",
    "▶ Установить как стартовое":     "▶ Set as entry point",
    "⏺ Запись":                      "⏺ Record",
    "Отладка:":                      "Debug:",
    "Готов":                         "Ready",
    "Без анимации":                  "No animation",
    "Отключить анимацию выполнения (подсветку нод, centerOn).\nУскоряет выполнение, не дёргает канвас.\nРезультат виден в логе и диалоге агентов.":
        "Disable execution animation (node highlight, centerOn).\nSpeeds up execution, no canvas jumps.\nResult visible in log and agent dialog.",
    "🌐 Закрывать браузер":          "🌐 Close browser",
    "Закрывать все браузеры проекта автоматически по завершении workflow.\nВыключите, если нужно оставить браузер открытым после выполнения.":
        "Auto-close all project browsers when workflow finishes.\nDisable if you need the browser open after execution.",
    # ── Main window (title bar) support buttons ──────────────
    "💬 Форум":                      "💬 Forum",
    "Открыть форум поддержки в браузере":  "Open support forum in browser",
    "🛟 Поддержка":                  "🛟 Support",
    "Открыть документацию и FAQ":    "Open documentation and FAQ",
    "❤ Донат":                       "❤ Donate",
    "Поддержать разработку проекта": "Support project development",
    # ── Program panel (browser_module) ───────────────────────
    "🖥 Открытые программы":         "🖥 Open Programs",
    "🔄 Обновить":                   "🔄 Refresh",
    "Нет открытых программ.\nИспользуйте сниппет 🖥 Program Open\nс опцией «Скрыть за экран» для управления программами здесь.":
        "No open programs.\nUse the 🖥 Program Open snippet\nwith the 'Hide offscreen' option to manage programs here.",
    "👁 Показать":                   "👁 Show",
    "🙈 Скрыть":                     "🙈 Hide",
    "✖ Закрыть":                     "✖ Close",
    # ── Zoom panel ───────────────────────────────────────────
    "🔍+":                           "🔍+",
    "Увеличить (Ctrl+колесо)":       "Zoom in (Ctrl+scroll)",
    "🔍−":                           "🔍−",
    "Уменьшить":                     "Zoom out",
    "⊞":                             "⊞",
    "Вместить всё":                  "Fit all",
    "100%":                          "100%",
    "Сбросить масштаб":              "Reset zoom",
    "Масштаб":                       "Zoom",
    "⏮ Начало":                      "⏮ Start",
    "Перейти к начальному узлу":     "Go to start node",
    "Конец ⏭":                       "End ⏭",
    "Перейти к последнему узлу":     "Go to end node",
    # ── GlobalSettingsDialog ─────────────────────────────────
    "⚙  Глобальные настройки":       "⚙  Global Settings",
    "Макс. параллельных проектов:":  "Max parallel projects:",
    "Сколько проектов можно запускать одновременно.\nОстальные ждут в очереди.":
        "How many projects can run simultaneously.\nOthers wait in the queue.",
    "Таймаут одного проекта:":       "Single project timeout:",
    " сек":                          " sec",
    "🧵 Потоки":                     "🧵 Threads",
    "Лимит ОЗУ (мягкий):":          "RAM limit (soft):",
    " МБ":                           " MB",
    "Предупреждение при ОЗУ >:":    "Warn when RAM >:",
    "💾 Память":                     "💾 Memory",
    "Макс. браузеров одновременно:": "Max concurrent browsers:",
    "Интервал скриншота (трей):":    "Screenshot interval (tray):",
    " мс":                           " ms",
    "Масштаб миниатюры:":           "Thumbnail scale:",
    " %":                            " %",
    "🌐 Браузеры":                   "🌐 Browsers",
    "Макс. глобальных потоков:":    "Max global threads:",
    "Максимальное количество потоков для ВСЕХ проектов вместе.\nАналог 'Максимальное количество потоков' в ZennoPoster.":
        "Maximum number of threads for ALL projects combined.\nAnalog of 'Maximum threads' in ZennoPoster.",
    "Отслеживать ресурсы компьютера":   "Monitor computer resources",
    "Запуск потоков только при наличии свободных ресурсов.":
        "Launch threads only when resources are available.",
    "Приоритетные потоки прерывают менее приоритетных":
        "Priority threads interrupt lower-priority ones",
    "Обнулять неуспехи при добавлении попыток":
        "Reset failures when adding retries",
    "Безопасно сохранять файлы":    "Safe file saving",
    "Запускать незавершённые проекты при старте":
        "Resume unfinished projects on startup",
    "⚡ Глобальные потоки":          "⚡ Global threads",
    "ID модели":                     "Model ID",
    "🤖 Модели":                     "🤖 Models",
    "— Удалить":                     "— Remove",

    # ── Settings dialog ──────────────────────────────────────
    "Настройки — AI Code Sherlock":  "Settings — AI Code Sherlock",
    # ── Settings dialog ──────────────────────────────────────
    "Настройки — AI Code Sherlock":  "Settings — AI Code Sherlock",
    "Модели":                        "Models",
    "Файловый сигнал":               "File Signal",
    "Общие":                         "General",
    "🎨 Внешний вид":                "🎨 Appearance",
    "Отмена":                        "Cancel",
    "Сохранить":                     "Save",
    "МОДЕЛИ":                        "MODELS",
    "+ Добавить":                    "+ Add",
    "Удалить":                       "Delete",
    "Основные параметры":            "Basic Parameters",
    "Название:":                     "Name:",
    "Имя модели:":                   "Model name:",
    "Тип источника:":                "Source type:",
    "Max tokens:":                   "Max tokens:",
    "Temperature:":                  "Temperature:",
    "Использовать по умолчанию":     "Use as default",
    "Ollama (локальная)":            "Ollama (local)",
    "Custom API (OpenAI-совместимый)": "Custom API (OpenAI-compatible)",
    "File Signal (ZennoPoster)":     "File Signal (ZennoPoster)",
    "Проверить соединение":          "Test connection",
    "Проверить API":                 "Test API",
    "Base URL:":                     "Base URL:",
    "API Key:":                      "API Key:",
    "Model ID:":                     "Model ID:",
    "Доп. заголовки:":               "Extra headers:",
    "Папка запросов:":               "Request folder:",
    "Папка ответов:":                "Response folder:",
    "Таймаут:":                      "Timeout:",
    "Поведение":                     "Behaviour",
    "Включить режим Шерлока по умолчанию":   "Enable Sherlock mode by default",
    "Автоматически прикреплять логи к запросам": "Auto-attach logs to requests",
    "Контекст и токены":             "Context & Tokens",
    "Сжимать контекст для экономии токенов":   "Compress context to save tokens",
    "Включать полный лог без обрезки":         "Include full log without truncation",
    "История диалога (сообщений):":            "Conversation history (messages):",
    "Лимит символов файла:":                   "File char limit:",
    "Лимит символов лога:":                    "Log char limit:",
    # ── Settings — AI request group (manual chat) ──────────────
    "Запросы к AI (ручной чат)":   "AI Requests (manual chat)",
    "Настройки применяются к запросам из основного чата.\nНе влияют на Pipeline — у него свои настройки.":
        "Settings apply to requests from the main chat.\nDo not affect the Pipeline — it has its own settings.",
    "Таймаут AI:":                 "AI Timeout:",
    "Повторов при сбое:":          "Retries on failure:",
    "Сколько секунд ждать ответа AI в чате.\n300=5мин  600=10мин  1200=20мин\nУвеличь если модель медленная или контекст большой.":
        "How many seconds to wait for an AI response in chat.\n300=5min  600=10min  1200=20min\nIncrease if the model is slow or context is large.",
    "Сколько раз повторить запрос если AI не ответил.\n0 = нет повторов  3 = до 4 попыток суммарно\nМежду попытками: пауза 10с, 20с, 30с.":
        "How many times to retry if AI did not respond.\n0 = no retries  3 = up to 4 attempts total\nBetween attempts: pause 10s, 20s, 30s.",
    # ── Settings / Pipeline — shared timeout/retry labels ──────
    "= нет повторов":          "= no retries",
    "до":                      "up to",
    "попыток суммарно":        "attempts total",
    "жду":                     "waiting",
    # ── Pipeline advanced tab — AI request group ───────────────
    "Запросы к AI":            "AI Requests",
    "Настройки применяются к каждому вызову AI в пайплайне.":
        "Settings apply to every AI call in the pipeline.",
    "Таймаут AI:":             "AI Timeout:",
    "Повторов при сбое AI:":   "Retries on AI failure:",
    "Сколько секунд ждать ответа AI.\n300=5мин  600=10мин  1200=20мин  3600=1ч\nУвеличь если промпт большой и модель медленная.":
        "How many seconds to wait for AI response.\n300=5min  600=10min  1200=20min  3600=1h\nIncrease if the prompt is large and the model is slow.",
    "Сколько раз повторять запрос если AI не ответил или вернул пустой ответ.\n0 = нет повторов (провал сразу)\n3 = до 4 попыток суммарно (1 + 3 повтора)\nМежду попытками: пауза 10с, 20с, 30с (нарастающая).":
        "How many times to retry if AI didn't respond or returned empty.\n0 = no retries (fail immediately)\n3 = up to 4 attempts total (1 + 3 retries)\nBetween attempts: pause 10s, 20s, 30s (increasing).",
    # ── Chat retry status messages ──────────────────────────────
    "Повтор":                  "Retry",
    "с":                       "s",
    "Кастомные стратегии AI":        "Custom AI Strategies",
    "+ Создать":                     "+ Create",
    "✏ Изменить":                    "✏ Edit",
    "✕ Удалить":                     "✕ Delete",
    "Цвет темы (акцент)":            "Theme Color (accent)",
    # ── Theme selector ──────────────────────────────────────
    "Тема оформления":               "Color Theme",
    "Цветовая схема интерфейса. Изменение применяется сразу.":
        "Interface color scheme. Change is applied immediately.",
    "Тема:":                         "Theme:",
    "🌙 Dark (Tokyo Night)":         "🌙 Dark (Tokyo Night)",
    "☀️ Light":                      "☀️ Light",
    "🎨 Monokai":                    "🎨 Monokai",
    "🧛 Dracula":                    "🧛 Dracula",
    "HEX:":                          "HEX:",
    "🎨 Выбрать цвет…":              "🎨 Pick color…",
    "Шрифт интерфейса":              "Interface Font",
    "Размер:":                       "Size:",
    "Превью:":                       "Preview:",
    "Предпросмотр текста интерфейса": "Interface text preview",
    "Язык интерфейса":               "Interface Language",
    "Язык:":                         "Language:",
    # ── Patch cards ──────────────────────────────────────────
    "✓ Применить":                   "✓ Apply",
    "✕ Отклонить":                   "✕ Reject",
    "👁 Превью":                     "👁 Preview",
    "строк":                         "lines",
    # PatchCard dynamic
    "👁 Просмотр":                   "👁 Preview",
    "─ Удалить":                     "─ Remove",
    "+ Добавить":                    "+ Add",
    "текущий файл":                  "current file",
    "● ожидает":                     "● pending",
    "● применён":                    "● applied",
    "● отклонён":                    "● rejected",
    "● ошибка":                      "● error",
    # Patches panel header
    "ПАТЧИ AI":                      "AI PATCHES",
    "0 патчей":                      "0 patches",
    "✓ Все":                         "✓ All",
    "🔍\n\nПатчей нет\nОтправь запрос AI":
        "🔍\n\nNo patches\nSend an AI request",
    # ── Pipeline dialog ───────────────────────────────────────
    "Откат если валидатор сломался после патча": "Rollback if validator breaks after patch",
    "Если валидатор падает после применения патча —\nосновные скрипты откатываются к предыдущей версии,\nа AI получает информацию о причине сбоя.": "If validator crashes after applying patch —\nprimary scripts are rolled back to previous version,\nand AI receives info about the failure reason.",
    "Сжатие кода:": "Code compression:",
    "🤖 Авто (сжимать только при превышении бюджета)": "🤖 Auto (compress only if over budget)",
    "⚡ Всегда (убирать комментарии и доки)": "⚡ Always (remove comments and docs)",
    "📄 Никогда (всегда полный код)": "📄 Never (always full code)",
    "Авто: сжатие включается только если код не влезает в токен-бюджет\nВсегда: комментарии, докстринги и лог-строки убираются всегда\nНикогда: AI всегда получает полный исходный код": "Auto: compression enabled only if code exceeds token budget\nAlways: comments, docstrings and log lines are always removed\nNever: AI always receives full source code",
    "Режим патчинга:": "Patch mode:",
    "⚡ Сразу (Primary → AI → Apply → Validators)": "⚡ Immediate (Primary → AI → Apply → Validators)",
    "🔒 Валидаторы до AI (Primary → Validators → AI → Apply)": "🔒 Validators before AI (Primary → Validators → AI → Apply)",
    "🔍 Валидаторы первыми (Validators → Primary → AI → Apply)": "🔍 Validators first (Validators → Primary → AI → Apply)",
    "🧠 Полный анализ (Primary → Validators → AI → Apply)": "🧠 Full analysis (Primary → Validators → AI → Apply)",
    "⚡ Сразу: основной скрипт → AI → патч → валидаторы\n🔒 Валидаторы до AI: основной → валидаторы → AI видит оба лога → патч\n🔍 Валидаторы первыми: сначала валидаторы → если OK → основной скрипт → AI → патч\n🧠 Полный анализ: основной скрипт + ВСЕ валидаторы → AI анализирует всё → патч": "⚡ Immediate: primary script → AI → patch → validators\n🔒 Validators before AI: primary → validators → AI sees both logs → patch\n🔍 Validators first: validators first → if OK → primary script → AI → patch\n🧠 Full analysis: primary script + ALL validators → AI analyzes everything → patch",
    "Файлы которые скрипт генерирует — будут прикреплены к контексту AI.\nПоддерживаются: .csv .json .xlsx .txt .log .pkl .npy .npz .parquet и любой текст.\nТакже можно мониторить папки и захватывать снимки окон программы.": "Files the script generates — will be attached to AI context.\nSupported: .csv .json .xlsx .txt .log .pkl .npy .npz .parquet and any text.\nYou can also monitor folders and capture program window screenshots.",
    "симв": "chars",
    "⚙️  Основное":                  "⚙️  General",
    "📜  Скрипты":                   "📜  Scripts",
    "📁  Файлы вывода":              "📁  Output Files",
    "🧠  Стратегия AI":              "🧠  AI Strategy",
    "🤝  Консенсус AI":              "🤝  AI Consensus",
    "✏️  Мои стратегии":             "✏️  My Strategies",
    "🔧  Расширенные":               "🔧  Advanced",
    "Задание":                       "Task",
    "Название:":                     "Name:",
    "Цель оптимизации":              "Optimization Goal",
    "Условие остановки":             "Stop Condition",
    "Условие:":                      "Condition:",
    "Макс. итераций:":               "Max iterations:",
    "Максимум итераций":             "Max iterations",
    "Успешное завершение (exit 0)":  "Successful completion (exit 0)",
    "Цель достигнута (AI пишет GOAL_ACHIEVED)": "Goal reached (AI writes GOAL_ACHIEVED)",
    "Ручная остановка":              "Manual stop",
    "Автоматически применять патчи": "Automatically apply patches",
    "Автооткат при синтаксической ошибке": "Auto-rollback on syntax error",
    "Повторов при неудаче:":         "Retries on failure:",
    "СКРИПТЫ В ПАЙПЛАЙНЕ":           "PIPELINE SCRIPTS",
    "Роль":                          "Role",
    "Файл":                          "File",
    "Аргументы":                     "Arguments",
    "Таймаут":                       "Timeout",
    "Патчить":                       "Patchable",
    "ДЕТАЛИ СКРИПТА":                "SCRIPT DETAILS",
    "Файл:":                         "File:",
    "Аргументы:":                    "Arguments:",
    "Рабочая папка:":                "Working dir:",
    "Таймаут:":                      "Timeout:",
    "Переменные среды:":             "Env vars:",
    "+ Добавить основной":           "+ Add primary",
    "+ Добавить валидатор":          "+ Add validator",
    "+ Контекст AI":                 "+ AI Context",
    "Сопутствующий скрипт — AI видит его при анализе, но не запускает и не патчит":
        "Companion script — AI sees it during analysis, but doesn't run or patch it",
    "Авто-ввод (автоматические ответы скрипту)": "Auto-input (auto-responses to script)",
    "Включить автоматические ответы stdin": "Enable automatic stdin responses",
    "Задержка:":                     "Delay:",
    "💾 Сохранить изменения скрипта": "💾 Save script changes",
    "Выходные файлы по скриптам":    "Output files by scripts",
    "Лимиты контекста":              "Context limits",
    "Макс. символов лога:":          "Max log chars:",
    "Макс. символов на файл:":       "Max chars per file:",
    "+ Файл":                        "+ File",
    "+ Паттерн (glob)":              "+ Pattern (glob)",
    "Стратегия AI":                  "AI Strategy",
    "Стратегия:":                    "Strategy:",
    "Ротация (Explorer):":           "Rotation (Explorer):",
    "Память и лимит токенов":        "Memory & Token Limit",
    "Итераций в памяти:":            "Iterations in memory:",
    "Лимит токенов:":                "Token limit:",
    "Включать историю патчей в промпт": "Include patch history in prompt",
    "Паттерны извлечения метрик из лога (regex)": "Metric extraction patterns from log (regex)",
    "Поведение AI":                  "AI Behaviour",
    "Включать историю патчей (AI не повторяет неудачные)": "Include patch history (AI won't repeat failed)",
    "Использовать карту ошибок (запрещённые подходы)": "Use error map (forbidden approaches)",
    "Безопасность":                  "Safety",
    "Проверять синтаксис Python перед применением патча": "Check Python syntax before applying patch",
    "Резервная копия перед каждым патчем (.backups/)": "Backup before each patch (.backups/)",
    "📂 Загрузить":                  "📂 Load",
    "💾 Сохранить в файл":           "💾 Save to file",
    "▶ Запустить 1 раз":             "▶ Run once",
    "⚡ Запустить Pipeline":          "⚡ Run Pipeline",
    "Нет скриптов":                  "No scripts",
    "Нет цели":                      "No goal",
    "Мониторинг папок":              "Folder Monitoring",
    "Захват снимков экрана":         "Screenshot Capture",
    "Обработка файлов вывода":       "Output File Processing",
    "Добавить папку":                "Add folder",
    "Включать подпапки":             "Include subdirs",
    "Расширения файлов:":            "File extensions:",
    "Авто-включать новые файлы в контекст": "Auto-include new files in context",
    "Включить захват скриншотов":    "Enable screenshot capture",
    "Паттерн заголовка окна:":       "Window title pattern:",
    "Интервал захвата (сек):":       "Capture interval (sec):",
    "Макс. снимков на итерацию:":    "Max screenshots per iter:",
    "Папка для снимков:":            "Screenshots folder:",
    "Включить снимки в контекст AI": "Include screenshots in AI context",
    "Формат:":                       "Format:",
    "Автопарсинг CSV/JSON данных":   "Auto-parse CSV/JSON data",
    "Определять кодировку автоматически": "Auto-detect file encoding",
    "Макс. размер файла (КБ):":      "Max file size (KB):",
    "создан":                        "created",
    "Ошибка":                        "Error",
    "Нет папки":                     "No folder",
    "Укажи папку проекта.":          "Please select a project folder.",
    "Выберите папку проекта":        "Select project folder",
    "Выберите папку проекта...":     "Select project folder...",
    "Сохранить состояние всего проекта": "Save entire project state",
    "Предпросмотр патча":            "Patch Preview",
    "История версий":                "Version History",
    # ── Snapshot strings ─────────────────────────────────────
    "Снапшот":                       "Snapshot",
    # ── Settings dialog tabs ─────────────────────────────────
    "Модели":                        "Models",
    "Файловый сигнал":               "File Signal",
    "Общие":                         "General",
    # ── Project open dialog ───────────────────────────────────
    "Открыть файлы проекта":         "Open Project Files",
    "Выбрать...":                    "Choose...",
    "Выбрать файлы для открытия":    "Select files to open",
    "Отметь файлы которые нужно открыть в редакторе:":
        "Check the files you want to open in the editor:",
    "Выбрать все":                   "Select all",
    "Снять все":                     "Deselect all",
    "Открыть выбранные":             "Open selected",
    "Проект":                        "Project",
    "Найдено файлов":                "Files found",
    "Открыто":                       "Opened",
    "Режим":                         "Mode",
    # ── Consensus dialog ─────────────────────────────────────
    "Модели для консенсуса":         "Consensus Models",
    "Выбери модели для участия в консенсусе.\nЕсли ничего не выбрано — используются все модели.":
        "Choose models to participate in consensus.\nIf nothing is selected — all models are used.",
    # ── Main window dynamic labels ───────────────────────────
    "нет файла":                     "no file",
    "нет модели":                    "no model",
    "🆕 Новый проект":               "🆕 New Project",
    "🔧 Существующий":               "🔧 Existing",
    "🆕 Новый":                      "🆕 New",
    "Обработка":                     "Processing",
    "○ Ожидание":                    "○ Waiting",
    "▶ Запустить скрипт":            "▶ Run Script",
    "Запуск...":                     "Running...",
    "Скрипт завершён":               "Script finished",
    "Ошибка запуска":                "Launch error",
    "файл(ов)":                      "file(s)",
    "токенов в памяти":              "tokens in memory",
    "токенов":                       "tokens",
    "Проверяю модель...":            "Checking model...",
    "Модель доступна":               "Model available",
    "Модель недоступна":             "Model unavailable",
    "Патч применён":                 "Patch applied",
    "Нет активного файла для патча.": "No active file for patch.",
    "Патч не применён":              "Patch not applied",
    "Блок не найден в файле:":       "Block not found in file:",
    "Патчить:":                      "Patch targets:",
    # ── Auto-run panel labels ────────────────────────────────
    "Нет активного пайплайна":       "No active pipeline",
    "ИТЕРАЦИИ":                      "ITERATIONS",
    "○ Ожидание":                    "○ Waiting",
    "■ Остановить":                  "■ Stop",
    "Очистить":                      "Clear",
    "↓ Автоскролл":                  "↓ Autoscroll",
    "📡 Лайв-лог":                   "📡 Live log",
    "🤖 AI анализ":                  "🤖 AI analysis",
    "✂️ Патчи":                      "✂️ Patches",
    "Патчей применено:":             "Patches applied:",
    "Откатов:":                      "Rollbacks:",
    "Итераций:":                     "Iterations:",
    # ── Pipeline dialog labels ───────────────────────────────
    "  Настрой автономный цикл самоулучшения скриптов":
        "  Set up the autonomous self-improvement cycle",
    "СКРИПТЫ В ПАЙПЛАЙНЕ":           "PIPELINE SCRIPTS",
    "● исполняются":                 "● executed",
    "ФАЙЛЫ ДЛЯ ПАТЧИНГА":           "PATCH TARGET FILES",
    "◈ не запускаются":              "◈ not executed",
    "Файлы которые AI будет патчить вместе со скриптом,\nно НЕ запускать — модули, конфиги, библиотеки.":
        "Files that AI will patch along with the script,\nbut NOT run — modules, configs, libraries.",
    "Группа (напр. utils, models, config)…":
        "Group (e.g. utils, models, config)…",
    "+ Файлы":                       "+ Files",
    "+ Папка":                       "+ Folder",
    "Только активный скрипт":        "Active script only",
    "+ Все открытые в редакторе":    "+ All open in editor",
    "0 файлов для патчинга":         "0 patch target files",
    "ДЕТАЛИ СКРИПТА":                "SCRIPT DETAILS",
    "— нет выбранного —":           "— none selected —",
    "Расширения файлов":             "File extensions",
    "Включить файлы с расширениями (через пробел или запятую):":
        "Include files with extensions (space or comma separated):",
    "Нет файлов":                    "No files",
    # ── Version history dialog ───────────────────────────────
    "История версий":                "Version History",
    "● Текущая версия":              "● Current version",
    "версий":                        "versions",
    "Изменений нет — файл идентичен текущей версии.":
        "No changes — file is identical to current version.",
    "Это текущая версия файла.":     "This is the current version of the file.",
    "Текущая версия — не сохранена в истории.":
        "Current version — not saved in history.",
    "Восстановить версию":           "Restore Version",
    "Восстановить файл к версии от": "Restore file to version from",
    "Текущий файл будет сохранён как резервная копия.":
        "The current file will be saved as a backup.",
    "Успешно":                       "Success",
    "Файл восстановлен к версии":    "File restored to version",
    "Не удалось восстановить:":      "Could not restore:",
    "Снапшот проекта":               "Project Snapshot",
    "Название снапшота:":            "Snapshot name:",
    "Описание":                      "Description",
    "Описание (необязательно):":     "Description (optional):",
    "Снапшот создан":                "Snapshot created",
    "файл(ов) сохранено.":           "file(s) saved.",
    # ── Patch preview dialog ─────────────────────────────────
    "📋 Предпросмотр изменений":     "📋 Preview Changes",
    "ПОИСК (удаляемый код)":         "SEARCH (code to remove)",
    "ЗАМЕНА (новый код)":            "REPLACE (new code)",
    "строк":                         "lines",
    "Закрыть":                       "Close",

    # ── Pipeline dialog (full) ────────────────────────────────
    "Одна итерация без цикла":           "Single iteration, no loop",
    "Название пайплайна":                "Pipeline name",
    "Опиши что нужно улучшить. AI использует это как критерий успеха.":
        "Describe what to improve. AI uses this as the success criterion.",
    "Условие:":                          "Condition:",
    "Макс. итераций:":                   "Max iterations:",
    "Повторов при неудаче:":             "Retries on failure:",
    "● исполняются":                     "● executed",
    "◈ не запускаются":                  "◈ not executed",
    "Группа (напр. utils, models, config)…": "Group (e.g. utils, models, config)…",
    "+ Файлы":                           "+ Files",
    "+ Папка":                           "+ Folder",
    "Только активный скрипт":           "Active script only",
    "+ Все открытые в редакторе":       "+ All open in editor",
    "0 файлов для патчинга":             "0 patch target files",
    "файл для патчинга":                 "patch target file",
    "файла для патчинга":                "patch target files",
    "файлов для патчинга":               "patch target files",
    "— нет выбранного —":               "— none selected —",
    "Путь к скрипту...":                 "Path to script...",
    "(по умолчанию: папка скрипта)":    "(default: script folder)",
    "Рабочая папка:":                    "Working dir:",
    "3600=1ч  21600=6ч  86400=24ч  356400=99ч": "3600=1h  21600=6h  86400=24h  356400=99h",
    "= 1 ч 0 мин":                      "= 1 h 0 min",
    "Разрешить AI патчить этот скрипт": "Allow AI to patch this script",
    "Авто-ввод (автоматические ответы скрипту)": "Auto-input (automatic responses to script)",
    "Если скрипт спрашивает пользователя — задай автоответы здесь":
        "If the script asks the user — set auto-responses here",
    "Включить автоматические ответы stdin": "Enable automatic stdin responses",
    "Задержка:":                         "Delay:",
    "💾 Сохранить изменения скрипта":   "💾 Save script changes",
    "Выбери файлы для патчинга":        "Select files to patch",
    "Выбери папку с модулями":          "Select module folder",
    "Включить файлы с расширениями (через пробел или запятую):":
        "Include files with extensions (space or comma separated):",
    "В папке не найдено файлов с расширениями:": "No files with extensions found in folder:",
    "Выходные файлы по скриптам":       "Output files by scripts",
    "Примеры: *.csv   results/*.json   output_*   models/*.pkl":
        "Examples: *.csv   results/*.json   output_*   models/*.pkl",
    "Мониторинг папок с файлами":       "Folder monitoring",
    "Включить мониторинг папок":        "Enable folder monitoring",
    "📁 Добавить папку":                "📁 Add folder",
    "Включать подпапки рекурсивно":     "Include subdirs recursively",
    "Разделяй пробелом или запятой. Пусто = все файлы.":
        "Separate by space or comma. Empty = all files.",
    "Авто-включать новые файлы в контекст AI": "Auto-include new files in AI context",
    "Файлы крупнее этого порога будут усечены": "Files larger than this will be truncated",
    "Макс. размер файла:":              "Max file size:",
    "Автопарсинг CSV/JSON — передавать структуру данных AI": "Auto-parse CSV/JSON for AI",
    "Определять кодировку файлов автоматически": "Auto-detect file encoding",
    "Захват снимка экрана / окна программы": "Screenshot / Window Capture",
    "Включить захват снимков экрана":   "Enable screenshot capture",
    "Паттерн заголовка окна:":          "Window title pattern:",
    "часть заголовка окна  (пусто = весь экран)": "part of window title  (empty = full screen)",
    "Интервал захвата:":                "Capture interval:",
    "Последние N снимков будут включены в контекст AI на каждой итерации":
        "Last N screenshots will be included in AI context per iteration",
    "Макс. снимков на итерацию:":      "Max screenshots per iteration:",
    "screenshots/  (по умолчанию, рядом со скриптом)":
        "screenshots/  (default, next to script)",
    "Папка для снимков:":               "Screenshots folder:",
    "PNG (без потерь)":                 "PNG (lossless)",
    "JPEG (меньше размер)":             "JPEG (smaller size)",
    "WebP (сбаланс.)":                  "WebP (balanced)",
    "Формат:":                          "Format:",
    "Включить снимки в контекст AI (multimodal)": "Include screenshots in AI context (multimodal)",
    "Сохранять только снимки с изменениями (diff-порог)":
        "Save only changed screenshots (diff threshold)",
    "Лимиты контекста":                 "Context limits",
    "Макс. символов лога:":             "Max log chars:",
    "Макс. символов на файл:":          "Max chars per file:",
    "Выбери папку для мониторинга":     "Select folder to monitor",
    "Папка для снимков экрана":         "Screenshots folder",
    "Для EXPLORER: через сколько итераций менять подход":
        "For EXPLORER: how many iterations before switching approach",
    "Сколько прошлых итераций включать в контекст":
        "How many past iterations to include in context",
    "Первая группа захвата = числовое значение метрики.AI будет видеть тренд метрик и принимать решения на основе них.":
        "First capture group = metric numeric value. AI will see metric trends and make decisions.",
    "Консенсус AI — запрашивает несколько моделей одновременно и выбирает лучший ответ.Повышает качество патчей за счёт перекрёстной проверки.":
        "AI Consensus — queries multiple models simultaneously and picks the best answer. Improves patch quality through cross-validation.",
    "Использовать несколько AI-моделей":    "Use multiple AI models",
    "Режим:":                           "Mode:",
    "Для режима Vote: сколько моделей должны предложить один патч":
        "For Vote mode: how many models must agree on a patch",
    "Мин. согласие (Vote):":            "Min agreement (Vote):",
    "Таймаут на модель:":               "Timeout per model:",
    "Выбери модели которые будут участвовать в консенсусе:":
        "Select models to participate in consensus:",
    "Нажми ↑ чтобы обновить список из настроек моделей.":
        "Press ↑ to refresh the list from model settings.",
    "↑ Обновить список моделей":        "↑ Refresh model list",
    "Судья (для режима Judge)":         "Judge (for Judge mode)",
    "Модель-судья:":                    "Judge model:",
    "Судья получает все ответы других моделей и выбирает лучший.":
        "The judge receives all model responses and picks the best.",
    "Создавай собственные стратегии AI с полностью кастомными инструкциями.Активная кастомная стратегия заменяет стандартную стратегию из вкладки 'Стратегия AI'.":
        "Create custom AI strategies with fully custom instructions. The active custom strategy replaces the standard one.",
    "Активная кастомная стратегия":     "Active Custom Strategy",
    "Использовать кастомную стратегию вместо стандартной":
        "Use custom strategy instead of standard",
    "(нет кастомных стратегий)":        "(no custom strategies)",
    "✏️ Редактор стратегий":            "✏️ Strategy Editor",
    "(нет / использовать стандартную)": "(none / use standard)",
    "🎯 Основной":                      "🎯 Primary",
    "✓ Валидатор":                      "✓ Validator",
    "📖 Контекст":                      "📖 Context",
    "СОПУТСТВУЮЩИЕ СКРИПТЫ (только чтение — не патчить)":
        "COMPANION SCRIPTS (read-only — do not patch)",
    "Эти файлы предоставлены **только для понимания архитектуры**.":
        "These files are provided **for architectural understanding only**.",
    "Не предлагай патчи для них — патчи применяются только к основным скриптам.":
        "Do not suggest patches for them — patches apply only to primary scripts.",
    "Скрипт":                           "Script",
    "Рабочая папка":                    "Working dir",
    "Выбери скрипт":                    "Select script",
    "🔍 {p}  [паттерн]":               "🔍 {p}  [pattern]",
    "Выходные файлы":                   "Output files",
    "Паттерн (*.csv, results/*.json, ...): ": "Pattern (*.csv, results/*.json, ...): ",
    # ── Main window (input area) ──────────────────────────────
    "＋ файл":                          "＋ file",
    "Добавить файл в цели патчинга для этого запроса":
        "Add file to patch targets for this request",
    "＋ папка":                         "＋ folder",
    "Добавить все .py файлы из папки как цели патчинга":
        "Add all .py files from folder as patch targets",
    "Очистить все дополнительные цели патчинга": "Clear all extra patch targets",
    "Патчить:":                         "Patch targets:",
    "Файлы для патчинга":               "Files to patch",
    "Папка с модулями для патчинга":    "Module folder for patching",
    "Подходящих файлов не найдено в папке.": "No matching files found in folder.",
    # ── Main window status/messages ───────────────────────────
    "Несохранённые изменения":          "Unsaved Changes",
    "Сохранить перед выходом?":         "Save before exiting?",
    "У вас есть несохранённые изменения в следующих файлах:":
        "You have unsaved changes in the following files:",
    "🎨 Патчи":                         "🎨 Patches",
    "Подсветить пропатченные блоки в редакторе":
        "Highlight patched blocks in the editor",
    "ПАТЧ #{idx + 1}":                  "PATCH #{idx + 1}",
    "текущий файл":                     "current file",
    "КОД":                              "CODE",
    "нет файла":                        "no file",
    "0 файлов":                         "0 files",
    "Модель:":                          "Model:",
    "Настройки":                        "Settings",
    "Режим анализа ошибок":             "Error analysis mode",
    "Вкл = Новый проект (полные ответы)\nВыкл = Только патчи":
        "On = New project (full answers)\nOff = Patches only",
    "История версий файла":             "File version history",
    "Настроить и запустить Auto-Improve Pipeline":
        "Configure and run Auto-Improve Pipeline",
    "Запустить активный файл или выбрать скрипт из проекта.":
        "Run the active file or select a script from the project.",
    "Очистить":                         "Clear",
    "📋 Копировать":                    "📋 Copy",
    "КОНТЕКСТ AI":                      "AI CONTEXT",
    "↺ Обновить":                       "↺ Refresh",
    "Контекст не построен":             "Context not built",
    "Открой файл и отправь запрос для построения контекста...":
        "Open a file and send a request to build context...",
    "МОНИТОРИНГ СИГНАЛОВ":              "SIGNAL MONITOR",
    "○ Остановлен":                     "○ Stopped",
    "События файловых сигналов появятся здесь...":
        "File signal events will appear here...",
    "Событий: 0":                       "Events: 0",
    "Стратегия AI для обычного чата":   "AI strategy for regular chat",
    "Выбрать кастомную стратегию из сохранённых":
        "Select a saved custom strategy",
    "Запросить несколько моделей и выбрать лучший ответ":
        "Query multiple models and pick the best answer",
    "Выбрать модели для консенсуса":    "Select models for consensus",
    "Вариантов:":                       "Variants:",
    "1 = обычный ответ\n2–5 = AI генерирует N независимых вариантов,\n      каждый показывается отдельным сообщением":
        "1 = regular answer\n2–5 = AI generates N independent variants,\n      each shown as a separate message",
    "⊘  Без кастомной стратегии":       "⊘  No custom strategy",
    "⚙  Создать стратегии в Настройках…": "⚙  Create strategies in Settings…",
    "Нет активного файла для патча.":   "No active file for patch.",
    "Применить все":                    "Apply all",
    "нет модели":                       "no model",
    "Обработка...":                     "Processing...",
    "SherlockAnalyzer не инициализирован.": "SherlockAnalyzer not initialized.",
    "🔍 Шерлок анализирует...":         "🔍 Sherlock analyzing...",
    "Нет активной модели":              "No active model",
    "Нет моделей для консенсуса. Добавь модели в настройках.":
        "No models for consensus. Add models in settings.",
    "ConsensusEngine недоступен. Проверь services/consensus_engine.py":
        "ConsensusEngine unavailable. Check services/consensus_engine.py",
    "Вариант {variant_idx + 1}/{n_variants}...": "Variant {variant_idx + 1}/{n_variants}...",
    "Генерирую ответ...":               "Generating response...",
    "Шерлок  •  {model_name}":         "Sherlock  •  {model_name}",
    "Вы":                               "You",
    "Шерлок":                           "Sherlock",
    "Система":                          "System",
    "Патч не применён":                 "Patch not applied",
    "Ошибка патча: {e}":               "Patch error: {e}",
    "Открыть файл":                     "Open file",
    "Открыть папку проекта":            "Open project folder",
    "История":                          "History",
    "Открой файл для просмотра истории.": "Open a file to view history.",
    "✅ Настройки сохранены":           "✅ Settings saved",
    "Экспорт логов":                    "Export logs",
    "💾 Сохранено: {name}":            "💾 Saved: {name}",
    "Закрыть все":                      "Close all",
    "Закрыть все открытые файлы?\nНесохранённые изменения будут потеряны.":
        "Close all open files?\nUnsaved changes will be lost.",
    "💾 Сохранить все":                 "💾 Save all",
    "✕ Закрыть все":                    "✕ Close all",
    "✕ Закрыть все кроме этого":        "✕ Close all except this",
    "✕✓ Закрыть несохранённые":        "✕✓ Close unsaved",
    "📋 Копировать путь":               "📋 Copy path",
    "🤖 Отправить все открытые в AI":   "🤖 Send all open to AI",
    "Несохранённые изменения":          "Unsaved changes",
    "Готов":                            "Ready",
    "⏹ Операция остановлена":          "⏹ Operation stopped",
    "🆕 Новый проект":                  "🆕 New Project",
    "Выбери скрипт для запуска":        "Select script to run",
    "Выполняю":                         "Running",
    "файл(ов)":                         "file(s)",
    "токенов в памяти":                 "tokens in memory",
    # ── Tab labels in main window ─────────────────────────────
    "💬 Диалог":                        "💬 Chat",
    "📋 Логи":                          "📋 Logs",
    "📦 Контекст":                      "📦 Context",
    "📡 Сигналы":                       "📡 Signals",
    "⚡ Авто-запуск":                   "⚡ Auto-run",
    "КОД":                              "CODE",
    "ПАТЧИ AI":                         "AI PATCHES",

    # ── New project wizard ───────────────────────────────────
    "Новый проект — AI Code Sherlock":  "New Project — AI Code Sherlock",
    "🆕 Создать новый проект":          "🆕 Create New Project",
    "Информация о проекте":             "Project Info",
    "Название:":                        "Name:",
    "Папка:":                           "Folder:",
    "Режим работы с AI":                "AI Mode",
    "🆕 Новый проект — разработка с нуля": "🆕 New project — from scratch",
    "🔧 Существующий проект — доработка": "🔧 Existing project — improvements",
    "Создать проект":                   "Create Project",
    # ── Messages ─────────────────────────────────────────────
    "Нет модели":                       "No model",
    "Настрой модель через ⚙ перед отправкой.": "Configure a model via ⚙ first.",
    "✅ Настройки сохранены":           "✅ Settings saved",
    "Нет файлов":                       "No files",
    "Нет патчей":                       "No patches",
    # ── Version history ──────────────────────────────────────
    "ВЕРСИИ":                           "VERSIONS",
    "Diff (относительно текущего)":     "Diff (vs current)",
    "Содержимое версии":                "Version content",
    "Метаданные":                       "Metadata",
    "📸 Создать снапшот":               "📸 Create snapshot",
    "⏪ Восстановить эту версию":       "⏪ Restore this version",
    # ── Error map ────────────────────────────────────────────
    "Карта ошибок":                     "Error Map",
    # ── Editor status ────────────────────────────────────────
    "Spaces: 4":                        "Spaces: 4",
    "UTF-8":                            "UTF-8",
    "🔍 Найти":                         "🔍 Find",
    "⇄ Заменить":                       "⇄ Replace",
    "↵ Wrap":                           "↵ Wrap",
    "▶ Запустить":                      "▶ Run",
    "Найти...":                         "Find...",
    "Заменить...":                      "Replace...",
    "Заменить":                         "Replace",
    "Все":                              "All",
    "Перейти к строке":                 "Go to line",
    "Строка:":                          "Line:",
    "Перейти":                          "Go",
    # ── Context menu editor ──────────────────────────────────
    "🤖 Отправить выделение в AI":      "🤖 Send selection to AI",
    "🤖 Отправить файл в AI":           "🤖 Send file to AI",
    "↗ Перейти к строке...  Ctrl+G":   "↗ Go to line...  Ctrl+G",
    "⧉ Дублировать строку  Ctrl+Shift+D": "⧉ Duplicate line  Ctrl+Shift+D",
    "⌫ Удалить строку  Ctrl+Shift+K":   "⌫ Delete line  Ctrl+Shift+K",
    "// Переключить комментарий  Ctrl+/": "// Toggle comment  Ctrl+/",
    "🔍+ Увеличить шрифт  Ctrl+=":     "🔍+ Zoom in  Ctrl+=",
    "🔍- Уменьшить шрифт  Ctrl+−":     "🔍- Zoom out  Ctrl+−",
    "🔍 Сбросить размер  Ctrl+0":       "🔍 Reset zoom  Ctrl+0",
    "⊖ Свернуть блок  Ctrl+Shift+[":   "⊖ Fold block  Ctrl+Shift+[",
    "⊕ Развернуть всё  Ctrl+Shift+]":  "⊕ Unfold all  Ctrl+Shift+]",
    # ── Auto-run panel ───────────────────────────────────────
    "📡 Лайв-лог":                      "📡 Live log",
    "🤖 AI анализ":                      "🤖 AI analysis",
    "✂️ Патчи":                          "✂️ Patches",
    "Нет активного пайплайна":           "No active pipeline",
    "ИТЕРАЦИИ":                          "ITERATIONS",
    "■ Остановить":                      "■ Stop",
    "↓ Автоскролл":                      "↓ Autoscroll",
    "○ Ожидание":                        "○ Waiting",
    "▶ Запуск":                          "▶ Running",
    "⏹ Остановка...":                    "⏹ Stopping...",
    "Итерация":                          "Iteration",
    "● запуск...":                       "● starting...",
    "↩ откат":                           "↩ rollback",
    "✓ Успешно":                         "✓ Success",
    "⚠ Ошибки":                         "⚠ Errors",
    "🎯 Цель!":                          "🎯 Goal!",
    # ── Patches mode button ───────────────────────────────────
    "🔧 Патчи":                          "🔧 Patches",
    "🔧 Режим патчей":                   "🔧 Patch Mode",
    "ПАТЧ #":                            "PATCH #",
    # ── Error map dialog ─────────────────────────────────────
    "Карта ошибок — AI Code Sherlock":   "Error Map — AI Code Sherlock",
    "🗂 Карта ошибок и решений":         "🗂 Error Map & Solutions",
    "Поиск по ошибкам...":               "Search errors...",
    "Все":                               "All",
    "Открытые":                          "Open",
    "Решённые":                          "Resolved",
    "Игнорируемые":                      "Ignored",
    "⚠️ Ошибки":                        "⚠️ Errors",
    "🚫 Запрещённые подходы":           "🚫 Forbidden approaches",
    "➕ Добавить":                       "➕ Add",
    "🗑 Очистить решённые":              "🗑 Clear resolved",
    "Тип":                               "Type",
    "Сообщение":                         "Message",
    "Кол-во":                            "Count",
    "Последний раз":                     "Last seen",
    "ДЕТАЛИ":                            "DETAILS",
    "✓ Отметить решённой":              "✓ Mark as resolved",
    "Игнорировать":                      "Ignore",
    "🚫 Добавить запрет":               "🚫 Add forbidden",
    "Плохой подход":                     "Bad approach",
    "Лучше делать":                      "Better approach",
    "🗑 Удалить выбранный":             "🗑 Delete selected",
    "Добавить запрещённый подход вручную:": "Add forbidden approach manually:",
    "Описание плохого подхода...":       "Describe the bad approach...",
    "Плохой подход:":                    "Bad approach:",
    "Что делать вместо этого...":        "What to do instead...",
    "Правильный подход:":                "Better approach:",
    "В каком контексте это произошло...": "Context in which this occurred...",
    "Контекст (необязательно):":         "Context (optional):",
    "Отметить решённой":                 "Mark as resolved",
    "Опиши решение (необязательно):":    "Describe solution (optional):",
    "Запрещённый подход":                "Forbidden approach",
    "Что НЕ нужно делать?":             "What NOT to do?",
    "Лучший подход":                     "Better approach",
    "Что нужно делать вместо этого?":    "What to do instead?",
    "Заполни оба поля.":                "Fill in both fields.",
    "Добавлено":                         "Added",
    "Запрещённый подход добавлен.":      "Forbidden approach added.",
    "Удалить все решённые ошибки из базы?": "Delete all resolved errors from the database?",
    # ── New project wizard descriptions ──────────────────────
    "AI даёт полные реализации кода, объяснения архитектуры.\nПодходит для создания новых скриптов и приложений.":
        "AI gives full code implementations, architecture explanations.\nSuitable for creating new scripts and apps.",
    "AI даёт ТОЛЬКО точечные патчи [SEARCH/REPLACE].\nПодходит для улучшения готового кода без переписывания.":
        "AI gives ONLY precise patches [SEARCH/REPLACE].\nSuitable for improving existing code without rewriting.",
    "Настрой проект перед началом работы с AI Code Sherlock":
        "Set up the project before starting with AI Code Sherlock",
    # ── Open Project dialog ───────────────────────────────────
    "Открыть все файлы или только первые 12?": "Open all files or only the first 12?",
    "Открыть все":                       "Open all",
    # ── Main window misc ─────────────────────────────────────
    "Ошибок:":                           "Errors:",
    "Очистить список":                   "Clear list",

    # ── Settings dialog (long tooltips joined by auto-wrapper) ──────────────
    "Максимум токенов в запросе к модели.\n8192 = стандарт, 32768 = большой контекст,\n200000 = Claude/Gemini, 1000000+ = Gemini Ultra":
        "Max tokens per model request.\n8192 = standard, 32768 = large context,\n200000 = Claude/Gemini, 1000000+ = Gemini Ultra",
    "ВКЛ (по умолчанию): файлы и логи обрезаются до лимита токенов.\nВЫКЛ: передаётся полный контент без обрезки — для точного анализа.":
        "ON (default): files and logs are trimmed to token limit.\nOFF: full content without truncation — for precise analysis.",
    "Передавать весь лог ошибок целиком (может сильно увеличить контекст).":
        "Send the full error log without truncation (may significantly increase context).",
    "Сколько прошлых сообщений включать в каждый запрос к AI.":
        "How many past messages to include in each AI request.",
    "Максимум символов одного файла в контексте AI.":
        "Maximum characters per file in AI context.",
    "Максимум символов лога ошибок в контексте AI.":
        "Maximum characters of error log in AI context.",
    "Создавай собственные стратегии поведения AI для основного чата.\nВыбранная стратегия добавляется к системному промпту вместо стандартной.":
        "Create custom AI behavior strategies for the main chat.\nThe selected strategy is added to the system prompt instead of the standard one.",
    "Основной цвет интерфейса — кнопки, выделения, активные элементы.\nИзменение применится после перезапуска.":
        "Primary interface color — buttons, highlights, active elements.\nChange takes effect after restart.",
    "Размер шрифта всех меню, кнопок и панелей (не редактора кода).":
        "Font size for all menus, buttons and panels (not the code editor).",
    "Язык меню, кнопок и сообщений. Изменение применится при перезапуске.\nЯзык AI-ответов задаётся в системном промпте.":
        "Language for menus, buttons and messages. Change takes effect after restart.\nAI response language is set in the system prompt.",
    "Тест API будет вызван при первом запросе к модели.\nУбедись что URL и API Key правильные.":
        "API test will be called on first model request.\nMake sure the URL and API Key are correct.",
    "Инструкции для AI (добавляются к системному промпту).\n\nПример:\nТы — строгий code reviewer. При каждом ответе:\n1. Указывай потенциальные проблемы с производительностью\n2. Предлагай альтернативные реализации\n3. Давай только минимально необходимые патчи.":
        "Instructions for AI (added to system prompt).\n\nExample:\nYou are a strict code reviewer. For each response:\n1. Point out potential performance issues\n2. Suggest alternative implementations\n3. Give only the minimum necessary patches.",
    "gpt-4o (оставь пустым для имени модели)":
        "gpt-4o (leave empty to use model name)",
    "Краткое описание (необязательно)":     "Brief description (optional)",
    "Название стратегии":                   "Strategy name",
    "Выбрать цвет акцента":                 "Pick accent color",
    "Глобальные пути сигналов":             "Global signal paths",
    "Иконка:":                              "Icon:",
    "Системный промпт:":                    "System prompt:",
    "Например: GPT-4o Local":               "E.g.: GPT-4o Local",
    "Новая модель":                         "New model",
    "Подтверждение":                        "Confirmation",
    "Редактор стратегии":                   "Strategy editor",
    "Удалить стратегию":                    "Delete strategy",
    "Удалить эту модель?":                  "Delete this model?",
    "Удалить эту стратегию?":               "Delete this strategy?",
    "✅ Соединение успешно!\n{url}":       "✅ Connection successful!\n{url}",
    "❌ Недоступен: {url}\nПроверь, что Ollama запущена.":
        "❌ Unavailable: {url}\nMake sure Ollama is running.",
    "🇷🇺  Русский":                          "🇷🇺  Russian",
    "Описание:":                             "Description:",
    # ── Code editor toolbar ───────────────────────────────────
    "Найти (Ctrl+F)":                       "Find (Ctrl+F)",
    "Найти и заменить (Ctrl+H)":            "Find and replace (Ctrl+H)",
    "Перенос строк (Alt+Z)":                "Wrap lines (Alt+Z)",
    "Увеличить (Ctrl+=)":                   "Zoom in (Ctrl+=)",
    "Уменьшить (Ctrl+-)":                   "Zoom out (Ctrl+-)",
    "Сбросить размер (Ctrl+0)":             "Reset zoom (Ctrl+0)",
    "Дублировать строку (Ctrl+Shift+D)":    "Duplicate line (Ctrl+Shift+D)",
    "Удалить строку (Ctrl+Shift+K)":        "Delete line (Ctrl+Shift+K)",
    "Комментарий (Ctrl+/)":                 "Toggle comment (Ctrl+/)",
    "Запустить этот скрипт":                "Run this script",
    "Не найдено":                           "Not found",
    "Миникарта — нажми для прокрутки":      "Minimap — click to scroll",
    # ── Consensus dropdown (main_window) ─────────────────────
    "🗳 Голосование":                       "🗳 Vote",
    "🏆 Best-of-N":                         "🏆 Best-of-N",
    "🔀 Merge":                             "🔀 Merge",
    "⚖️ Judge":                             "⚖️ Judge",
    # ── Open project dialog buttons ───────────────────────────
    "Только":                               "Only",

    # ── AI Strategy descriptions ─────────────────────────────
    "Только исправляет ошибки. Минимальные изменения. Не трогает рабочий код без явной причины.":
        "Only fixes errors. Minimal changes. Does not touch working code without explicit reason.",
    "Исправляет ошибки + умеренные улучшения. Оптимальный баланс между стабильностью и прогрессом.":
        "Fixes errors + moderate improvements. Optimal balance between stability and progress.",
    "Максимальные улучшения, творческие изменения. Может рефакторить логику для достижения цели.":
        "Maximum improvements, creative changes. May refactor logic to achieve the goal.",
    "Каждую итерацию пробует разный подход. Ищет неочевидные решения, избегает повторения.":
        "Each iteration tries a different approach. Seeks non-obvious solutions, avoids repetition.",
    "Углубляет то что уже работало в предыдущих итерациях. Усиливает успешные паттерны.":
        "Deepens what worked in previous iterations. Reinforces successful patterns.",
    "Применяет патч только если метрики улучшились. При ухудшении — откат + другой подход.":
        "Applies patch only if metrics improved. On regression — rollback + different approach.",
    "Формулирует гипотезу → патч → проверка → вывод. Научный подход к оптимизации.":
        "Formulates hypothesis → patch → verify → conclusion. Scientific approach to optimization.",
    "Генерирует 3 варианта патча, выбирает наиболее обоснованный. Медленнее, но точнее.":
        "Generates 3 patch variants, picks the most justified. Slower but more precise.",
    # ── Pipeline consensus mode items (long form) ─────────────
    "🗳 Голосование (Vote) — патч принимается если ≥N моделей согласны":
        "🗳 Vote — patch accepted if ≥N models agree",
    "🏆 Best-of-N — лучший ответ (больше патчей)":
        "🏆 Best-of-N — best response (more patches)",
    "🔀 Merge — объединить уникальные патчи из всех":
        "🔀 Merge — combine unique patches from all",
    "⚖️ Judge — одна модель оценивает ответы других":
        "⚖️ Judge — one model evaluates others' answers",
    # ── Pipeline info label descriptions (still in RU) ────────
    "Файлы которые скрипт генерирует — будут прикреплены к контексту AI.\nПоддерживаются: .csv .json .xlsx .txt .log .pkl .npy .npz .parquet и любой текст.\nТакже можно мониторить папки и захватывать снимки окон программы.":
        "Files generated by the script — will be attached to AI context.\nSupported: .csv .json .xlsx .txt .log .pkl .npy .npz .parquet and any text.\nYou can also monitor folders and capture window screenshots.",
    "Добавь папки — все новые/изменённые файлы с нужными расширениями будут прикрепляться к контексту каждой итерации:":
        "Add folders — all new/changed files with the required extensions will be attached to each iteration's context:",
    "Стратегия определяет как AI подходит к улучшению кода — консервативно или агрессивно, исследуя или эксплуатируя успех.":
        "The strategy defines how AI approaches code improvement — conservatively or aggressively, exploring or exploiting success.",
    "Консенсус AI — запрашивает несколько моделей одновременно и выбирает лучший ответ.\nПовышает качество патчей за счёт перекрёстной проверки.":
        "AI Consensus — queries multiple models simultaneously and picks the best answer.\nImproves patch quality through cross-validation.",
    "Создавай собственные стратегии AI с полностью кастомными инструкциями.\nАктивная кастомная стратегия заменяет стандартную стратегию из вкладки 'Стратегия AI'.":
        "Create custom AI strategies with fully custom instructions.\nThe active custom strategy replaces the standard one from the 'AI Strategy' tab.",
    "Наблюдает за папками — автоматически подхватывает новые и изменённые файлы, добавляет их в контекст AI.":
        "Monitors folders — automatically picks up new and changed files, adds them to AI context.",
    "Если скрипт открывает GUI-окно (например, браузер, программа-трекер), снимок экрана можно автоматически включить в контекст AI для анализа.":
        "If the script opens a GUI window (e.g., browser, tracker), the screenshot can automatically be included in AI context for analysis.",
    "Делает скриншот указанного окна (по паттерну заголовка) или всего экрана.\nИзображение передаётся AI для визуального анализа прогресса.":
        "Takes a screenshot of the specified window (by title pattern) or the full screen.\nThe image is passed to AI for visual progress analysis.",
    "Пример: 'Chrome', 'Notepad', 'TradingView'\nЗахватывается первое окно, заголовок которого содержит этот текст (регистр не важен).\nОставь пустым, чтобы снимать весь экран.":
        "Example: 'Chrome', 'Notepad', 'TradingView'\nCaptures the first window whose title contains this text (case-insensitive).\nLeave empty to capture the full screen.",
    "Пропускает снимки идентичные предыдущему (экономит контекст и место на диске).":
        "Skips screenshots identical to the previous one (saves context and disk space).",
    "Передаёт снимки в запросы к AI-модели.\nТребует поддержки vision (GPT-4o, Claude, Gemini и др.).":
        "Passes screenshots to AI model requests.\nRequires vision support (GPT-4o, Claude, Gemini, etc.).",
    "⚠  Для захвата окон на Windows используется win32gui/mss.\n   На Linux — scrot/gnome-screenshot (должен быть установлен).\n   Для работы multimodal AI нужна модель с поддержкой vision.":
        "⚠  On Windows, win32gui/mss is used for window capture.\n   On Linux — scrot/gnome-screenshot (must be installed).\n   Multimodal AI requires a model with vision support.",
    # ── Error Map stats ───────────────────────────────────────
    "Всего:":                            "Total:",
    "Открытых:":                         "Open:",
    "Решённых:":                         "Resolved:",
    "Запретов:":                         "Forbidden:",
    # ── Pipeline plural forms ─────────────────────────────────
    "файл для патчинга":                 "patch target file",
    "файла для патчинга":                "patch target files",
    "файлов для патчинга":               "patch target files",
    # ── Timeout format strings ────────────────────────────────
    "= {h} ч {m} мин":                  "= {h} h {m} min",
    "= {m} мин {s} сек":                "= {m} min {s} sec",
    "= {s} сек":                         "= {s} sec",
    "= 1 ч 0 мин":                      "= 1 h 0 min",

    # ── Pipeline dialog remaining keys ──────────────────────────
    " КБ":                               " KB",
    "0.5=полсекунды  5=каждые 5 сек  60=раз в минуту":
        "0.5=half a second  5=every 5 sec  60=once a minute",
    "200k=стандарт, 1M=Gemini 1.5 Pro, 2M=Gemini 1.5 Ultra":
        "200k=standard, 1M=Gemini 1.5 Pro, 2M=Gemini 1.5 Ultra",
    "AI патчит только выбранный основной скрипт + файлы из этого списка.\nСнять галочку = патчить также все файлы открытые в редакторе.":
        "AI patches only the selected primary script + files from this list.\nUncheck = also patch all files open in the editor.",
    "Glob-паттерн":                      "Glob pattern",
    "y\n\nall\n\n(пустая строка = Enter)":
        "y\n\nall\n\n(empty line = Enter)",
    "{h}ч {m}м":                         "{h}h {m}m",
    "{m}м":                              "{m}m",
    "{sc.timeout_seconds}с":             "{sc.timeout_seconds}s",
    "В папке не найдено файлов с расширениями: {exts_str}":
        "No files with extensions found in folder: {exts_str}",
    "Включить консенсус":                "Enable consensus",
    "Добавить все файлы с нужными расширениями из папки.\nВыбор расширений появится после выбора папки.":
        "Add all files with required extensions from folder.\nExtension selection appears after choosing folder.",
    "Добавить отдельные файлы (модули, конфиги…)":
        "Add individual files (modules, configs…)",
    "Добавь скрипты.":                   "Add scripts.",
    "Дополнительно включить в патчинг все файлы,\nкоторые открыты во вкладках главного редактора.":
        "Additionally include all files\nopen in the main editor tabs for patching.",
    "Каждая строка = один ответ, отправляемый в stdin по порядку.\nПустая строка = Enter. Примеры: 'y', 'yes', 'all', '1', '0'":
        "Each line = one response sent to stdin in order.\nEmpty line = Enter. Examples: 'y', 'yes', 'all', '1', '0'",
    "Не удалось загрузить: {e}":         "Failed to load: {e}",
    "Необязательная метка группы — AI увидит связь файлов.\nНапример: 'models', 'utils', 'config', 'shared'":
        "Optional group label — AI will see file relationships.\nExamples: 'models', 'utils', 'config', 'shared'",
    "Относительный путь":                "Relative path",
    "Первая группа захвата = числовое значение метрики.\nAI будет видеть тренд метрик и принимать решения на основе них.":
        "First capture group = numeric metric value.\nAI will see metric trends and make decisions based on them.",
    "Пример: Улучшить Precision > 70% и Signal Rate > 25%.\nУстранять все ошибки в логах.\nОптимизировать параметры CatBoost без переобучения.":
        "Example: Improve Precision > 70% and Signal Rate > 25%.\nFix all errors in logs.\nOptimize CatBoost parameters without overfitting.",
    "Укажи цель на вкладке 'Основное'.":  "Set a goal in the 'General' tab.",
    "Только исправляет ошибки. Минимальные изменения. Не трогает рабочий код без явной причины.":
        "Only fixes errors. Minimal changes. Does not touch working code without explicit reason.",

    # ── Auto-run panel f-strings ─────────────────────────────
    "Pipeline '{config.name}' запущен • Цель: {config.goal[:60]}":
        "Pipeline '{config.name}' started • Goal: {config.goal[:60]}",
    "Итерация {n}":                      "Iteration {n}",
    " • ЦЕЛЬ ДОСТИГНУТА":               " • GOAL ACHIEVED",
    "🤖 AI: найдено {count} патч(ей)":   "🤖 AI: found {count} patch(es)",
    "↩ Откат: {d.get('reason','')}":    "↩ Rollback: {d.get('reason','')}",
    "Pipeline завершён: {stop}":         "Pipeline finished: {stop}",
    "Pipeline ошибка: {error}":          "Pipeline error: {error}",
    "Завершён":                          "Finished",
    "✓ Завершён: {stop}":               "✓ Finished: {stop}",
    "Патчей применено: {total_p}  |  Откатов: {total_r}":
        "Patches applied: {total_p}  |  Rollbacks: {total_r}",
    "Патчей применено: 0  |  Откатов: 0":
        "Patches applied: 0  |  Rollbacks: 0",
    "Итераций: {n} / {max_i}":          "Iterations: {n} / {max_i}",
    "{role_tag} Запуск: {d['script']}":  "{role_tag} Run: {d['script']}",
    "✗ код {d['exit_code']}":           "✗ code {d['exit_code']}",
    "↩ Откат":                          "↩ Rollback",
    "  ↩ Файл восстановлен: {d['file']}": "  ↩ File restored: {d['file']}",
    " ({failed} неудач)":               " ({failed} failed)",
    "+{applied} патчей":                "+{applied} patches",
    # ── Code editor status bar ────────────────────────────────
    "стр":                               "ln",
    "слов":                              "words",
    "выбр.":                             "sel.",
    "ошибок":                            "errors",
    # ── Main window f-string labels ───────────────────────────
    "токенов":                           "tokens",
    "файл(ов)":                          "file(s)",
    "файлов":                            "files",
    "Скриптов":                          "Scripts",
    # ── Pipeline misc ─────────────────────────────────────────
    "New Pipeline":                      "New Pipeline",
    "My Strategy":                       "My Strategy",

    # ── File tree ─────────────────────────────────────────────
    "ПРОВОДНИК":                         "EXPLORER",
    "Открыть папку проекта":             "Open project folder",
    "Обновить":                          "Refresh",
    "Папка не открыта":                  "No folder open",
    "📂  Раскрыть":                      "📂  Expand",
    # ── Timeout format strings ────────────────────────────────
    "ч":                                 "h",
    "м":                                 "m",
    "с":                                 "s",
    "мин":                               "min",
    "сек":                               "sec",
    # ── Pattern list item ─────────────────────────────────────
    "паттерн":                           "pattern",
    # ── Settings dialog fix (ftr → tr) ───────────────────────
    "✅ Соединение успешно!":            "✅ Connection successful!",
    "❌ Недоступен:":                    "❌ Unavailable:",
    "Проверь, что Ollama запущена.":     "Make sure Ollama is running.",
    "В папке не найдено файлов с расширениями:":
        "No files with extensions found in folder:",
    "Не удалось загрузить:":             "Failed to load:",

    # ── Open Project dialog body ─────────────────────────────
    "В проекте найдено":                 "Found in project",
    "файлов кода.":                      "code files.",
    "В корневой папке:":                 "In root folder:",
    "В подпапках:":                      "In subfolders:",
    "Открыть все файлы или только первые": "Open all files or only the first",
    # ── Main window initial static labels ─────────────────────
    "~0 токенов":                        "~0 tokens",
    "0 файлов":                          "0 files",
    "○ Сигнал":                          "○ Signal",

    # ── Main window dynamic labels ───────────────────────────
    "мод.":                              "mod.",
    "Вариант":                           "Variant",
    "Шерлок":                            "Sherlock",
    "Итераций":                          "Iterations",
    "Скриптов":                          "Scripts",

    # ── Chat bubbles ────────────────────────────────────────
    "Вы":                                "You",
    "Система":                           "System",
    "Ошибка":                            "Error",
    # Шерлок already exists above

    # ── New-project file creation ───────────────────────────
    "💾 Сохранить как файл":             "💾 Save as file",
    "Сохранить ответ AI как новый файл": "Save AI response as new file",
    "Сохранить код как файл":            "Save code as file",
    "Файл создан":                       "File created",
    "Новый файл":                        "New file",
    "💡 Опиши что нужно создать — AI сгенерирует файл(ы) нужного расширения автоматически.\nНапример: «Создай main.py — скрипт для парсинга CSV» или «Создай index.js — Express сервер»":
        "💡 Describe what to create — AI will generate file(s) with the correct extension.\nExample: 'Create main.py — CSV parser script' or 'Create index.js — Express server'",
    "Новый проект создан":               "New project created",
    "Папка":                             "Folder",

    # ── Error / apply messages ──────────────────────────────
    "Не удалось создать файл":           "Failed to create file",
    "Нет файлов":                        "No files",
    "Подходящих файлов не найдено в папке.": "No matching files found in the folder.",

    # ── Context menu in editor tabs ─────────────────────────
    "Несохранённые изменения":           "Unsaved changes",
    "Закрыть все":                       "Close all",
    "Закрыть все открытые файлы?\nНесохранённые изменения будут потеряны.":
        "Close all open files?\nUnsaved changes will be lost.",
    "Сохранить все":                     "Save all",
    "Закрыть все кроме этого":           "Close all except this",
    "Закрыть несохранённые":             "Close unsaved",
    "Отправить все открытые в AI":       "Send all open to AI",
    "Проанализируй все открытые файлы:": "Analyse all open files:",

    # ── Patch panel context labels ───────────────────────────
    "ПАТЧ #":                            "PATCH #",
    "текущий файл":                      "current file",

    # ── New-project wizard ───────────────────────────────────
    "Новый проект — AI Code Sherlock":   "New Project — AI Code Sherlock",
    "🆕 Создать новый проект":           "🆕 Create New Project",
    "Настрой проект перед началом работы с AI Code Sherlock":
        "Set up your project before starting with AI Code Sherlock",
    "Информация о проекте":              "Project Info",
    "Режим работы с AI":                 "AI Working Mode",
    "🆕 Новый проект — разработка с нуля":   "🆕 New Project — development from scratch",
    "AI даёт полные реализации кода, объяснения архитектуры.\nПодходит для создания новых скриптов и приложений.":
        "AI provides full code implementations and architecture explanations.\nSuitable for new scripts and applications.",
    "🔧 Существующий проект — доработка":    "🔧 Existing Project — improvements",
    "AI даёт ТОЛЬКО точечные патчи [SEARCH/REPLACE].\nПодходит для улучшения готового кода без переписывания.":
        "AI provides ONLY targeted [SEARCH/REPLACE] patches.\nSuitable for improving existing code without rewriting.",
    "Создать проект":                    "Create Project",
    "Название:":                         "Name:",
    "Папка:":                            "Folder:",
    "Выберите папку проекта...":         "Select project folder...",

    # ── Version history dialog ───────────────────────────────
    "История":                           "History",
    "версий":                            "versions",
    "ВЕРСИИ":                            "VERSIONS",
    "Diff (относительно текущего)":      "Diff (vs current)",
    "Содержимое версии":                 "Version content",
    "Метаданные":                        "Metadata",
    "📸 Создать снапшот":               "📸 Create snapshot",
    "⏪ Восстановить эту версию":        "⏪ Restore this version",
    "Это текущая версия файла.":         "This is the current version of the file.",
    "Текущая версия — не сохранена в истории.": "Current version — not saved in history.",
    "Изменений нет — файл идентичен текущей версии.":
        "No changes — file is identical to current version.",
    "Восстановить версию":               "Restore Version",
    "Восстановить файл к версии от":     "Restore file to version from",
    "Текущий файл будет сохранён как резервная копия.":
        "Current file will be saved as a backup.",
    "Успешно":                           "Success",
    "Файл восстановлен к версии":        "File restored to version",
    "Не удалось восстановить:":          "Failed to restore:",
    "Снапшот проекта":                   "Project Snapshot",
    "Название снапшота:":                "Snapshot name:",
    "Описание (необязательно):":         "Description (optional):",
    "Снапшот создан":                    "Snapshot created",
    "файл(ов) сохранено.":               "file(s) saved.",

    # ── Error map dialog ─────────────────────────────────────
    "Открой файл для просмотра истории.": "Open a file to view its history.",

    # ── System message snippets (f-string parts) ─────────────
    "Патч применён":                        "Patch applied",
    "резервная копия сохранена":            "backup saved",
    "Сохранено вкладок":                    "Tabs saved",
    "Закрыто несохранённых":               "Unsaved tabs closed",
    "Сохранено":                            "Saved",
    "Запуск скрипта":                       "Running script",
    "запущен":                              "started",
    "восстановлен к предыдущей версии.":   "restored to previous version.",
    "Логи экспортированы":                  "Logs exported",

    # ── Mode toggle messages ──────────────────────────────────
    "🆕 **Режим: Новый проект** — AI даёт полные реализации кода.":
        "🆕 **Mode: New Project** — AI provides full code implementations.",
    "🔧 **Режим: Существующий проект** — AI даёт ТОЛЬКО [SEARCH/REPLACE] патчи.":
        "🔧 **Mode: Existing Project** — AI provides ONLY [SEARCH/REPLACE] patches.",
    "🔧 Режим патчей":                      "🔧 Patch Mode",

    # ── Load project system messages ─────────────────────────
    "AI Code Sherlock готов к работе.\nОткрой проект (📁) или файл (📄), выбери модель и начни работу.":
        "AI Code Sherlock is ready.\nOpen a project (📁) or file (📄), select a model and start.",
    "Открой файл и отправь запрос для построения контекста...":
        "Open a file and send a request to build the context...",
    "AI Code Sherlock инициализирован":     "AI Code Sherlock initialised",
    "Вкл = Новый проект (полные ответы)\nВыкл = Только патчи":
        "On = New Project (full responses)\nOff = Patches only",
    "Режим анализа ошибок":                 "Error analysis mode",
    "!= (не равно)":                        "!= (not equal)",
    "## DOM страницы (сжатый):":            "## DOM pages (compressed):",
    "## Задача от Planner:":                "## Task from Planner:",
    "## СКИЛЛЫ АГЕНТА":                     "## AGENT SKILLS",
    "#id или .class или //xpath":           "#id or .class or //xpath",
    "&& (И) — все истинны":                 "&& (AND) — all are true",
    "' добавлен к":                         "' added to",
    "' не найден:":                         "' not found:",
    "' не найдена в project_variables (исходное: '":
            "' not found in project_variables (original: '",
    "' не существует":                      "' doesn't exist",
    "' не существует, пропуск":             "' doesn't exist, pass",
    "' пропущено":                          "' missed",
    "' уже запущен (ID:":                   "' already launched (ID:",
    "    # Фоллбэк на node":                "    # Fallback on node",
    "'. Размер:":                           "'. Size:",
    "': не удалось конвертировать в":       "': failed to convert to",
    "': нет ProjectBrowserManager в контексте":
            "': No ProjectBrowserManager in context",
    "': нет активного браузера для проекта":
            "': there is no active browser for the project",
    "(не в выборке)":                       "(not in the sample)",
    "(не задавать)":                        "(don't ask)",
    "(не задана рабочая папка)":            "(working folder not specified)",
    "(нет переменных)":                     "(no variables)",
    "(полный код для контекста) ---":       "(full code for context) ---",
    "(размер:":                             "(size:",
    "(следуй строго):":                     "(follow strictly):",
    "(сохраните workflow для записи на диск)":
            "(save workflow to write to disk)",
    "(тег:":                                "(tag:",
    "(текущий размер:":                     "(current size:",
    "(тип:":                                "(type:",
    "(удалена)":                            "(deleted)",
    "(удалено)":                            "(deleted)",
    "), переиспользуем — новый НЕ запускаем":
            "), reuse — We are NOT launching a new one",
    "), сдвиг (":                           "), shift (",
    "), текущая позиция (":                 "), current position (",
    "): удалено":                           "): deleted",
    ", tools пример:":                      ", tools example:",
    ", используется как string":            ", used as string",
    ", осталось":                           ", left",
    ", получен":                            ", received",
    ", текст:":                             ", text:",
    "--- Дамп контекста ---":               "--- Context dump ---",
    "--- Итерация":                         "--- Iteration",
    "--- Контекст ---":                     "--- Context ---",
    "--- Результаты узлов ---":             "--- Node results ---",
    "--- конец ---":                        "--- end ---",
    ". Выполни только эту конкретную задачу.":
            ". Complete only this specific task.",
    ". Осталось:":                          ". Left:",
    ". Размер:":                            ". Size:",
    "0 = до конца":                         "0 = to the end",
    "0 = не закрывать":                     "0 = don't close",
    "0 совпадений":                         "0 matches",
    ": SEARCH/REPLACE не совпал — полная перезапись...":
            ": SEARCH/REPLACE didn't match — complete rewrite...",
    ": код длины":                          ": length code",
    ": ошибка фоллбэка:":                   ": fallback error:",
    ": полная перезапись (фоллбэк)":        ": complete rewrite (fallback)",
    ": фоллбэк тоже не дал код":            ": the fallback didn't give the code either",
    "< (меньше)":                           "< (less)",
    "</b><br><i style='color: #565f89;'>Нажмите «Продолжить» или «Шаг» для запуска</i>":
            "</b><br><i style='color: #565f89;'>Click «Continue» or «Step» to launch</i>",
    "<= (меньше или равно)":                "<= (less than or equal to)",
    "<b style='color: #7AA2F7;'>🚀 Запуск workflow:":
            "<b style='color: #7AA2F7;'>🚀 Launch workflow:",
    "<b>Шпаргалка:</b> <code>.</code> любой символ | <code>\\d</code> цифра | <code>\\w</code> буква/цифра | <code>\\s</code> пробел | <code>*</code> 0+ | <code>+</code> 1+ | <code>?</code> 0-1 | <code>(?<=X)</code> после X | <code>(?=X)</code> перед X | <code>[abc]</code> один из | <code>(a|b)</code> или":
        "<b>Crib:</b> <code>.</code> any character | <code>\\d</code> number | <code>\\w</code> letter/number | <code>\\s</code> space | <code>*</code> 0+ | <code>+</code> 1+ | <code>?</code> 0-1 | <code>(?<=X)</code> after X | <code>(?=X)</code> before X | <code>[abc]</code> one of | <code>(a|b)</code> or",
    "<br><i style='color: #565f89;'>--- Запуск":
            "<br><i style='color: #565f89;'>--- Launch",
    "== (равно)":                           "== (equals)",
    "=== ЗАДАЧА ===":                       "=== TASK ===",
    "Исправь ошибку. Используй file_write для перезаписи сломанных файлов и shell_exec/code_execute для повторного теста.":
            "Correct the mistake. Use file_write to overwrite broken files and shell_exec/code_execute for retest.",
    "=== КОНЕЦ ===":                        "=== END ===",
    "=== КОНЕЦ КОНТЕКСТА ===":              "=== END OF CONTEXT ===",
    "=== КОНТЕКСТ ТЕКУЩЕЙ ЗАДАЧИ ===":      "=== CONTEXT OF THE CURRENT TASK ===",
    "=== ОШИБКА ТЕСТИРОВАНИЯ (попытка":     "=== TESTING ERROR (attempt",
    "=== ФАЙЛЫ ПРОЕКТА ===":                "=== PROJECT FILES ===",
    "> (больше)":                           "> (more)",
    ">= (больше или равно)":                ">= (greater than or equal to)",
    "AI-агент анализирует DOM страницы и выполняет действия в браузере. Получает задачу от Planner-ноды, составляет и исполняет план кликов/ввода.":
            "AI-agent analyzes DOM pages and performs actions in the browser. Receives a task from Planner-nodes, creates and executes a click plan/input.",
    "Browser Module — Полноценный модуль браузерной автоматизации.":
            "Browser Module — Full-fledged browser automation module.",
    "Аналог ZennoPoster Browser Actions:":  "Analogue ZennoPoster Browser Actions:",
    "  - Запуск браузера с профилем / прокси":
            "  - Launching a browser with a profile / proxy",
    "  - Навигация, клики, ввод текста":    "  - Navigation, clicks, text input",
    "  - Куки, JS, скриншоты":              "  - Cookies, JS, screenshots",
    "  - Управление вкладками":             "  - Managing tabs",
    "  - Настройки браузера (картинки, медиа, JS, Canvas и т.д.)":
            "  - Browser settings (pictures, media, JS, Canvas etc.d.)",
    "Поддерживает Selenium (chromedriver) и Playwright (async).":
            "Supports Selenium (chromedriver) And Playwright (async).",
    "Если ни одна библиотека не установлена — работает в «заглушечном» режиме.":
            "If no library is installed — works in «stub» mode.",
    "CSS-селектор, XPath, URL или JS-код":  "CSS-selector, XPath, URL or JS-code",
    "Callback для runtime — обновляет переменную проекта и UI":
            "Callback For runtime — updates the project variable and UI",
    "DOM (сокращённый):":                   "DOM (abbreviated):",
    "Default (нет совпадения):":            "Default (no match):",
    "Eval в Python (js2py)":                "Eval V Python (js2py)",
    "F5 — Запуск с начала":                 "F5 — Starting from the beginning",
    "F6 — Запуск от выбранного сниппета до конца":
            "F6 — Run from the selected snippet to the end",
    "F7 — Выполнить только выделенные сниппеты":
            "F7 — Execute selected snippets only",
    "F8 — Запуск в пошаговом режиме (пауза перед каждым)":
            "F8 — Start in step-by-step mode (pause before each)",
    "Headless режим":                       "Headless mode",
    "Headless режим (без окна)":            "Headless mode (without window)",
    "ID инстанса →:":                       "ID instance →:",
    "ID инстанса:":                         "ID instance:",
    "IP или домен":                         "IP or domain",
    "JsonPath / XPath запрос":              "JsonPath / XPath request",
    "KEY=VALUE по строкам":                 "KEY=VALUE line by line",
    "LLM Маршрутизатор":                    "LLM Router",
    "Patcher: читает ошибку, читает файлы, фиксит по одному.":
            "Patcher: reads the error, reads files, fixes one by one.",
    "Python выражение (свободный)":         "Python expression (free)",
    "Random (генерация)":                   "Random (generation)",
    "Redo отменённого действия":            "Redo canceled action",
    "Regex (поиск)":                        "Regex (search)",
    "Regex / Что искать:":                  "Regex / What to look for:",
    "Regex не нашёл:":                      "Regex didn't find it:",
    "SEARCH/REPLACE патчи":                 "SEARCH/REPLACE patches",
    "STOP: Switch: нет совпадения для '":   "STOP: Switch: no match for '",
    "Script Runner: спрашивает AI что запустить → запускает → возвращает результат.":
            "Script Runner: asks AI what to run → launches → returns the result.",
    "Shift+колесико = горизонтально, Ctrl+колесико = зум, иначе = вертикально.":
            "Shift+wheel = horizontally, Ctrl+wheel = zoom, otherwise = vertically.",
    "Split (разделить)":                    "Split (divide)",
    "Switch: нет совпадения для '":         "Switch: no match for '",
    "URL или селектор":                     "URL or selector",
    "URL реферера (откуда пришли)":         "URL referrer (where did you come from)",
    "Undo последнего действия":             "Undo last action",
    "Vision модель:":                       "Vision model:",
    "    Opened from main window via '🤖 Конструктор агентов' button.":
            "    Opened from main window via '🤖 Agent constructor' button.",
    "While (пока условие)":                 "While (while the condition)",
    "Workflow не задан":                    "Workflow not specified",
    "Workflow уже выполняется.":            "Workflow already running.",
    "[DEBUG CHECK] В модели:":              "[DEBUG CHECK] In the model:",
    "[DEBUG] BROWSER_AGENT: fallback на глобальный инстанс":
            "[DEBUG] BROWSER_AGENT: fallback to a global instance",
    "[DEBUG] BROWSER_AGENT: fallback не сработал:":
            "[DEBUG] BROWSER_AGENT: fallback didn't work:",
    "[DEBUG] BROWSER_AGENT: ищу browser_id, найдено:":
            "[DEBUG] BROWSER_AGENT: looking for browser_id, found:",
    "[DEBUG] Callback вызван успешно":      "[DEBUG] Callback called successfully",
    "[DEBUG] _project_variables не установлен":
            "[DEBUG] _project_variables not installed",
    "[DEBUG] _vars_panel недоступен":       "[DEBUG] _vars_panel unavailable",
    "[DEBUG] execute_browser_agent_node: ищу iid=":
            "[DEBUG] execute_browser_agent_node: looking for iid=",
    "[DEBUG] Восстановлен browser_instance_id из project_variables:":
            "[DEBUG] Restored browser_instance_id from project_variables:",
    "[DEBUG] Использован fallback на активный инстанс:":
            "[DEBUG] Used fallback to active instance:",
    "[DEBUG] Найден инстанс в ProjectBrowserManager:":
            "[DEBUG] Instance found in ProjectBrowserManager:",
    "[DEBUG] Найден инстанс в глобальном BrowserManager:":
            "[DEBUG] Found instance in global BrowserManager:",
    "[DEBUG] Ошибка fallback:":             "[DEBUG] Error fallback:",
    "[DEBUG] Ошибка получения из BrowserManager:":
            "[DEBUG] Error receiving from BrowserManager:",
    "[DEBUG] Ошибка получения из ProjectBrowserManager:":
            "[DEBUG] Error receiving from ProjectBrowserManager:",
    "[DEBUG] Переменная '":                 "[DEBUG] Variable '",
    "[DEBUG] Подготовлены project_vars:":   "[DEBUG] Prepared project_vars:",
    "[DEBUG] Синхронизирован browser_instance_id в project_variables":
            "[DEBUG] Synchronized browser_instance_id V project_variables",
    "[DELAYED LOAD] node is None или не валиден, пропускаю":
            "[DELAYED LOAD] node is None or not valid, I'm missing",
    "[LOAD OK] Применено":                  "[LOAD OK] Applied",
    "[LOAD] node_settings_by_name не найден в":
            "[LOAD] node_settings_by_name not found in",
    "[POPULATE] Повторная загрузка для":    "[POPULATE] Reload for",
    "[SAVE ALL] Всего сохранено сниппетов:":
            "[SAVE ALL] Total snippets saved:",
    "[SAVE ALL] Текущая нода":              "[SAVE ALL] Current node",
    "[UI SYNC WARNING] Переменная":         "[UI SYNC WARNING] Variable",
    "[UI SYNC] Обновлена строка":           "[UI SYNC] Line updated",
    "] Выполнение:":                        "] Execution:",
    "] Выполнено (":                        "] Done (",
    "] Исправляю:":                         "] I'm correcting:",
    "] Ошибка:":                            "] Error:",
    "] Пропуск (уже есть):":                "] Pass (already there):",
    "] Создаю:":                            "] I create:",
    "] заполнен (":                         "] filled (",
    "] удалён":                             "] deleted",
    "contains (содержит)":                  "contains (contains)",
    "endswith (заканчивается)":             "endswith (ends)",
    "is empty (пустой)":                    "is empty (empty)",
    "is not empty (не пустой)":             "is not empty (not empty)",
    "login:pass@host:port  или  host:port": "login:pass@host:port  or  host:port",
    "not contains (не содержит)":           "not contains (does not contain)",
    "s из":                                 "s from",
    "startswith (начинается)":              "startswith (begins)",
    "target=x,y (например: 100,200)":       "target=x,y (For example: 100,200)",
    "target=домен (пусто=все)":             "target=domain (empty=All)",
    "target=домен → variable_out":          "target=domain → variable_out",
    "target=имя/номер":                     "target=Name/number",
    "target=имя/номер/текущую":             "target=Name/number/current",
    "target=код → variable_out":            "target=code → variable_out",
    "target=логин value=пароль":            "target=login value=password",
    "target=паттерн":                       "target=pattern",
    "target=селектор":                      "target=selector",
    "target=селектор value=true/false":     "target=selector value=true/false",
    "target=селектор value=атрибут → variable_out":
            "target=selector value=attribute → variable_out",
    "target=селектор value=значение":       "target=selector value=meaning",
    "target=селектор value=путь":           "target=selector value=path",
    "target=селектор value=текст":          "target=selector value=text",
    "target=селектор → variable_out":       "target=selector → variable_out",
    "target=текст":                         "target=text",
    "target=текст для поиска":              "target=search text",
    "value=имя":                            "value=Name",
    "value=описание_что_сделать (Planner context)":
            "value=description_What_do (Planner context)",
    "value=ответ":                          "value=answer",
    "value=путь":                           "value=path",
    "value=секунды":                        "value=seconds",
    "{имя_переменной} для сохранения последнего извлечённого значения":
            "{Name_variable} to save the last retrieved value",
    "{имя_переменной} для сохранения результата":
            "{Name_variable} to save the result",
    "|| (ИЛИ) — хотя бы одно":              "|| (OR) — at least one",
    "Авто":                                 "Auto",
    "Автовстраивание в панель":             "Auto-embedding into panel",
    "Автозакрытие через (сек):":            "Auto-close after (sec):",
    "Автоисправление отступов":             "Auto-correct indentation",
    "Автоматически подогнать размер заметки под текст.":
            "Automatically adjust note size to fit text.",
    "Автоматический патчинг кода при ошибке":
            "Automatic code patching in case of error",
    "Автоопределение":                      "Auto detection",
    "Автоопределение типа (число/bool/строка)":
            "Auto type detection (number/bool/line)",
    "Автопатчинг при ошибках":              "Auto-patching for errors",
    "Автотестирование результата":          "Autotest result",
    "Автоформатирование":                   "Autoformatting",
    "Агент со скиллом":                     "Agent with skill",
    "Адрес:":                               "Address:",
    "Активировать вкладку":                 "Activate tab",
    "Анализ CSV, JSON, логов, метрик":      "Analysis CSV, JSON, lairs, metrics",
    "Анализ данных":                        "Data Analysis",
    "Анализ изображений":                   "Image Analysis",
    "Анализ кода на баги, уязвимости и улучшения":
            "Code analysis for bugs, vulnerabilities and improvements",
    "Анализ скриншотов и изображений через vision модель":
            "Analysis of screenshots and images via vision model",
    "Аналог для Playwright (упрощённый).":  "Analogue for Playwright (simplified).",
    "Аргументы командной строки. Переменные: {var_name}":
            "Command Line Arguments. Variables: {var_name}",
    "Архитектура":                          "Architecture",
    "Базовые":                              "Basic",
    "Базовый класс для команд undo/redo":   "Base class for commands undo/redo",
    "Башня из":                             "Tower of",
    "Без названия":                         "Untitled",
    "Без учёта регистра":                   "Case insensitive",
    "Безопасная синхронизация текущей ноды перед сохранением.":
            "Secure synchronization of the current node before saving.",
    "Безопасное самоудаление из сцены.":    "Safely remove yourself from a scene.",
    "Безопасное удаление шапки.":           "Safely removing the header.",
    "Бирюзовый":                            "Turquoise",
    "Блокировать всплывающие окна":         "Block pop-ups",
    "Блокировать уведомления браузера":     "Block browser notifications",
    "Браузер":                              "Browser",
    "Браузер запущен":                      "Browser is running",
    "Браузер не запущен":                   "Browser is not running",
    "Браузер:":                             "Browser:",
    "Булево (True/False)":                  "Boolean (True/False)",
    "Булево (bool)":                        "Boolean (bool)",
    "Быстрая модель:":                      "Fast model:",
    "Быстрый запуск браузера через диалог.":
            "Quickly launch the browser through a dialog.",
    "Бэкап папки перед ЭТИМ сниппетом":     "Backup folder before THIS snippet",
    "Бэкап папки проекта перед КАЖДЫМ агентом (глобально)":
            "Backup project folder before EACH agent (globally)",
    "Бэкап рабочей папки перед выполнением узла.":
            "Backup of the working folder before running the node.",
    "В конец":                              "To the end",
    "В начало":                             "To the beginning",
    "В переменную":                         "To a variable",
    "В список":                             "Add to list",
    "В:":                                   "IN:",
    "ВЫПОЛНИ ЗАДАЧУ:":                      "COMPLETE THE TASK:",
    "Валидировать перед применением":       "Validate before use",
    "Введите JS код. Переменные: {var_name}":
            "Enter JS code. Variables: {var_name}",
    "Введите код здесь. Переменные: {var_name}":
            "Enter code here. Variables: {var_name}",
    "Введите код...":                       "Enter code...",
    "Ввести текст":                         "Enter text",
    "Верификация что клик попал туда куда нужно.":
            "Verification that the click went where it should.",
    "        Возвращает (успех, сообщение)":
            "        Returns (success, message)",
    "Верификация:":                         "Verification:",
    "Вернуть данные обратно при ошибке":    "Return data back on error",
    "Вернуться к началу (перезапуск)":      "Return to top (restart)",
    "Взять столбец в список":               "Take a column into a list",
    "Взять текст (прочитать)":              "Take text (read)",
    "Вид (View) с поддержкой зума и навигации.":
            "View (View) with zoom and navigation support.",
    "Виджет конфигурации сниппета BROWSER_ACTION.":
            "Snippet configuration widget BROWSER_ACTION.",
    "    Встраивается в панель свойств AgentConstructor.":
            "    Embeds in the properties panel AgentConstructor.",
    "Виджет конфигурации сниппета BROWSER_LAUNCH.":
            "Snippet configuration widget BROWSER_LAUNCH.",
    "    Позволяет задать профиль, прокси и аргументы прямо в ноде.":
            "    Allows you to set a profile, proxies and arguments directly in the node.",
    "Видимый текст:":                       "Visible text:",
    "Визуальный конструктор":               "Visual designer",
    "Вкладка управления скиллами (заглушка - основная логика в палитре слева)":
            "Skills management tab (stub - main logic in the palette on the left)",
    "Включать элементы внутри Shadow DOM (нужно для современных SPA)":
            "Include elements inside Shadow DOM (needed for modern SPA)",
    "Включить JavaScript":                  "Turn on JavaScript",
    "Включить верификацию":                 "Enable verification",
    "Включить время выполнения":            "Enable runtime",
    "Включить имя ошибочного узла":         "Include the name of the failed node",
    "Включить контекст в отчёт":            "Include context in the report",
    "Включить текст последней ошибки":      "Include last error text",
    "Включить эмуляцию геолокации":         "Enable geolocation emulation",
    "Вместить все элементы в видимую область.":
            "Fit all elements into visible area.",
    "Вместить всё":                         "Fit everything",
    "Восстановить данные в списки":         "Restore data to lists",
    "Восстановить данные таблицы переменных":
            "Restore variable table data",
    "Восстановить окно браузера как отдельное.":
            "Restore the browser window as a separate one.",
    "Восстановление состояния ноды из snapshot":
            "Restoring the node state from snapshot",
    "Вперёд":                               "Forward",
    "Время выполнения:":                    "lead time:",
    "Время:":                               "Time:",
    "Все":                                  "All",
    "Все попытки исчерпаны:":               "All attempts are exhausted:",
    "Всего действий в браузере:":           "Total browser actions:",
    "Вспомогательный метод для создания ноды и авто-подключения стрелки.":
            "Helper method for creating a node and auto-connecting an arrow.",
    "Вставить regex в поле 'Regex / Что искать' текущего сниппета":
            "Insert regex in the field 'Regex / What to look for' current snippet",
    "Вставить regex из тестера в поле 'pattern' текущего сниппета.":
            "Insert regex from tester to field 'pattern' current snippet.",
    "Вставить в указанную позицию, восстанавливая блоковую структуру":
            "Paste at specified position, restoring the block structure",
    "Вставить выбранную переменную контекста как новую строку в таблицу.":
            "Insert the selected context variable as a new row into the table.",
    "Вставить переменную":                  "Insert Variable",
    "Вставить путь к папке через диалог.":  "Paste folder path via dialog.",
    "Вставить путь к файлу через диалог.":  "Paste file path through dialog.",
    "Вставить путь:":                       "Paste path:",
    "Вставить содержимое буфера обмена как список (по строкам).":
            "Paste clipboard contents as list (line by line).",
    "Вставить текст в виджет в позицию курсора.":
            "Insert text into widget at cursor position.",
    "Вставить текст переменной в виджет в позицию курсора.":
            "Insert variable text into widget at cursor position.",
    "Вставка":                              "Insert",
    "Вставьте JSON или XML. Переменные: {var_name}":
            "Paste JSON or XML. Variables: {var_name}",
    "Вставьте текст для поиска регулярным выражением...":
            "Insert text to search with regular expression...",
    "Встроить / открепить выбранный инстанс.":
            "Embed / unpin the selected instance.",
    "Встроить окно браузера в Qt-виджет (Windows-only через WinAPI).":
            "Embed browser window in Qt-widget (Windows-only through WinAPI).",
    "Встроить окно браузера в панель (только Windows)":
            "Embed a browser window in a panel (only Windows)",
    "Входной текст — User Prompt или поле ниже. Переменные: {var_name}":
            "Input text — User Prompt or field below. Variables: {var_name}",
    "Входной текст:":                       "Input text:",
    "Выбери ровно 2 агента для соединения.":
            "Choose exactly 2 connection agent.",
    "Выберите агента, от которого начать выполнение.":
            "Select an agent, from which to start execution.",
    "Выберите базовую папку для проекта":   "Select a base folder for the project",
    "Выберите инстанс из списка":           "Select an instance from the list",
    "Выберите модель...":                   "Select model...",
    "Выберите папку для создания файлов...":
            "Select a folder to create files...",
    "Выберите папку со скиллами":           "Select a folder with skills",
    "Выберите рабочую папку для проекта":   "Select a working folder for the project",
    "Выбор файла:":                         "File selection:",
    "Выбрать CSV/TSV файл для прикрепления к сниппету.":
            "Choose CSV/TSV file to attach to snippet.",
    "Выбрать CSV/TSV файл с переменными":   "Choose CSV/TSV variable file",
    "Выбрать кастомный цвет для текущей ноды.":
            "Select a custom color for the current node.",
    "Выбрать кастомный цвет для этого узла":
            "Select a custom color for this node",
    "Выбрать лучшую доступную модель для сложных задач":
            "Choose the best available model for complex tasks",
    "Выбрать опцию":                        "Select option",
    "Выбрать папку":                        "Select folder",
    "Выбрать папку профиля":                "Select profile folder",
    "Выбрать файл":                         "Select file",
    "Выбрать файл скрипта":                 "Select script file",
    "Выбрать цвет заметки.":                "Select note color.",
    "Выводить в консоль":                   "Output to console",
    "Выделите агентов для выполнения.":     "Allocate agents to execute.",
    "Вызывается извне для заполнения комбобоксов моделями":
            "Called externally to fill comboboxes with models",
    "Вызывается при любом изменении в правой панели свойств.":
            "Called when any change is made in the right property pane.",
    "Вызывается при смене темы":            "Called when the theme is changed",
    "Вызывать при запуске/закрытии инстанса.":
            "Call on startup/closing the instance.",
    "Выполнение":                           "Execution",
    "Выполнение shell команд":              "Execution shell teams",
    "Выполнение действий через Selenium.":  "Performing actions via Selenium.",
    "Выполнение действия браузера.":        "Execute a browser action.",
    "Выполнение кода":                      "Executing Code",
    "Выполнение с повторами и самоисправлением":
            "Execution with repetitions and self-correction",
    "Выполнено действий:":                  "Actions completed:",
    "Выполни действие из задачи выше.":     "Complete the action from the task above.",
    "Выполнить BROWSER_AGENT:":             "Execute BROWSER_AGENT:",
    "Выполнить JS":                         "Execute JS",
    "Выполнить действие. Возвращает результат или None.":
            "Perform an action. Returns the result or None.",
    "Выполнить один шаг и снова встать на паузу.":
            "Take one step and pause again.",
    "Выполнить сниппет BROWSER_ACTION.":    "Run snippet BROWSER_ACTION.",
    "    Возвращает обновлённый context.":  "    Returns updated context.",
    "Выполнить сниппет BROWSER_LAUNCH.":    "Run snippet BROWSER_LAUNCH.",
    "    Возвращает обновлённый context.":  "    Returns updated context.",
    "Выполнить только выделенные сниппеты (создаем временный workflow).":
            "Execute selected snippets only (create a temporary workflow).",
    "Выполняет JavaScript код. Режим: локально или в контексте данных. Переменные: {var_name}":
            "Performs JavaScript code. Mode: locally or in data context. Variables: {var_name}",
    "Выполняет Python/Shell/Node код. Переменные: {var_name}":
            "Performs Python/Shell/Node code. Variables: {var_name}",
    "Выполняет действие в открытом браузере. Используйте {переменные} в полях. Для координат: X и Y от левого верхнего угла окна браузера.":
            "Performs an action while the browser is open. Use {variables} in the fields. For coordinates: X And Y from the upper left corner of the browser window.",
    "Выполняется при ошибке в любом узле, если узел не имеет ON_FAILURE ребра. Используйте для восстановления данных, логирования ошибок.":
            "Executed when there is an error in any node, if the node does not have ON_FAILURE ribs. Use for data recovery, error logging.",
    "Выполняется при успешном завершении ветки. Действия привязанные после Good End выполнятся перед финальным завершением.":
            "Executed when a branch is completed successfully. Actions linked after Good End will be executed before final completion.",
    "Высота":                               "Height",
    "Высота viewport":                      "Height viewport",
    "Высота окна браузера":                 "Browser window height",
    "Высота окна:":                         "Window height:",
    "Выстроить выбранные сниппеты в вертикальную башню и соединить стрелками.":
            "Arrange the selected snippets in a vertical tower and connect with arrows.",
    "Выход по ON_FAILURE":                  "Exit by ON_FAILURE",
    "Выход по условию:":                    "Exit by condition:",
    "Выходной порт — зависит от стороны цели (левый или правый).":
            "Output port — depends on the side of the target (left or right).",
    "Генерация изображений":                "Generating Images",
    "Генерация кода":                       "Code generation",
    "Генерация чисел, строк, логинов. Результат в переменной.":
            "Number generation, lines, logins. Result in variable.",
    "Глобальная область видимости":         "Global scope",
    "Готов":                                "Ready",
    "Готово":                               "Ready",
    "Графические элементы нод и связей.":   "Graphic elements of nodes and connections.",
    "Дамп всего контекста":                 "Dump the entire context",
    "Дважды кликните на иконке трея чтобы показать":
            "Double click on the tray icon to show",
    "Движок:":                              "Engine:",
    "Двойной клик - создать агента":        "Double click - create agent",
    "Двойной клик по координатам":          "Double click on coordinates",
    "Двойной клик по элементу":             "Double click on an element",
    "Двойной клик — быстрое открепление первого нода из блока":
            "Double click — quick detachment of the first node from the block",
    "Действие:":                            "Action:",
    "Детали по задачам:":                   "Details by task:",
    "Детали:":                              "Details:",
    "Дефолт — верхний левый (используется только как fallback).":
            "Default — top left (used only as fallback).",
    "Диалог ввода произвольного имени переменной.":
            "Dialog for entering a custom variable name.",
    "Диалог запуска браузера.":             "Browser launch dialog.",
    "    Позволяет выбрать/создать профиль и настроить прокси.":
            "    Allows you to select/create a profile and configure a proxy.",
    "Диалог создания кастомного скилла":    "Dialogue for creating a custom skill",
    "Диапазон случайности %:":              "Range of randomness %:",
    "Динамическое изменение высоты для Switch.":
            "Dynamic height change for Switch.",
    "Директории":                           "Directories",
    "Директория не существует:":            "Directory does not exist:",
    "Длина (length)":                       "Length (length)",
    "Длина строки до:":                     "Line length up to:",
    "Длина строки от:":                     "Line length from:",
    "Для POST/PUT/PATCH":                   "For POST/PUT/PATCH",
    "Для clear_all: через запятую":         "For clear_all: separated by commas",
    "Для copy/length: куда записать результат":
            "For copy/length: where to write the result",
    "Для foreach_list: имя списка/переменной":
            "For foreach_list: list name/variable",
    "Для list_files/list_dirs":             "For list_files/list_dirs",
    "Для query/to_list — список совпадений":
            "For query/to_list — hit list",
    "Для set. Переменные: {var_name}. Для concat: через запятую var1,var2,text":
            "For set. Variables: {var_name}. For concat: separated by commas var1,var2,text",
    "Для set_value. Переменные: {var_name}":
            "For set_value. Variables: {var_name}",
    "Для split":                            "For split",
    "Для split/regex all":                  "For split/regex all",
    "Для to_list: имя поля в каждом элементе":
            "For to_list: field name in each element",
    "Для to_table":                         "For to_table",
    "Для взять столбец / получить строку":  "To take a column / get string",
    "Для внутреннего использования (загрузка файлов) - без валидации":
            "For internal use (uploading files) - without validation",
    "Для добавления, поиска, фильтрации. Переменные: {var_name}":
            "To add, search, filtering. Variables: {var_name}",
    "Для замены":                           "For replacement",
    "Для записи. Переменные: {var_name}":   "For recording. Variables: {var_name}",
    "Для копирования/перемещения":          "To copy/movements",
    "Для поиска/фильтрации":                "To search/filtering",
    "Для разбиения строки в список":        "To split a string into a list",
    "Для цикличных workflow":               "For cyclic workflow",
    "Добавить Command объект в историю":    "Add Command object into history",
    "Добавить в список (по свойству)":      "Add to list (by property)",
    "Добавить в таблицу":                   "Add to table",
    "Добавить выбранную переменную контекста как строку в таблицу":
            "Add the selected context variable as a row to the table",
    "Добавить действие в историю (legacy tuple format)":
            "Add action to story (legacy tuple format)",
    "Добавить к списку (Append)":           "Add to list (Append)",
    "Добавить скилл":                       "Add skill",
    "Добавить скилл к выбранному агенту":   "Add a skill to the selected agent",
    "Добавить скилл к ноде напрямую (для контекстного меню)":
            "Add a skill to a node directly (for context menu)",
    "Добавить скилл к текущей выбранной ноде":
            "Add a skill to the currently selected node",
    "Добавить список в столбец":            "Add a list to a column",
    "Добавить строку":                      "Add line",
    "Добавить строку переменной в таблицу сниппета":
            "Add a variable row to the snippet table",
    "Добавить текст (многострочный)":       "Add text (multiline)",
    "Добавлен агент:":                      "Agent added:",
    "Добавлена строка (":                   "Added line (",
    "Добавление":                           "Addition",
    "Добавлено":                            "Added",
    "Добавлено: '":                         "Added: '",
    "Добавлять timestamp":                  "Add timestamp",
    "Добавлять имя ноды":                   "Add node name",
    "Добавьте хотя бы одного агента.":      "Add at least one agent.",
    "Документация":                         "Documentation",
    "Долгота (°):":                         "Longitude (°):",
    "Доп. условия (по строкам):":           "Extra. conditions (line by line):",
    "Дописать в файл (не перезаписывать)":  "Append to file (do not overwrite)",
    "Дописывать в файл (не перезаписывать)":
            "Append to file (do not overwrite)",
    "Дополнительные инструкции...":         "Additional Instructions...",
    "Дополнительный перенос строки":        "Additional line break",
    "Дробное (float)":                      "Fractional (float)",
    "Дубли (по столбцу":                    "Doubles (by column",
    "Если заполнено — используются только эти":
            "If filled — only these are used",
    "Если отключено — последняя строка stdout = результат":
            "If disabled — last line stdout = result",
    "Ждать URL":                            "Wait URL",
    "Ждать подтверждения пользователя":     "Wait for user confirmation",
    "Ждать после клика (сек)":              "Wait after click (sec)",
    "Ждать элемент":                        "Wait element",
    "Желтый":                               "Yellow",
    "Завершено за":                         "Completed in",
    "Заглавные (A-Z)":                      "Uppercase (A-Z)",
    "Заголовки (по строкам):":              "Headings (line by line):",
    "Заголовки и содержимое":               "Headings and content",
    "Заголовок заметки...":                 "Note title...",
    "Заголовок...":                         "Heading...",
    "Заголовок:":                           "Heading:",
    "Загружаем ВСЕ глобальные настройки из workflow metadata.":
            "Loading ALL global settings from workflow metadata.",
    "Загружать CSS стили":                  "Load CSS styles",
    "Загружать картинки":                   "Upload pictures",
    "Загружать медиа (video/audio)":        "Upload media (video/audio)",
    "Загружать фреймы":                     "Load frames",
    "Загружать:":                           "Load:",
    "Загружено":                            "Uploaded",
    "Загрузить CSV/TSV файл в таблицу переменных.":
            "Download CSV/TSV file to variable table.",
    "Загрузить snippet_config из ноды в виджеты.":
            "Download snippet_config from node to widgets.",
    "Загрузить встроенные + глобальные скиллы из папки программы":
            "Load built-in + global skills from the program folder",
    "Загрузить данные":                     "Download data",
    "Загрузить данные из файла и вставить в виджет.":
            "Load data from file and paste into widget.",
    "Загрузить из файла":                   "Load from file",
    "Загрузить конфиг сниппета из ноды в виджеты.":
            "Load snippet config from node to widgets.",
    "Загрузить переменные из CSV/TSV файла (столбцы: имя, значение, тип, описание)":
            "Load variables from CSV/TSV file (columns: Name, meaning, type, description)",
    "Загрузить переменные при открытии проекта.":
            "Load variables when opening a project.",
    "Загрузить прикреплённый файл таблицы в виджет переменных (предпросмотр).":
            "Load the attached table file into the variables widget (preview).",
    "Загрузить скиллы из проекта":          "Upload skills from the project",
    "Загрузка и сохранение профилей браузера на диск.":
            "Loading and saving browser profiles to disk.",
    "Задержка после каждого действия для загрузки страницы":
            "Delay after each action to load the page",
    "Зажатие средней кнопки мыши для панорамирования.":
            "Middle mouse button to pan.",
    "Зажмите чтобы переместить блок":       "Press to move block",
    "Зажмите шапку чтобы переместить блок": "Hold the cap to move the block",
    "Закрывает браузерный инстанс. Оставьте поле пустым чтобы закрыть все.":
            "Closes the browser instance. Leave the field blank to close all.",
    "Закрытие браузерного инстанса.":       "Closing a browser instance.",
    "Закрыть браузер":                      "Close browser",
    "Закрыть браузер.":                     "Close browser.",
    "Закрыть вкладку":                      "Close tab",
    "Закрыть проект":                       "Close project",
    "Замена (replace)":                     "Replacement (replace)",
    "Заметка:":                             "Note:",
    "Записано [":                           "Recorded [",
    "Записать EXIT CODE":                   "Write down EXIT CODE",
    "Записать STD ERR в переменную":        "Write down STD ERR into a variable",
    "Записать STD OUT в переменную":        "Write down STD OUT into a variable",
    "Записать в лог об успешном завершении":
            "Write to log about successful completion",
    "Записать ошибку в лог":                "Log the error",
    "Записать перенос строки в конец":      "Write line break to end",
    "Записать текст":                       "Write text",
    "Записать ячейку":                      "Write cell",
    "Записывает сообщение в лог и/или файл. Переменные: {name}":
            "Writes the message to the log and/or file. Variables: {name}",
    "Записывать в лог":                     "Write to log",
    "Записывать в файл":                    "Write to file",
    "Запись файлов":                        "Recording files",
    "Запуск":                               "Launch",
    "Запуск .exe, .bat, Python-скриптов, ffmpeg, ImageMagick и т.д. Переменные: {var_name}":
            "Launch .exe, .bat, Python-scripts, ffmpeg, ImageMagick etc.d. Variables: {var_name}",
    "Запуск Selenium WebDriver.":           "Launch Selenium WebDriver.",
    "Запуск workflow с полным контролем":   "Launch workflow with full control",
    "Запуск без видимого окна браузера":    "Running without a visible browser window",
    "Запуск браузерного инстанса.":         "Launching a browser instance.",
    "Запуск в пошаговом режиме — пауза перед каждым сниппетом.":
            "Start in step-by-step mode — pause before each snippet.",
    "Запуск от выбранного сниппета до конца.":
            "Run from the selected snippet to the end.",
    "Запуск программы":                     "Starting the program",
    "Запуск с начала.":                     "Starting from the beginning.",
    "Запускает браузер с выбранным профилем и прокси. ID инстанса сохраняется в переменную. Убедитесь что установлено: pip install selenium webdriver-manager":
            "Launches the browser with the selected profile and proxy. ID instance is saved to a variable. Make sure it's installed: pip install selenium webdriver-manager",
    "Запустить браузер прямо сейчас для теста.":
            "Launch your browser right now to test.",
    "Запустить браузер. Возвращает True при успехе.":
            "Launch browser. Returns True upon success.",
    "Запустить новый инстанс браузера.":    "Launch a new browser instance.",
    "Запустить тест регулярного выражения.":
            "Run a regular expression test.",
    "Запятая (,)":                          "Comma (,)",
    "Захват текущего состояния ноды для undo":
            "Capture the current state of the node for undo",
    "Здесь будет отображаться диалог с AI агентами...":
            "A dialog with AI agents...",
    "Зеленый":                              "Green",
    "Значение":                             "Meaning",
    "Значение / текст:":                    "Meaning / text:",
    "Значение для ввода/параметр...":       "Input value/parameter...",
    "Значение для сравнения. Пример: {max_count} или 10":
            "Comparison value. Example: {max_count} or 10",
    "Значение или {другая_переменная}":     "Meaning or {other_variable}",
    "Значение:":                            "Meaning:",
    "Значения строки:":                     "Row values:",
    "Зум миникарты колесиком мыши.":        "Zoom minimap with mouse wheel.",
    "Идти по последнему ребру":             "Walk along the last rib",
    "Из контекста:":                        "From context:",
    "Из переменной":                        "From variable",
    "Из файла":                             "From file",
    "Извлечь DOM текущей страницы и сжать до max_tokens примерно (~4 символа = 1 токен).":
            "Extract DOM current page and compress to max_tokens approximately (~4 symbol = 1 token).",
    "        Убирает скрипты, стили, svg, мета-теги. Оставляет текст, alt, placeholder, aria-label,":
            "        Removes scripts, styles, svg, meta tags. Leaves text, alt, placeholder, aria-label,",
    "        href, id, name — всё что нужно AI для понимания структуры страницы.":
            "        href, id, name — everything you need AI to understand the page structure.",
    "Извлечь файлы из markdown code-блоков и записать на диск.":
            "Extract files from markdown code-blocks and write to disk.",
    "        Ищет паттерны вида:":          "        Looks for patterns like:",
    "          # filename.py   (или ## filename.py, или **filename.py**)":
            "          # filename.py   (or ## filename.py, or **filename.py**)",
    "        А также прямые file_write tool-блоки которые не были выполнены.":
            "        And also direct file_write tool-blocks that were not completed.",
    "Изменение":                            "Change",
    "Изменение кода":                       "Code change",
    "Изменение таблицы переменных":         "Changing the variable table",
    "Изменить размер заметки на канвасе.":  "Change note size on canvas.",
    "Изменить размер шрифта заметки.":      "Change note font size.",
    "Иконка:":                              "Icon:",
    "Или используйте User Prompt. Переменные: {var_name}":
            "Or use User Prompt. Variables: {var_name}",
    "Импорт из JSON/TXT":                   "Import from JSON/TXT",
    "Импорт куки из JSON-строки.":          "Import cookies from JSON-lines.",
    "Импорт переменных":                    "Importing Variables",
    "Импорт переменных из CSV/TSV файла в таблицу.":
            "Importing variables from CSV/TSV file to table.",
    "Импорт переменных из JSON/TXT файла.": "Importing variables from JSON/TXT file.",
    "Импорт переменных из файла":           "Importing variables from a file",
    "Имя":                                  "Name",
    "Имя в контексте (без фигурных скобок)":
            "Name in context (without curly braces)",
    "Имя вкладки или номер (0, 1, 2...)":   "Tab name or number (0, 1, 2...)",
    "Имя переменной":                       "Variable name",
    "Имя переменной для установки/изменения":
            "Variable name to set/changes",
    "Имя переменной из контекста (без фигурных скобок)":
            "Variable name from context (without curly braces)",
    "Имя переменной с данными. Пример: {http_response}":
            "Data variable name. Example: {http_response}",
    "Имя переменной-списка в контексте":    "List variable name in context",
    "Имя переменной-таблицы в контексте":   "Table variable name in context",
    "Имя переменной:":                      "Variable name:",
    "Имя профиля:":                         "Profile name:",
    "Имя списка (переменная):":             "List name (variable):",
    "Имя таблицы (переменная):":            "Table name (variable):",
    "Имя файла отчёта:":                    "Report file name:",
    "Имя файла:":                           "File name:",
    "Имя:":                                 "Name:",
    "Инвертировать результат (NOT)":        "Invert result (NOT)",
    "Инжектировать переменные из таблицы в контекст":
            "Inject variables from table into context",
    "Инициализация недостающих атрибутов при вставке нод.":
            "Initialization of missing attributes when inserting nodes.",
    "Инлайн-список:":                       "Inline list:",
    "Инстанс браузера":                     "Browser instance",
    "Инстанс:":                             "Instance:",
    "Инструкции:":                          "Instructions:",
    "Искать в поддиректориях":              "Search in subdirectories",
    "Искомый текст начинается с:":          "The search text begins with:",
    "Исполняемый файл:":                    "Executable file:",
    "Использовать LLM для рекомендации скиллов под задачу":
            "Use LLM to recommend skills for a task",
    "Использовать оригинальный URL":        "Use original URL",
    "Использовать основную":                "Use main",
    "Использовать прокси":                  "Use proxy",
    "Использует LLM для выбора релевантных скиллов из базы":
            "Uses LLM to select relevant skills from the database",
    "Используйте {имя_переменной} в полях выше для подстановки значений":
            "Use {Name_variable} in the fields above to substitute values",
    "Источник данных:":                     "Data source:",
    "Источник:":                            "Source:",
    "Исходный агент не найден":             "Source agent not found",
    "Итеративное создание файлов: один файл = один вызов модели.":
            "Iterative file creation: one file = one model call.",
    "        Шаг 1: Просим модель составить список файлов":
            "        Step 1: We ask the model to make a list of files",
    "        Шаг 2: Для каждого файла — отдельный вызов с контекстом уже созданных":
            "        Step 2: For each file — separate call with context of already created",
    "КОД ВЫХОДА:":                          "EXIT CODE:",
    "КОМАНДА:":                             "TEAM:",
    "КОНТЕКСТ ПОЛНОГО ПЛАНА:":              "CONTEXT OF THE FULL PLAN:",
    "Каждая строка = одно условие. Рёбра привязываются по порядку: 1-е ребро → 1-я строка и т.д.":
            "Each line = one condition. The edges are attached in order: 1-e edge → 1-I'm a string etc.d.",
    "Как файл":                             "As file",
    "Как файл + заголовки":                 "As file + headers",
    "Кастомный View с поддержкой Shift+Scroll (горизонтально), ":
            "Custom View with support Shift+Scroll (horizontally), ",
    "    Ctrl+Scroll (зум без вертикальной прокрутки) и панорамирования.":
            "    Ctrl+Scroll (zoom without vertical scrolling) and panning.",
    "Категория:":                           "Category:",
    "Клик в браузере":                      "Click in browser",
    "Клик по координатам":                  "Click on coordinates",
    "Клик по тексту на странице":           "Click on text on the page",
    "Клик по элементу":                     "Click on an element",
    "Клик попал не в тот элемент: ожидался":
            "The click hit the wrong element: was expected",
    "Клик — открыть":                       "Cry — open",
    "Клики по элементам UI":                "Clicks on elements UI",
    "Ключ / путь:":                         "Key / path:",
    "Код в поле User Prompt":               "Code in the field User Prompt",
    "Кодировка":                            "Encoding",
    "Кодировка:":                           "Encoding:",
    "Количество строк:":                    "Number of lines:",
    "Команда изменения виджета сниппета":   "Command to change snippet widget",
    "Комментарий":                          "Comment",
    "Комментарий (видимый на канвасе)...":  "Comment (visible on canvas)...",
    "Комментарий...":                       "Comment...",
    "Компактный словарь элемента для AI.":  "Compact element dictionary for AI.",
    "Конец искомого текста — ВКЛЮЧАЕТСЯ в результат":
            "End of search text — INCLUDED in the result",
    "Конец ⏭":                              "End ⏭",
    "Конкатенация (склеить)":               "Concatenation (glue)",
    "Константы, цвета и типы нод.":         "Constants, colors and types of nodes.",
    "Контекстное меню для скилла":          "Context menu for skill",
    "Контекстное меню для таблицы переменных.":
            "Context menu for the variable table.",
    "Контекстное меню с вставкой переменных проекта на любое текстовое поле.":
            "Context menu with insertion of project variables on any text field.",
    "Координата X:":                        "Coordinate X:",
    "Координата Y:":                        "Coordinate Y:",
    "Копирование выбранных агентов вместе с блоковой структурой":
            "Copying selected agents along with the block structure",
    "Копировать":                           "Copy",
    "Копировать в другую":                  "Copy to another",
    "Копировать ссылку {var_name} на выбранную переменную в буфер обмена.":
            "Copy link {var_name} to the selected variable to the clipboard.",
    "Красный":                              "Red",
    "Критерий получения/удаления:":         "Receipt criterion/removal:",
    "Критерий строк:":                      "Row criterion:",
    "Куда сохранить stderr":                "Where to save stderr",
    "Куда сохранить stdout":                "Where to save stdout",
    "Куда сохранить полученное значение":   "Where to save the received value",
    "ЛОГ":                                  "LOG",
    "Левая сторона, около верхнего края — когда источник слева.":
            "Left side, near the top edge — when the source is on the left.",
    "Левый операнд:":                       "Left operand:",
    "Лимит памяти (MB)":                    "Memory limit (MB)",
    "Логин (если нужен)":                   "Login (if needed)",
    "Логин / никнейм":                      "Login / nickname",
    "Логин:":                               "Login:",
    "Логировать результат сравнения":       "Log comparison result",
    "Логировать сравнения":                 "Log comparisons",
    "Локальная позиция i-го выходного порта Switch (правая сторона).":
            "Local position i-th output port Switch (right side).",
    "Локально (Node.js)":                   "Locally (Node.js)",
    "Макс. действий за шаг:":               "Max. actions per step:",
    "Макс. итераций:":                      "Max. iterations:",
    "Макс. перезапусков:":                  "Max. restarts:",
    "Макс. размер для записи (KB)":         "Max. recording size (KB)",
    "Макс. размер файла (KB)":              "Max. file size (KB)",
    "Макс. редиректов:":                    "Max. redirects:",
    "Макс. строк вывода":                   "Max. lines of output",
    "Макс. элементов DOM:":                 "Max. elements DOM:",
    "Максимальное время ожидания ответа от AI":
            "Maximum waiting time for a response from AI",
    "Максимизировать":                      "Maximize",
    "Максимум действий в одном запросе к AI":
            "Maximum actions in one request to AI",
    "Максимум итераций:":                   "Maximum iterations:",
    "Максимум элементов для анализа. Больше = точнее, но медленнее":
            "Maximum elements for analysis. More = more precisely, but slower",
    "Масштаб":                              "Scale",
    "Масштабирование канваса.":             "Scaling the canvas.",
    "Менеджер браузерных инстансов.":       "Browser Instance Manager.",
    "    Синглтон — один на всё приложение.":
            "    Singleton — one for the entire application.",
    "Менеджер браузеров для одного проекта.":
            "Browser manager for one project.",
    "    Оборачивает BrowserManager и добавляет project_id-изоляцию.":
            "    Wraps BrowserManager and adds project_id-isolation.",
    "    Каждый проект имеет свой независимый набор инстансов.":
            "    Each project has its own independent set of instances.",
    "Метод:":                               "Method:",
    "Миниатюра браузера в трее — показывает масштабированный скриншот браузера":
            "Browser thumbnail in tray — shows a scaled browser screenshot",
    "    реального размера. Клик = открыть полный инстанс. ":
            "    actual size. Cry = open full instance. ",
    "    Браузер при этом «свёрнут» (minimized), но физически имеет заданный размер.":
            "    The browser «rolled up» (minimized), but physically has a given size.",
    "Миникарта проекта с кнопками навигации.":
            "Project minimap with navigation buttons.",
    "Миникарта проекта.":                   "Project minimap.",
    "Минимальный % изменений пикселей для считывания «действие сработало»":
            "Minimum % pixel changes to read «the action worked»",
    "Многострочный":                        "Multiline",
    "Множественная установка:":             "Multiple installation:",
    "Модели":                               "Models",
    "Модель верификатора:":                 "Verifier model:",
    "Модель для подбора скиллов:":          "Model for selecting skills:",
    "Модель для рассуждений:":              "Model for Reasoning:",
    "Модель:":                              "Model:",
    "НЕ создан на диске!":                  "NOT created on disk!",
    "НЕ существует":                        "does NOT exist",
    "На сколько увеличить/уменьшить":       "How much to increase/decrease",
    "На что заменить:":                     "What to replace with:",
    "Наведение на элемент":                 "Hover over element",
    "Наведение по координатам":             "Guidance by coordinates",
    "Навигация и скриншоты":                "Navigation and screenshots",
    "Назад":                                "Back",
    "Название":                             "Name",
    "Название сниппета":                    "Snippet title",
    "Название:":                            "Name:",
    "Найти HWND главного ВИДИМОГО окна Chrome по PID драйвера.":
            "Find HWND main VISIBLE window Chrome By PID drivers.",
    "Нарисовать иконку глобуса 16×16.":     "Draw a globe icon 16×16.",
    "Наследует глобальную Vision модель, если не выбрано":
            "Inherits global Vision model, if not selected",
    "Наследует глобальную модель, если не выбрано":
            "Inherits the global model, if not selected",
    "Настройки прокси для браузера.":       "Browser proxy settings.",
    "Настройки сниппета":                   "Snippet settings",
    "Настройте AI модель в главном окне перед запуском.":
            "Set up AI model in the main window before launch.",
    "Начало искомого текста — ВКЛЮЧАЕТСЯ в результат":
            "Beginning of search text — INCLUDED in the result",
    "Начало перетаскивания конца стрелки (таргета).":
            "Start dragging the end of the arrow (target).",
    "Начало перетаскивания — запоминаем выбранные ноды.":
            "Start dragging — remember the selected nodes.",
    "Начинается с (startswith)":            "Starts with (startswith)",
    "Не анализировать":                     "Don't analyze",
    "Не возвращать значение":               "Don't return a value",
    "Не выбрано":                           "Not selected",
    "Не ждать завершения работы":           "Don't wait for work to complete",
    "Не использовать":                      "Do not use",
    "Не найден файл:":                      "File not found:",
    "Не найдена точка входа (нода без входящих связей)":
            "Entry point not found (node without incoming connections)",
    "Не очищать:":                          "Do not clean:",
    "Не показывать окно процесса":          "Don't show process window",
    "Не равно (!=)":                        "Not equal (!=)",
    "Не содержит текст":                    "Does not contain text",
    "Не удалось запустить ChromeDriver:":   "Failed to start ChromeDriver:",
    "Не удалось импортировать:":            "Failed to import:",
    "Не удалось прочитать файл:":           "Failed to read file:",
    "Не удалось создать папку:":            "Failed to create folder:",
    "Не удалось сохранить файл:":           "Failed to save file:",
    "Неизвестная операция:":                "Unknown operation:",
    "Неизвестная ошибка":                   "Unknown error",
    "Неизвестный узел":                     "Unknown node",
    "Нельзя связать агента самого с собой": "You cannot link an agent to yourself",
    "Несохранённые изменения":              "Unsaved changes",
    "Нет (одно условие)":                   "No (one condition)",
    "Нет активной AI модели. Настройте модель в главном окне.":
            "No active AI models. Set up the model in the main window.",
    "Нет выбора":                           "No choice",
    "Нет модели":                           "No model",
    "Нет папки":                            "No folder",
    "Нет переменных для экспорта.":         "No variables to export.",
    "Нет строк данных.":                    "No data rows.",
    "Нет файла":                            "No file",
    "Нет файлов в":                         "No files in",
    "Нет элемента по координатам (":        "No element at coordinates (",
    "Нечего отменять":                      "Nothing to cancel",
    "Нечего повторять":                     "Nothing to repeat",
    "Новая вкладка":                        "New tab",
    "Новая заметка":                        "New note",
    "Новый AI-агент: понимает контекст Planner + DOM + screenshot.":
            "New AI-agent: understands the context Planner + DOM + screenshot.",
    "Новый агент":                          "New agent",
    "Новый проект":                         "New project",
    "Новый проект создан":                  "New project created",
    "Новый профиль":                        "New profile",
    "Новый путь:":                          "New way:",
    "Новый скилл":                          "New skill",
    "Номер (с 0) или буква (A, B, C...). Переменные: {var_name}":
            "Number (With 0) or letter (A, B, C...). Variables: {var_name}",
    "Номер итерации (1-based)":             "Iteration number (1-based)",
    "Номер позиции:":                       "Item number:",
    "Номер совпадения:":                    "Match number:",
    "Номер строки:":                        "Line number:",
    "Номер файла:":                         "File number:",
    "Нумерация с 0":                        "Numbering from 0",
    "Нумерация с 0. Переменные: {var_name}":
            "Numbering from 0. Variables: {var_name}",
    "Обзор...":                             "Review...",
    "Обновить вид миникарты чтобы следовать за основным видом.":
            "Update minimap view to follow main view.",
    "Обновить заголовок окна с индикатором изменений.":
            "Update window title with change indicator.",
    "Обновить значение в таблице переменных проекта":
            "Update value in project variable table",
    "Обновить значение переменной в таблице UI без полной перезагрузки":
            "Update the value of a variable in a table UI without a full reboot",
    "Обновить комбобокс переменных контекста из runtime.":
            "Update context variable combobox from runtime.",
    "Обновить комментарий ноды при вводе.": "Update node comment on input.",
    "Обновить корень проекта для браузерных профилей.":
            "Update project root for browser profiles.",
    "Обновить лейбл и слайдер масштаба.":   "Update label and scale slider.",
    "Обновить миникарту под реальные границы проекта (расширение и сужение).":
            "Update the minimap to match the real boundaries of the project (expansion and contraction).",
    "Обновить ноду-заметку при изменении полей.":
            "Update note node when fields change.",
    "Обновить отслеживаемое значение после загрузки (без создания команды)":
            "Update tracked value after loading (without creating a team)",
    "Обновить позицию и размер относительно родительской ноды.":
            "Update position and size relative to parent node.",
    "Обновить позицию шапки при движении ноды.":
            "Update header position when node moves.",
    "Обновить состояние кнопки встраивания.":
            "Update embed button state.",
    "Обновить список скиллов":              "Update skill list",
    "Обработка закрытия окна с проверкой несохранённых изменений.":
            "Handling window closing with checking for unsaved changes.",
    "Обработка клика по портам для создания связей.":
            "Processing a click on ports to create connections.",
    "Обработка переменных":                 "Handling Variables",
    "Обработка ползунка масштаба.":         "Handling the scale slider.",
    "Обработка текста":                     "Word processing",
    "Обработчик изменения значения":        "Value change handler",
    "Объединение условий:":                 "Combining conditions:",
    "Объединено":                           "Merged",
    "Объединить элементы":                  "Merge elements",
    "Обычный режим BROWSER_AGENT — одна задача.":
            "Normal mode BROWSER_AGENT — one task.",
    "Обязательно все типы символов":        "All character types required",
    "Обёртка для HistoryManager.push чтобы отслеживать изменения.":
            "Wrapper for HistoryManager.push to track changes.",
    "Обёртка над реальным браузером (Selenium или Playwright).":
            "A wrapper over a real browser (Selenium or Playwright).",
    "    Сигнализирует об изменении статуса и логах.":
            "    Signals status changes and logs.",
    "Ограничение для любого типа цикла":    "Limit for any loop type",
    "Ограничить рабочей папкой":            "Limit to working folder",
    "Один проект = одна вкладка.":          "One project = one tab.",
    "    Содержит собственную сцену, вид, историю, браузер-менеджер и переменные.":
            "    Contains its own scene, view, history, browser manager and variables.",
    "Один шаг (для пошаговой отладки)":     "One step (for step-by-step debugging)",
    "Одно действие браузера (для сниппета BROWSER_ACTION).":
            "One browser action (for snippet BROWSER_ACTION).",
    "Оператор:":                            "Operator:",
    "Операции с таблицей":                  "Table Operations",
    "Операции со списком":                  "List Operations",
    "Операция:":                            "Operation:",
    "Описание":                             "Description",
    "Описание...":                          "Description...",
    "Описание:":                            "Description:",
    "Определение следующего шага с поддержкой LLM-routing":
            "Determining the next step with support LLM-routing",
    "Определить категорию ноды: 'ai', 'snippet', 'note'.":
            "Determine node category: 'ai', 'snippet', 'note'.",
    "Оранжевый":                            "Orange",
    "Основная вкладка с базовыми настройками агента":
            "Main tab with basic agent settings",
    "Основная модель:":                     "Basic model:",
    "Оставьте пустым для авто":             "Leave blank for auto",
    "Оставьте пустым если не нужно":        "Leave blank if not needed",
    "Останавливает workflow на заданное время":
            "Stops workflow for a given time",
    "Останавливать при ошибке":             "Stop on error",
    "Останавливаться перед выполнением":    "Stop before doing",
    "Остановить workflow":                  "Stop workflow",
    "Остановлено":                          "Stopped",
    "Открепить ноду от родителя и перестроить связи в цепочке":
            "Unpin a node from its parent and rebuild connections in the chain",
    "Открыт:":                              "Open:",
    "Открыть":                              "Open",
    "Открыть workflow":                     "Open workflow",
    "Отладка":                              "Debugging",
    "Отладка:":                             "Debugging:",
    "Отложенная загрузка конфига сниппета (после создания всех виджетов).":
            "Lazy loading of snippet config (after creating all widgets).",
    "Отложенное обновление после открепления.":
            "Delayed update after unpin.",
    "Отметить что проект сохранён.":        "Mark that the project is saved.",
    "Отображение потокового вывода от агента":
            "Displaying streaming output from an agent",
    "Отправить браузер в трей + полностью скрыть окно":
            "Send browser to tray + completely hide the window",
    "Отправка HTTP-запросов. Переменные: {name}":
            "Dispatch HTTP-requests. Variables: {name}",
    "Отпускание кнопки - сброс режимов.":   "Release the button - reset modes.",
    "Отпускание — присоединение к новому сниппету или отмена.":
            "Letting go — joining a new snippet or canceling.",
    "Отслеживаем фокус для сохранения состояния перед редактированием (для undo)":
            "Tracking focus to save state before editing (For undo)",
    "Отслеживает изменения в виджетах сниппета для undo/redo":
            "Tracks changes in snippet widgets for undo/redo",
    "Отсортировано":                        "Sorted",
    "Очистить":                             "Clear",
    "Очистить все переменные":              "Clear all variables",
    "Очистить всю историю":                 "Clear all history",
    "Очистить всю сетку (legacy, оставлен для совместимости).":
            "Clear entire grid (legacy, left for compatibility).",
    "Очистить всё отслеживание":            "Clear all tracking",
    "Очистить куки":                        "Clear cookies",
    "Очистить переменную":                  "Clear variable",
    "Очистить поле":                        "Clear field",
    "Ошибка":                               "Error",
    "Ошибка загрузки":                      "Loading error",
    "Ошибка импорта":                       "Import error",
    "Ошибка при пустом результате":         "Error with empty result",
    "Ошибка сохранения":                    "Save error",
    "Ошибка экспорта":                      "Export error",
    "Ошибка:":                              "Error:",
    "Ошибок:":                              "Errors:",
    "Ошибочный узел:":                      "Invalid node:",
    "ПКМ меню: стандартные действия + вставка переменных проекта.":
            "RMB menu: standard actions + inserting project variables.",
    "Панель переменных проекта и заметок.": "Project Variables and Notes Panel.",
    "Панель переменных проекта как в ZennoPoster.":
            "Project variable panel as in ZennoPoster.",
    "Панель свойств ноды.":                 "Node properties panel.",
    "Панель трея — горизонтальная полоса с миниатюрами всех браузеров проекта.":
            "Tray panel — horizontal bar with thumbnails of all project browsers.",
    "    Кнопка «→ Трей» на каждом инстансе отправляет его сюда.":
            "    Button «→ Trey» on each instance sends it here.",
    "Панель управления запущенными браузерными инстансами.":
            "Control panel for running browser instances.",
    "    Добавляется в боковой таб Agent Constructor.":
            "    Added to side tab Agent Constructor.",
    "Папка выполнения (пусто = папка проекта)":
            "Execution folder (empty = project folder)",
    "Папка профиля:":                       "Profile folder:",
    "Параллельно":                          "Parallel",
    "Параметры запуска:":                   "Launch options:",
    "Пароль":                               "Password",
    "Пароль:":                              "Password:",
    "Парсинг":                              "Parsing",
    "Парсинг, запросы, изменение JSON/XML. Переменные: {var_name}":
            "Parsing, requests, change JSON/XML. Variables: {var_name}",
    "Патчинг":                              "Patching",
    "Патчинг кода":                         "Code patching",
    "Пауза (сек)":                          "Pause (sec)",
    "Пауза для подтверждения пользователем (human in loop).":
            "Pause for user confirmation (human in loop).",
    "Пауза между действиями (сек):":        "Pause between actions (sec):",
    "Пауза между итерациями (сек):":        "Pause between iterations (sec):",
    "Пауза после (с):":                     "Pause after (With):",
    "Пауза после (сек):":                   "Pause after (sec):",
    "Первое":                               "First",
    "Первую":                               "First",
    "Перебор инлайн-списка":                "Iterating over an inline list",
    "Перебор списка (переменная)":          "Iterating over a list (variable)",
    "Перебор строк файла":                  "Looping through file lines",
    "Перед выполнением каждого агента создаёт копию рабочей папки в папке .backups/":
            "Before executing each agent, it creates a copy of the working folder in the folder .backups/",
    "Перед текстом всегда есть:":           "There is always before the text:",
    "Перезагрузить":                        "Reboot",
    "Перезапустить с начала":               "Restart from the beginning",
    "Перейти к начальному узлу":            "Go to start node",
    "Перейти к начальному узлу.":           "Go to start node.",
    "Перейти к последнему узлу":            "Go to last node",
    "Перейти к последнему узлу (без исходящих связей).":
            "Go to last node (no outgoing connections).",
    "Перейти по URL":                       "Go to URL",
    "Переключились на другой проект — переключаем активные ресурсы.":
            "Switched to another project — switch active resources.",
    "Переключить видимость полей IF: визуальный конструктор vs Python выражение.":
            "Toggle field visibility IF: visual designer vs Python expression.",
    "Переключить видимость: редактор кода vs путь к файлу.":
            "Toggle visibility: code editor vs file path.",
    "Переключить менеджер при смене активного проекта.":
            "Switch manager when changing active project.",
    "Переключить правую панель и левые табы под выбранный тип ноды.":
            "Switch the right panel and left tabs for the selected node type.",
    "Переменная ID инстанса:":              "Variable ID instance:",
    "Переменная для EXIT CODE:":            "Variable for EXIT CODE:",
    "Переменная для STD ERR:":              "Variable for STD ERR:",
    "Переменная для STD OUT:":              "Variable for STD OUT:",
    "Переменная для stderr:":               "Variable for stderr:",
    "Переменная для заголовков:":           "Variable for headers:",
    "Переменная для результата:":           "Result variable:",
    "Переменная для сохранения ID":         "Variable to save ID",
    "Переменная значения:":                 "Value variable:",
    "Переменная или значение. Пример: {counter} или 5":
            "Variable or value. Example: {counter} or 5",
    "Переменная ответа:":                   "Response variable:",
    "Переменная результата:":               "Outcome variable:",
    "Переменная с ID браузерного инстанса (из Browser Launch)":
            "Variable with ID browser instance (from Browser Launch)",
    "Переменная статуса:":                  "Status Variable:",
    "Переменная счётчика:":                 "Counter variable:",
    "Переменная-источник:":                 "Source variable:",
    "Переменная:":                          "Variable:",
    "Переменные будут доступны как {имя}":  "Variables will be available as {Name}",
    "Переменные для восстановления:":       "Variables to restore:",
    "Переменные окружения:":                "Environment Variables:",
    "Переменные: {var_name}":               "Variables: {var_name}",
    "Переместить":                          "Move",
    "Переместить выбранную строку переменной вверх.":
            "Move selected variable row up.",
    "Переместить выбранную строку переменной вниз.":
            "Move selected variable row down.",
    "Переместить строку вверх":             "Move line up",
    "Переместить строку вниз":              "Move line down",
    "Перемешано. Размер:":                  "Shuffled. Size:",
    "Перемешать":                           "Mix",
    "Перемешать элементы":                  "Shuffle elements",
    "Перемещение":                          "Moving",
    "Перемещение блока (":                  "Moving a block (",
    "Перемещено":                           "Moved",
    "Переподключение":                      "Reconnection",
    "Перетаскивание блока целиком.":        "Dragging an entire block.",
    "Перетаскивание конца стрелки к новому таргету.":
            "Dragging the end of the arrow to a new target.",
    "Перетаскивание по миникарте — плавная навигация основного вида.":
            "Drag and drop on the minimap — Smooth main view navigation.",
    "Песочница (ограниченный импорт)":      "Sandbox (limited imports)",
    "Пиксели от верхнего края (пример: 300)":
            "Pixels from top edge (example: 300)",
    "Пиксели от левого края (пример: 500)": "Pixels from left edge (example: 500)",
    "Пиксельная верификация после действий":
            "Pixel verification after actions",
    "По номеру":                            "By number",
    "По строкам: имя = значение":           "By line: Name = meaning",
    "По убыванию":                          "Descending",
    "По умолч.":                            "By default.",
    "По умолчанию":                         "Default",
    "По умолчанию (из глобальных)":         "Default (from global)",
    "Повторяет выполнение дочерних узлов. Поддерживает: счётчик, while, перебор списка/файла":
            "Repeats execution of child nodes. Supports: counter, while, iterating over the list/file",
    "Поддерживаются переменные {name}":     "Variables supported {name}",
    "Подключить обработчик изменения размера контейнера для синхронизации с окном браузера.":
            "Connect a container resize handler to synchronize with the browser window.",
    "Подключить отслеживание к виджету":    "Connect tracking to widget",
    "Подогнать вид миникарты под все элементы проекта.":
            "Adjust the minimap view to fit all project elements.",
    "Подставить ВСЕ переменные контекста в текст. Работает с любым типом значений.":
            "Substitute ALL context variables into text. Works with any value type.",
    "Подстрока":                            "Substring",
    "Подстрока до:":                        "Substring to:",
    "Подстрока от:":                        "Substring from:",
    "Подсчитать количество нодов в цепочке.":
            "Count the number of nodes in the chain.",
    "Подтвердите выполнение:":              "Confirm execution:",
    "Позиция i-го case-порта Switch в координатах сцены.":
            "Position i-th case-port Switch in scene coordinates.",
    "Позиция вставки:":                     "Insertion position:",
    "Позиция порта ошибки в локальных координатах (нижний правый).":
            "Position of the error port in local coordinates (bottom right).",
    "Позиция порта ошибки в сцене.":        "Position of the error port in the scene.",
    "Поиск и исправление ошибок по логам и трейсбекам":
            "Finding and correcting errors using logs and tracebacks",
    "Показать контекстное меню со списком переменных проекта для вставки.":
            "Show a context menu with a list of project variables to insert.",
    "Показать меню выбора скилла для добавления к текущей ноде":
            "Show a menu for selecting a skill to add to the current node",
    "Показать окно Chrome из скрытого / свёрнутого состояния.":
            "Show window Chrome from hidden / collapsed state.",
    "Показывать всплывающее окно":          "Show popup",
    "Полная коллекция DOM для AI-агента (аналог ZP AiDomMapper + AiDomPreprocessor).":
            "Complete collection DOM For AI-agent (analogue ZP AiDomMapper + AiDomPreprocessor).",
    "        Собирает ВСЕ элементы страницы включая Shadow DOM, затем фильтрует для AI.":
            "        Collects ALL page elements including Shadow DOM, then filters for AI.",
    "        Возвращает dict: {meta, elements, interactive, dom_text}.":
            "        Returns dict: {meta, elements, interactive, dom_text}.",
    "Полная перестройка стрелок во всей цепочке от top_parent вниз.":
            "Complete restructuring of arrows in the entire chain from top_parent down.",
    "Полная страница":                      "Full page",
    "Полноценный движок выполнения workflow с автопатчингом и самоулучшением":
            "Full execution engine workflow with auto-patching and self-improvement",
    "Полноценный движок выполнения workflow.":
            "Full execution engine workflow.",
    "Полный URL с http(s)://. Переменные: {name}":
            "Full URL With http(s)://. Variables: {name}",
    "Полный дамп переменных для отладки":   "Complete variable dump for debugging",
    "Полный цикл: анализ → генерация → тестирование → патчинг":
            "Full cycle: analysis → generation → testing → patching",
    "Получено [":                           "Received [",
    "Получить HTML":                        "Get HTML",
    "Получить URL":                         "Get URL",
    "Получить атрибут":                     "Get attribute",
    "Получить все переменные в формате {name: {...}}":
            "Get all variables in format {name: {...}}",
    "Получить все элементы цепочки.":       "Get all elements of a chain.",
    "Получить выбранный инстанс браузера.": "Get the selected browser instance.",
    "Получить заголовок":                   "Get title",
    "Получить значение по ключу":           "Get value by key",
    "Получить инстанс по ID если он принадлежит этому проекту.":
            "Get an instance by ID if it belongs to this project.",
    "Получить кол-во столбцов":             "Get number of columns",
    "Получить кол-во строк":                "Get number of rows",
    "Получить количество строк":            "Get number of rows",
    "Получить куки":                        "Get cookies",
    "Получить переменные для подстановки в контексте выполнения.":
            "Get variables for substitution in execution context.",
    "        Берём ТЕКУЩИЕ значения из таблицы UI (колонка Значение), а не из модели.":
            "        We take CURRENT values \u200b\u200bfrom the table UI (Column Meaning), not from the model.",
    "Получить позицию исходного порта для временной отрисовки.":
            "Get source port position for temporary rendering.",
    "Получить скриншот текущей страницы как base64 PNG.":
            "Get a screenshot of the current page like base64 PNG.",
    "Получить список директорий":           "Get a list of directories",
    "Получить список интерактивных видимых элементов с координатами.":
            "Get a list of interactive visible elements with coordinates.",
    "        Только элементы которые можно кликнуть, ввести текст, выбрать.":
            "        Only elements that can be clicked, enter text, choose.",
    "Получить список моделей из главного окна":
            "Get a list of models from the main window",
    "Получить список файлов":               "Get a list of files",
    "Получить строку":                      "Get string",
    "Получить текст":                       "Get text",
    "Получить текущую конфигурацию сниппета из виджетов":
            "Get the current snippet configuration from widgets",
    "Получить элемент по координатам (для верификации клика).":
            "Get element by coordinates (to verify the click).",
    "Поменять местами две строки в таблице переменных.":
            "Swap two rows in the variable table.",
    "Попытаться встроить браузер с повторными попытками.":
            "Try to embed browser with retries.",
    "Порог diff (%):":                      "Threshold diff (%):",
    "После Bad End:":                       "After Bad End:",
    "Последнюю":                            "The last one",
    "Последовательно":                      "Consistently",
    "Пошаговый отладчик workflow.":         "Step-by-step debugger workflow.",
    "Правая сторона, около верхнего края — когда источник справа.":
            "Right side, near the top edge — when the source is on the right.",
    "Правый клик по координатам":           "Right click on coordinates",
    "Правый клик по элементу":              "Right click on element",
    "Правый операнд:":                      "Right operand:",
    "Превращает любой путь в безопасный относительный.":
            "Turns any path into a safe relative one.",
    "Предобработка вывода Planner'а и выполнение Browser Agent для каждого пункта.":
            "Output preprocessing Planner'and execution Browser Agent for each item.",
    "Предпросмотр: загрузить переменные из прикреплённого файла в таблицу":
            "Preview: load variables from attached file into table",
    "Прервать при ошибке дочернего узла":   "Abort on child node error",
    "При изменении размера окна перецентровываем вид на проект.":
            "When changing the window size, we re-center the view of the project.",
    "Приведение типа (cast)":               "Type casting (cast)",
    "Привязать к менеджеру для получения скриншотов.":
            "Link to manager to receive screenshots.",
    "Прикрепить дочернюю ноду к родительской (ZennoPoster-стиль)":
            "Attach a child node to the parent node (ZennoPoster-style)",
    "Прикрепить дочернюю ноду к родительской (с автоматической стрелкой)":
            "Attach a child node to the parent node (with automatic arrow)",
    "Прикрепить файл таблицы с переменными":
            "Attach a table file with variables",
    "Применить детальные настройки для tools":
            "Apply detailed settings for tools",
    "Применить конфиг к ноде (для undo/redo).":
            "Apply config to node (For undo/redo).",
    "Применить стиль к кнопке добавления заметки":
            "Apply a style to the add note button",
    "Применить текущие значения из виджетов к объекту ноды.":
            "Apply current values \u200b\u200bfrom widgets to a node object.",
    "Применить текущие цвета темы к палитре":
            "Apply current theme colors to palette",
    "Применить текущие цвета темы ко всем виджетам панели":
            "Apply current theme colors to all panel widgets",
    "Пример входа:":                        "Login example:",
    "Пример выхода:":                       "Example output:",
    "Пример: *.png|*.jpg":                  "Example: *.png|*.jpg",
    "Пример: .html":                        "Example: .html",
    "Пример: </title>":                     "Example: </title>",
    "Пример: <title>":                      "Example: <title>",
    "Пример: ctx.get(\"count\", 0) > 5 and ctx.get(\"status\") == \"ok\"":
            "Example: ctx.get(\"count\", 0) > 5 and ctx.get(\"status\") == \"ok\"",
    "Пример: ctx.get(\"done\") == True  или  iteration > 5":
            "Example: ctx.get(\"done\") == True  or  iteration > 5",
    "Пример: data.items[0].name":           "Example: data.items[0].name",
    "Пример: http":                         "Example: http",
    "Принудительная синхронизация текущих данных из UI в ноду перед переключением.":
            "Force synchronization of current data from UI to the node before switching.",
    "Принудительно сохранить все виджеты сниппета в node.snippet_config":
            "Force save all snippet widgets to node.snippet_config",
    "Проверить существование":              "Check existence",
    "Проверяет условие. True → зелёная ветка (ON_SUCCESS), False → красная (ON_FAILURE). Переменные: {var_name}":
            "Checks a condition. True → green branch (ON_SUCCESS), False → red (ON_FAILURE). Variables: {var_name}",
    "Проверяет, создаст ли новая связь цикл в графе":
            "Checks, will the new connection create a cycle in the graph",
    "Проверять SSL-сертификат":             "Check SSL-certificate",
    "Продолжить выполнение до конца (или до следующего breakpoint).":
            "Continue execution to completion (or until next time breakpoint).",
    "Продолжить со следующего":             "Continue with next",
    "Проект":                               "Project",
    "Проект изменён. Сохранить перед закрытием?":
            "Project changed. Save before closing?",
    "Проект содержит несохранённые изменения.":
            "The project contains unsaved changes.",
    "Проектирование архитектуры и структуры проекта":
            "Design of architecture and project structure",
    "Прокрутить страницу вниз перед сбором элементов (для lazy-load контента)":
            "Scroll down the page before collecting items (For lazy-load content)",
    "Прокси:":                              "Proxy:",
    "Промпт верификации:":                  "Verification prompt:",
    "Протокол:":                            "Protocol:",
    "Профиль":                              "Profile",
    "Профиль браузера — набор настроек для конкретного сеанса.":
            "Browser profile — a set of settings for a specific session.",
    "Профиль:":                             "Profile:",
    "Прочитать ячейку":                     "Read cell",
    "Прямая запись per-node настроек в JSON-файл.":
            "Direct recording per-node settings in JSON-file.",
    "        КРИТИЧНО: читаем из scene._node_items (оригиналы), ":
            "        CRITICAL: read from scene._node_items (originals), ",
    "        а НЕ из workflow.nodes (Pydantic возвращает копии!).":
            "        and NOT from workflow.nodes (Pydantic returns copies!).",
    "Прямое чтение per-node настроек из JSON-файла.":
            "Direct reading per-node settings from JSON-file.",
    "        КРИТИЧНО: применяем на объекты СЦЕНЫ (оригиналы),":
            "        CRITICAL: apply to SCENE objects (originals),",
    "        а НЕ на workflow.nodes (Pydantic копии!).":
            "        and NOT on workflow.nodes (Pydantic copies!).",
    "Пусто":                                "Empty",
    "Пусто = дефолтный":                    "Empty = default",
    "Пусто = закрыть все. Или {browser_instance_id}":
            "Empty = close all. Or {browser_instance_id}",
    "Пусто = первый доступный. Или {browser_instance_id}":
            "Empty = first available. Or {browser_instance_id}",
    "Путь для режима \"Как файл\"":         "Path for mode \"As file\"",
    "Путь к CSV/TSV (переменные загрузятся при запуске)...":
            "Path to CSV/TSV (variables will be loaded on startup)...",
    "Путь к директории:":                   "Directory path:",
    "Путь к папке профиля (переопределяет профиль)...":
            "Path to profile folder (overrides profile)...",
    "Путь к папке профиля Chromium (пусто = временный профиль)":
            "Path to profile folder Chromium (empty = temporary profile)",
    "Путь к папке профиля...":              "Path to profile folder...",
    "Путь к папке... ({project_dir} = рабочая папка)":
            "Folder path... ({project_dir} = working folder)",
    "Путь к файлу (по номеру/случайный)":   "File path (by number/random)",
    "Путь к файлу (пусто = screenshot.png)":
            "File path (empty = screenshot.png)",
    "Путь к файлу... ({project_dir} = рабочая папка)":
            "File path... ({project_dir} = working folder)",
    "Путь к файлу:":                        "File path:",
    "Работа с папками. Переменные: {var_name}":
            "Working with folders. Variables: {var_name}",
    "Работа с переменными проекта и контекста. Переменные: {var_name}":
            "Working with Project and Context Variables. Variables: {var_name}",
    "Работа с таблицами (CSV/TSV): чтение, запись ячеек, строк, столбцов, сортировка, дедупликация. Данные в контексте.":
            "Working with tables (CSV/TSV): reading, cell recording, lines, columns, sorting, deduplication. Data in Context.",
    "Работа с файлами. Переменные: {var_name}":
            "Working with files. Variables: {var_name}",
    "Работа со списками: добавление, получение, удаление, сортировка, перемешивание, дедупликация. Данные хранятся в контексте.":
            "Working with Lists: addition, receiving, deletion, sorting, mixing, deduplication. Data is stored in context.",
    "Рабочая папка:":                       "Working folder:",
    "Равно (==)":                           "Equals (==)",
    "Разделитель (concat):":                "Separator (concat):",
    "Разделитель (для объединения):":       "Separator (for unification):",
    "Разделитель:":                         "Separator:",
    "Размер:":                              "Size:",
    "Разрешение:":                          "Permission:",
    "Разрешенные команды":                  "Allowed commands",
    "Разрешенные модули":                   "Allowed modules",
    "Разрешенные расширения":               "Allowed extensions",
    "Разрешить самомодификацию":            "Allow self-modification",
    "Ревью кода":                           "Code review",
    "Регулярное выражение или текст для поиска":
            "Regular expression or text to search",
    "Редактирование:":                      "Editing:",
    "Редактировать выбранный скилл в списке текущей ноды":
            "Edit the selected skill in the list of the current node",
    "Редактировать комментарий":            "Edit comment",
    "Редактировать комментарий ноды":       "Edit node comment",
    "Редактировать скилл":                  "Edit skill",
    "Режим выполнения:":                    "Execution mode:",
    "Режим полной автоматизации проекта":   "Full project automation mode",
    "Режим предобработки: разбиваем план на задачи и выполняем по очереди.":
            "Preprocessing mode: We break the plan down into tasks and execute them one by one.",
    "Режим сравнения:":                     "Comparison mode:",
    "Режим:":                               "Mode:",
    "Результат (переменная) →:":            "Result (variable) →:",
    "Результат →:":                         "Result →:",
    "Результат:":                           "Result:",
    "Рисование заметки — бумажный стиль, без портов.":
            "Drawing a note — paper style, no ports.",
    "Рисуем рамку текущей видимой области основного вида.":
            "Draw a frame for the current visible area of \u200b\u200bthe main view.",
    "Рисует единую обёртку для всего блока прикреплённых нодов.":
            "Draws a single wrapper for the entire block of attached nodes.",
    "Самое короткое":                       "The shortest",
    "Самоулучшение промптов":               "Self-improvement of prompts",
    "Сброс вкладок Тулзы/Выполнение/Авто к дефолтам при смене проекта.":
            "Resetting Toolsa tabs/Execution/Automatic defaults when changing projects.",
    "Сброс масштаба к 100%.":               "Resetting the scale to 100%.",
    "Сбросить все значения переменных к колонке 'По умолч.'":
            "Reset all variable values \u200b\u200bto a column 'By default.'",
    "        Вызывается при открытии проекта и перед каждым новым запуском.":
            "        Called when opening a project and before each new launch.",
    "Сбросить к цвету по умолчанию":        "Reset to default color",
    "Сбросить кастомный цвет ноды.":        "Reset custom node color.",
    "Сбросить масштаб":                     "Reset scale",
    "Свои символы:":                        "Your symbols:",
    "Свойство массива:":                    "Array property:",
    "Связь":                                "Connection",
    "Связь:":                               "Connection:",
    "Секунды:":                             "Seconds:",
    "Секция палитры: Браузер.":             "Palette section: Browser.",
    "Селектор / URL / JS-код...":           "Selector / URL / JS-code...",
    "Селектор / URL / JS:":                 "Selector / URL / JS:",
    "Сериализовать данные таблицы переменных":
            "Serialize variable table data",
    "Символ между частями. Пустой = без разделителя":
            "Symbol between parts. Empty = without separator",
    "Синий":                                "Blue",
    "Синхронизировать код из редактора в node.snippet_config['_code'].":
            "Sync code from editor to node.snippet_config['_code'].",
    "Синхронизировать размер окна браузера с контейнером.":
            "Synchronize browser window size with container.",
    "Синхронизировать с переменными проекта":
            "Synchronize with project variables",
    "Система Undo/Redo и истории изменений.":
            "System Undo/Redo and history of changes.",
    "Системный промпт...":                  "System prompt...",
    "Системный трей для управления несколькими браузерными инстансами.":
            "System tray for managing multiple browser instances.",
    "    Синглтон — создаётся при первом запуске браузера.":
            "    Singleton — created when the browser is launched for the first time.",
    "Сканировать Shadow DOM":               "Scan Shadow DOM",
    "Сканировать файлы на диске в рабочей папке.":
            "Scan files on disk in working folder.",
    "Скиллы:":                              "Skills:",
    "Скопировано":                          "Copied",
    "Скопировать значение переменной из таблицы.":
            "Copy variable value from table.",
    "Скопировать содержимое root в root/.backups/label_YYYYMMDD_HHMMSS/.":
            "Copy content root V root/.backups/label_YYYYMMDD_HHMMSS/.",
    "Скопировать ссылку на переменную вида {имя} в буфер обмена":
            "Copy a reference to a view variable {Name} to clipboard",
    "Скриншот":                             "Screenshot",
    "Скриншот:":                            "Screenshot:",
    "Скриншоты страницы или элемента":      "Screenshots of a page or element",
    "Скрипт упал (код":                     "The script crashed (code",
    "Скролл к элементу":                    "Scroll to element",
    "Скролл страницы":                      "Page scroll",
    "Скроллить перед сканированием DOM":    "Scroll before scanning DOM",
    "Скрыть окно Chrome (убрать в трей — скрыть из taskbar и экрана).":
            "Hide window Chrome (put in tray — hide from taskbar and screen).",
    "Скрыть/показать поля сниппета в зависимости от текущего значения primary combo.":
            "Hide/show snippet fields depending on the current value primary combo.",
    "Слоги + цифры":                        "Syllables + numbers",
    "Случайная задержка ±50%":              "Random delay ±50%",
    "Случайное":                            "Random",
    "Случайную":                            "Random",
    "Случайный":                            "Random",
    "Сначала выберите рабочую папку.":      "First select your working folder.",
    "Собирает контекст из предыдущих узлов для передачи текущему":
            "Collects context from previous nodes to transfer to the current one",
    "Собрать regex из полей помощника (4 поля как в ZennoPoster).":
            "Collect regex from assistant fields (4 fields as in ZennoPoster).",
    "Содержит (contains)":                  "Contains (contains)",
    "Содержит текст":                       "Contains text",
    "Создавать бэкап":                      "Create a backup",
    "Создание":                             "Creation",
    "Создание документации, README, комментариев":
            "Creating documentation, README, comments",
    "Создание и запуск тестов, анализ результатов":
            "Creating and running tests, analysis of results",
    "Создание и модификация":               "Creation and modification",
    "Создание изображений через AI":        "Creating images via AI",
    "Создание нового кода по описанию задачи":
            "Creating new code based on the task description",
    "Создание связи с валидацией логики через UI.":
            "Creating a link to logic validation via UI.",
    "        Ручные связи (output/error/switch) НЕ перестраивают автоматические цепочки.":
            "        Manual connections (output/error/switch) DO NOT rebuild automatic chains.",
    "Создание, чтение, организация файлов проекта":
            "Creation, reading, organizing project files",
    "Создать":                              "Create",
    "Создать агента с предустановленным скиллом":
            "Create an agent with a preset skill",
    "Создать агента-планировщика для разбора задачи":
            "Create a scheduler agent to parse the task",
    "Создать виджеты настроек для конкретного типа сниппета.":
            "Create settings widgets for a specific snippet type.",
    "Создать если не существует":           "Create if does not exist",
    "Создать или удалить шапку блока в зависимости от статуса.":
            "Create or delete a block header depending on the status.",
    "Создать новую подпапку с датой-временем в текущей рабочей папке":
            "Create a new subfolder with date-time in the current working folder",
    "Создать новый скилл":                  "Create a new skill",
    "Создать папку вида base_dir/run_YYYYMMDD_HHMMSS/ и установить её как рабочую.":
            "Create view folder base_dir/run_YYYYMMDD_HHMMSS/ and install it as working.",
    "Создать папку если не существует":     "Create folder if does not exist",
    "Создать папку, если не существует":    "Create a folder, if doesn't exist",
    "Создать переменную если не существует":
            "Create a variable if it doesn't exist",
    "Создать ячейку в сетке и встроить браузер туда.":
            "Create a cell in the grid and embed the browser there.",
    "Создаёт копию рабочей папки перед выполнением именно этого агента":
            "Creates a copy of the working folder before executing this particular agent",
    "Сокращённый DOM + описание страницы + скриншот (если нужно).":
            "Abbreviated DOM + page description + screenshot (if necessary).",
    "Сообщение из User Prompt. Отображается в логе и/или всплывающим окном. Переменные: {name}":
            "Message from User Prompt. Displayed in the log and/or pop-up window. Variables: {name}",
    "Сообщение при успехе:":                "Message on success:",
    "Сообщение:":                           "Message:",
    "Сортировать":                          "Sort",
    "Сортировать как числа, а не как строки":
            "Sort as numbers, not like strings",
    "Сортировка по столбцу":                "Sort by column",
    "Сохранено":                            "Saved",
    "Сохранить HTTP-статус":                "Save HTTP-status",
    "Сохранить snippet_config в текущую ноду.":
            "Save snippet_config to the current node.",
    "Сохранить snippet_config для ВСЕХ нод-сниппетов перед сохранением файла.":
            "Save snippet_config for ALL snippet nodes before saving the file.",
    "Сохранить stderr в переменную":        "Save stderr into a variable",
    "Сохранить stdout в переменную":        "Save stdout into a variable",
    "Сохранить workflow":                   "Save workflow",
    "Сохранить в файл":                     "Save to file",
    "Сохранить в файл:":                    "Save to file:",
    "Сохранить лог ошибок в файл":          "Save error log to file",
    "Сохранить отчёт в файл":               "Save report to file",
    "Сохранить перед закрытием?":           "Save before closing?",
    "Сохранить переменные в CSV файл":      "Save variables to CSV file",
    "Сохранить путь рабочей папки в проект workflow":
            "Save the working folder path to the project workflow",
    "Сохранить рабочую папку в workflow metadata (без полного Save As).":
            "Save working folder to workflow metadata (without complete Save As).",
    "Сохранить результат в переменную":     "Save the result to a variable",
    "Сохранить текст в переменную":         "Save text to variable",
    "Сохранить текущие значения виджетов в node.snippet_config перед переключением.":
            "Save current widget values \u200b\u200bto node.snippet_config before switching.",
    "Сохраняем ВСЕ глобальные настройки в workflow metadata":
            "We save ALL global settings in workflow metadata",
    "Сохраняет изменения и создает undo entry.":
            "Saves changes and creates undo entry.",
    "Сохраняет изменения свойств в историю":
            "Saves property changes to history",
    "Сохранён:":                            "Saved:",
    "Список для результатов:":              "List for results:",
    "Список значений cases из snippet_config Switch-ноды.":
            "List of values cases from snippet_config Switch-nodes.",
    "Список назначения:":                   "Destination List:",
    "Список очищен":                        "List cleared",
    "Список пуст":                          "The list is empty",
    "Список результатов:":                  "List of results:",
    "Список:":                              "List:",
    "Сравнивает значение переменной с условиями. Поддерживает ==, !=, >, <, >=, <=, contains, regex. По Default если ничего не совпало.":
            "Compares the value of a variable with conditions. Supports ==, !=, >, <, >=, <=, contains, regex. By Default if nothing matches.",
    "Сравнивать как:":                      "Compare how:",
    "Сравнивать скриншоты до/после для проверки результата":
            "Compare screenshots before/after to check the result",
    "Сравнить два значения по оператору.":  "Compare two values \u200b\u200busing operator.",
    "Сравнить два скриншота (base64 PNG). ":
            "Compare two screenshots (base64 PNG). ",
    "        Возвращает (изменилось, доля_изменённых_пикселей).":
            "        Returns (has changed, share_changed_pixels).",
    "        Работает без PIL — через простое побайтное сравнение.":
            "        Works without PIL — via simple byte-by-byte comparison.",
    "Столбец [":                            "Column [",
    "Столбец дедупликации:":                "Deduplication Column:",
    "Столбец сортировки:":                  "Sort Column:",
    "Столбец:":                             "Column:",
    "Столбцов:":                            "Stolbtsov:",
    "Строк:":                               "Rows:",
    "Строка":                               "Line",
    "Строка (string)":                      "Line (string)",
    "Строка [":                             "Line [",
    "Строки":                               "Strings",
    "Строчные (a-z)":                       "Lowercase (a-z)",
    "Существует":                           "Exists",
    "Сформируй список из не более":         "Create a list of no more than",
    "Сцена workflow с логикой нод и связей.":
            "Scene workflow with the logic of nodes and connections.",
    "Счётчик (N итераций)":                 "Counter (N iterations)",
    "Таблица пуста":                        "Table is empty",
    "Таблица:":                             "Table:",
    "Табуляция (Tab)":                      "Tabulation (Tab)",
    "Таймаут (":                            "Time-out (",
    "Таймаут (с):":                         "Time-out (With):",
    "Таймаут (сек)":                        "Time-out (sec)",
    "Таймаут (сек):":                       "Time-out (sec):",
    "Таймаут AI (сек):":                    "Time-out AI (sec):",
    "Таймаут загрузки":                     "Load timeout",
    "Таймаут:":                             "Time-out:",
    "Такая связь уже существует":           "This connection already exists",
    "Текст (ввести ниже)":                  "Text (enter below)",
    "Текст для ввода, атрибут, параметр...":
            "Text to enter, attribute, parameter...",
    "Текст для записи в лог. Переменные: {var_name}":
            "Log text. Variables: {var_name}",
    "Текст для записи:":                    "Text to write:",
    "Текст для обработки:":                 "Text to process:",
    "Текст для поиска:":                    "Search text:",
    "Текст заметки...":                     "Note text...",
    "Текст заметки...":                     "Note text...",
    "Можно писать что угодно:":             "You can write anything:",
    "- Описание архитектуры":               "- Description of the architecture",
    "- Ссылки":                             "- Links",
    "- Идеи":                               "- Ideas",
    "Текст комментария:":                   "Comment text:",
    "Текст который ВСЕГДА идёт ДО искомого. НЕ включается в результат (lookbehind)":
            "Text that ALWAYS goes BEFORE the searched one. NOT included in the result (lookbehind)",
    "Текст который ВСЕГДА идёт ПОСЛЕ искомого. НЕ включается в результат (lookahead)":
            "Text that ALWAYS comes AFTER the searched text. NOT included in the result (lookahead)",
    "Текст фильтра:":                       "Filter text:",
    "Текст:":                               "Text:",
    "Текущий элемент (для foreach)":        "Current item (For foreach)",
    "Тело запроса:":                        "Request body:",
    "Температура (x10):":                   "Temperature (x10):",
    "Терминал":                             "Terminal",
    "Тестирование":                         "Testing",
    "Тип":                                  "Type",
    "Тип (для cast):":                      "Type (For cast):",
    "Тип данных:":                          "Data type:",
    "Тип селектора:":                       "Selector type:",
    "Тип цикла:":                           "Cycle type:",
    "Тип:":                                 "Type:",
    "Только для режима \"Перезапустить\"":  "Only for mode \"Restart\"",
    "Только если галочка выше":             "Only if the checkmark is above",
    "Только заголовки":                     "Headers only",
    "Только с галочкой выше":               "Only with a checkmark above",
    "Только содержимое":                    "Contents only",
    "Точечные исправления в существующем коде через SEARCH/REPLACE":
            "Spot fixes to existing code via SEARCH/REPLACE",
    "Точка = любой символ":                 "Dot = any character",
    "Точка с запятой (;)":                  "Semicolon (;)",
    "Точность (м):":                        "Accuracy (m):",
    "Точный или частичный текст элемента":  "Exact or partial element text",
    "Транслитерация":                       "Transliteration",
    "Тулзы":                                "Tools",
    "Ты анализируешь изображения. Описывай что видишь на скриншоте: элементы UI, текст, ошибки, состояние программы.":
            "You analyze images. Describe what you see in the screenshot: elements UI, text, errors, program status.",
    "Ты патчишь код. Используй формат [SEARCH_BLOCK]/[REPLACE_BLOCK]. SEARCH должен ТОЧНО совпадать с существующим кодом.":
            "You patch the code. Use the format [SEARCH_BLOCK]/[REPLACE_BLOCK]. SEARCH must match EXACTLY the existing code.",
    "Ты управляешь файлами проекта. Создавай структуру директорий, перемещай файлы, организуй код по модулям.":
            "You manage the project files. Create a directory structure, move files, organize your code into modules.",
    "Ты — QA инженер. Создавай тесты для всех edge cases. Используй pytest. Проверяй граничные условия.":
            "You — QA engineer. Create tests for everyone edge cases. Use pytest. Check boundary conditions.",
    "Ты — code reviewer. Найди баги, уязвимости, антипаттерны. Предложи конкретные улучшения с примерами кода.":
            "You — code reviewer. Find bugs, vulnerabilities, antipatterns. Suggest specific improvements with code examples.",
    "Ты — аналитик данных. Анализируй данные, находи паттерны, визуализируй результаты. Используй pandas, numpy.":
            "You — data analyst. Analyze data, find patterns, visualize the results. Use pandas, numpy.",
    "Ты — архитектор ПО. Проектируй модульные, масштабируемые системы. Документируй решения. Рисуй схемы в Mermaid.":
            "You — software architect. Design modular, scalable systems. Document your decisions. Draw diagrams in Mermaid.",
    "Ты — браузерный агент. Получаешь задачу и список интерактивных элементов с координатами.":
            "You — browser agent. You receive a task and a list of interactive elements with coordinates.",
    "Формат элементов: [id] tag:type[role] (x,y) WxH | текст/placeholder":
            "Element Format: [id] tag:type[role] (x,y) WxH | text/placeholder",
    "Отвечай ТОЛЬКО JSON-списком действий:":
            "Answer ONLY JSON-list of actions:",
    "[{\"action\":\"click\",\"target\":\"#id или координаты\"},{\"action\":\"type_text\",\"target\":\"#id\",\"value\":\"текст\"},...]":
            "[{\"action\":\"click\",\"target\":\"#id or coordinates\"},{\"action\":\"type_text\",\"target\":\"#id\",\"value\":\"text\"},...]",
    "Доступные action:":                    "Available action:",
    "- click: клик по CSS-селектору или координатам (x,y)":
            "- click: click on CSS-selector or coordinates (x,y)",
    "- click_xy: клик по точным координатам":
            "- click_xy: click on exact coordinates",
    "- type_text: ввод текста в поле":      "- type_text: entering text into a field",
    "- get_text: получить текст элемента":  "- get_text: get element text",
    "- navigate: переход по URL":           "- navigate: transition by URL",
    "- wait: ожидание секунд":              "- wait: waiting seconds",
    "Используй ID элементов из скобок [id] как селекторы: [el_0] → #el_0 или [data-ai-id='el_0']":
            "Use ID elements from brackets [id] like selectors: [el_0] → #el_0 or [data-ai-id='el_0']",
    "Ты — браузерный агент. Получаешь конкретную задачу и выполняешь её в браузере. Отвечай JSON-списком действий.":
            "You — browser agent. You receive a specific task and perform it in the browser. Answer JSON-list of actions.",
    "Ты — опытный программист. Генерируй чистый, документированный код. Используй лучшие практики. Всегда добавляй обработку ошибок.":
            "You — experienced programmer. Generate clean, documented code. Use best practices. Always add error handling.",
    "Ты — отладчик. Анализируй логи, трейсбеки, поведение. Найди корневую причину и предложи минимальный фикс.":
            "You — debugger. Analyze logs, tracebacks, behavior. Find the root cause and suggest a minimal fix.",
    "Ты — технический писатель. Пиши ясную, структурированную документацию. Используй примеры. Документируй API, параметры, возвращаемые значения.":
            "You — technical writer. Write clear, structured documentation. Use examples. Document API, parameters, return values.",
    "Убрать ячейку конкретного инстанса из сетки и перестроить сетку.":
            "Remove a specific instance cell from the grid and rebuild the grid.",
    "Увеличить (Ctrl+колесо)":              "Increase (Ctrl+wheel)",
    "Увеличить (Increment)":                "Increase (Increment)",
    "Увеличить счётчик":                    "Increase counter",
    "Удаление":                             "Removal",
    "Удалено":                              "Deleted",
    "Удалено дублей:":                      "Duplicates removed:",
    "Удалить":                              "Delete",
    "Удалить '":                            "Delete '",
    "Удалить (Delete)":                     "Delete (Delete)",
    "Удалить выбранную строку переменной":  "Delete selected variable row",
    "Удалить выбранный скилл из текущей ноды":
            "Remove the selected skill from the current node",
    "Удалить дубли":                        "Remove duplicates",
    "Удалить кастомный скилл":              "Delete custom skill",
    "Удалить ноду и все связанные рёбра из сцены и workflow.":
            "Remove the node and all associated edges from the scene and workflow.",
    "Удалить скилл":                        "Delete skill",
    "Удалить список нод (для удаления всего блока).":
            "Delete list of nodes (to delete the entire block).",
    "Удалить столбец":                      "Delete Column",
    "Удалить строки":                       "Delete rows",
    "Удалить строку после получения":       "Delete row after receiving",
    "Удалить файл после чтения":            "Delete file after reading",
    "Уже созданные файлы проекта:":         "Already created project files:",
    "Узлов выполнено:":                     "Nodes completed:",
    "Укажите путь к файлу таблицы.":        "Specify the path to the table file.",
    "Уменьшить":                            "Decrease",
    "Уменьшить (Decrement)":                "Decrease (Decrement)",
    "Уменьшить счётчик":                    "Decrement counter",
    "Умный выбор модели под тип задачи":    "Smart choice of model for the type of task",
    "Управление историей действий для Undo/Redo":
            "Manage activity history for Undo/Redo",
    "Управление проектом":                  "Project management",
    "Управление профилями":                 "Profile management",
    "Управление скиллами доступно в левой панели 'СКИЛЛЫ'":
            "Skill management is available in the left panel 'SKILLS'",
    "Уровень сообщения:":                   "Message Level:",
    "Уровень:":                             "Level:",
    "Условие выхода (Python):":             "Exit condition (Python):",
    "Условия (по строкам):":                "Terms (line by line):",
    "Условно":                              "Conditionally",
    "Успешно:":                             "Successfully:",
    "Устанавливаемое значение:":            "Set value:",
    "Установить (Set)":                     "Install (Set)",
    "Установить значение":                  "Set value",
    "Установить кастомный цвет ноды":       "Set custom node color",
    "Установить контекстное меню с вставкой переменных на любое текстовое поле.":
            "Set context menu with variable insertion to any text field.",
    "Установить куку":                      "Set cookie",
    "Установить текущую ноду для редактирования. Сохраняет предыдущую ноду перед переключением.":
            "Set the current node for editing. Saves the previous node before switching.",
    "Установить флаг восстановления (для загрузки без создания команд)":
            "Set recovery flag (to download without creating commands)",
    "Установить цвет ноды":                 "Set node color",
    "Установка переменных в контекст. Используйте поля ниже ИЛИ таблицу переменных. Переменные: {var_name}":
            "Setting variables to context. Use the fields below OR the variable table. Variables: {var_name}",
    "Учитывать регистр":                    "Match case",
    "Файл лога ошибок:":                    "Error log file:",
    "Файл не найден":                       "File not found",
    "Файл не найден:":                      "File not found:",
    "Файл не существует:":                  "The file does not exist:",
    "Файл пуст.":                           "File is empty.",
    "Файл с данными:":                      "Data file:",
    "Файл скрипта":                         "Script file",
    "Файловые операции":                    "File operations",
    "Файлы":                                "Files",
    "Фатальная ошибка:":                    "Fatal error:",
    "Фильтр переменных...":                 "Variable filter...",
    "Фильтр по маске:":                     "Filter by mask:",
    "Фиолетовый":                           "Violet",
    "Формат":                               "Format",
    "Формат: Header-Name: value":           "Format: Header-Name: value",
    "Формат: {var} == значение (по строке на каждое)":
            "Format: {var} == meaning (one line for each)",
    "Формула логина:":                      "Login formula:",
    "Цвет заметки":                         "Note color",
    "Цвет сообщения:":                      "Message color:",
    "Цвет узла":                            "Node color",
    "Цвет:":                                "Color:",
    "Целевая переменная:":                  "Target variable:",
    "Целевой агент не найден":              "Target agent not found",
    "Целое число (int)":                    "Integer (int)",
    "Цель:":                                "Target:",
    "Цифры (0-9)":                          "Numbers (0-9)",
    "Часовой пояс:":                        "Time zone:",
    "Через запятую: var1, var2":            "Separated by commas: var1, var2",
    "Через разделитель: val1;val2;val3":    "Through a separator: val1;val2;val3",
    "Числа":                                "Numbers",
    "Число":                                "Number",
    "Число до (не включительно):":          "Number up (not inclusive):",
    "Число от:":                            "Number from:",
    "Числовая сортировка":                  "Numeric sort",
    "Числовое сравнение":                   "Numeric comparison",
    "Чтение с ограничениями":               "Reading with limitations",
    "Чтение файлов":                        "Reading files",
    "Что брать (regex):":                   "What to take (regex):",
    "Ш:":                                   "Sh:",
    "Шаг (для inc/dec):":                   "Step (For inc/dec):",
    "Ширина":                               "Width",
    "Ширина viewport":                      "Width viewport",
    "Ширина окна браузера":                 "Browser window width",
    "Ширина окна:":                         "Window width:",
    "Широта (°):":                          "Latitude (°):",
    "Шрифт:":                               "Font:",
    "Экспорт переменных в CSV":             "Export variables to CSV",
    "Экспорт переменных из таблицы в CSV файл.":
            "Exporting variables from a table to CSV file.",
    "Экшен не будет ждать пока программа закончит":
            "The action will not wait until the program finishes",
    "Элемент сдвинулся! Ожидалось (":       "The element has moved! Expected (",
    "Элементы по строкам (для foreach_inline)":
            "Elements by Row (For foreach_inline)",
    "Эмулировать AudioContext":             "Emulate AudioContext",
    "Эмулировать Canvas/WebGL":             "Emulate Canvas/WebGL",
    "Эмулировать Гео/TZ по IP прокси":      "Emulate Geo/TZ By IP proxy",
    "Этим заканчивается искомый текст:":    "This ends the search text:",
    "Это задача":                           "This is the task",
    "Это идёт после искомого текста:":      "This comes after the search text:",
    "Язык:":                                "Language:",
    "Ячейка [":                             "Cell [",
    "а":                                    "A",
    "агентов":                              "agents",
    "агентов,":                             "agents,",
    "б":                                    "b",
    "байт →":                               "byte →",
    "в":                                    "V",
    "выполнен":                             "completed",
    "вытянут,":                             "pulled out,",
    "г":                                    "G",
    "д":                                    "d",
    "да":                                   "Yes",
    "действий для выполнения задачи.":      "actions to complete a task.",
    "действий)":                            "actions)",
    "е":                                    "e",
    "ж":                                    "and",
    "з":                                    "h",
    "задач":                                "tasks",
    "заканчивается на «":                   "ends with «",
    "запущено":                             "launched",
    "запущено)":                            "launched)",
    "значение1":                            "meaning1",
    "значение2":                            "meaning2",
    "значение3":                            "meaning3",
    "значений":                             "values",
    "значений)":                            "values)",
    "и":                                    "And",
    "из":                                   "from",
    "имя":                                  "Name",
    "имя переменной":                       "variable name",
    "интерактивных":                        "interactive",
    "итераций":                             "iterations",
    "й":                                    "th",
    "к":                                    "To",
    "код (":                                "code (",
    "л":                                    "l",
    "любой текст":                          "any text",
    "м":                                    "m",
    "мс)":                                  "ms)",
    "н":                                    "n",
    "найти окно...":                        "find the window...",
    "начинается с «":                       "starts with «",
    "не найдена в таблице!":                "not found in table!",
    "не разрешена для":                     "not allowed for",
    "не удалась:":                          "failed:",
    "неизвестная ошибка":                   "unknown error",
    "нод":                                  "node",
    "нод (через сцену):":                   "node (across the stage):",
    "нодов":                                "nodes",
    "нодов  ⠿":                             "nodes  ⠿",
    "нодов (с блоковой структурой)":        "nodes (with block structure)",
    "нодов в (":                            "nodes in (",
    "нодов осталось":                       "nodes left",
    "нодов)":                               "nodes)",
    "о":                                    "O",
    "откреплён, связи перестроены":         "unpinned, connections rebuilt",
    "отправлен в трей":                     "sent to tray",
    "ошибок,":                              "errors,",
    "п":                                    "n",
    "патч(ей) применено":                   "patch(to her) applied",
    "перед «":                              "before «",
    "переменная":                           "variable",
    "переменных":                           "variables",
    "переменных в":                         "variables in",
    "переменных из":                        "variables from",
    "переменных из runtime в проект":       "variables from runtime to the project",
    "полностью готов (":                    "completely ready (",
    "посещён":                              "visited",
    "после «":                              "after «",
    "пусто":                                "empty",
    "р":                                    "r",
    "раз — прерываю цикл":                  "once — I break the cycle",
    "результатов":                          "results",
    "с":                                    "With",
    "с)":                                   "With)",
    "с)...":                                "With)...",
    "с:":                                   "With:",
    "связей":                               "connections",
    "сек":                                  "sec",
    "сек завершена":                        "sec completed",
    "сек)":                                 "sec)",
    "сек...":                               "sec...",
    "симв)...":                             "char)...",
    "символов":                             "characters",
    "символов (":                           "characters (",
    "символов из":                          "characters from",
    "символов)":                            "characters)",
    "скиллов":                              "skills",
    "скиллов":                              "skills",
    "Всего:":                               "Total:",
    "скиллов из":                           "skills from",
    "сниппетов выстроены и соединены":      "snippets lined up and connected",
    "совпадений | Regex:":                  "matches | Regex:",
    "совпадений →":                         "matches →",
    "столбцов":                             "columns",
    "столбцов). Всего строк:":              "columns). Total lines:",
    "строк":                                "lines",
    "строк в":                              "lines in",
    "строк из":                             "lines from",
    "строк из CSV":                         "lines from CSV",
    "строк из буфера обмена":               "lines from clipboard",
    "строк)":                               "lines)",
    "строк,":                               "lines,",
    "строк. Осталось:":                     "lines. Left:",
    "строк. Размер:":                       "lines. Size:",
    "существует":                           "exists",
    "т":                                    "T",
    "у":                                    "at",
    "успешно":                              "successfully",
    "Всего действий в браузере:":           "Total browser actions:",
    "успешно,":                             "successfully,",
    "ф":                                    "f",
    "файлов":                               "files",
    "файлов:":                              "files:",
    "х":                                    "X",
    "ц":                                    "ts",
    "ч":                                    "h",
    "частей":                               "parts",
    "ш":                                    "w",
    "шагов":                                "steps",
    "шт.":                                  "pcs.",
    "щ":                                    "sch",
    "ъ":                                    "ъ",
    "ы":                                    "s",
    "ь":                                    "b",
    "э":                                    "uh",
    "элементов":                            "elements",
    "элементов (":                          "elements (",
    "элементов всего,":                     "elements of everything,",
    "ю":                                    "yu",
    "я":                                    "I",
    "ё":                                    "e",
    "— выбрать переменную контекста —":     "— select context variable —",
    "— выбрать —":                          "— choose —",
    "— не выбран —":                        "— not selected —",
    "— первый доступный —":                 "— first available —",
    "ℹ Инфо":                               "ℹ Info",
    "→ variable_out (сокращённый DOM + описание)":
            "→ variable_out (abbreviated DOM + description)",
    "↩️ Восстановлен полный workflow":      "↩️ Full restored workflow",
    "↩️ Нечего отменять":                   "↩️ Nothing to cancel",
    "↩️ Отменено:":                         "↩️ Canceled:",
    "↪️ Нечего повторять":                  "↪️ Nothing to repeat",
    "↪️ Повторено:":                        "↪️ Repeated:",
    "↺ Переподключено:":                    "↺ Reconnected:",
    "↺ перетащить":                         "↺ drag",
    "⌨ Ввести текст":                       "⌨ Enter text",
    "⏩ Продолжить":                         "⏩ Continue",
    "⏭ По шагам":                           "⏭ Step by step",
    "⏭ Пошаговый режим":                    "⏭ Step by step mode",
    "⏭ Пропуск:":                           "⏭ Pass:",
    "⏭ Шаг (F10)":                          "⏭ Step (F10)",
    "⏭️ Шаг:":                              "⏭️ Step:",
    "⏮ Начало":                             "⏮ Start",
    "⏱ Таймаут ожидания ответа от AI (":    "⏱ Timeout waiting for response from AI (",
    "⏱ Таймаут при создании":               "⏱ Timeout during creation",
    "⏱ Таймаут при фиксе":                  "⏱ Timeout on fix",
    "⏱ Таймаут:":                           "⏱ Time-out:",
    "⏳ Delay — пауза выполнения":           "⏳ Delay — pause execution",
    "⏳ Delay: ждёт N секунд с поддержкой рандомизации и прерыванием.":
            "⏳ Delay: waiting N seconds with randomization support and interruption.",
    "⏳ Автовстраивание через 500мс...":     "⏳ Auto embedding via 500ms...",
    "⏳ Готово":                             "⏳ Ready",
    "⏳ Ждать URL":                          "⏳ Wait URL",
    "⏳ Ждать текст":                        "⏳ Wait for text",
    "⏳ Ждать элемент":                      "⏳ Wait element",
    "⏳ Загрузка...":                        "⏳ Loading...",
    "⏳ Не удалось, повтор через 500мс...":  "⏳ Failed, repeat in 500ms...",
    "⏳ Пауза":                              "⏳ Pause",
    "⏳ Попытка":                            "⏳ Attempt",
    "⏸ Пауза:":                             "⏸ Pause:",
    "⏸ Точка останова:":                    "⏸ Breakpoint:",
    "⏹ Delay прерван на":                   "⏹ Delay interrupted by",
    "⏹ Остановить загрузку":                "⏹ Stop downloading",
    "⏹ Остановка запрошена...":             "⏹ Stop requested...",
    "⏹ Остановлено пользователем":          "⏹ Stopped by user",
    "⏹ Пауза прервана на":                  "⏹ The pause was interrupted by",
    "⏹ Стоп":                               "⏹ Stop",
    "⏹️ Остановлено":                       "⏹️ Stopped",
    "⏻  Убрать иконку из трея":             "⏻  Remove tray icon",
    "▲ Переместить вверх":                  "▲ Move up",
    "▶ Вперёд":                             "▶ Forward",
    "▶ Выполняется":                        "▶ In progress",
    "▶ Запуск от выбранного:":              "▶ Run from selected:",
    "▶ Продолжение выполнения...":          "▶ Continue execution...",
    "▶ Продолжение...":                     "▶ Continuation...",
    "▶ Старт":                              "▶ Start",
    "▶ Тест":                               "▶ Test",
    "▶ Шаг":                                "▶ Step",
    "▶| Запуск от:":                        "▶| Launch from:",
    "▶| От выбранного":                     "▶| From selected",
    "▶️ Старт:":                            "▶️ Start:",
    "▼ Переместить вниз":                   "▼ Move Down",
    "◀ Назад":                              "◀ Back",
    "☑ Только выбранные":                   "☑ Only selected",
    "☑ Только выбранные:":                  "☑ Only selected:",
    "☑ Установить чекбокс":                 "☑ Set checkbox",
    "♻️ Браузер с профилем '":              "♻️ Browser with profile '",
    "♻️ Восстановлено:":                    "♻️ Restored:",
    "⚙️ Program Launch: запуск внешней программы.":
            "⚙️ Program Launch: launching an external program.",
    "⚙️ АВТОМАТИЗАЦИЯ":                     "⚙️ AUTOMATION",
    "⚙️ Выполняю Python (":                 "⚙️ Execute Python (",
    "⚙️ Запуск программы — внешние утилиты и скрипты":
            "⚙️ Starting the program — external utilities and scripts",
    "⚙️ Запуск:":                           "⚙️ Launch:",
    "⚙️ Настройки":                         "⚙️ Settings",
    "⚙️ Настройки сниппета":                "⚙️ Snippet settings",
    "⚙️ Системные":                         "⚙️ System",
    "⚙️ Системные переменные":              "⚙️ System Variables",
    "⚙️ Сниппеты":                          "⚙️ Snippets",
    "⚠ 0 файлов! Повтор итеративного создания...":
            "⚠ 0 files! Repeat Iterative Creation...",
    "⚠ Regex ошибка в условии":             "⚠ Regex error in condition",
    "⚠ SEARCH блок не найден в файле":      "⚠ SEARCH block not found in file",
    "⚠ Switch: нет условий для сравнения":  "⚠ Switch: no conditions for comparison",
    "⚠ Switch: пустой список условий":      "⚠ Switch: empty condition list",
    "⚠ URL не указан":                      "⚠ URL not specified",
    "⚠ Авто-тест не пройден":               "⚠ Auto-test failed",
    "⚠ Буфер обмена пуст":                  "⚠ Clipboard is empty",
    "⚠ Бэкап не удался:":                   "⚠ Backup failed:",
    "⚠ Введите регулярное выражение":       "⚠ Enter a regular expression",
    "⚠ Выберите минимум 2 сниппета для башни":
            "⚠ Select minimum 2 snippet for tower",
    "⚠ Не определено что фиксить, пробую все .py файлы":
            "⚠ It is not determined what to fix, I try everything .py files",
    "⚠ Не удалось записать в":              "⚠ Failed to write to",
    "⚠ Не удалось определить список файлов, фоллбэк на обычный вызов":
            "⚠ Could not determine file list, fallback to a regular call",
    "⚠ Не удалось создать":                 "⚠ Failed to create",
    "⚠ Не удалось создать бэкап:":          "⚠ Failed to create backup:",
    "⚠ Не указан исполняемый файл":         "⚠ Executable file not specified",
    "⚠ Не указан путь к файлу скрипта (заполните 'Путь к файлу' в настройках)":
            "⚠ The path to the script file is not specified (fill in 'File path' in settings)",
    "⚠ Не указан файл":                     "⚠ File not specified",
    "⚠ Невалидный JSON для tool call":      "⚠ Invalid JSON For tool call",
    "⚠ Неизвестное действие":               "⚠ Unknown action",
    "⚠ Нет JS кода для выполнения":         "⚠ No JS code to execute",
    "⚠ Нет бэкапа для:":                    "⚠ No backup for:",
    "⚠ Нет входных данных для парсинга":    "⚠ No input data for parsing",
    "⚠ Нет кода для выполнения (заполните User Prompt или выберите 'Файл скрипта')":
            "⚠ No code to execute (fill in User Prompt or select 'Script file')",
    "⚠ Ошибка callback UI:":                "⚠ Error callback UI:",
    "⚠ Ошибка callback:":                   "⚠ Error callback:",
    "⚠ Ошибка tool:":                       "⚠ Error tool:",
    "⚠ Ошибка в regex:":                    "⚠ Error in regex:",
    "⚠ Ошибка в доп. условии '":            "⚠ Error in additional. condition '",
    "⚠ Ошибка в условии выхода:":           "⚠ Error in exit condition:",
    "⚠ Ошибка вычисления:":                 "⚠ Calculation error:",
    "⚠ Ошибка загрузки прикреплённой таблицы:":
            "⚠ Error loading attached table:",
    "⚠ Ошибка записи notification в файл:": "⚠ Write error notification to file:",
    "⚠ Ошибка при создании":                "⚠ Error while creating",
    "⚠ Ошибка сохранения лога:":            "⚠ Error saving log:",
    "⚠ Ошибка сохранения отчёта:":          "⚠ Error saving report:",
    "⚠ Ошибка чтения файла":                "⚠ Error reading file",
    "⚠ Ошибка чтения файла:":               "⚠ Error reading file:",
    "⚠ Переменная '":                       "⚠ Variable '",
    "⚠ Прикреплённый файл таблицы не найден:":
            "⚠ Attached table file not found:",
    "⚠ Программа завершилась с кодом":      "⚠ The program exited with the code",
    "⚠ Тулза":                              "⚠ Toolza",
    "⚠ Файл не найден:":                    "⚠ File not found:",
    "⚠ Фоллбэк: полная замена файла":       "⚠ Fallback: complete file replacement",
    "⚠️ BROWSER_AGENT: AI не вернул список действий":
            "⚠️ BROWSER_AGENT: AI did not return the list of actions",
    "⚠️ BROWSER_AGENT: нет активного браузера для проекта":
            "⚠️ BROWSER_AGENT: there is no active browser for the project",
    "⚠️ I/O Load: не удалось сопоставить ни одной ноды! JSON IDs:":
            "⚠️ I/O Load: could not match any nodes! JSON IDs:",
    "⚠️ I/O Save: не удалось сопоставить ни одной ноды! JSON IDs:":
            "⚠️ I/O Save: could not match any nodes! JSON IDs:",
    "⚠️ Playwright: ошибка '":              "⚠️ Playwright: error '",
    "⚠️ Selenium и Playwright не установлены. Работаю в режиме заглушки.":
            "⚠️ Selenium And Playwright not installed. Работаю в режAndме заглушкAnd.",
    "⚠️ _browser_tray_callback не найден":  "⚠️ _browser_tray_callback not found",
    "⚠️ click_text: не указан текст для поиска":
            "⚠️ click_text: search text not specified",
    "⚠️ Браузер не запущен (instance_id=":  "⚠️ Browser is not running (instance_id=",
    "⚠️ Браузер не запущен, действие '":    "⚠️ Browser is not running, action '",
    "⚠️ ВАЖНО: Создай ВСЕ файлы из структуры выше, не только один!":
            "⚠️ IMPORTANT: Create ALL files from the structure above, not just one!",
    "⚠️ Встраивание окна поддерживается только на Windows":
            "⚠️ Window embedding is only supported on Windows",
    "⚠️ Инстанс не запущен, отмена встраивания":
            "⚠️ Instance not running, unembedding",
    "⚠️ Клик может быть не точным!":        "⚠️ The click may not be accurate!",
    "⚠️ НА ДИСКЕ НЕТ ФАЙЛОВ! Code Writer не создал ничего.":
            "⚠️ THERE ARE NO FILES ON THE DISK! Code Writer didn't create anything.",
    "⚠️ Не найден вывод Planner'а":         "⚠️ Output not found Planner'A",
    "⚠️ Не найдены chrome процессы":        "⚠️ Not found chrome processes",
    "⚠️ Не удалось встроить":               "⚠️ Failed to embed",
    "⚠️ Не удалось встроить окно":          "⚠️ Failed to embed window",
    "⚠️ Не удалось найти окно браузера для PID:":
            "⚠️ Could not find the browser window for PID:",
    "⚠️ Нет активного браузера для задачи": "⚠️ There is no active browser for the task",
    "⚠️ Ошибка get_element_at_position:":   "⚠️ Error get_element_at_position:",
    "⚠️ Ошибка regex:":                     "⚠️ Error regex:",
    "⚠️ Ошибка верификации:":               "⚠️ Verification error:",
    "⚠️ Ошибка встраивания окна:":          "⚠️ Error embedding window:",
    "⚠️ Ошибка действия":                   "⚠️ Action Error",
    "⚠️ Ошибка действия '":                 "⚠️ Action Error '",
    "⚠️ Ошибка импорта куки:":              "⚠️ Error importing cookies:",
    "⚠️ Ошибка получения дочерних процессов:":
            "⚠️ Error getting child processes:",
    "⚠️ Ошибка при закрытии:":              "⚠️ Error when closing:",
    "⚠️ ПРЕДЫДУЩАЯ ОШИБКА ТЕСТА:":          "⚠️ PREVIOUS TEST ERROR:",
    "⚠️ Попытка":                           "⚠️ Attempt",
    "⚠️ Предобработка: не найден вывод Planner'а, выполняю как обычно":
            "⚠️ Preprocessing: no output found Planner'A, выполняю кAк обычно",
    "⚠️ Требуется доработка":               "⚠️ Needs improvement",
    "⚠️ Элемент сдвинулся после клика: Δx=":
            "⚠️ Element moved after click: Δx=",
    "⚠️ изменений нет":                     "⚠️ no changes",
    "⚡  Только при ошибке":                 "⚡  Only if there is an error",
    "⚡ Запуск":                             "⚡ Launch",
    "⛓ Блок ·":                             "⛓ Block ·",
    "✂️ Вырезано":                          "✂️ Cut",
    "✂️ Замена:":                           "✂️ Replacement:",
    "✂️ Обработка текста — regex, замена, split, spintax":
            "✂️ Word processing — regex, replacement, split, spintax",
    "✅  Только при успехе":                 "✅  Only if successful",
    "✅ Code Snippet выполнен":              "✅ Code Snippet completed",
    "✅ Good End — успешное завершение":     "✅ Good End — successful completion",
    "✅ Good End: успешное завершение ветки.":
            "✅ Good End: successful completion of branch.",
    "✅ JavaScript выполнен":                "✅ JavaScript completed",
    "✅ Selenium импортирован":              "✅ Selenium imported",
    "✅ Switch: совпадение #":               "✅ Switch: coincidence #",
    "✅ True → зелёная ветка":               "✅ True → green branch",
    "✅ Браузер запущен":                    "✅ Browser is running",
    "✅ Браузер запущен!":                   "✅ Browser is running!",
    "✅ Браузер успешно запущен! ID:":       "✅ Browser launched successfully! ID:",
    "✅ Встраивание успешно!":               "✅ Embedding successful!",
    "✅ Движок запущен, ID:":                "✅ The engine is running, ID:",
    "✅ Действие выполнено:":                "✅ Action completed:",
    "✅ Инстанс":                            "✅ Instance",
    "✅ Используется существующий браузер, ID:":
            "✅ Using an existing browser, ID:",
    "✅ Клик верифицирован:":                "✅ Click verified:",
    "✅ Клик выполнен (верификация недоступна)":
            "✅ Click completed (verification not available)",
    "✅ Клик выполнен, элемент стабилен (":  "✅ Click completed, the element is stable (",
    "✅ Найдено окно: hwnd=":                "✅ Window found: hwnd=",
    "✅ Обработчик resize подключён":        "✅ Handler resize connected",
    "✅ Окно встроено в панель":             "✅ Window built into panel",
    "✅ Программа завершена (exit=":         "✅ Program completed (exit=",
    "✅ Проект успешно создан!":             "✅ The project has been successfully created!",
    "✅ Редирект":                           "✅ Redirect",
    "✅ Скрипт выполнен успешно (код":       "✅ Script completed successfully (code",
    "✅ Условие ИСТИННО":                    "✅ Condition is TRUE",
    "✅ Элемент найден, выполняю клик":      "✅ Item found, I perform a click",
    "✅ изменение обнаружено":               "✅ change detected",
    "✅ получен":                            "✅ received",
    "✏️ Ввести имя вручную...":             "✏️ Enter name manually...",
    "✏️ Ввести имя переменной...":          "✏️ Enter variable name...",
    "✏️ Записан:":                          "✏️ Recorded:",
    "✏️ Обновлен скилл:":                   "✏️ Updated skill:",
    "✏️ Редактировать":                     "✏️ Edit",
    "✏️ Редактировать в панели":            "✏️ Edit in panel",
    "✏️ Редактировать скилл":               "✏️ Edit skill",
    "✓ Патч применён (":                    "✓ Patch applied (",
    "✓ Патч применён (fuzzy, строки":       "✓ Patch applied (fuzzy, lines",
    "✓ Создан новый файл:":                 "✓ New file created:",
    "✖  Закрыть браузер":                   "✖  Close browser",
    "✖  Закрыть все":                       "✖  Close all",
    "✖ Закрыть":                            "✖ Close",
    "✖ Закрыть вкладку":                    "✖ Close tab",
    "✨ Создан скилл:":                      "✨ Skill created:",
    "❌ BROWSER_AGENT: ошибка AI:":          "❌ BROWSER_AGENT: error AI:",
    "❌ False → красная ветка":              "❌ False → red branch",
    "❌ Браузер не запущен":                 "❌ Browser is not running",
    "❌ Встраивание не удалось после всех попыток":
            "❌ Embedding failed after all attempts",
    "❌ Закрыть браузер":                    "❌ Close browser",
    "❌ Не удалось запустить браузер.":      "❌ Browser failed to start.",
    "Убедитесь что установлен selenium:":   "Make sure it is installed selenium:",
    "❌ Не удалось запустить браузер.":      "❌ Browser failed to start.",
    "Установите: pip install selenium webdriver-manager":
            "Install: pip install selenium webdriver-manager",
    "❌ Не удалось запустить инстанс":       "❌ Failed to start instance",
    "❌ Нет открытого браузера (запустите BROWSER_LAUNCH)":
            "❌ No browser open (run BROWSER_LAUNCH)",
    "❌ ОШИБКА запуска браузера:":           "❌ Browser launch ERROR:",
    "❌ ОШИБКА: Selenium не установлен:":    "❌ ERROR: Selenium not installed:",
    "❌ ОШИБКА: Браузер не запустился (launch вернул None)":
            "❌ ERROR: The browser did not start (launch returned None)",
    "❌ Отмена":                             "❌ Cancel",
    "❌ Ошибка в":                           "❌ Error in",
    "❌ Ошибка в задаче":                    "❌ Error in task",
    "❌ Ошибка вставки:":                    "❌ Insertion error:",
    "❌ Ошибка действия браузера:":          "❌ Browser Action Error:",
    "❌ Ошибка закрытия браузера:":          "❌ Browser closing error:",
    "❌ Ошибка запуска браузера:":           "❌ Browser launch error:",
    "❌ Ошибка клика по элементу '":         "❌ Error clicking on element '",
    "❌ Ошибка парсинга JSON:":              "❌ Parsing error JSON:",
    "❌ Ошибка при создании":                "❌ Error while creating",
    "❌ Ошибка при фиксе":                   "❌ Error during fix",
    "❌ Ошибка:":                            "❌ Error:",
    "❌ ПРЕДЫДУЩИЕ ОШИБКИ:":                 "❌ PREVIOUS ERRORS:",
    "❌ Скрипт упал (код":                   "❌ The script crashed (code",
    "❌ Совпадений не найдено":              "❌ No matches found",
    "❌ Элемент с текстом '":                "❌ Element with text '",
    "❌ не нужен":                           "❌ not needed",
    "❓  По условию":                        "❓  By condition",
    "❓ IF Condition — условный переход":    "❓ IF Condition — conditional jump",
    "❓ IF Condition: визуальный конструктор условий + свободный Python режим.":
            "❓ IF Condition: visual condition builder + free Python mode.",
    "❓ Python выражение:":                  "❓ Python expression:",
    "❓ Доп (eval): '":                      "❓ Extra (eval): '",
    "❓ Доп: '":                             "❓ Extra: '",
    "❓ Итоговый результат:":                "❓ Final result:",
    "❓ Условие: '":                         "❓ Condition: '",
    "➕ Добавить":                           "➕ Add",
    "➕ Добавить к '":                       "➕ Add to '",
    "➕ Добавить переменную":                "➕ Add a variable",
    "➕ Добавить скилл":                     "➕ Add skill",
    "➕ Новая вкладка":                      "➕ New tab",
    "➕ Создать":                            "➕ Create",
    "➡️  Всегда":                           "➡️  Always",
    "⬆️ Открепить окно":                    "⬆️ Undock window",
    "⬇ Вставить в таблицу":                 "⬇ Insert into table",
    "⬇ Скролл к элементу":                  "⬇ Scroll to element",
    "⬇️ Автовстраивание окна...":           "⬇️ Automatic window embedding...",
    "⬇️ Встроить в панель":                 "⬇️ Embed in panel",
    "⬇️ Попытка встраивания":               "⬇️ Embedding attempt",
    "⬛ Максимизировать":                    "⬛ Maximize",
    "🌍 Геолокация":                        "🌍 Geolocation",
    "🌐  Браузеры   (":                     "🌐  Browsers   (",
    "🌐  Нет запущенных браузеров":         "🌐  No browsers running",
    "🌐 BROWSER_AGENT: сканирование DOM страницы...":
            "🌐 BROWSER_AGENT: scanning DOM pages...",
    "🌐 BROWSER_LAUNCH: запуск...":         "🌐 BROWSER_LAUNCH: launch...",
    "🌐 Browser Agent готов":               "🌐 Browser Agent ready",
    "🌐 Browser Launch — запуск браузера":  "🌐 Browser Launch — launch browser",
    "🌐 HTTP Request — веб-запросы":        "🌐 HTTP Request — web requests",
    "🌐 HTTP Request: отправляет запрос (стиль ZennoPoster).":
            "🌐 HTTP Request: sends a request (style ZennoPoster).",
    "🌐 БРАУЗЕР КОНТЕКСТ:":                 "🌐 BROWSER CONTEXT:",
    "🌐 Браузер":                           "🌐 Browser",
    "🌐 Браузер восстановлен как отдельное окно":
            "🌐 The browser is restored as a separate window",
    "🌐 Браузер встроен: hwnd=":            "🌐 Browser built-in: hwnd=",
    "🌐 Браузер запущен":                   "🌐 Browser is running",
    "🌐 Браузер запущен (Playwright) | профиль:":
            "🌐 Browser is running (Playwright) | profile:",
    "🌐 Браузер запущен (Selenium) | профиль:":
            "🌐 Browser is running (Selenium) | profile:",
    "🌐 Браузер запущен:":                  "🌐 Browser is running:",
    "🌐 Браузерные инстансы":               "🌐 Browser instances",
    "🌐 Браузеры":                          "🌐 Browsers",
    "🌐 Браузеры — нет запущенных":         "🌐 Browsers — no running",
    "🌐 Браузеры:":                         "🌐 Browsers:",
    "🌐 Браузеры: нет запущенных":          "🌐 Browsers: no running",
    "🌐 Запуск браузера":                   "🌐 Launching the browser",
    "🌐 Запустить браузер":                 "🌐 Launch browser",
    "🌐 Нет запущенных браузеров":          "🌐 No browsers running",
    "Запустите сниппет Browser Launch":     "Run the snippet Browser Launch",
    "или нажмите «Тест запуска»":           "or click «Launch test»",
    "🌐 Перейти по URL":                    "🌐 Go to URL",
    "🌐🧠 Browser Agent — AI-управление браузером":
            "🌐🧠 Browser Agent — AI-browser control",
    "🍪 Использовать CookieContainer":      "🍪 Use CookieContainer",
    "🍪 Получить куки":                     "🍪 Get cookies",
    "🍪 Установить куку":                   "🍪 Set cookie",
    "🍪🧹 Очистить куки":                   "🍪🧹 Clear cookies",
    "🎨 Выбрать":                           "🎨 Choose",
    "🎨 Цвет":                              "🎨 Color",
    "🎨 Цвет заметки":                      "🎨 Note color",
    "🎨 Цвет ноды":                         "🎨 Node color",
    "🎯 ГЛОБАЛЬНАЯ ЦЕЛЬ:":                  "🎯 GLOBAL GOAL:",
    "🎯 Захвачен блок:":                    "🎯 Block captured:",
    "🎯 Цель проекта:":                     "🎯 Project goal:",
    "🎲 Random — генерация случайных данных":
            "🎲 Random — random data generation",
    "🏷 Получить атрибут":                  "🏷 Get attribute",
    "👁  Показать все":                     "👁  Show all",
    "👁  Показать окно":                    "👁  Show window",
    "👆 Наведение мыши":                    "👆 Mouse over",
    "👆 Наведение по координатам: (":       "👆 Guidance by coordinates: (",
    "👆📍 Наведение по координатам":        "👆📍 Guidance by coordinates",
    "👤 Кастомный агент":                   "👤 Custom agent",
    "👤 Ожидание пользователя:":            "👤 User Waiting:",
    "👤 Ожидание:":                         "👤 Expectation:",
    "👤 Профиль":                           "👤 Profile",
    "👻 Headless режим (без окна)":         "👻 Headless mode (without window)",
    "💡 Проверьте: 1) Установлен Chrome 2) pip install selenium webdriver-manager":
            "💡 Check: 1) Installed Chrome 2) pip install selenium webdriver-manager",
    "💡 Установите: pip install selenium webdriver-manager":
            "💡 Install: pip install selenium webdriver-manager",
    "💥 Скрипт завершился с ошибкой — передаю агенту исправления":
            "💥 The script ended with an error — I pass it on to the correction agent",
    "💥 Тест не пройден (попытка":          "💥 Test failed (attempt",
    "💥 Фатальная ошибка:":                 "💥 Fatal error:",
    "💬 Диалог агентов":                    "💬 Agent dialogue",
    "💬 Комментарий":                       "💬 Comment",
    "💬 Комментарий:":                      "💬 Comment:",
    "💾 ID сохранён в переменную:":         "💾 ID saved to variable:",
    "💾 ID также сохранён в переменную: browser_instance_id":
            "💾 ID also saved to a variable: browser_instance_id",
    "💾 Бэкап перед":                       "💾 Backup before",
    "💾 Бэкап создан:":                     "💾 Backup created:",
    "💾 Бэкап:":                            "💾 Backup:",
    "💾 Рабочая папка запомнена:":          "💾 Working folder saved:",
    "💾 Рабочая папка сохранена в проект:": "💾 The working folder is saved in the project:",
    "💾 Сохранить":                         "💾 Save",
    "💾 Файл сохранён:":                    "💾 File saved:",
    "📁 Авто-создано файлов:":              "📁 Auto-created files:",
    "📁 Временный профиль (без сохранения)":
            "📁 Temporary profile (without saving)",
    "📁 Вставить путь к папке...":          "📁 Paste folder path...",
    "📁 Директории — создание, удаление, списки файлов":
            "📁 Directories — Creation, deletion, file lists",
    "📁 Итого на диске:":                   "📁 Total on disk:",
    "📁 Найдено:":                          "📁 Found:",
    "📁 Обнаружены файлы:":                 "📁 Files detected:",
    "📁 Папка профиля:":                    "📁 Profile folder:",
    "📁 Профиль:":                          "📁 Profile:",
    "📁 Рабочая папка:":                    "📁 Working folder:",
    "📁 Создана папка запуска:":            "📁 Launch folder created:",
    "📁 Создана:":                          "📁 Created:",
    "📁 УЖЕ СОЗДАННЫЕ ФАЙЛЫ:":              "📁 ALREADY CREATED FILES:",
    "📁 Удалена:":                          "📁 Deleted:",
    "📁 ФАЙЛЫ НА ДИСКЕ (":                  "📁 FILES ON DISK (",
    "📁 ФАЙЛЫ НА ДИСКЕ:":                   "📁 FILES ON DISK:",
    "📁 Файл:":                             "📁 File:",
    "📁 Файлов на диске после Code Writer:":
            "📁 Files on disk after Code Writer:",
    "📂 Вложенные .py:":                    "📂 Nested .py:",
    "📂 Восстановлена рабочая папка:":      "📂 Working folder restored:",
    "📂 Восстановлены скиллы из":           "📂 Skills from",
    "📂 Загружено":                         "📂 Uploaded",
    "📂 Загружено из файла:":               "📂 Loaded from file:",
    "📂 Загрузить скиллы из папки...":      "📂 Load skills from a folder...",
    "📂 Источники данных":                  "📂 Data sources",
    "📂 Корневые .py:":                     "📂 Root .py:",
    "📂 Открыть":                           "📂 Open",
    "📂 Проектные скиллы:":                 "📂 Project skills:",
    "📂 Пути проекта":                      "📂 Project paths",
    "📂 Рабочая папка (⚠ не существует):":  "📂 Working folder (⚠ doesn't exist):",
    "📂 Рабочая папка (⚠ папка удалена):":  "📂 Working folder (⚠ folder deleted):",
    "📂 Рабочая папка:":                    "📂 Working folder:",
    "📃 List Operation: операции со списками в контексте.":
            "📃 List Operation: list operations in context.",
    "📃 Regex не найден: '":                "📃 Regex not found: '",
    "📃 Не найдено: '":                     "📃 Not found: '",
    "📃 Операции со списком":               "📃 List Operations",
    "📃 Список '":                          "📃 List '",
    "📄 Загружено":                         "📄 Uploaded",
    "📄 Загрузить из TXT-списка...":        "📄 Download from TXT-list...",
    "📄 Записано в":                        "📄 Recorded in",
    "📄 Лог ошибок:":                       "📄 Error log:",
    "📄 Новый":                             "📄 New",
    "📄 Отчёт сохранён:":                   "📄 Report saved:",
    "📄 Перемещено →":                      "📄 Moved →",
    "📄 Получить текст":                    "📄 Get text",
    "📄 Получить умный DOM-контекст":       "📄 Get smart DOM-context",
    "📄 Прочитано":                         "📄 Read",
    "📄 Скопировано →":                     "📄 Copied →",
    "📄 Удалено:":                          "📄 Deleted:",
    "📄 ФАЙЛ":                              "📄 FILE",
    "📄 ФАЙЛЫ С ОШИБКАМИ:":                 "📄 FILES WITH ERROR:",
    "📄 Файл":                              "📄 File",
    "📄 Файлы — чтение, запись, копирование":
            "📄 Files — reading, recording, copying",
    "📊 Table Operation: операции с таблицами в контексте.":
            "📊 Table Operation: table operations in context.",
    "📊 Загружено":                         "📊 Uploaded",
    "📊 Загрузить из CSV/TSV...":           "📊 Download from CSV/TSV...",
    "📊 Операции с таблицей":               "📊 Table Operations",
    "📊 Строка не найдена":                 "📊 String not found",
    "📊 Таблица '":                         "📊 Table '",
    "📋 BROWSER_AGENT: получен ответ (":    "📋 BROWSER_AGENT: response received (",
    "📋 Code Writer должен создать:":       "📋 Code Writer must create:",
    "📋 Log Message — запись в лог":        "📋 Log Message — log entry",
    "📋 Log Message: выводит сообщение в лог с расширенными настройками.":
            "📋 Log Message: displays a message in the log with advanced settings.",
    "📋 Анализ:":                           "📋 Analysis:",
    "📋 ВЫВОД ОТ":                          "📋 OUTPUT FROM",
    "📋 Всего задач для выполнения:":       "📋 Total tasks to complete:",
    "📋 Вставить список из буфера":         "📋 Paste list from clipboard",
    "📋 Вставлено":                         "📋 Inserted",
    "📋 Выбрать опцию":                     "📋 Select option",
    "📋 К созданию:":                       "📋 Towards creation:",
    "📋 КОНТЕКСТ ОТ PLANNER:":              "📋 CONTEXT FROM PLANNER:",
    "📋 Конфиг:":                           "📋 Config:",
    "📋 Копировать regex":                  "📋 Copy regex",
    "📋 Копировать {":                      "📋 Copy {",
    "📋 Копировать {имя}":                  "📋 Copy {Name}",
    "📋 Копировать значение":               "📋 Copy value",
    "📋 Копировать результат":              "📋 Copy result",
    "📋 ПОЛНЫЙ ПЛАН ОТ":                    "📋 FULL PLAN FROM",
    "📋 Переменные":                        "📋 Variables",
    "📋 Переменные проекта":                "📋 Project Variables",
    "📋 Переменные проекта:":               "📋 Project Variables:",
    "📋 План получен:":                     "📋 Plan received:",
    "📋 Получен план:":                     "📋 Plan received:",
    "📋 Предобработка плана завершена":     "📋 Plan preprocessing completed",
    "    Всего задач:":                     "    Total tasks:",
    "📋 Предобработка плана:":              "📋 Plan preprocessing:",
    "📋 Разбито по параграфам:":            "📋 Broken down by paragraphs:",
    "📋 Распознан формат '":                "📋 Format recognized '",
    "📋 Распознано задач:":                 "📋 Recognized tasks:",
    "📋 Системный лог":                     "📋 System log",
    "📋 Скопировано:":                      "📋 Copied:",
    "📋 Список файлов:":                    "📋 List of files:",
    "📋 Только 1 задача, выполняю как обычно":
            "📋 Only 1 task, I do it as usual",
    "📋 Файлы для исправления:":            "📋 Files to fix:",
    "📋 Шаг 1: Запрашиваю список файлов...":
            "📋 Step 1: Requesting a list of files...",
    "📌  Свернуть":                         "📌  Collapse",
    "📌 Добавить заметку на канвас":        "📌 Add a note to the canvas",
    "📌 Заметка":                           "📌 Note",
    "📌 Заметки":                           "📌 Notes",
    "📌 Пропуск заметки:":                  "📌 Skip a note:",
    "📌 Создать заметку":                   "📌 Create a note",
    "📎 Загружено":                         "📎 Uploaded",
    "📎 Загрузить файл":                    "📎 Upload file",
    "📎 Прикрепить":                        "📎 Attach",
    "📎 Файл таблицы:":                     "📎 Table file:",
    "📐 Авторазмер по тексту":              "📐 Autosize by text",
    "📐 Размер окна":                       "📐 Window size",
    "📖 Загружен скрипт:":                  "📖 Script loaded:",
    "📖 Прочитан:":                         "📖 Read:",
    "📜 Code Snippet — выполнение кода":    "📜 Code Snippet — code execution",
    "📜 Code Snippet: выполняет Python/Shell/Node код.":
            "📜 Code Snippet: performs Python/Shell/Node code.",
    "        Поддерживает:":                "        Supports:",
    "        - Инжекцию переменных из таблицы Variables в контекст":
            "        - Injecting variables from a table Variables into context",
    "        - Подстановку {var_name} в код":
            "        - Substitution {var_name} into code",
    "        - Типизацию переменных (string/int/float/bool/json/list)":
            "        - Variable typing (string/int/float/bool/json/list)",
    "        - Сохранение stdout и stderr в переменные":
            "        - Saving stdout And stderr into variables",
    "        - Рабочую папку, env vars, таймаут":
            "        - Working folder, env vars, time-out",
    "        - Флаг \"не возвращать значение\"":
            "        - Flag \"do not return a value\"",
    "📜 Выполняю":                          "📜 Execute",
    "📜 ИСТОРИЯ ВЫПОЛНЕНИЯ:":               "📜 EXECUTION HISTORY:",
    "📜 Скролл страницы":                   "📜 Page scroll",
    "📜 Создать сниппет":                   "📜 Create a snippet",
    "📝 (таблица)":                         "📝 (table)",
    "📝 JavaScript код:":                   "📝 JavaScript code:",
    "📝 Python выражение (свободный режим):":
            "📝 Python expression (free mode):",
    "📝 SET из stdout:":                    "📝 SET from stdout:",
    "📝 Variable Set — установка переменных":
            "📝 Variable Set — setting variables",
    "📝 Variable Set: устанавливает переменные в контексте.":
            "📝 Variable Set: sets variables in context.",
    "📝 Авто-создан (паттерн 2):":          "📝 Auto-created (pattern 2):",
    "📝 Авто-создан файл:":                 "📝 Auto-created file:",
    "📝 Данные (JSON/XML):":                "📝 Data (JSON/XML):",
    "📝 Записано в файл:":                  "📝 Written to file:",
    "📝 Из таблицы Variables":              "📝 From the table Variables",
    "📝 Код для выполнения:":               "📝 Code to run:",
    "📝 Новая заметка":                     "📝 New note",
    "📝 Обновлена переменная проекта:":     "📝 Updated project variable:",
    "📝 Переменные (Variables)":            "📝 Variables (Variables)",
    "📝 Переменные сниппета":               "📝 Snippet variables",
    "📝 Получить заголовок":                "📝 Get title",
    "📝 Сообщение:":                        "📝 Message:",
    "📝 Сохранено в переменную:":           "📝 Saved to variable:",
    "📝 Удалено:":                          "📝 Deleted:",
    "📝 Установлено":                       "📝 Installed",
    "📤 Открепить":                         "📤 Unpin",
    "📤 Экспорт CSV":                       "📤 Export CSV",
    "📤 Экспортировано":                    "📤 Exported",
    "📥 Браузер":                           "📥 Browser",
    "📥 В поле сниппета":                   "📥 In the snippet field",
    "📥 Вставить переменную {var}":         "📥 Insert Variable {var}",
    "📥 Вставить сюда":                     "📥 Paste here",
    "📥 Вставлено":                         "📥 Inserted",
    "📥 Импорт CSV/TSV":                    "📥 Import CSV/TSV",
    "📥 Импортировано":                     "📥 Imported",
    "📥 Контекст:":                         "📥 Context:",
    "📥 Переменная:":                       "📥 Variable:",
    "📦 Положить в переменную":             "📦 Put it in a variable",
    "📸 BROWSER_AGENT: пиксельная верификация —":
            "📸 BROWSER_AGENT: pixel verification —",
    "📸 Скриншот":                          "📸 Screenshot",
    "📸 Скриншот элемента":                 "📸 Screenshot of the element",
    "🔀 Switch — множественный выбор":      "🔀 Switch — multiple choice",
    "🔀 Switch: Default (нет совпадения для '":
            "🔀 Switch: Default (no match for '",
    "🔀 Switch: множественный выбор по значению переменной.":
            "🔀 Switch: multiple selection by variable value.",
    "🔀 Switch: нет совпадений → Default":  "🔀 Switch: no matches → Default",
    "🔀 Switch: переменная '":              "🔀 Switch: variable '",
    "🔀 Switch: совпадение #":              "🔀 Switch: coincidence #",
    "🔀 Активировать вкладку":              "🔀 Activate tab",
    "🔀 Ребро →":                           "🔀 Edge →",
    "🔀 Тип перехода":                      "🔀 Transition type",
    "🔀 Условие":                           "🔀 Condition",
    "🔁 LOOP — цикл с итерациями":          "🔁 LOOP — loop with iterations",
    "🔁 Loop: цикл с множеством режимов.":  "🔁 Loop: cycle with many modes.",
    "🔁 Выход из цикла по условию на итерации":
            "🔁 Exiting a loop based on a condition at an iteration",
    "🔁 Итерация":                          "🔁 Iteration",
    "🔁 Прерывание по ошибке в":            "🔁 Error interrupt in",
    "🔁 Цикл (":                            "🔁 Cycle (",
    "🔄 Запрос исправления от модели...":   "🔄 Request a correction from the model...",
    "🔄 Запрошен перезапуск workflow":      "🔄 Restart requested workflow",
    "🔄 Из контекста (runtime)":            "🔄 From context (runtime)",
    "🔄 Инвертировано →":                   "🔄 Inverted →",
    "🔄 Контекст runtime":                  "🔄 Context runtime",
    "🔄 Перезагрузить":                     "🔄 Reboot",
    "🔄 Перезапуск #":                      "🔄 Restart #",
    "🔄 Попытка":                           "🔄 Attempt",
    "🔄 Синхронизировано":                  "🔄 Synchronized",
    "🔍 Regex Тестер":                      "🔍 Regex Tester",
    "🔍 Regex вставлен в поле сниппета:":   "🔍 Regex inserted into the snippet field:",
    "🔍 Верификация клика:":                "🔍 Click verification:",
    "🔍 Найден chrome процесс: pid=":       "🔍 Found chrome process: pid=",
    "🔍 Самопроверка":                      "🔍 Self-test",
    "🔍 Точка входа:":                      "🔍 Entry point:",
    "🔍 Трейс:":                            "🔍 Trace:",
    "🔍 Шаг 1: Определяю точку входа...":   "🔍 Step 1: Determining the entry point...",
    "🔐 JS авторизация":                    "🔐 JS authorization",
    "🔒 Прокси":                            "🔒 Proxy",
    "🔒 Прокси строка:":                    "🔒 Proxy string:",
    "🔒 Прокси:":                           "🔒 Proxy:",
    "🔔 Notification — оповещение":         "🔔 Notification — notification",
    "🔔 Notification: оповещение пользователя.":
            "🔔 Notification: user notification.",
    "🔗 Авто-переподключение:":             "🔗 Auto-reconnect:",
    "🔗 Авто-связь с":                      "🔗 Auto-connection with",
    "🔗 Авто-связь:":                       "🔗 Auto communication:",
    "🔗 Вставить путь к файлу...":          "🔗 Paste file path...",
    "🔗 Вставлен между:":                   "🔗 Inserted between:",
    "🔗 Получить URL":                      "🔗 Get URL",
    "🔢 Количество элементов":              "🔢 Number of elements",
    "🔣 JSON / XML — парсинг и запросы":    "🔣 JSON / XML — parsing and queries",
    "🔣 Загружен JSON из":                  "🔣 Loaded JSON from",
    "🔣 Загрузить из JSON...":              "🔣 Download from JSON...",
    "🔤 Поиск элемента по тексту: '":       "🔤 Searching for an element by text: '",
    "🔧 Автоподгружен скилл:":              "🔧 Skill loaded automatically:",
    "🔧 Вызов:":                            "🔧 Call:",
    "🔧 Инициализация Selenium...":         "🔧 Initialization Selenium...",
    "🔧 Маршрут к агенту исправления:":     "🔧 Path to remediation agent:",
    "🔧 Начало запуска браузера...":        "🔧 Starting to launch the browser...",
    "🔧 Обработка переменных — set, inc, dec, copy, cast, concat":
            "🔧 Handling Variables — set, inc, dec, copy, cast, concat",
    "🔧 Очищено":                           "🔧 Cleared",
    "🔧 Очищено:":                          "🔧 Cleared:",
    "🔧 Патч применён:":                    "🔧 Patch applied:",
    "🔧 Попытка патчинга для":              "🔧 Attempt to patch for",
    "🔧 СКИЛЛЫ":                            "🔧 SKILLS",
    "🔧 Скилл '":                           "🔧 Skill '",
    "🔧 Скилл добавлен к":                  "🔧 Skill added to",
    "🔧 Скиллы":                            "🔧 Skills",
    "🔧 Создание инстанса":                 "🔧 Creating an instance",
    "🔧 Создать новый скилл":               "🔧 Create a new skill",
    "🔧 Текущие скиллы":                    "🔧 Current skills",
    "🔨 Помощник по созданию regex":        "🔨 Creation Assistant regex",
    "🔨 Собрано:":                          "🔨 Collected:",
    "🔨 Собрать regex":                     "🔨 Collect regex",
    "🔴 Browser Close — закрыть браузер":   "🔴 Browser Close — close browser",
    "🔴 Браузер закрыт":                    "🔴 Browser is closed",
    "🔴 Все браузеры закрыты":              "🔴 All browsers are closed",
    "🔴 Закрыт инстанс:":                   "🔴 Instance closed:",
    "🔴 Закрыть браузер":                   "🔴 Close browser",
    "🔴 Красный":                           "🔴 Red",
    "🔵 Синий":                             "🔵 Blue",
    "🔷 Задача":                            "🔷 Task",
    "🖱 Browser Action — действие браузера":
            "🖱 Browser Action — browser action",
    "🖱 Действие браузера":                 "🖱 Browser action",
    "🖱 Клик по координатам: (":            "🖱 Click on coordinates: (",
    "🖱 Клик по элементу":                  "🖱 Click on an element",
    "🖱 Клик по элементу:":                 "🖱 Click on an element:",
    "🖱 Правый клик":                       "🖱 Right click",
    "🖱 Правый клик по координатам: (":     "🖱 Right click on coordinates: (",
    "🖱📍 Клик по координатам":             "🖱📍 Click on coordinates",
    "🖱📍 Правый клик по координатам":      "🖱📍 Right click on coordinates",
    "🖱🔤 Клик по тексту на странице":      "🖱🔤 Click on text on the page",
    "🖱🖱 Двойной клик":                    "🖱🖱 Double click",
    "🖱🖱 Двойной клик по координатам: (":  "🖱🖱 Double click on coordinates: (",
    "🖱🖱📍 Двойной клик по координатам":   "🖱🖱📍 Double click on coordinates",
    "🖱🟨 Клик через JS":                   "🖱🟨 Click through JS",
    "🗑 Удалить":                           "🗑 Delete",
    "🗑 Удалить весь блок":                 "🗑 Delete entire block",
    "🗑 Удалить связь":                     "🗑 Delete connection",
    "🗑 Удалить строку":                    "🗑 Delete line",
    "🗑 Удалён блок из":                    "🗑 Removed block from",
    "🗑️ Не сохранять":                     "🗑️ Don't save",
    "🗑️ Скилл удален:":                    "🗑️ Skill removed:",
    "🗑️ Удалено:":                         "🗑️ Deleted:",
    "🗑️ Удалить":                          "🗑️ Delete",
    "🗑️ Удалить скилл":                    "🗑️ Delete skill",
    "🗼 Башня:":                            "🗼 Tower:",
    "🚀 AI Project Constructor — Автоматический режим":
            "🚀 AI Project Constructor — Automatic mode",
    "🚀 Запуск workflow...":                "🚀 Launch workflow...",
    "🚀 Запуск браузера...":                "🚀 Launching the browser...",
    "🚀 Запуск движка (headless=":          "🚀 Starting the engine (headless=",
    "🚀 Запустить браузер":                 "🚀 Launch browser",
    "🚀 Запустить прямо сейчас...":         "🚀 Launch now...",
    "🚀 Команда:":                          "🚀 Team:",
    "🚨 ОШИБКА ВЫПОЛНЕНИЯ СКРИПТА:":        "🚨 SCRIPT EXECUTION ERROR:",
    "🛑 Bad End — завершение с ошибкой":    "🛑 Bad End — exit with error",
    "🛑 Bad End — ошибка в workflow":       "🛑 Bad End — error in workflow",
    "🛑 Bad End: завершение с ошибкой — логирование и восстановление.":
            "🛑 Bad End: exit with error — logging and recovery.",
    "🛑 Остановка по ошибке (stop_on_task_error=True)":
            "🛑 Stop by mistake (stop_on_task_error=True)",
    "🟡 Жёлтый":                            "🟡 Yellow",
    "🟢 Зелёный":                           "🟢 Green",
    "🟣 Фиолетовый":                        "🟣 Violet",
    "🟨 JavaScript Snippet: выполняет JS код.":
            "🟨 JavaScript Snippet: performs JS code.",
    "🟨 JavaScript — выполнение JS кода":   "🟨 JavaScript — execution JS code",
    "🟨 Выполнить JS":                      "🟨 Execute JS",
    "🟨 Выполняю JavaScript (":             "🟨 Execute JavaScript (",
    "🟨 JS Тестер":                         "🟨 JS Tester",
    "🔣 X/JSON Path":                       "🔣 X/JSON Path",
    "🤖 AI АГЕНТЫ":                         "🤖 AI AGENTS",
    "🤖 BROWSER_AGENT: запрос к AI (таймаут":
            "🤖 BROWSER_AGENT: request to AI (time-out",
    "🤖 Агенты":                            "🤖 Agents",
    "🤖 Другая модель":                     "🤖 Other model",
    "🤖 Конструктор AI-агентов — AI Code Sherlock":
            "🤖 Constructor AI-agents — AI Code Sherlock",
    "🤖 Создан агент в (":                  "🤖 Agent created in (",
    "🤖 Создан агент:":                     "🤖 Agent created:",
    "🤖 Создать агент":                     "🤖 Create agent",
    "🤖 Создать агента со скиллом":         "🤖 Create an agent with a skill",
    "🧠 Улучшаю промпт...":                 "🧠 Improving the prompt...",
    "🧠 Умное действие по DOM":             "🧠 Smart action by DOM",
    "🧪 Тест запуска (здесь и сейчас)":     "🧪 Launch test (here and now)",
    "🧹 Очистить всё":                      "🧹 Clear all",
    "🧹 Очистить поле":                     "🧹 Clear field",
    "🧾 Получить HTML":                     "🧾 Get HTML",
    "🩹 Patcher: анализ ошибки...":         "🩹 Patcher: error analysis...",
    "🩹 Исправлено:":                       "🩹 Corrected:",
    "🩹 Ошибка для исправления:":           "🩹 Error to fix:",
    "🪟 Оконный режим":                     "🪟 Windowed mode",
    "🪟 Размер окна:":                      "🪟 Window size:",
    "🤖 Конструктор":                       "🤖 Constructor",
    # ── Agent Constructor — Basic tab labels ──────────────────
    "Верификация:":                     "Verification:",
    "Модель верификатора:":             "Verifier model:",
    "Промпт верификации:":              "Verification prompt:",
    "Системный промпт:":                "System Prompt:",
    "Промпт пользователя:":             "User Prompt:",
    "Vision:":                          "Vision:",
    "Скиллы:":                          "Skills:",
    "Комментарий:":                     "Comment:",
    "Добавить скилл":                   "Add skill",
    "Удалить скилл":                    "Remove skill",
    "Основная вкладка с базовыми настройками агента":
        "Main tab with basic agent settings",

    # ── Agent Constructor — Tools tab labels ──────────────────
    "Выполнение кода":                  "Code execution",
    "Чтение файлов":                    "File reading",
    "Запись файлов":                    "File writing",
    "Веб-поиск":                        "Web search",
    "Браузер":                          "Browser",
    "Применить детальные настройки для tools":
        "Apply detailed settings for tools",
    "Вкладка управления скиллами (заглушка - основная логика в палитре слева)":
        "Skills management tab (stub - main logic in the palette on the left)",

    # ── Agent Constructor — Skills selection window ───────────
    "Добавить скилл к выбранному агенту":
                                        "Add skill to selected agent",
    "Выберите скилл":                   "Select skill",
    "Скилл добавлен":                   "Skill added",
    "Скилл уже добавлен":               "Skill already added",

    # ── Agent Constructor — Snippet/Automation windows ────────
    "Настройки сниппета":               "Snippet settings",
    "Тип:":                             "Type:",
    "Snippet title":                    "Snippet title",
    
    #GlobalSettingsDialog
    "⚙  Глобальные настройки":                     "⚙ Global Settings",
    "Сколько проектов можно запускать одновременно.\nОстальные ждут в очереди.": "How many projects can be run simultaneously.\nThe rest wait in the queue.",
    "Макс. параллельных проектов:":                "Max parallel projects:",
    " сек":                                        " sec",
    "Таймаут одного проекта:":                     "Project timeout:",
    "🧵 Потоки":                                   "🧵 Threads",
    " МБ":                                         " MB",
    "Лимит ОЗУ (мягкий):":                         "RAM limit (soft):",
    "Предупреждение при ОЗУ >:":                   "Warning when RAM >:",
    "💾 Память":                                   "💾 Memory",
    "Макс. браузеров одновременно:":               "Max simultaneous browsers:",
    " мс":                                         " ms",
    "Как часто обновлять миниатюру в трее.\n500мс = нагрузка, 5000мс = почти без нагрузки.": "How often to update the tray thumbnail.\n500ms = high load, 5000ms = almost no load.",
    "Интервал скриншота (трей):":                  "Screenshot interval (tray):",
    " %":                                          " %",
    "Масштаб скриншота для трея.\n30% = 3× меньше памяти и CPU при захвате.": "Tray screenshot scale.\n30% = 3x less memory and CPU during capture.",
    "Масштаб миниатюры:":                          "Thumbnail scale:",
    "🌐 Браузеры":                                 "🌐 Browsers",
    "Для каждой модели можно задать:\n• Макс. параллельных вызовов — семафор (1 = очередь).\n• Режим: parallel (одновременно) или sequential (по одному).\n\nПример: локальная LLM ollama/llama3 → sequential, limit=1\n        OpenAI gpt-4o → parallel, limit=5": "For each model you can set:\n• Max parallel calls — semaphore (1 = queue).\n• Mode: parallel (simultaneously) or sequential (one by one).\n\nExample: local LLM ollama/llama3 → sequential, limit=1\n        OpenAI gpt-4o → parallel, limit=5",
    "ID модели":                                   "Model ID",
    "Лимит":                                       "Limit",
    "Режим":                                       "Mode",
    "+ Добавить":                                  "+ Add",
    "— Удалить":                                   "— Delete",
    "🤖 Модели":                                   "🤖 Models",
    "model_id":                                    "model_id",
    "Комментарий":                                  "Comment",
    "Текст:":                                       "Text:",
    "Текст комментария:":                           "Comment text:",
    "Тип:":                                         "Type:",
    "Связь":                                        "Connection",
    "🔗 Авто-связь:":                               "🔗 Auto-connect:",
    "откреплён, связи перестроены":                 "detached, connections rebuilt",
    "🔗 Авто-переподключение:":                     "🔗 Auto-reconnect:",
    "🗑 Удалён блок из":                            "🗑 Deleted block of",
    "нод":                                          "nodes",
    "🔗 Авто-связь с":                              "🔗 Auto-connect with",
    
    "🤖 Создать агент":                             "🤖 Create agent",
    "📜 Создать сниппет":                           "📜 Create snippet",
    "📌 Создать заметку":                           "📌 Create note",
    "📥 Вставить сюда":                             "📥 Paste here",
    "🔧 Создать новый скилл":                       "🔧 Create new skill",
    "📂 Загрузить скиллы из папки...":              "📂 Load skills from folder...",
    
    "🔀 Тип перехода":                              "🔀 Transition type",
    "➡️  Всегда":                                   "➡️  Always",
    "✅  Только при успехе":                        "✅  On success only",
    "⚡  Только при ошибке":                        "⚡  On error only",
    "❓  По условию":                               "❓  On condition",
    
    "🗑 Удалить связь":                             "🗑 Delete connection",
    "🎨 Цвет":                                      "🎨 Color",
    "По умолчанию":                                 "Default",
    "Красный":                                      "Red",
    "Зеленый":                                      "Green",
    "Желтый":                                       "Yellow",
    "Синий":                                        "Blue",
    "Фиолетовый":                                   "Purple",
    "Оранжевый":                                    "Orange",
    "Бирюзовый":                                    "Turquoise",
    
    "💬 Комментарий":                               "💬 Comment",
    "🗑 Удалить весь блок":                         "🗑 Delete entire block",
    "📎 Прикрепить":                                "📎 Attach",
    "📤 Открепить":                                 "📤 Detach",
    "🗑 Удалить":                                   "🗑 Delete",
    
    "➕ Добавить скилл":                            "➕ Add skill",
    "🔧 Текущие скиллы":                            "🔧 Current skills",
    "⚙️ Настройки сниппета":                        "⚙️ Snippet settings",
    "✏️ Редактировать в панели":                    "✏️ Edit in panel",
    
    "вытянут, {0} нодов осталось":                  "pulled out, {0} nodes remaining",
    "Вставлен между: {0} → {1} → {2}":              "Inserted between: {0} → {1} → {2}",
    "Захвачен блок: {0} нодов":                      "Block captured: {0} nodes",
    "Перемещение блока ({0} нодов)":                 "Block movement ({0} nodes)",
    "Перемещение {0}":                               "Movement {0}",
    "Блок · {0} нодов":                              "Block · {0} nodes",
    "Зажмите чтобы переместить блок":                "Hold to move block",
    "перетащить":                                    "drag",
    "Переподключено: {0} → {1}":                     "Reconnected: {0} → {1}",
    "Переподключение {0} → {1}":                     "Reconnection {0} → {1}",
    # ── Another ────────
    "## АКТИВНАЯ СТРАТЕГИЯ:":               "## ACTIVE STRATEGY:",
    "## ВЫХОДНЫЕ ФАЙЛЫ":                    "## OUTPUT FILES",
    "## ДОПОЛНИТЕЛЬНЫЕ ФАЙЛЫ ДЛЯ ПАТЧИНГА": "## ADDITIONAL FILES FOR PATCHING",
    "## ЗАДАЧА":                            "## TASK",
    "## ЗАДАЧА":                            "## TASK",
    "1. Определи первопричину ошибки (с указанием строк если возможно)":
            "1. Determine the root cause of the error (with lines if possible)",
    "2. Объясни цепочку событий: что вызвало что":
            "2. Explain the chain of events: what caused what",
    "3. Дай МИНИМАЛЬНЫЙ патч в формате [SEARCH_BLOCK]/[REPLACE_BLOCK]":
            "3. Give me a MINIMUM patch in format [SEARCH_BLOCK]/[REPLACE_BLOCK]",
    "4. Оцени уверенность: ВЫСОКАЯ / СРЕДНЯЯ / НИЗКАЯ и объясни почему":
            "4. Rate your confidence: HIGH / AVERAGE / LOW and explain why",
    "## ЗАДАЧА":                            "## TASK",
    "Метрики ухудшились. Предложи АЛЬТЕРНАТИВНЫЙ подход который:":
            "Metrics have gotten worse. Suggest an ALTERNATIVE approach that:",
    "1. Не повторяет предыдущий патч":      "1. Does not repeat the previous patch",
    "2. Восстановит и улучшит метрики":     "2. Restore and improve metrics",
    "Скрипты:":                             "Scripts:",
    "## ЗАДАЧА СУДЬИ":                      "## JUDGE'S TASK",
    "## ЗАПРОС ПОЛЬЗОВАТЕЛЯ":               "## USER REQUEST",
    "## ИСТОРИЯ ПОСЛЕДНИХ":                 "## HISTORY OF THE LAST",
    "## КАСТОМНАЯ СТРАТЕГИЯ AI":            "## CUSTOM STRATEGY AI",
    "## КОД ПРОЕКТА":                       "## PROJECT CODE",
    "## КОНТЕКСТ ОКРУЖЕНИЯ (только для понимания — НЕ изменяй)":
            "## ENVIRONMENTAL CONTEXT (just for understanding — DON'T change)",
    "## ЛОГИ":                              "## LOGS",
    "## ЛОГИ ВАЛИДАТОРОВ":                  "## VALIDATOR LOGS",
    "## ЛОГИ ОШИБОК":                       "## ERROR LOGS",
    "## ОТВЕТ МОДЕЛИ":                      "## MODEL RESPONSE",
    "## ПОДСКАЗКА ПОЛЬЗОВАТЕЛЯ":            "## USER HINT",
    "## РЕГРЕССИЯ МЕТРИК":                  "## REGRESSION OF METRICS",
    "Предыдущие:":                          "Previous:",
    "## РЕЛЕВАНТНЫЙ КОД":                   "## RELEVANT CODE",
    "## СОПУТСТВУЮЩИЕ СКРИПТЫ (только чтение — не патчить)":
            "## RELATED SCRIPTS (read only — don't patch)",
    "## СТРАТЕГИЯ:":                        "## STRATEGY:",
    "## ТЕКУЩИЙ КОД":                       "## CURRENT CODE",
    "## ФАЙЛ ДЛЯ ИЗМЕНЕНИЯ":                "## FILE TO CHANGE",
    "## ФОРМАТ ОТВЕТА":                     "## REPLY FORMAT",
    "1. Краткий анализ (3-5 предложений) — что происходит, почему, что менять":
            "1. Brief Analysis (3-5 proposals) — what's happening, Why, what to change",
    "2. Патчи в формате [SEARCH_BLOCK]/[REPLACE_BLOCK]":
            "2. Patches in format [SEARCH_BLOCK]/[REPLACE_BLOCK]",
    "3. Если цель достигнута — напиши GOAL_ACHIEVED":
            "3. If the goal is achieved — write GOAL_ACHIEVED",
    "SEARCH_BLOCK должен ТОЧНО совпадать с кодом файла (с пробелами и отступами).":
            "SEARCH_BLOCK must EXACTLY match the file code (with spaces and indents).",
    "## ЦЕЛЬ":                              "## TARGET",
    "## код проекта":                       "## project code",
    "## релевантный код":                   "## relevant code",
    "## ⚠️ ЗАПРЕЩЁННЫЕ ПОДХОДЫ (уже пробовали — стало хуже):":
            "## ⚠️ PROHIBITED APPROACHES (already tried — it got worse):",
    "## ⚠️ КРИТИЧНО: ПРЕДЫДУЩИЙ ПАТЧ ВЫЗВАЛ БЕСКОНЕЧНЫЙ ЦИКЛ ОШИБОК":
            "## ⚠️ CRITICAL: THE PREVIOUS PATCH CAUSED AN ENDLESS LOOP OF ERRORS",
    "Скрипт повторял одну и ту же строку **":
            "The script repeated the same line **",
    "## ⚠️ ОШИБКИ ВАЛИДАТОРА":              "## ⚠️ VALIDator ERRORS",
    "## 🗂 КАРТА ОШИБОК — Ранее решённые проблемы:":
            "## 🗂 ERROR CARD — Previously resolved problems:",
    "### Файл: `":                          "### File: `",
    "' не найдена в конфигурации":          "' not found in configuration",
    "' не найдена в настройках":            "' not found in settings",
    "' не указан file_path":                "' not specified file_path",
    "' очищен":                             "' cleared",
    "' очищена":                            "' cleared",
    "' пуст":                               "' empty",
    "' пуста":                              "' empty",
    "' сейчас выполняется.":                "' currently running.",
    "Остановить и закрыть?":                "Stop and close?",
    "' уже добавлен":                       "' already added",
    "'). Убедитесь что BROWSER_LAUNCH выполнен и переменная с ID передана корректно.":
            "'). Make sure that BROWSER_LAUNCH executed and variable with ID transmitted correctly.",
    "'>Ошибка:":                            "'>Error:",
    "        // Ждём body если его ещё нет":
            "        // We are waiting body if it doesn't exist yet",
    "            // Пробуем document.documentElement как fallback":
            "            // Let's try document.documentElement How fallback",
    "        // Отладка: если элементов 0, проверим что вообще есть в DOM":
            "        // Debugging: if elements 0, let's check what's in there DOM",
    "(не выбран)":                          "(not selected)",
    "(нет настроек / БД)":                  "(no settings / DB)",
    "(нет патчей)":                         "(no patches)",
    "(нет списков — нажмите ➕ Список)":     "(no lists — click ➕ List)",
    "(нет таблиц — нажмите ➕ Таблица)":     "(no tables — click ➕ Table)",
    "(новый)":                              "(new)",
    "(пусто)":                              "(empty)",
    "(смена профиля)":                      "(change profile)",
    ") в окне":                             ") in the window",
    ") затем ввод текста":                  ") then enter text",
    ") и ввод текста":                      ") and text input",
    ") не ответил — откат к best-of-N":     ") didn't answer — rollback to best-of-N",
    ") по координатам (":                   ") by coordinates (",
    ") — откат основных скриптов...":       ") — rollback of main scripts...",
    "), выполняю":                          "), I'm doing",
    "), жду":                               "), I am waiting",
    "). Запуск всё равно разрешён (QThread).":
            "). Launch is still allowed (QThread).",
    "). Подход должен отличаться от предыдущего.":
            "). The approach should be different from the previous one.",
    "): до":                                "): to",
    "*(сжато)*":                            "*(condensed)*",
    "**Итерация":                           "**Iteration",
    "**Итерация:**":                        "**Iteration:**",
    "**Лучшие метрики за все итерации:**":  "**Best metrics for all iterations:**",
    "**Основной файл:** `":                 "**Main file:** `",
    "**Ошибка:**":                          "**Error:**",
    "**Патч:**":                            "**Patch:**",
    "**Причина:**":                         "**Cause:**",
    "**РЕЖИМ: ВОПРОС** — Ответь развёрнутым текстом. Патчи [SEARCH_BLOCK]/[REPLACE_BLOCK] НЕ нужны.":
            "**MODE: QUESTION** — Answer with expanded text. Patches [SEARCH_BLOCK]/[REPLACE_BLOCK] NOT needed.",
    "**РЕЖИМ: ИЗМЕНЕНИЕ КОДА** — Используй формат [SEARCH_BLOCK]/[REPLACE_BLOCK].":
            "**MODE: CODE CHANGE** — Use the format [SEARCH_BLOCK]/[REPLACE_BLOCK].",
    "**Решение:**":                         "**Solution:**",
    "**⚠ КРИТИЧЕСКИЕ ОШИБКИ ВАЛИДАТОРА `":  "**⚠ CRITICAL VALIDator ERRORS `",
    "**⚠ ОШИБКА в `":                       "**⚠ ERROR in `",
    "**🤝 Консенсус [":                     "**🤝 Consensus [",
    "*Полный код (":                        "*Full code (",
    "+ Новая":                              "+ New",
    "+ подряд — принудительная остановка процесса!":
            "+ contract — forced process stop!",
    ", видимых=":                           ", visible=",
    ", задача:":                            ", task:",
    ", интерактивных=":                     ", interactive=",
    ", используем Ctrl+A":                  ", we use Ctrl+A",
    ", порог:":                             ", threshold:",
    ", пробуем стандартный путь":           ", try the standard path",
    ",20000) ещё до HWND-поиска":           ",20000) even before HWND-search",
    "- НЕ делать:":                         "- DON'T do:",
    "--use-file-for-fake-audio-capture=\"путь\". Добавьте %noloop для однократного воспроизведения":
            "--use-file-for-fake-audio-capture=\"path\". Add %noloop for single playback",
    "--use-file-for-fake-video-capture=\"путь\"":
            "--use-file-for-fake-video-capture=\"path\"",
    "-1 = использовать температуру из настроек модели":
            "-1 = use temperature from model settings",
    "Проанализируй скриншот и верни ТОЛЬКО JSON без пояснений:":
            "Analyze the screenshot and return ONLY JSON no explanation:",
    "action=done — задача выполнена. action=fail — невозможно выполнить.":
            "action=done — task completed. action=fail — impossible to perform.",
    ". Совет: уменьши max_context_tokens или log_max_chars, увеличь ai_timeout_seconds в настройках пайплайна.":
            ". Advice: reduce max_context_tokens or log_max_chars, increase ai_timeout_seconds in the pipeline settings.",
    "... (сокращено)":                      "... (abbreviated)",
    "... [обрезано]":                       "... [cropped]",
    "... ещё строк (показано":              "... more lines (shown",
    "... и ещё строк (файл обрезан до":     "... and more lines (file cropped to",
    "0 = без ограничений":                  "0 = without restrictions",
    "0 = без ограничений. При превышении — ротация":
            "0 = without restrictions. If exceeded — rotation",
    "0 = без ожидания":                     "0 = without waiting",
    "0 = без ожидания. Используется для wait_appear/wait_disappear/check_exists":
            "0 = without waiting. Used for wait_appear/wait_disappear/check_exists",
    "0, 1, 2... или имя колонки. Поддерживает {переменную}":
            "0, 1, 2... or column name. Supports {variable}",
    "0–20 → 0.0–2.0; 7 = 0.7 — баланс креативность/точность":
            "0–20 → 0.0–2.0; 7 = 0.7 — balance creativity/accuracy",
    "1 = минимальный, 10 = максимальный приоритет":
            "1 = minimum, 10 = maximum priority",
    "1. Точность — SEARCH_BLOCK точно совпадает с реальным кодом":
            "1. Accuracy — SEARCH_BLOCK exactly matches the real code",
    "12ч":                                  "12h",
    "1м":                                   "1m",
    "2. Минимальность — только необходимые изменения":
            "2. Minimality — only necessary changes",
    "3. Правильность — патч решает заявленную проблему":
            "3. Right — The patch solves the stated problem",
    "30м":                                  "30m",
    "50 = нечёткое, 80 = хорошо, 95 = точное":
            "50 = fuzzy, 80 = Fine, 95 = exact",
    "50 = нечёткое, 80 = хорошо, 95 = точное совпадение":
            "50 = fuzzy, 80 = Fine, 95 = exact match",
    ": изолированный профиль":              ": isolated profile",
    ": патч вызвал бесконечный цикл ошибок":
            ": the patch caused an endless loop of errors",
    "= 10 мин":                             "= 10 min",
    "=== Лист:":                            "=== Sheet:",
    "AI Agent Browser - Работает в фоне":   "AI Agent Browser - Runs in the background",
    "Работает в двух режимах:":             "Works in two modes:",
    "  1. Правильная структура (после organize.py): core/, ui/, services/ ...":
            "  1. Correct structure (after organize.py): core/, ui/, services/ ...",
    "  2. Плоская папка (все .py в одном месте): запускает organize.py автоматически":
            "  2. Flat folder (All .py in one place): launches organize.py automatically",
    "AI Code Sherlock — первый запуск":     "AI Code Sherlock — first launch",
    "AI анализирует [":                     "AI analyzes [",
    "AI вернул пустой ответ":               "AI returned an empty response",
    "AI не ответил за":                     "AI didn't answer for",
    "AI не ответил после":                  "AI didn't answer after",
    "AI не смог:":                          "AI couldn't:",
    "AI-агент делает скриншот окна программы, анализирует его и выполняет действия (клики, ввод текста). Работает аналогично Browser Agent, но для любых настольных приложений.":
            "AI-the agent takes a screenshot of the program window, analyzes it and performs actions (clicks, text input). Works similar Browser Agent, but for any desktop applications.",
    "AI: ошибка (":                         "AI: error (",
    "API ключ капча-сервиса":               "API captcha service key",
    "API ключ:":                            "API key:",
    "Accept-Language заголовок. Пример: en-US,en;q=0.9":
            "Accept-Language title. Example: en-US,en;q=0.9",
    "BotUI — параметры, отображаемые пользователю перед запуском проекта.":
            "BotUI — parameters, displayed to the user before starting the project.",
    "Добавьте поля, которые пользователь должен заполнить.":
            "Add fields, which the user must fill out.",
    "Bypass прокси:":                       "Bypass proxy:",
    "CSS или XPath — только для режима «Элемент»":
            "CSS or XPath — only for mode «Element»",
    "Callback от runtime — обновляет данные списка/таблицы в _vars_panel и перерисовывает чипы.":
            "Callback from runtime — updates list data/tables in _vars_panel and redraws the chips.",
    "Called when the '🎨 Патчи' checkbox is toggled.":
            "Called when the '🎨 Patches' checkbox is toggled.",
    "Canvas с поддержкой выделения прямоугольной области мышью.":
            "Canvas with support for selecting a rectangular area with the mouse.",
    "Canvas с поддержкой выделения региона мышью.":
            "Canvas with support for selecting a region with the mouse.",
    "HDF5 ключи:":                          "HDF5 keys:",
    "ID активного браузера →:":             "ID active browser →:",
    "JSON-массив":                          "JSON-array",
    "JSON-объектов":                        "JSON-objects",
    "JSON-строка (dict)":                   "JSON-line (dict)",
    "KEY=VALUE (одна на строку):":          "KEY=VALUE (one per line):",
    "NPZ файл с ключами:":                  "NPZ key file:",
    "PID или HWND из сниппета Program Open":
            "PID or HWND from snippet Program Open",
    "PID или HWND программы из PROGRAM_OPEN":
            "PID or HWND programs from PROGRAM_OPEN",
    "Pickle объект типа:":                  "Pickle object of type:",
    "Pipeline завершён •":                  "Pipeline completed •",
    "Project Dashboard — окно управления проектами в стиле ZennoPoster.":
            "Project Dashboard — style project management window ZennoPoster.",
    "Содержит:":                            "Contains:",
    "  - Таблицу проектов с колонками (статус, имя, прогресс, успехи, потоки, метки...)":
            "  - Project table with columns (status, Name, progress, successes, streams, tags...)",
    "  - Боковое меню фильтрации (по статусу, меткам)":
            "  - Side filter menu (by status, tags)",
    "  - Диалог запуска проекта (потоки, попытки, режим, расписание, bottleneck)":
            "  - Project launch dialog (streams, attempts, mode, schedule, bottleneck)",
    "  - Кнопки управления (Старт/Стоп/Пауза/+N/∞)":
            "  - Control buttons (Start/Stop/Pause/+N/∞)",
    "  - Глобальную статистику потоков":    "  - Global flow statistics",
    # ── Project Dashboard UI strings ──────────────────────────
    "Добавить":                             "Add",
    "Запустить":                            "Run",
    "Остановить":                           "Stop",
    "Пауза":                                "Pause",
    "Возобновить":                          "Resume",
    "Открыть в редакторе":                  "Open in editor",
    "Потоки":                               "Threads",
    "Приоритет":                            "Priority",
    "Задания":                              "Tasks",
    "Максимум":                             "Maximum",
    "Выполняется":                          "Running",
    "Выполнен":                             "Completed",
    "Остановлен":                           "Stopped",
    "Сбросить статистику":                  "Reset stats",
    "Настройки...":                         "Settings...",
    "Добавить попытки":                     "Add attempts",
    "Бесконечно":                           "Infinite",
    "потоков":                              "threads",
    "Инфо":                                 "Info",
    "Project Execution Manager — многопоточное управление проектами в стиле ZennoPoster.":
            "Project Execution Manager — multi-threaded project management in style ZennoPoster.",
    "Архитектура:":                         "Architecture:",
    "  - ProjectEntry: данные одного проекта (настройки, состояние, статистика)":
            "  - ProjectEntry: data from one project (settings, state, statistics)",
    "  - ProjectExecutor: изолированный QThread для одного запуска проекта":
            "  - ProjectExecutor: isolated QThread for one project launch",
    "  - ProjectExecutionManager: синглтон-диспетчер всех проектов":
            "  - ProjectExecutionManager: Singleton manager of all projects",
    "  - ProjectScheduler: планировщик расписания запусков":
            "  - ProjectScheduler: launch scheduler",
    "Каждый проект выполняется в полностью изолированном потоке.":
            "Each project runs in a completely isolated thread.",
    "Основной UI НИКОГДА не блокируется выполнением.":
            "Basic UI NEVER blocked by execution.",
    "PyTorch модель, параметров:":          "PyTorch model, parameters:",
    "Python-код, выполняемый перед первым узлом. Доступны: context, variables, log":
            "Python-code, executed before the first node. Available: context, variables, log",
    "Regex (в столбце)":                    "Regex (in column)",
    "Runtime и отладка.":                   "Runtime and debugging.",
    "SQLite (локально)":                    "SQLite (locally)",
    "Timeout после":                        "Timeout after",
    "X координата:":                        "X coordinate:",
    "Y координата:":                        "Y coordinate:",
    "ZennoPoster загружает до 4000, ProjectMaker — до 400":
            "ZennoPoster loads up to 4000, ProjectMaker — to 400",
    "[DEBUG] Найден активный инстанс:":     "[DEBUG] Active instance found:",
    "[EXEC] Выполняется... (":              "[EXEC] In progress... (",
    "[EXEC] Завершено:":                    "[EXEC] Completed:",
    "[EXEC] Запуск workflow...":            "[EXEC] Launch workflow...",
    "[EXEC] Конфигурация runtime...":       "[EXEC] Configuration runtime...",
    "[EXEC] Копирование workflow...":       "[EXEC] Copy workflow...",
    "[EXEC] Получен сигнал остановки":      "[EXEC] Stop signal received",
    "[EXEC] Результат определён из runtime._results (fallback)":
            "[EXEC] The result is determined from runtime._results (fallback)",
    "[EXEC] Создание runtime...":           "[EXEC] Creation runtime...",
    "[EXEC] Создание браузерного менеджера...":
            "[EXEC] Creating a browser manager...",
    "[EXEC] Старт выполнения workflow":     "[EXEC] Start execution workflow",
    "[Excel файл — openpyxl не установлен]":
            "[Excel file — openpyxl not installed]",
    "[Excel файл,":                         "[Excel file,",
    "[LOAD GLOBALS] восстанавливаем project_root из metadata: '":
            "[LOAD GLOBALS] we restore project_root from metadata: '",
    "[NumPy файл — numpy не установлен]":   "[NumPy file — numpy not installed]",
    "[Parquet файл — pandas не установлен]":
            "[Parquet file — pandas not installed]",
    "[ProjectExecutor] Ошибка в потоке":    "[ProjectExecutor] Error in stream",
    "[PyTorch не установлен]":              "[PyTorch not installed]",
    "[aria-label=\"Найти\"]":               "[aria-label=\"Find\"]",
    "[h5py не установлен]":                 "[h5py not installed]",
    "[КОНСЕНСУС:":                          "[CONSENSUS:",
    "[ЛОГ:":                                "[LOG:",
    "[Ошибка конвертации":                  "[Conversion error",
    "[Ошибка чтения CSV:":                  "[Reading error CSV:",
    "[Ошибка чтения Excel:":                "[Reading error Excel:",
    "[Ошибка чтения NumPy:":                "[Reading error NumPy:",
    "[Ошибка чтения Parquet:":              "[Reading error Parquet:",
    "[Ошибка чтения Pickle:":               "[Reading error Pickle:",
    "[Ошибка:":                             "[Error:",
    "[Файл не найден:":                     "[File not found:",
    "[краш]":                               "[crush]",
    "[полный]":                             "[full]",
    "[последний прогресс]":                 "[latest progress]",
    "[сжато]":                              "[condensed]",
    "] ЗАЦИКЛЕННАЯ ОШИБКА ×":               "] Looping ERROR ×",
    "] ПРИМЕНЁН ->":                        "] APPLIED ->",
    "] в трей":                             "] to tray",
    "] в трей после":                       "] in tray after",
    "] из '":                               "] from '",
    "] найден, но координаты нулевые":      "] found, but the coordinates are zero",
    "] не найден в DOM":                    "] not found in DOM",
    "] уже стартовал невидимым (трей-режим)":
            "] already started invisible (tray mode)",
    "] успешно скрыт в трей":               "] successfully hidden in tray",
    "] — опрашиваю":                        "] — I'm asking",
    "]</span> <span style='color:#e0af68'>[СИСТЕМА]</span>":
            "]</span> <span style='color:#e0af68'>[SYSTEM]</span>",
    "^[a-zA-Zа-яёА-ЯЁ]{5,}$":               "^[a-zA-Za-yayoA-YAYO]{5,}$",
    "Патчи той итерации откачены автоматически.":
            "Patches from that iteration are automatically rolled back.",
    "` (без коммент.,":                     "` (no comment.,",
    "` [СКЕЛЕТ API,":                       "` [SKELETON API,",
    "` [СКЕЛЕТ, доп. файл]:":               "` [SKELETON, extra. file]:",
    "` [СКЕЛЕТ, сопутствующий контекст]:":  "` [SKELETON, related context]:",
    "` [доп. файл для патчинга]:":          "` [extra. patching file]:",
    "` [сопутствующий контекст]:":          "` [related context]:",
    "` содержит несохранённые изменения.":  "` contains unsaved changes.",
    "Патчи из той итерации **откачены автоматически**.":
            "Patches from that iteration **pumped out automatically**.",
    "**Требования к новому патчу:**":       "**Requirements for the new patch:**",
    "1. Предложи принципиально другой подход — не повторяй предыдущий":
            "1. Offer a fundamentally different approach — don't repeat the previous one",
    "2. Исправь первопричину ошибки, а не её симптом":
            "2. Fix the root cause of the error, not a symptom",
    "3. Убедись что SEARCH_BLOCK точно совпадает с текущим (откаченным) кодом":
            "3. Make sure that SEARCH_BLOCK exactly matches the current one (pumped out) code",
    "Эти ошибки означают что предыдущий патч сломал интерфейс/данные которые валидатор проверяет. Исправь первопричину.":
            "These errors mean that the previous patch broke the interface/data that the validator checks. Fix the root cause.",
    "https://…  (Enter — перейти)":         "https://…  (Enter — go)",
    "login, password, last_activity — только если режим «Выбранные»":
            "login, password, last_activity — only if mode «Selected»",
    "login:pass@host:port  или  socks5://host:port  или  {proxy_var}":
            "login:pass@host:port  or  socks5://host:port  or  {proxy_var}",
    "organize.py завершился с ошибкой.":    "organize.py failed with an error.",
    "tok / оригинал":                       "tok / original",
    "tok) — сжатие отключено:":             "tok) — compression disabled:",
    "true/false — найден ли шаблон. {переменная}":
            "true/false — is the template found?. {variable}",
    "val1;val2;val3 — для добавления строки. Поддерживает {переменную}":
            "val1;val2;val3 — to add a line. Supports {variable}",
    "Marvin  → первое имя профиля":         "Marvin  → first profile name",
    "{browser_instance_id}  (первый/текущий)":
            "{browser_instance_id}  (first/current)",
    "{переменная} для сохранения итога работы AI":
            "{variable} to save the result of the work AI",
    "{переменная} — куда сохранить результат (путь, статус, имя профиля)":
            "{variable} — where to save the result (path, status, profile name)",
    "{переменная} — получить Marvin после загрузки":
            "{variable} — get Marvin after loading",
    "|  **Стратегия:**":                    "|  **Strategy:**",
    "|  Отказов:":                          "|  Bounces:",
    "| Колонок:":                           "| Columns:",
    "| Оригинал:":                          "| Original:",
    "| Режим:":                             "| Mode:",
    "| метрики=":                           "| metrics=",
    "| патчей=":                            "| patches=",
    "» содержит несохранённые изменения.":  "» contains unsaved changes.",
    "» уже выполняется в этой вкладке.":    "» already running in this tab.",
    "Аварийная очистка при любом завершении программы.":
            "Emergency cleaning at any program termination.",
    "Автозапуск браузера при старте":       "Browser autostart at startup",
    "Автоматически создаю правильную структуру...":
            "Automatically create the correct structure...",
    "Автоскролл выключен — прокрути вниз чтобы включить":
            "Autoscroll disabled — scroll down to enable",
    "Автосохранить все изменённые вкладки.":
            "Autosave all changed tabs.",
    "Активировать layout этого таба без изменения размера окна":
            "Activate layout this tab without changing the window size",
    "Акцент на метриках из лога":           "Focus on log metrics",
    "Алиас close() — совместимость с BrowserManager API.":
            "Alias close() — compatible with BrowserManager API.",
    "Аргументы запуска браузера:":          "Browser launch arguments:",
    "Аргументы командной строки. {переменные}":
            "Command Line Arguments. {variables}",
    "Атрибуты:":                            "Attributes:",
    "Аудио без повтора (%noloop)":          "Audio without repeat (%noloop)",
    "Аудио-файл (.wav):":                   "Audio file (.wav):",
    "БД":                                   "DB",
    "БЫЛО (SEARCH):":                       "WAS (SEARCH):",
    "База / файл:":                         "Base / file:",
    "Базовая блокировка по EasyList-правилам":
            "Basic blocking by EasyList-rules",
    "Без GUI (headless)":                   "Without GUI (headless)",
    "Без ограничений":                      "No restrictions",
    "Бесконечное выполнение":               "Infinite execution",
    "Бинарный файл:":                       "Binary file:",
    "Блок вставлен: {0} нодов в {1}":       "Block inserted: {0} nodes in {1}",
    "Блок не найден:":                      "Block not found:",
    "Блокировать видео и аудио":            "Block video and audio",
    "Блокировать рекламу (adblock)":        "Block ads (adblock)",
    "Блокировать трекеры":                  "Block trackers",
    "Боковая панель как в ZennoPoster: фильтрация по статусу и меткам.":
            "Sidebar as in ZennoPoster: filtering by status and tags.",
    "Более осторожный точечный патч":       "More discreet spot patch",
    "Браузер: ошибка (":                    "Browser: error (",
    "Быстрая проверка изменений без полного скриншота.":
            "Quickly check changes without taking a full screenshot.",
    "Быстрая проверка изменений — не блокирует UI.":
            "Quickly check changes — doesn't block UI.",
    "Быстрое переименование списка через диалог.":
            "Quickly rename a list through a dialog.",
    "Быстрое переименование таблицы через диалог.":
            "Quickly rename a table via dialog.",
    "В очереди":                            "Queued",
    "В папке не найдено файлов *.workflow.json":
            "No files found in folder *.workflow.json",
    "В переменную (base64)":                "To a variable (base64)",
    "В проекте нет элементов. Добавьте их на вкладке 'Списки / Таблицы'.":
            "There are no elements in the project. Add them to the tab 'Lists / Tables'.",
    "В файл":                               "To file",
    "В этой вкладке идёт выполнение проекта.":
            "This tab is where the project is running..",
    "Остановить и закрыть?":                "Stop and close?",
    "Валидатор обнаружил проблемы после патча. AI ДОЛЖЕН исправить эти ошибки в следующем патче.":
            "Validator found problems after the patch. AI MUST fix these bugs in the next patch.",
    "Валидатор упал после патча:":          "Validator crashed after patch:",
    "Введите строки — каждая строка будет отдельным элементом списка":
            "Enter lines — each line will be a separate element of the list",
    "Ввод текста не удался:":               "Text input failed:",
    "Верификация скриншотами":              "Verification with screenshots",
    "Вернуть snippet_config только если тип совпадает с текущим agent_type.":
            "Return snippet_config only if the type matches the current one agent_type.",
    "Вернуть все списки проекта (для runtime и сниппетов).":
            "Return all project lists (For runtime and snippets).",
    "Вернуть все таблицы проекта (для runtime и сниппетов).":
            "Return all project tables (For runtime and snippets).",
    "Вернуть семафор для конкретной модели (создать если нет).":
            "Return a semaphore for a specific model (create if not).",
    "Версия:":                              "Version:",
    "Верхняя половина":                     "Upper half",
    "Взять скриншот из выбранного (по instance_id) или первого доступного браузера через Selenium.":
            "Take a screenshot from the selected one (By instance_id) or the first available browser via Selenium.",
    "Видео-файл (.y4m):":                   "Video file (.y4m):",
    "Виджет конфигурации сниппета BROWSER_CLICK_IMAGE.":
            "Snippet configuration widget BROWSER_CLICK_IMAGE.",
    "    Показывает скриншот текущего браузера, позволяет выделить регион-шаблон.":
            "    Shows a screenshot of the current browser, allows you to select a template region.",
    "Вкладка глобальных переменных, доступных между потоками.":
            "Global Variables Tab, available between threads.",
    "Вкладка управления списками и таблицами проекта.":
            "Tab for managing project lists and tables.",
    "Включать неактивные инстансы":         "Enable inactive instances",
    "Включить антидетект":                  "Enable antidetect",
    "Включить расписание":                  "Enable schedule",
    "Включить/выключить запись действий браузера в сниппеты.":
            "Turn on/disable recording browser actions in snippets.",
    "Вместо этого:":                        "Instead:",
    "Возобновить проект.":                  "Resume project.",
    "Восстановить workflow объекты из file_path при загрузке состояния.":
            "Restore workflow objects from file_path when loading state.",
    "Восстановить проекты из автосохранения?":
            "Restore projects from autosave?",
    "Восстановить файл к состоянию ДО этого патча":
            "Restore the file to the state BEFORE this patch",
    "Восстановить файл к состоянию ДО этого патча?":
            "Restore the file to the state BEFORE this patch?",
    "Временна́я зона:":                     "TemporarýI'm zone:",
    "Временная зона:":                      "Time zone:",
    "Временны́е метки в логе":              "Temporarýe marks in the log",
    "Все переменные":                       "All variables",
    "Вставка блока ({0} нодов)":            "Inserting a block ({0} nodes)",
    "Встроить окно браузера в ячейку сетки.":
            "Embed a browser window in a grid cell.",
    "Вся страница":                         "Whole page",
    "Вся страница (fullpage)":              "Whole page (fullpage)",
    "Всё окно":                             "Whole window",
    "Входные настройки / BotUI":            "Input settings / BotUI",
    "Вхождений:":                           "Occurrences:",
    "Выбери ЛУЧШИЙ ответ по критериям:":    "Choose the BEST answer according to the criteria:",
    "Выберите проект:":                     "Select a project:",
    "Выберите проектную таблицу:":          "Select a design table:",
    "Выберите проектный список:":           "Select project list:",
    "Выбор списка":                         "List selection",
    "Выбор таблицы":                        "Table selection",
    "Выбранный шаблон изображения":         "Selected image template",
    "Выбрать из списков проекта":           "Select from project lists",
    "Выбрать из таблиц проекта":            "Select from project tables",
    "Выбрать папку с проектами":            "Select folder with projects",
    "Выбрать рабочую папку":                "Select working folder",
    "Выбрать файл списка":                  "Select list file",
    "Выбрать файлы проектов":               "Select project files",
    "Выбрать цвет ноды START.":             "Select node color START.",
    "Выбрать шаблон":                       "Select a template",
    "Выделено: x=":                         "Highlighted: x=",
    "Выделите область мышью ↓":             "Select an area with the mouse ↓",
    "Вызов модели с конкретным model_id (или default).":
            "Calling a model with a specific model_id (or default).",
    "Вызывается при каждом записанном действии браузера — создаёт сниппет.":
            "Called on every recorded browser action — creates a snippet.",
    "Вызывается при переключении основных вкладок панели переменных.":
            "Called when switching main tabs of the variable panel.",
    "Выполни ВСЕ шаги по порядку. Максимум действий:":
            "Follow ALL steps in order. Maximum action:",
    "Выполняет workflow с защитой от зависаний.":
            "Performs workflow with freeze protection.",
    "Выполнять JavaScript":                 "Fulfill JavaScript",
    "Вырезаем выделенную область из полного скриншота.":
            "Cut out the selected area from the full screenshot.",
    "ГБ":                                   "GB",
    "Геолокация (lat,lon):":                "Geolocation (lat,lon):",
    "Главное окно управления проектами в стиле ZennoPoster.":
            "Styled main project management window ZennoPoster.",
    "    Может использоваться как:":        "    Can be used as:",
    "    - Отдельное окно (QWidget + show())":
            "    - Separate window (QWidget + show())",
    "    - Вкладка в главном окне конструктора":
            "    - Tab in the main designer window",
    "Глобальные настройки выполнения:":     "Global Execution Settings:",
    "потоки, ОЗУ, браузеры, семафоры моделей":
            "streams, RAM, browsers, model semaphores",
    "Голосование:":                         "Vote:",
    "Голосование: нет согласия при мин.=":  "Vote: no agreement at min.=",
    "Графические компоненты сцены.":        "Scene Graphics Components.",
    "Дай другой вариант ответа (вариант":   "Give me another answer (option",
    "Данные таблицы":                       "Table data",
    "Данные:":                              "Data:",
    "Дата рождения (YYYY-MM-DD):":          "Date of birth (YYYY-MM-DD):",
    "Движок браузера:":                     "Browser engine:",
    "Дебаггер":                             "Debugger",
    "Действие после загрузки:":             "Action after loading:",
    "Делаем скриншот браузера и открываем редактор выделения области.":
            "Take a screenshot of the browser and open the selection editor.",
    "Делаем скриншот окна программы через HWND и открываем редактор выделения.":
            "We take a screenshot of the program window using HWND and open the selection editor.",
    "Делает скриншот браузера, ищет шаблон, возвращает (found, cx, cy).":
            "Takes a browser screenshot, looking for a pattern, returns (found, cx, cy).",
    "Делает скриншот окна или области окна программы.":
            "Takes a screenshot of a window or area of \u200b\u200ba program window.",
    "Делает скриншот текущей страницы браузера. Сохраняет в переменную (base64), файл или оба варианта.":
            "Takes a screenshot of the current browser page. Saves to a variable (base64), file or both.",
    "Делегат для отрисовки прогресс-бара в ячейке таблицы.":
            "Delegate for drawing a progress bar in a table cell.",
    "Диалог входных настроек проекта и BotUI.":
            "Project input settings dialog and BotUI.",
    "Диалог выбора прямоугольной области на скриншоте браузера.":
            "Dialog for selecting a rectangular area on a browser screenshot.",
    "Диалог глобальных настроек (кнопка ⚙ в toolbar).":
            "Global settings dialog (button ⚙ V toolbar).",
    "Диалог настроек запуска проекта.":     "Project launch settings dialog.",
    "    Открывается при нажатии \"Запустить\" — позволяет задать":
            "    Opens when pressed \"Launch\" — allows you to set",
    "    все параметры выполнения перед стартом.":
            "    all execution parameters before start.",
    "Диалог редактирования проектного списка.":
            "Project list editing dialog.",
    "Диалог редактирования проектной таблицы.":
            "Project table editing dialog.",
    "Динамическое обновление темы без перезапуска.":
            "Dynamic theme update without restart.",
    "Длина:":                               "Length:",
    "Для contains/regex. Поддерживает {переменную}":
            "For contains/regex. Supports {variable}",
    "Для upload_file":                      "For upload_file",
    "Для режима «Указанная область»":       "For mode «Specified area»",
    "Добавить базу данных":                 "Add database",
    "Добавить все .workflow.json проекты из выбранной папки.":
            "Add all .workflow.json projects from the selected folder.",
    "Добавить колонку":                     "Add a column",
    "Добавить подключение к базе данных в проект.":
            "Add a database connection to the project.",
    "Добавить попытки к проекту (как кнопка +N в ZennoPoster).":
            "Add attempts to the project (like a button +N V ZennoPoster).",
    "Добавить проект":                      "Add a project",
    "Добавить проект в менеджер.":          "Add a project to manager.",
    "Добавить проекты выбрав один или несколько .workflow.json файлов.":
            "Add projects by selecting one or more .workflow.json files.",
    "Добавить пустую строку":               "Add an empty line",
    "Добавить таблицу":                     "Add table",
    "Добавить текущий открытый проект из конструктора.":
            "Add the currently open project from the designer.",
    "Добавлена строка в '":                 "Added line to '",
    "Добавлено в '":                        "Posted in '",
    "Добавляет: --use-fake-device-for-media-stream --use-fake-ui-for-media-stream":
            "Adds: --use-fake-device-for-media-stream --use-fake-ui-for-media-stream",
    "Ежедневно в указанное время":          "Every day at the specified time",
    "Если ВЫКЛЮЧЕНО — данные таблицы НЕ будут храниться в .workflow.json":
            "If OFF — table data will NOT be stored in .workflow.json",
    "и будут загружаться из файла при каждом открытии.":
            "and will be loaded from the file every time it is opened.",
    "Рекомендуется выключить для больших таблиц.":
            "Recommended to be disabled for large tables.",
    "Если ВЫКЛЮЧЕНО — содержимое НЕ будет храниться в .workflow.json":
            "If OFF — content will NOT be stored in .workflow.json",
    "и будет загружаться из файла при каждом открытии проекта.":
            "and will be loaded from the file every time the project is opened.",
    "Рекомендуется выключить для больших списков (тысячи строк).":
            "Recommended to turn off for large lists (thousands of lines).",
    "Если включено — все браузеры проекта будут закрыты":
            "If enabled — all project browsers will be closed",
    "автоматически после завершения workflow.":
            "automatically after completion workflow.",
    "Выключите, если нужно оставить браузер открытым.":
            "Turn off, if you need to leave the browser open.",
    "Если не найдено:":                     "If not found:",
    "Ждать бесконечно":                     "Wait forever",
    "Женский":                              "Female",
    "ЗАПРЕЩЁННЫЕ":                          "PROHIBITED",
    "ЗАПРЕЩЕНО":                            "FORBIDDEN",
    "Завершить проект.":                    "Complete the project.",
    "Заголовок окна (поиск):":              "Window title (search):",
    "Загружает workflow из файла в указанный таб.":
            "Loads workflow from file to specified tab.",
    "Загружается в переменную {data_lines} как список строк":
            "Loaded into a variable {data_lines} as a list of strings",
    "Загружать CSS / стили":                "Load CSS / styles",
    "Загружать из файла при каждом запуске":
            "Load from file on every startup",
    "Загружать изображения":                "Upload images",
    "Загружать шрифты":                     "Download fonts",
    "Загружен '":                           "Loaded '",
    "Загрузить глобальные переменные из метаданных workflow в контекст выполнения.":
            "Load global variables from metadata workflow into the execution context.",
    "        Берёт конфиг именно для типа текущего сниппета из кэша по типу.":
            "        Takes the config specifically for the type of the current snippet from the cache by type.",
    "Загрузить настройки из GlobalSettings.":
            "Load settings from GlobalSettings.",
    "Загрузить настройки с диска и применить.":
            "Load settings from disk and apply.",
    "Загрузить проектные списки и таблицы в контекст выполнения.":
            "Load project lists and tables into the execution context.",
    "Загрузить сохранённое состояние.":     "Load saved state.",
    "Загрузить шаблон из PNG/JPG файла":    "Download template from PNG/JPG file",
    "Задача выполнена":                     "Task completed",
    "Задача для AI:":                       "Task for AI:",
    "Задача:":                              "Task:",
    "Задержка макс. (мс):":                 "Delay max. (ms):",
    "Задержка между повторами (мс):":       "Delay between retries (ms):",
    "Задержка мин. (мс):":                  "Delay min. (ms):",
    "Задержка старта (мс):":                "Start delay (ms):",
    "Зажмите ЛКМ и выделите область — именно этот фрагмент будет шаблоном для клика по картинке.":
            "Hold LMB and select an area — This fragment will be the template for clicking on the picture.",
    "Закрывать браузер по завершении":      "Close browser when finished",
    "Закрыть браузер по завершении workflow если флаг close_browser_on_finish=True.":
            "Close browser when finished workflow if flag close_browser_on_finish=True.",
    "Заметка: {0}":                         "Note: {0}",
    "Записано:":                            "Recorded:",
    "Записать сообщение в лог выполнения.": "Write a message to the execution log.",
    "Запись о проекте в менеджере выполнения.":
            "Project entry in Execution Manager.",
    "Запланирован":                         "Scheduled",
    "Заполнить одну строку таблицы.":       "Fill in one row of the table.",
    "Запрашиваю AI...":                     "I request AI...",
    "Запуск без видимого окна — быстрее, не требует экрана":
            "Running without a visible window — faster, does not require a screen",
    "Запускает внешнюю программу, управляет окном. Аналог Browser Launch для программ.":
            "Launches an external program, controls the window. Analogue Browser Launch for programs.",
    "Запустить workflow на всех вкладках-проектах.":
            "Launch workflow on all project tabs.",
    "Запустить браузерный инстанс перед выполнением первого узла":
            "Start a browser instance before executing the first node",
    "Запустить отладку на всех открытых вкладках — с начала каждого проекта.":
            "Run debugging on all open tabs — from the beginning of each project.",
    "Запустить проект в отдельном потоке с учётом лимита.":
            "Run the project in a separate thread, taking into account the limit.",
    "Запустить проект с передачей сервисов из конструктора.":
            "Start a project with passing services from the constructor.",
    "Запустить проект с учётом его настроек потоков.":
            "Run the project taking into account its thread settings.",
    "Запустить таймер автосохранения и зарегистрировать обработчики краша.":
            "Start autosave timer and register crash handlers.",
    "Зарегистрировать проект из вкладки конструктора.":
            "Register a project from the designer tab.",
    "        Возвращает project_id.":       "        Returns project_id.",
    "Захват + масштабирование скриншота в фоновом потоке.":
            "Capture + scaling screenshot in background thread.",
    "Захватить скриншот и показать в QLabel (потокобезопасно).":
            "Capture screenshot and show in QLabel (thread safe).",
    "Звуковой сигнал по завершении":        "Beep when completed",
    "Значение (для добавления/удаления):":  "Meaning (to add/removal):",
    "Значение по умолч.":                   "Default value.",
    "Значение ячейки (для записи):":        "Cell value (for recording):",
    "Значения строки (через ;):":           "Row values (through ;):",
    "И в файл, и в переменную":             "And to the file, and into a variable",
    "ИТЕРАЦИЙ":                             "ITERATIONS",
    "Игнорировать SSL-ошибки":              "Ignore SSL-errors",
    "Из '":                                 "From '",
    "Изменить количество потоков проекта на лету.":
            "Change the number of project threads on the fly.",
    "Изолированный поток для одного запуска проекта.":
            "Isolated thread for one project run.",
    "    Каждый экземпляр получает КОПИЮ workflow и собственный контекст,":
            "    Each copy receives a COPY workflow and own context,",
    "    что обеспечивает полную изоляцию от других потоков.":
            "    which provides complete isolation from other threads.",
    "Иконка + Название:":                   "Icon + Name:",
    "Импорт из файла...":                   "Import from file...",
    "Импорт списков и таблиц":              "Importing lists and tables",
    "Импорт списков и таблиц из JSON/CSV файла.":
            "Importing lists and tables from JSON/CSV file.",
    "Импорт стратегий":                     "Import strategies",
    "Импортировать из файла...":            "Import from file...",
    "Имя AudioInput-устройства:":           "Name AudioInput-devices:",
    "Имя AudioOutput-устройства:":          "Name AudioOutput-devices:",
    "Имя VideoInput-устройства:":           "Name VideoInput-devices:",
    "Имя из панели \"Списки/Таблицы\". Поддерживает {переменную}":
            "Name from panel \"Lists/Tables\". Supports {variable}",
    "Имя колонки:":                         "Column name:",
    "Имя переменной для base64-строки PNG": "Variable name for base64-lines PNG",
    "Имя подключения (для ссылок)":         "Connection name (for links)",
    "Имя поля":                             "Field name",
    "Имя профиля →:":                       "Profile name →:",
    "Имя узла в каждой строке":             "Node name on each line",
    "Инжектируем JS-скрипт записи в браузер.":
            "Injecting JS-browser recording script.",
    "Инструкции для AI. Что именно делать, как принимать решения, на что обращать внимание. Пиши чётко и директивно.":
            "Instructions for AI. What exactly to do, how to make decisions, what to pay attention to. Write clearly and directively.",
    "Инструкция:":                          "Instructions:",
    "Интервал повтора (мс):":               "Repeat interval (ms):",
    "Интервал повторов (мс):":              "Retry interval (ms):",
    "Интервал:":                            "Interval:",
    "Исполнение сниппета операций с профилем браузера.":
            "Executing a snippet of operations with a browser profile.",
    "Используй формат [SEARCH_BLOCK]/[REPLACE_BLOCK] для ВСЕХ изменений.":
            "Use the format [SEARCH_BLOCK]/[REPLACE_BLOCK] for ALL changes.",
    "SEARCH_BLOCK должен ТОЧНО совпадать с содержимым файла.":
            "SEARCH_BLOCK must EXACTLY match the contents of the file.",
    "Исправить первопричину ошибки, а не её симптом; проверить изменения на корректность до применения":
            "Fix the root cause of the error, not a symptom; check changes for correctness before applying",
    "Источник файла (CSV/TSV)":             "File source (CSV/TSV)",
    "Источник файла (необязательно)":       "File source (optional)",
    "Ищет изображение-шаблон на скриншоте окна программы и выполняет действие. Нажмите 📷 чтобы сделать скриншот программы и выделить нужную область.":
            "Looks for a template image in the screenshot of the program window and performs the action. Click 📷 to take a screenshot of the program and highlight the desired area.",
    "Ищет изображение-шаблон на странице браузера и выполняет действие по нему. Нажмите 📷 чтобы сделать скриншот браузера и выделить нужную область.":
            "Looks for a template image on the browser page and performs an action on it. Click 📷 to take a browser screenshot and highlight the desired area.",
    "КАРТА ОШИБОК":                         "ERROR CARD",
    "Каждые N минут":                       "Every N minutes",
    "Каждый проект запустится от того узла, на котором он остановился":
            "Each project will start from that node, where he stopped",
    "Каждый раз перед выполнением этого сниппета загружать список из файла заново":
            "Each time before executing this snippet, load the list from the file again",
    "Каждый раз перед выполнением этого сниппета загружать таблицу из файла заново":
            "Each time before executing this snippet, load the table from the file again",
    "Каждый следующий повтор ждёт в 2× дольше":
            "Each next repetition waits in 2× longer",
    "Какие переменные:":                    "What variables:",
    "Капча-сервис:":                        "Captcha service:",
    "Каскадное перепозиционирование цепочки сверху вниз (без рёбер).":
            "Cascading chain repositioning from top to bottom (without ribs).",
    "Кастомная стратегия:":                 "Custom strategy:",
    "Качество JPEG (1-100):":               "Quality JPEG (1-100):",
    "Клиентская часть":                     "Client part",
    "Клик (левый)":                         "Cry (left)",
    "Клик — открыть редактор":              "Cry — open editor",
    "Клик, ввод текста, скролл, хоткеи в окне программы.":
            "Cry, text input, scroll, hotkeys in the program window.",
    "Ключи state_dict:":                    "Keys state_dict:",
    "Кодировка файла:":                     "File encoding:",
    "Кол-во браузеров →:":                  "Number of browsers →:",
    "Кол-во:":                              "Qty:",
    "Количество выполнений:":               "Number of executions:",
    "Количество параллельных потоков выполнения":
            "Number of parallel threads",
    "Количество потоков:":                  "Number of threads:",
    "Колонка":                              "Column",
    "Колонка 1":                            "Column 1",
    "Колонки":                              "Columns",
    "Комбо":                                "Combo",
    "Компактная раскрывающаяся панель списков/таблиц над debug-баром.":
            "Compact drop-down list panel/tables above debug-bar.",
    "Компактный словарь элемента для AI — только критически важное.":
            "Compact element dictionary for AI — only critical.",
    "Консенсус [":                          "Consensus [",
    "Консенсус: сжимаю контекст...":        "Consensus: compressing the context...",
    "Конструктор AI-агентов — визуальный редактор workflow":
            "Constructor AI-agents — visual editor workflow",
    "Конструктор не подключён":             "The constructor is not connected",
    "Контекст для AI перед стартом проекта. Поддерживает {переменные}":
            "Context for AI before the start of the project. Supports {variables}",
    "Контекстное меню для чипа БД.":        "Context menu for the DB chip.",
    "Контекстное меню для чипа настроек.":  "Context menu for settings chip.",
    "Контекстное меню для чипа списка.":    "Context menu for list chip.",
    "Контекстное меню для чипа таблицы.":   "Context menu for table chip.",
    "Контекстное меню при ПКМ по заголовку панели списков/таблиц.":
            "Context menu when right-clicking on the title of the list panel/tables.",
    "Контекстное меню при ПКМ по пустому месту в зоне списков или таблиц.":
            "Context menu when RMB on an empty space in the area of \u200b\u200blists or tables.",
    "Координата X внутри окна программы":   "Coordinate X inside the program window",
    "Координата Y внутри окна программы":   "Coordinate Y inside the program window",
    "Координаты (x,y) в переменную:":       "Coordinates (x,y) into a variable:",
    "Копирование выбранных агентов вместе с блоковой структурой и рёбрами":
            "Copying selected agents along with block structure and edges",
    "Красивое окно-сетка всех открытых браузерных инстансов по всем проектам.":
            "A beautiful grid window of all open browser instances for all projects.",
    "Кратко опиши этот файл для использования как контекст при анализе большого проекта.":
            "Briefly describe this file for use as context when analyzing a large project.",
    "Краткое описание (будет показано в списке)":
            "Brief description (will be shown in the list)",
    "Критерий получения (проект):":         "Receipt criterion (project):",
    "Критерий строки (проект):":            "Row criterion (project):",
    "Критическая ошибка":                   "Critical error",
    "Критическая ошибка:":                  "Critical error:",
    "Левая половина":                       "Left half",
    "Лог выполнения...":                    "Execution log...",
    "Логирование через сигнал менеджера.":  "Logging via manager signal.",
    "Лёгкое обновление: только URL-метки и статус-точки в существующих карточках.":
            "Easy update: only URL-labels and status points in existing cards.",
    "МОИ СТРАТЕГИИ":                        "MY STRATEGIES",
    "Макс. одновременно:":                  "Max. simultaneously:",
    "Макс. патчей за итерацию:":            "Max. patches per iteration:",
    "Макс. потоков":                        "Max. streams",
    "Макс. профилей для поиска:":           "Max. profiles to search:",
    "Макс. размер лога (МБ):":              "Max. log size (MB):",
    "Максимум действий в одном цикле AI":   "Maximum actions in one cycle AI",
    "Максимум:":                            "Maximum:",
    "Максимум: 10":                         "Maximum: 10",
    "Маскирует следы автоматизации (navigator.webdriver, plugins и т.д.)":
            "Masks traces of automation (navigator.webdriver, plugins etc.d.)",
    "Менеджер системного трея для управления скрытыми окнами браузеров.":
            "System tray manager for managing hidden browser windows.",
    "    Реализует паттерн Синглтон для работы с несколькими браузерными инстансами.":
            "    Implements the Singleton pattern for working with multiple browser instances.",
    "Метки":                                "Tags",
    "Метки (через запятую):":               "Tags (separated by commas):",
    "Миниатюра одной открытой программы — аналог BrowserTrayMiniature.":
            "Thumbnail of one open program — analogue BrowserTrayMiniature.",
    "Минимизировать окно после запуска":    "Minimize window after launch",
    "Модель '":                             "Model '",
    "Моя стратегия":                        "My strategy",
    "Мужской":                              "Male",
    "НОВЫЙ ПРОЕКТ":                         "NEW PROJECT",
    "Нажать Enter":                         "Click Enter",
    "Нажми Enter...":                       "Click Enter...",
    "Нажмите «Сделать скриншот браузера»":  "Click «Take a browser screenshot»",
    "Нажмите 📷 для скриншота браузера → выделите нужную область":
            "Click 📷 for browser screenshot → select the desired area",
    "Нажмите 📷 для скриншота программы → выделите нужную область":
            "Click 📷 for a screenshot of the program → select the desired area",
    "Название базы / путь к файлу SQLite":  "Base name / file path SQLite",
    "Название стартовой точки...":          "Starting point name...",
    "Найдено (true/false) →:":              "Found (true/false) →:",
    "Найти HWND главного окна Chrome по PID драйвера.":
            "Find HWND main window Chrome By PID drivers.",
    "Найти ID корневого элемента цепочки.": "Find ID root element of the chain.",
    "Найти template_b64 на screen_bytes через OpenCV / PIL.":
            "Find template_b64 on screen_bytes through OpenCV / PIL.",
    "Найти корневой блок под позицией (только корни цепочек).":
            "Find root block under position (only chain roots).",
    "Начальная инструкция для AI-модели...":
            "Initial instructions for AI-models...",
    "Начальная точка выполнения проекта. Выберите режим запуска и настройте браузер, AI-модель, переменные, ограничения, логирование и уведомления.":
            "Project starting point. Select launch mode and configure your browser, AI-model, variables, restrictions, logging and notifications.",
    "Начать запись действий в браузере.":   "Start recording browser activity.",
    "Клики, ввод текста, навигация — автоматически создают сниппеты в проекте.":
            "Clicks, text input, navigation — automatically create snippets in the project.",
    "Не менять":                            "Don't change",
    "Не удалось загрузить состояние:":      "Failed to load state:",
    "Не удалось найти окно программы.":     "Could not find the program window.",
    "Убедитесь что программа запущена (PROGRAM_OPEN)":
            "Make sure the program is running (PROGRAM_OPEN)",
    "и в поле 'Переменная PID/HWND' указано правильное имя.":
            "and in the field 'Variable PID/HWND' the name is correct.",
    "Не удалось найти поле ввода для:":     "Could not find the input field for:",
    "Не удалось открыть":                   "Failed to open",
    "Не удалось сделать скриншот.":         "Failed to take screenshot.",
    "Не удалось сделать скриншот.":         "Failed to take screenshot.",
    "Убедитесь что браузер запущен (BROWSER_LAUNCH).":
            "Make sure the browser is running (BROWSER_LAUNCH).",
    "Неизвестная proj_list операция:":      "Unknown proj_list operation:",
    "Неизвестная proj_table операция:":     "Unknown proj_table operation:",
    "Необработанное исключение:":           "Unhandled exception:",
    "Нет активной модели AI":               "No active model AI",
    "Нет браузеров":                        "No browsers",
    "Нет данных для отката — версия не сохранена.":
            "No data to roll back — version not saved.",
    "Нет открытых проектов":                "No open projects",
    "Нет пути":                             "There's no way",
    "Нет условия":                          "No condition",
    "Нет шаблона":                          "No template",
    "Неуспехи":                             "Failures",
    "Нижняя половина":                      "Bottom half",
    "Ничего":                               "Nothing",
    "Ничего не найдено":                    "Nothing found",
    "Новая стратегия":                      "New strategy",
    "Новое имя:":                           "New name:",
    "Номер строки (для by_index):":         "Line number (For by_index):",
    "Нумерация с 0. Поддерживает {переменную}":
            "Numbering from 0. Supports {variable}",
    "ОШИБКА импорта:":                      "Import ERROR:",
    "ОШИБКА: PyQt6 не установлен":          "ERROR: PyQt6 not installed",
    "ОШИБКА: organize.py не найден.":       "ERROR: organize.py not found.",
    "ОШИБКА: Не найдены файлы проекта рядом с main.py":
            "ERROR: Project files not found near main.py",
    "Область (x,y,w,h):":                   "Region (x,y,w,h):",
    "Область не выбрана":                   "No area selected",
    "Область поиска (x,y,w,h):":            "Search area (x,y,w,h):",
    "Область поиска:":                      "Search area:",
    "Область:":                             "Region:",
    "Обновить inline-панель при изменении списков/таблиц.":
            "Update inline-panel when changing lists/tables.",
    "Обновить визуальный превью при перетаскивании над блоком.":
            "Update visual preview when dragging over a block.",
    "Обновить глобальные настройки (из UI).":
            "Update global settings (from UI).",
    "Обновить кнопки debug-панели под состояние runtime текущей вкладки.":
            "Refresh buttons debug-panels for condition runtime current tab.",
    "Обновить ноду PROJECT_START при изменении полей.":
            "Update node PROJECT_START when changing fields.",
    "Обновить отображение потоков.":        "Refresh stream display.",
    "Обновить скриншот":                    "Update screenshot",
    "Обновить скриншоты всех карточек.":    "Update screenshots of all cards.",
    "Обновить стили при смене темы.":       "Update styles when changing theme.",
    "Обновить стили трей-панели и всех миниатюр при смене темы.":
            "Update tray and all thumbnail styles when changing theme.",
    "Обновить счётчики в списках.":         "Update counters in lists.",
    "Обновить цвета по текущей теме.":      "Update colors based on current theme.",
    "Обновление статистики для UI.":        "Update statistics for UI.",
    "Обработка закрытия окна — проверяем ВСЕ вкладки на несохранённые изменения.":
            "Window closing handling — check ALL tabs for unsaved changes.",
    "Обработчик SIGTERM/SIGINT — сохраняемся перед завершением.":
            "Handler SIGTERM/SIGINT — save before finishing.",
    "Обработчик изменения рабочей папки в поле ввода.":
            "Handler for changing the working folder in the input field.",
    "Обязательно начни с анализа (3-5 предложений) перед патчами.":
            "Be sure to start with analysis (3-5 proposals) before patches.",
    "Обёртка для обратной совместимости.":  "Wrapper for backward compatibility.",
    "Однократно":                           "One time",
    "Ожидалось в:":                         "Expected in:",
    "Ожидание готовности (сек):":           "Waiting for readiness (sec):",
    "Ожидание после действия":              "Waiting after action",
    "Ожидать (сек):":                       "Expect (sec):",
    "Операции с профилем браузера: сохранение, загрузка, профиль-папка, переназначение.":
            "Browser profile operations: conservation, loading, profile-folder, reassignment.",
    "Описание / комментарий...":            "Description / comment...",
    "Описание стратегии":                   "Description of the strategy",
    "Опишите что должен сделать AI в программе. {переменные}":
            "Describe what should be done AI in the program. {variables}",
    "Определить позицию вставки внутри блока: ('before', node) или ('after', node).":
            "Determine insertion position within block: ('before', node) or ('after', node).",
    "Определяет, используется ли темная тема.":
            "Defines, is dark theme used?.",
    "Оптимизация гиперпараметров ML моделей":
            "Hyperparameter Optimization ML models",
    "Оптимизация метрик":                   "Metric optimization",
    "Оригинал:":                            "Original:",
    "Основной цикл потока — выполняет workflow.":
            "Main thread loop — performs workflow.",
    "Оставшиеся попытки.":                  "Remaining attempts.",
    "Остановить все потоки проекта.":       "Stop all project threads.",
    "Остановить выполнение на всех вкладках.":
            "Stop execution on all tabs.",
    "Ответь в формате:":                    "Answer in the format:",
    "WINNER: <номер модели, 1-N>":          "WINNER: <model number, 1-N>",
    "REASON: <краткое обоснование>":        "REASON: <brief rationale>",
    "Затем воспроизведи только патчи победителя в формате [SEARCH_BLOCK]/[REPLACE_BLOCK].":
            "Then play only the winner's patches in the format [SEARCH_BLOCK]/[REPLACE_BLOCK].",
    "Откатить патч":                        "Roll back the patch",
    "Отключить флаги автоматизации Chrome": "Disable automation flags Chrome",
    "Открыть глобальную сводку всех инстансов из всех открытых проектов.":
            "Open a global summary of all instances from all open projects.",
    "Открыть диалог БД для редактирования существующей.":
            "Open the database dialog to edit an existing one.",
    "Открыть диалог выбора рабочей папки.": "Open the working folder selection dialog.",
    "Открыть диалог глобальных настроек.":  "Open global settings dialog.",
    "Открыть диалог запуска для каждого выделенного проекта.":
            "Open launch dialog for each selected project.",
    "Открыть диалог настроек проекта для редактирования.":
            "Open the project settings dialog for editing.",
    "Открыть окно сводки всех инстансов.":  "Open the summary window for all instances.",
    "Открыть при запуске. Поддерживает {переменные}":
            "Open on startup. Supports {variables}",
    "Открыть проект в редакторе по запросу из dashboard.":
            "Open the project in the editor upon request from dashboard.",
    "Открыть файл после сохранения":        "Open file after saving",
    "Открыть/показать окно менеджера проектов.":
            "Open/show project manager window.",
    "Отладка работает":                     "Debugging works",
    "Отложенное обновление рёбер (throttle).":
            "Lazy edge update (throttle).",
    "Отложенное скрытие окна браузера в трей.":
            "Delayed hiding of the browser window in the tray.",
    "Отмена запрошена...":                  "Cancellation requested...",
    "Отменено пользователем":               "Canceled by user",
    "Отметить что текущее состояние проверено.":
            "Mark that the current state is checked.",
    "Отправлять уведомления в Telegram":    "Send notifications to Telegram",
    "Охота на баги — только ошибки, никаких улучшений":
            "Hunting for bugs — only errors, no improvement",
    "Очистить все списки":                  "Clear all lists",
    "Очистить все списки проекта.":         "Clear all project lists.",
    "Очистить все таблицы":                 "Clear all tables",
    "Очистить все таблицы проекта.":        "Clear all project tables.",
    "Очистить системный лог при запуске":   "Clear system log on startup",
    "Очистить шаблон":                      "Clear template",
    "Очистка списков":                      "Clearing lists",
    "Очистка таблиц":                       "Cleaning tables",
    "Ошибка активации модели:":             "Model activation error:",
    "Ошибка консенсуса:":                   "Consensus error:",
    "Ошибка отката":                        "Rollback error",
    "Ошибка при загрузке несовместимого профиля":
            "Error loading incompatible profile",
    "Ошибка скриншота":                     "Screenshot error",
    "Ошибка создания файла:":               "Error creating file:",
    "ПЛАН ДЕЙСТВИЙ:":                       "ACTION PLAN:",
    "Панели интерфейса.":                   "Interface panels.",
    "Панель переменных не найдена.":        "Variables panel not found.",
    "Панель управления открытыми программами — аналог BrowserInstancePanel.":
            "Open Programs Control Panel — analogue BrowserInstancePanel.",
    "Папка для автосохранений.":            "Autosave folder.",
    "Папка для файла (пусто = рабочая папка проекта)":
            "File folder (empty = project working folder)",
    "Папка сохранения:":                    "Save folder:",
    "Параметры ML":                         "Options ML",
    "Параметры модели:":                    "Model parameters:",
    "Параметры поведения":                  "Behavior Options",
    "Парсинг индекса столбца: число, буква (A,B,C...) или имя колонки.":
            "Column index parsing: number, letter (A,B,C...) or column name.",
    "Патч итерации":                        "Patch iteration",
    "Патч откачен":                         "Patch rolled back",
    "Патчей применено: 0  |  Отказов: 0":   "Patches applied: 0  |  Bounces: 0",
    "Патчей:":                              "Patches:",
    "Патчить основной скрипт с учётом интерфейса валидатора; не менять сигнатуры функций/форматы вывода которые валидатор проверяет":
            "Patch the main script taking into account the validator interface; do not change function signatures/output formats that the validator checks",
    "Пауза между действиями (мс):":         "Pause between actions (ms):",
    "Пауза перед первым узлом":             "Pause before the first node",
    "Пауза перед скриншотом (мс):":         "Pause before screenshot (ms):",
    "Пауза после (мс):":                    "Pause after (ms):",
    "Первая строка — заголовок":            "First line — title",
    "Первое значение":                      "First value",
    "Первую строку":                        "First line",
    "Первые байты:":                        "First bytes:",
    "Первые значения:":                     "First values:",
    "Первые строки:":                       "First lines:",
    "Первый запуск:":                       "First launch:",
    "Первый раз:":                          "First time:",
    "Перевести все динамические label'ы сниппетов.":
            "Translate all dynamic label's snippets.",
    "Перед действием убедиться что браузер запущен и отвечает":
            "Before taking action, make sure that the browser is running and responding",
    "Перезагрузить страницу":               "Reload page",
    "Перезаписывать":                       "Overwrite",
    "Перезапуск...":                        "Restart...",
    "Переименовать":                        "Rename",
    "Переименовать список":                 "Rename list",
    "Переименовать таблицу":                "Rename table",
    "Переключение режима без анимации.":    "Switching mode without animation.",
    "Переменная (base64) →:":               "Variable (base64) →:",
    "Переменная HWND:":                     "Variable HWND:",
    "Переменная PID / HWND:":               "Variable PID / HWND:",
    "Переменная PID:":                      "Variable PID:",
    "Переменная base64 PNG — только для действия «Скриншот области»":
            "Variable base64 PNG — for action only «Screenshot of the area»",
    "Переменная для ID первого/единственного активного браузера":
            "Variable for ID first/the only active browser",
    "Переменная для base64 или пути к файлу":
            "Variable for base64 or file path",
    "Переменная для координат найденного шаблона":
            "Variable for the coordinates of the found template",
    "Переменная для результата. Для browser_ids → \"id1,id2\"; для all → JSON":
            "Result variable. For browser_ids → \"id1,id2\"; For all → JSON",
    "Переменная для числа открытых браузеров":
            "Variable for number of open browsers",
    "Переменная-список (Python list). Удобно для цикла Loop":
            "List variable (Python list). Convenient for looping Loop",
    "Переменная-флаг: \"true\" если найдено, \"false\" если нет":
            "Flag variable: \"true\" if found, \"false\" if not",
    "Переменные (через запятую):":          "Variables (separated by commas):",
    "Переменные из профиля, которых нет в проекте, будут созданы автоматически":
            "Variables from profile, which are not in the project, will be created automatically",
    "Переменные окружения установлены":     "Environment variables set",
    "Перемешать данные перед стартом":      "Shuffle the data before starting",
    "Переназначить прокси:":                "Reassign proxy:",
    "Переопределяем чтобы предотвратить появление пустой области при ресайзе":
            "Overridden to prevent the appearance of an empty area during resize",
    "Перестроить чипы списков/таблиц в inline-панели.":
            "Rebuild list chips/tables in inline-panels.",
    "Перетащить в X:":                      "Drag to X:",
    "Перетащить в Y:":                      "Drag to Y:",
    "Перехватчик действий браузера для режима записи.":
            "Browser Interceptor for Recording Mode.",
    "    Подключается к BrowserInstance и слушает события JS.":
            "    Connects to BrowserInstance and listens to events JS.",
    "Писать лог в файл":                    "Write log to file",
    "Плохой подход для":                    "Bad approach for",
    "По одному на строку. Пример:":         "One per line. Example:",
    "По таймауту (секунды)":                "By timeout (seconds)",
    "Поверх всех окон":                     "On top of all windows",
    "Повтор вставки блока (вручную)":       "Repeat block insertion (manually)",
    "Повторов при ошибке:":                 "Retry on error:",
    "Повторять":                            "Repeat",
    "Поддерживает {timestamp}, {переменные}. Расширение .png добавится автоматически":
            "Supports {timestamp}, {variables}. Extension .png will be added automatically",
    "Поддерживает {переменную}":            "Supports {variable}",
    "Поддерживает {переменные}. Пример: {login}@gmail.com":
            "Supports {variables}. Example: {login}@gmail.com",
    "Подключиться ко всем активным инстансам браузера и начать запись.":
            "Connect to all active browser instances and start recording.",
    "Подменю для кнопки 'Все проекты'.":    "Submenu for the button 'All projects'.",
    "Подождать N секунд пока окно появится":
            "Wait N seconds until the window appears",
    "Подробности в панели Логи.":           "Details in the Logs panel.",
    "Подставить {переменные} из context в строку.":
            "Substitute {variables} from context to line.",
    "Подставляет {project_dir} и прочие переменные.":
            "Substitutes {project_dir} and other variables.",
    "Подсчитать количество нодов в цепочке (рекурсивно).":
            "Count the number of nodes in the chain (recursively).",
    "Позиция добавления:":                  "Add position:",
    "Поиск:":                               "Search:",
    "Показать меню выбора источника при добавлении проекта.":
            "Show source selection menu when adding a project.",
    "Показать/скрыть патчи":                "Show/hide patches",
    "Показать/скрыть поле инструкции в зависимости от режима старта.":
            "Show/hide the instruction field depending on the start mode.",
    "Показывать прогресс-бар":              "Show progress bar",
    "Пол:":                                 "Floor:",
    "Полное обновление таблицы.":           "Full table update.",
    "Полный ретраслят ВСЕГО окна конструктора.":
            "Full relay of the ENTIRE designer window.",
    "Получает системную информацию проекта: ID открытых браузеров, имена списков, таблиц, переменных. Записывает данные в указанные переменные.":
            "Retrieves project system information: ID open browsers, list names, tables, variables. Writes data to the specified variables.",
    "Получить ID выделенных проектов.":     "Get ID allocated projects.",
    "Получить project_root текущего активного таба.":
            "Get project_root current active tab.",
    "Получить все ноды в цепочке начиная с корня (все дети рекурсивно).":
            "Get all nodes in the chain starting from the root (all children recursively).",
    "Получить все элементы цепочки (рекурсивно, все ветки).":
            "Get all elements of a chain (recursively, all branches).",
    "Получить значение глобальной переменной.":
            "Get the value of a global variable.",
    "Получить корень цепочки для этого блока.":
            "Get the root of the chain for this block.",
    "Получить последнюю ноду в линейной цепочке attached_children начиная с self.":
            "Get the last node in a linear chain attached_children starting from self.",
    "Получить реестр открытых программ из активного runtime или сохранённого состояния.":
            "Get the registry of open programs from the active one runtime or saved state.",
    "Получить скриншот как base64 PNG (потокобезопасно).":
            "Get screenshot how base64 PNG (thread safe).",
    "Получить строки списка по имени; если load_mode=always — перечитать файл.":
            "Get list rows by name; If load_mode=always — reread the file.",
    "Получить строки таблицы по имени; если load_mode=always — перечитать файл.":
            "Get table rows by name; If load_mode=always — reread the file.",
    "Получить текущий активный ProjectTab.":
            "Get current active ProjectTab.",
    "Пользователь":                         "User",
    "Пользователь запросил":                "User requested",
    "Пользователь:":                        "User:",
    "Попробуй запустить organize.py заново:":
            "Try to run organize.py again:",
    "Попытаться сделать скриншот если не заняты.":
            "Try to take a screenshot if you are not busy.",
    "Попытаться скрыть окно в трей с повторными попытками (ожидаем появления окна).":
            "Try to hide the tray window with repeated attempts (waiting for the window to appear).",
    "Попытки":                              "Attempts",
    "Порт:":                                "Port:",
    "После N ошибок подряд":                "After N mistakes in a row",
    "После N успехов":                      "After N success",
    "После скриншота: зажмите мышь на картинке и выделите нужную область →":
            "After the screenshot: hold the mouse on the picture and select the desired area →",
    "Последний патч нарушил контракт/интерфейс, ожидаемый валидатором":
            "The latest patch broke the contract/interface, expected by validator",
    "Последний патч привёл к":              "The latest patch led to",
    "Последний:":                           "Last:",
    "Последнюю строку":                     "Last line",
    "Последоват.":                          "Sequential",
    "Последовательно: потоки ждут друг друга.":
            "Consistently: streams are waiting for each other.",
    "Параллельно: все потоки работают одновременно.":
            "Parallel: all threads run simultaneously.",
    "С семафором: ресурсоёмкий сниппет ограничен лимитом.":
            "With semaphore: resource-intensive snippet is limited by a limit.",
    "Построчно":                            "Line by line",
    "Потоки:":                              "Streams:",
    "Потоки: 0":                            "Streams: 0",
    "Потоков:":                             "Streams:",
    "Правая половина":                      "Right half",
    "Правила, которые красятся поверх основного цвета (например, ":
            "Rules, which are painted over the base color (For example, ",
    " в строках)":                          " in lines)",
    "Предыдущий анализ AI:":                "Previous analysis AI:",
    "При загрузке: если файл не найден — создать новый профиль":
            "When loading: if the file is not found — create a new profile",
    "При закрытии сохраняем состояние.":    "When closing, save the state.",
    "При ошибке:":                          "If there is an error:",
    "При первой ошибке":                    "At the first mistake",
    "При старте проверить наличие автосохранений и предложить восстановление.":
            "At startup, check for autosaves and suggest recovery.",
    "При чистом выходе удаляем файлы автосохранения.":
            "On a clean exit, delete autosave files.",
    "Применить настройки из UI к ProjectEntry.":
            "Apply settings from UI To ProjectEntry.",
    "Применить настройки немедленно (браузеры, семафоры).":
            "Apply settings immediately (browsers, semaphores).",
    "Применить текущий фильтр.":            "Apply current filter.",
    "Применить текущую тему динамически.":  "Apply current theme dynamically.",
    "Применить тёмную тему ко всем диалогам/окнам.":
            "Apply dark theme to all dialogs/windows.",
    "Применяй эту стратегию при формировании ответа и патчей.":
            "Apply this strategy when creating your response and patches.",
    "Пример: 1024x768. Пусто = не менять":  "Example: 1024x768. Empty = don't change",
    "Пример: 1920x1080. Пусто = не менять": "Example: 1920x1080. Empty = don't change",
    "Пример: 55.7558,37.6176. Пусто = не менять":
            "Example: 55.7558,37.6176. Empty = don't change",
    "Пример: Europe/Moscow. Пусто = не менять":
            "Example: Europe/Moscow. Empty = don't change",
    "Пример: ctx.get(\"count\", 0) > 5 and ctx.get(\"status\") == \"ok\"":
            "Example: ctx.get(\"count\", 0) > 5 and ctx.get(\"status\") == \"ok\"",
    "Пример: ctx.get(\"done\") == True  или  iteration > 5":
            "Example: ctx.get(\"done\") == True  or  iteration > 5",
    "Пример: ru-RU,ru;q=0.9. Пусто = не менять":
            "Example: ru-RU,ru;q=0.9. Empty = don't change",
    "Принудительная остановка после N шагов":
            "Forced stop after N steps",
    "Принудительно сохранить все виджеты сниппета в node.snippet_config.":
            "Force save all snippet widgets to node.snippet_config.",
    "        Каждый тип сниппета хранит свои поля ОТДЕЛЬНО — нет пересечений между типами.":
            "        Each snippet type stores its fields SEPARATELY — no overlap between types.",
    "Приоритет:":                           "Priority:",
    "Приостановить проект.":                "Pause the project.",
    "Причина:":                             "Cause:",
    "Проанализируй этот код:":              "Analyze this code:",
    "Проанализируй этот файл:":             "Parse this file:",
    "Пробовали решить":                     "Tried to solve",
    "Проверить завершены ли все попытки.":  "Check if all attempts are completed.",
    "Проверить условие остановки.":         "Check stopping condition.",
    "Проверить что браузер активен":        "Check that the browser is active",
    "Проверить что координаты валидны (не нулевые и не слишком близко к краю).":
            "Check that the coordinates are valid (not zero and not too close to the edge).",
    "Проверить что координаты уже встречались (с допуском).":
            "Check that the coordinates have already been encountered (with permission).",
    "Проверить, является ли potential_ancestor предком этого блока.":
            "Check, is potential_ancestor ancestor of this block.",
    "Проверяет расписание каждые 10 секунд.":
            "Checks the schedule every 10 seconds.",
    "Проверяет, не является ли potential_ancestor_id предком node_id.":
            "Checks, isn't it potential_ancestor_id ancestor node_id.",
    "Прогресс":                             "Progress",
    "Прогресс в процентах.":                "Progress in percentage.",
    "Проект '":                             "Project '",
    "Проект «":                             "Project «",
    "Проект выполняется!":                  "The project is in progress!",
    "Проект запущен. Контекст:":            "The project has been launched. Context:",
    "Проект просканирован:":                "Project scanned:",
    "Проект создан:":                       "Project created:",
    "Проектная таблица '":                  "Design table '",
    "Проектный список '":                   "Project list '",
    "Пропустить":                           "Skip",
    "Простой расчёт следующего запуска.":   "Easy next run calculation.",
    "Профиль другого движка браузера вызовет ошибку вместо предупреждения":
            "A different browser engine profile will cause an error instead of a warning",
    "Псевдоним для совместимости с вызовами из BrowserManager.":
            "Alias \u200b\u200bfor compatibility with calls from BrowserManager.",
    "Пул соединений:":                      "Connection pool:",
    "Пусто = временный профиль. Папка с профилем браузера":
            "Empty = temporary profile. Browser profile folder",
    "Пусто = всё окно. Формат: 100,200,500,300":
            "Empty = whole window. Format: 100,200,500,300",
    "Пусто = из глобальных настроек. Пример: gpt-4o, claude-3-5-sonnet":
            "Empty = from global settings. Example: gpt-4o, claude-3-5-sonnet",
    "Пусто = не менять. Поддерживает {переменные}":
            "Empty = don't change. Supports {variables}",
    "Пусто = не эмулировать. Пример: 55.7558,37.6176":
            "Empty = do not emulate. Example: 55.7558,37.6176",
    "Пусто = первый активный. Или {browser_instance_id}":
            "Empty = first active. Or {browser_instance_id}",
    "Пусто = системная. Пример: Europe/Moscow, America/New_York":
            "Empty = systemic. Example: Europe/Moscow, America/New_York",
    "Пусто = стандартный. Поддерживает {переменные}":
            "Empty = standard. Supports {variables}",
    "Пустой шаблон":                        "Blank template",
    "Путь для режима \"Как файл\"":         "Path for mode \"As file\"",
    "Путь для сохранения результатов. Поддерживает {переменные}":
            "Path to save results. Supports {variables}",
    "Путь для сохранения. {переменные}, {timestamp}":
            "Path to save. {variables}, {timestamp}",
    "Путь к CSV/TSV файлу (поддерживает {переменные})":
            "Path to CSV/TSV file (supports {variables})",
    "Путь к файлу (поддерживает {переменные})":
            "File path (supports {variables})",
    "Путь к файлу / папке:":                "File path / folder:",
    "Путь к файлу данных / списку аккаунтов":
            "Data file path / list of accounts",
    "Путь к файлу или {переменная}:":       "File path or {variable}:",
    "Путь к файлу лога:":                   "Path to the log file:",
    "РЕДАКТОР СТРАТЕГИИ":                   "STRATEGY EDITOR",
    "РЕЖИМ: НОВЫЙ ПРОЕКТ":                  "MODE: NEW PROJECT",
    "- Давай полные реализации":            "- Let's have full realizations",
    "- Включай все необходимые импорты":    "- Include all necessary imports",
    "- Пиши комментарии и docstrings":      "- Write comments and docstrings",
    "- Объясняй архитектурные решения":     "- Explain architectural solutions",
    "- Можно давать полные файлы целиком":  "- You can provide complete files in their entirety",
    "СОЗДАНИЕ ФАЙЛА С НУЛЯ:":               "CREATE A FILE FROM SCRATCH:",
    "Когда файла ещё нет — SEARCH_BLOCK должен быть ПУСТЫМ:":
            "When the file doesn't exist yet — SEARCH_BLOCK must be EMPTY:",
    "<полный код файла>":                   "<full file code>",
    "Перед патчем обязательно укажи имя файла:":
            "Be sure to specify the file name before patching:",
    "\"Создаю `main.py`:\" или \"Файл `app.js`:\"":
            "\"I create `main.py`:\" or \"File `app.js`:\"",
    "НИКОГДА не пиши в SEARCH_BLOCK текст типа \"## РЕЛЕВАНТНЫЙ КОД\" или \"## КОД ПРОЕКТА\".":
            "NEVER write to SEARCH_BLOCK text type \"## RELEVANT CODE\" or \"## PROJECT CODE\".",
    "РЕЖИМ: РАБОТА С СУЩЕСТВУЮЩИМ ПРОЕКТОМ":
            "MODE: WORKING WITH AN EXISTING PROJECT",
    "СТРОГОЕ ПРАВИЛО: Давай ТОЛЬКО патчи в формате [SEARCH_BLOCK]/[REPLACE_BLOCK].":
            "STRICT RULE: Give ONLY patches in the format [SEARCH_BLOCK]/[REPLACE_BLOCK].",
    "ЗАПРЕЩЕНО:":                           "FORBIDDEN:",
    "  ✗ Переписывать весь файл":           "  ✗ Overwrite the entire file",
    "  ✗ Давать полный код функции если нужно изменить 2 строки":
            "  ✗ Give the full function code if you need to change it 2 lines",
    "  ✗ Добавлять код без точного указания места":
            "  ✗ Add code without specifying the exact location",
    "  ✗ Давать \"примерный\" код — только точные замены":
            "  ✗ Giving \"exemplary\" code — only exact replacements",
    "ОБЯЗАТЕЛЬНО:":                         "NECESSARILY:",
    "  ✓ [SEARCH_BLOCK] должен ТОЧНО совпадать с кодом в файле":
            "  ✓ [SEARCH_BLOCK] must EXACTLY match the code in the file",
    "  ✓ Минимальные изменения — только что нужно поменять":
            "  ✓ Minimal changes — just need to change",
    "  ✓ Объяснить ПОЧЕМУ это изменение (1-2 предложения)":
            "  ✓ Explain WHY this change (1-2 offers)",
    "  ✓ Указать файл если изменения в нескольких местах":
            "  ✓ Specify the file if changes are in several places",
    "РЕЖИМ: ТОЛЬКО ПАТЧИ [SEARCH/REPLACE]": "MODE: PATCHES ONLY [SEARCH/REPLACE]",
    "РЕЖИМ: ТОЛЬКО ПАТЧИ [SEARCH/REPLACE] — не переписывай файл целиком":
            "MODE: PATCHES ONLY [SEARCH/REPLACE] — do not rewrite the entire file",
    "Рабочая директория программы":         "Program working directory",
    "Развернуть браузеры":                  "Expand browsers",
    "Развернуть панель":                    "Expand panel",
    "Размер окна (WxH):":                   "Window size (WxH):",
    "Размер окна 0 (HWND=":                 "Window size 0 (HWND=",
    "Размер пула:":                         "Pool size:",
    "Разрешение экрана (WxH):":             "Screen resolution (WxH):",
    "Рандомизировать Audio fingerprint":    "Randomize Audio fingerprint",
    "Рандомизировать Canvas fingerprint":   "Randomize Canvas fingerprint",
    "Рандомизировать WebGL fingerprint":    "Randomize WebGL fingerprint",
    "Рандомизировать список шрифтов":       "Randomize the font list",
    "Редактор пользовательских стратегий":  "Custom Strategy Editor",
    "Режим Offline (нет сети)":             "Mode Offline (no network)",
    "Режим загрузки:":                      "Download mode:",
    "Режим записи результатов:":            "Results recording mode:",
    "Режим записи:":                        "Recording Mode:",
    "Режим окна:":                          "Window mode:",
    "Режим потоков:":                       "Stream mode:",
    "Режим старта:":                        "Start mode:",
    "Результат (x,y) →:":                   "Result (x,y) →:",
    "Рекурсивная проверка вниз по цепочке.":
            "Recursive check down the chain.",
    "Рекурсивно поднимаем Z-ордер ноды и всех её детей":
            "Raise recursively Z-order of a node and all its children",
    "Рефакторинг":                          "Refactoring",
    "Решение:":                             "Solution:",
    "Рисование стартового узла — круг с градиентом.":
            "Drawing a Start Node — circle with gradient.",
    "С семафором (bottleneck)":             "With semaphore (bottleneck)",
    "СТАЛО (REPLACE):":                     "BECAME (REPLACE):",
    "СТАРТ":                                "START",
    "СТРАТЕГИЯ:":                           "STRATEGY:",
    "СТРАТЕГИЯ: АГРЕССИВНАЯ":               "STRATEGY: AGGRESSIVE",
    "- Максимальные улучшения для достижения цели":
            "- Maximum improvements to achieve the goal",
    "- Можно рефакторить алгоритмическую логику":
            "- Algorithmic logic can be refactored",
    "- Экспериментируй с параметрами, порогами, архитектурой":
            "- Experiment with parameters, rapids, architecture",
    "- Несколько патчей за итерацию — норма":
            "- Several patches per iteration — norm",
    "- Цель важнее осторожности":           "- Purpose over caution",
    "СТРАТЕГИЯ: АНСАМБЛЬ":                  "STRATEGY: ENSEMBLE",
    "Предложи ТРИ варианта патча:":         "Offer THREE patch options:",
    "ВАРИАНТ А: [консервативный]":          "OPTION A: [conservative]",
    "ВАРИАНТ Б: [умеренный]":               "OPTION B: [moderate]",
    "ВАРИАНТ В: [агрессивный]":             "OPTION B: [aggressive]",
    "Затем выбери ОДИН наиболее обоснованный и оформи его как [SEARCH_BLOCK]/[REPLACE_BLOCK].":
            "Then choose the ONE most reasonable and format it as [SEARCH_BLOCK]/[REPLACE_BLOCK].",
    "Объясни почему выбрал именно его.":    "Explain why you chose him.",
    "СТРАТЕГИЯ: БЕЗОПАСНЫЙ ХРАПОВИК":       "STRATEGY: SAFE RATCHET",
    "- Сравни метрики ДО и ПОСЛЕ предыдущего патча":
            "- Compare metrics BEFORE and AFTER the previous patch",
    "- Если метрики улучшились — продолжай в том же направлении":
            "- If metrics have improved — continue in the same direction",
    "- Если метрики ухудшились — предложи откат + иной подход":
            "- If metrics get worse — offer a kickback + different approach",
    "- Никогда не допускай регрессию результатов":
            "- Never allow results to regress",
    "СТРАТЕГИЯ: ГИПОТЕЗА":                  "STRATEGY: HYPOTHESIS",
    "Структурируй ответ так:":              "Structure your answer like this:",
    "1. ГИПОТЕЗА: что именно и почему не работает":
            "1. HYPOTHESIS: what exactly doesn't work and why",
    "2. ПРЕДСКАЗАНИЕ: что изменится после патча":
            "2. PREDICTION: what will change after the patch",
    "3. ПАТЧ: [SEARCH_BLOCK]/[REPLACE_BLOCK]":
            "3. PATCH: [SEARCH_BLOCK]/[REPLACE_BLOCK]",
    "4. ПРОВЕРКА: как валидировать результат":
            "4. EXAMINATION: how to validate the result",
    "- Следующую итерацию начни с оценки правильности гипотезы":
            "- Start the next iteration by assessing the correctness of the hypothesis",
    "СТРАТЕГИЯ: ИССЛЕДОВАТЕЛЬ":             "STRATEGY: RESEARCHER",
    "- Каждую итерацию пробуй принципиально ДРУГОЙ подход":
            "- Every iteration, try a fundamentally DIFFERENT approach.",
    "- Смотри на предыдущие патчи — НЕ повторяй их":
            "- Look at previous patches — DO NOT repeat them",
    "- Ищи неочевидные точки улучшения":    "- Look for unobvious points of improvement",
    "- Документируй в анализе какую гипотезу проверяешь":
            "- Document in your analysis what hypothesis you are testing.",
    "СТРАТЕГИЯ: КОНСЕРВАТИВНАЯ":            "STRATEGY: CONSERVATIVE",
    "- Исправляй ТОЛЬКО явные ошибки из лога":
            "- Correct ONLY obvious errors from the log",
    "- Не меняй логику без крайней необходимости":
            "- Don't change logic unless absolutely necessary.",
    "- Патч должен быть минимальным — 1-3 строки максимум":
            "- The patch should be minimal — 1-3 lines maximum",
    "- Если ошибок нет — напиши GOAL_ACHIEVED":
            "- If there are no errors — write GOAL_ACHIEVED",
    "СТРАТЕГИЯ: МОЯ":                       "STRATEGY: MY",
    "- Сначала анализируй ошибки в логе":   "- First, analyze the errors in the log",
    "- Затем проверяй метрики":             "- Then check the metrics",
    "- Делай минимальные изменения":        "- Make minimal changes",
    "- Объясняй каждый патч":               "- Explain every patch",
    "СТРАТЕГИЯ: ОПТИМИЗАЦИЯ ГИПЕРПАРАМЕТРОВ":
            "STRATEGY: HYPERPARAMETER OPTIMIZATION",
    "- Анализируй метрики обучения в логе": "- Analyze training metrics in the log",
    "- Определи признаки переобучения (train >> val) или недообучения (train ≈ val, оба низкие)":
            "- Identify signs of overtraining (train >> val) or undertraining (train ≈ val, both low)",
    "- При переобучении: уменьши learning rate, добавь регуляризацию, уменьши сложность":
            "- When retraining: reduce learning rate, add regularization, reduce сложность",
    "- При недообучении: увеличь capacity, lr, epochs":
            "- With undertraining: increase capacity, lr, epochs",
    "- Меняй только числовые параметры — не трогай архитектуру":
            "- Change only numeric parameters — don't touch the architecture",
    "- Документируй почему выбрал именно эти значения":
            "- Document why you chose these values",
    "СТРАТЕГИЯ: ОПТИМИЗАЦИЯ МЕТРИК":        "STRATEGY: METRICS OPTIMIZATION",
    "- Извлеки все числовые метрики из лога":
            "- Extract all numerical metrics from the log",
    "- Определи какая метрика отстаёт от цели":
            "- Determine which metric is lagging behind the goal",
    "- Внеси изменение которое ПРЯМО влияет на эту метрику":
            "- Make a change that DIRECTLY affects this metric.",
    "- В анализе укажи: текущее значение → ожидаемое после патча":
            "- Indicate in the analysis: current value → expected after the patch",
    "- Не трогай код не связанный с метриками":
            "- Don't touch code not related to metrics",
    "СТРАТЕГИЯ: ОХОТНИК НА БАГИ":           "STRATEGY: BUG HUNTER",
    "- Найди ВСЕ ошибки и исключения в логе":
            "- Find ALL errors and exceptions in the log",
    "- Для каждой ошибки: опиши root cause (одно предложение)":
            "- For every mistake: describe root cause (one sentence)",
    "- Исправляй ТОЛЬКО ошибки — не улучшай ничего":
            "- Correct ONLY mistakes — don't improve anything",
    "- Если ошибок нет — напиши GOAL_ACHIEVED":
            "- If there are no errors — write GOAL_ACHIEVED",
    "- Каждый патч должен исправлять ровно одну ошибку":
            "- Each patch must fix exactly one bug",
    "СТРАТЕГИЯ: РЕФАКТОРИНГ":               "STRATEGY: REFACTORING",
    "- Улучшай структуру, читаемость и надёжность кода":
            "- Improve the structure, readability and reliability of code",
    "- Извлекай повторяющийся код в функции":
            "- Extract duplicate code into functions",
    "- Добавляй обработку исключений где её нет":
            "- Add exception handling where there is none",
    "- Улучшай имена переменных и функций": "- Improve variable and function names",
    "- НЕ меняй алгоритмическую логику":    "- DO NOT change the algorithmic logic",
    "СТРАТЕГИЯ: СБАЛАНСИРОВАННАЯ":          "STRATEGY: BALANCED",
    "- Исправляй ошибки + делай умеренные улучшения":
            "- Correct mistakes + make moderate improvements",
    "- Можно менять алгоритмические параметры для достижения цели":
            "- You can change algorithmic parameters to achieve the goal",
    "- Ориентируйся на метрики из лога":    "- Focus on metrics from the log",
    "- Каждый патч должен иметь чёткое обоснование":
            "- Each patch must have a clear rationale",
    "СТРАТЕГИЯ: ЭКСПЛУАТАЦИЯ":              "STRATEGY: OPERATION",
    "- Смотри на предыдущие успешные патчи":
            "- Look at previous successful patches",
    "- Углубляй и усиливай то, что уже дало улучшение":
            "- Deepen and strengthen it, which has already given an improvement",
    "- Если патч X улучшил метрику — попробуй X*2 или аналогичный подход":
            "- If the patch X improved the metric — try X*2 or similar approach",
    "- Игнорируй подходы которые не дали результата":
            "- Ignore approaches that don't work",
    "СУЩЕСТВУЮЩИМ ПРОЕКТОМ":                "EXISTING PROJECT",
    "Сбросить глобальные переменные к дефолту":
            "Reset global variables to default",
    "Сбросить глобальные переменные к значениям по умолчанию.":
            "Reset global variables to default values.",
    "Сбросить переменные к значениям по умолчанию":
            "Reset variables to default values",
    "Свернуть в трей":                      "Minimize to tray",
    "Свернуть панель":                      "Collapse panel",
    "Сводка всех запущенных браузеров во всех открытых проектах":
            "Summary of all running browsers in all open projects",
    "Сделать скриншот окна программы и выделить область для клика":
            "Take a screenshot of the program window and highlight the area to click",
    "Сделать скриншот окна программы через HWND.":
            "Take a screenshot of the program window using HWND.",
    "            Возвращает (png_bytes, win_left, win_top) — левый верхний угол окна":
            "            Returns (png_bytes, win_left, win_top) — upper left corner of the window",
    "            в экранных координатах нужен для последующей конвертации шаблонных":
            "            in screen coordinates is needed for subsequent conversion of template",
    "            координат → клиентских координат.":
            "            coordinates → клиентских coordinates.",
    "Сделать скриншот текущего браузера и выделить область для клика":
            "Take a screenshot of the current browser and highlight the area for clicking",
    "Секция палитры: Автоматизация программ.":
            "Palette section: Program automation.",
    "Селектор элемента:":                   "Element selector:",
    "Семафор":                              "Semaphore",
    "Сервис:":                              "Service:",
    "Сигналы от менеджера проектов для UI.":
            "Signals from the project manager for UI.",
    "Сигналы от одного потока выполнения.": "Signals from one thread of execution.",
    "Синглтон глобальных настроек выполнения.":
            "Global execution settings singleton.",
    "Синглтон — центральный диспетчер всех проектов.":
            "Singleton — central manager of all projects.",
    "    Управляет:":                       "    Manages:",
    "    - Реестром проектов (ProjectEntry)":
            "    - Project Registry (ProjectEntry)",
    "    - Глобальным лимитом потоков":     "    - Global stream limit",
    "    - Семафорами моделей (из GlobalSettings)":
            "    - Semaphores models (from GlobalSettings)",
    "    - Семафорами узких мест (bottleneck snippets)":
            "    - Semaphores bottlenecks (bottleneck snippets)",
    "    - Расписанием":                    "    - Schedule",
    "    - Статистикой":                    "    - Statistics",
    "Синтаксис:":                           "Syntax:",
    "Синтаксическая ошибка после патча":    "Syntax error after patch",
    "Синхронизировать UI элементы под конкретный таб.":
            "Synchronize UI elements for a specific tab.",
    "Синхронизировать настройку закрытия браузера в workflow текущего проекта.":
            "Sync browser close setting in workflow current project.",
    "Синхронизировать переменную контекста с project_variables.":
            "Synchronize context variable with project_variables.",
    "Синхронизировать список из контекста в metadata workflow для отображения в UI.":
            "Synchronize list from context to metadata workflow to display in UI.",
    "Синхронизировать таблицу из контекста в metadata workflow для отображения в UI.":
            "Synchronize table from context to metadata workflow to display in UI.",
    "Системный промпт стратегии":           "System strategy prompt",
    "Скачай файл organize.py из проекта.":  "Download the file organize.py from the project.",
    "Сколько потоков могут одновременно выполнять":
            "How many threads can execute simultaneously",
    "этот ресурсоёмкий сниппет. Остальные ждут.":
            "this resource-intensive snippet. The others are waiting.",
    "Сколько потоков одновременно выполняют этот проект.":
            "How many threads are running this project simultaneously?.",
    "Каждый поток — изолированный экземпляр workflow.":
            "Every thread — isolated copy workflow.",
    "Сколько раз выполнить проект.":        "How many times to complete the project.",
    "-1 = бесконечно (до ручной остановки).":
            "-1 = endlessly (to manual stop).",
    "Скриншот готов — обновляем картинку.": "Screenshot ready — update the picture.",
    "Скриншот области →:":                  "Screenshot of the area →:",
    "Скрипт: ошибка (":                     "Script: error (",
    "Скрыть/показать окно браузера (thumbnail остается на месте).":
            "Hide/show browser window (thumbnail stays in place).",
    "Следующие проекты содержат несохранённые изменения:":
            "The following projects contain unsaved changes:",
    "Следующий запуск":                     "Next launch",
    "Случайное разрешение экрана":          "Random screen resolution",
    "Случайную строку":                     "Random string",
    "Случайный User-Agent":                 "Random User-Agent",
    "Случайный User-Agent при каждом старте":
            "Random User-Agent at every start",
    "Смещение X от центра (px):":           "Bias X from the center (px):",
    "Смещение X от центра:":                "Bias X from the center:",
    "Смещение Y от центра (px):":           "Bias Y from the center (px):",
    "Смещение Y от центра:":                "Bias Y from the center:",
    "Сначала запустите браузер (BROWSER_LAUNCH).":
            "First launch your browser (BROWSER_LAUNCH).",
    "Сниппет BROWSER_CLICK_IMAGE:":         "Snippet BROWSER_CLICK_IMAGE:",
    "    ищет шаблон (base64 PNG) на скриншоте браузера и кликает по центру совпадения.":
            "    looking for a pattern (base64 PNG) on the browser screenshot and clicks on the center of the match.",
    "    Использует OpenCV если доступен, иначе — PIL.":
            "    Uses OpenCV if available, otherwise — PIL.",
    "Сниппет BROWSER_SCREENSHOT — делает скриншот страницы и сохраняет":
            "Snippet BROWSER_SCREENSHOT — takes a screenshot of the page and saves it",
    "    base64-строку в переменную контекста.":
            "    base64-string to context variable.",
    "Содержимое:":                          "Content:",
    "Содержит текст (в столбце)":           "Contains text (in column)",
    "Создать undo для вставки блока.":      "Create undo to insert a block.",
    "Создать и запустить один executor.":   "Create and run one executor.",
    "Создать из шаблона":                   "Create from template",
    "Создать отсутствующие переменные при загрузке":
            "Create missing variables on boot",
    "Создать папку/файл если не существует":
            "Create a folder/file if does not exist",
    "Создать ячейку в сетке и опционально встроить окно браузера.":
            "Create a cell in a grid and optionally embed a browser window.",
    "Сосредоточься на:":                    "Focus on:",
    "- Назначение файла (что делает)":      "- File purpose (what does it do)",
    "- Публичные классы/функции и их сигнатуры":
            "- Public classes/functions and their signatures",
    "- Ключевые зависимости/импорты":       "- Key Dependencies/imports",
    "- Важные паттерны или проблемы":       "- Important patterns or issues",
    "Не более 150 слов. Только технические факты, без деталей реализации.":
            "No more 150 words. Only technical facts, no implementation details.",
    "КОД:":                                 "CODE:",
    "Сохранение, загрузка, переназначение полей и обновление профиля браузера. Профиль хранит: личность (имя, e-mail, дата рождения), браузерный отпечаток, куки, прокси, User-Agent, разрешение, шрифты, временную зону, геолокацию и переменные.":
            "Saving, loading, reassigning fields and updating the browser profile. Profile stores: personality (Name, e-mail, date of birth), browser fingerprint, cookies, proxy, User-Agent, permission, fonts, time zone, geolocation and variables.",
    "Сохранить PID процесса в переменную":  "Save PID process to variable",
    "Сохранить handle окна в переменную":   "Save handle windows to variable",
    "Сохранить x,y найденной точки. {переменная}":
            "Save x,y found point. {variable}",
    "Сохранить все перед закрытием?":       "Save everything before closing?",
    "Сохранить как:":                       "Save as:",
    "Сохранить проект перед стартом":       "Save the project before starting",
    "Сохранить результат (текст/статус). {переменная}":
            "Save result (text/status). {variable}",
    "Сохранить состояние менеджера на диск.":
            "Save manager state to disk.",
    "Сохранить состояние менеджера.":       "Save Manager State.",
    "Сохранить:":                           "Save:",
    "Сохранять cookies между запусками":    "Save cookies between launches",
    "Сохранять переменные вместе с профилем":
            "Save variables with profile",
    "Сохранять прокси вместе с профилем":   "Save proxy with profile",
    "Список результатов →:":                "List of results →:",
    "Сравнивать скриншоты до/после каждого действия":
            "Compare screenshots before/after every action",
    "Стартовый URL:":                       "Starting URL:",
    "Стартовый скрипт:":                    "Start script:",
    "Статистика:":                          "Statistics:",
    "Статус":                               "Status",
    "Статус:":                              "Status:",
    "Столбец (номер или имя):":             "Column (number or name):",
    "Столбцы:":                             "Columns:",
    "Строго следуй этим инструкциям при формировании ответа.":
            "Follow these instructions strictly when generating your answer..",
    "Строго следуй этим инструкциям.":      "Follow these instructions strictly.",
    "Строк до:":                            "Lines up to:",
    "Строк после:":                         "Lines after:",
    "Строки списка (каждая строка — отдельный элемент)":
            "List lines (each line — separate element)",
    "Строю контекст для AI...":             "I'm building a context for AI...",
    "Строю промпт...":                      "I'm building a prompt...",
    "ТБ":                                   "TB",
    "Таймаут bottleneck":                   "Time-out bottleneck",
    "Таймаут выполнения workflow (30 мин)": "Execution timeout workflow (30 min)",
    "Таймаут ожидания (сек):":              "Wait timeout (sec):",
    "Таймаут ожидания bottleneck (300с)":   "Wait timeout bottleneck (300With)",
    "Таймаут ожидания глобального слота (300с)":
            "Global slot timeout (300With)",
    "Таймаут очереди":                      "Queue timeout",
    "Таймаут проекта (сек):":               "Project timeout (sec):",
    "Таймзона":                             "Timezone",
    "Таймзона:":                            "Timezone:",
    "Тебе предоставлены ответы нескольких AI-моделей на одну задачу патчинга кода.":
            "You have been given answers from several AI-models for one code patching task.",
    "Текст / клавиши:":                     "Text / keys:",
    "Текст для ввода или комбинация (ctrl+c). {переменные}":
            "Input text or combination (ctrl+c). {variables}",
    "Текущие:":                             "Current:",
    "Телефон:":                             "Telephone:",
    "Тип СУБД:":                            "DBMS type:",
    "Типы:":                                "Types:",
    "Токенов примерно:   ~":                "Approximately tokens:   ~",
    "Только видимая область":               "Visible area only",
    "Только для режима \"Перезапустить\"":  "Only for mode \"Restart\"",
    "Только одна модель ответила успешно — без голосования":
            "Only one model responded successfully — without voting",
    "Только та же ОС":                      "Just the same OS",
    "Только тот же движок браузера":        "Just the same browser engine",
    "Только тот же язык":                   "Just the same language",
    "Точечное обновление одной строки.":    "Single row spot update.",
    "Точность совпадения %:":               "Match accuracy %:",
    "Требовать анализ перед патчами (3-5 предложений)":
            "Require analysis before patches (3-5 proposals)",
    "Требуется pywin32 и Pillow:":          "Required pywin32 And Pillow:",
    "Триггерный сниппет:":                  "Trigger snippet:",
    "Ты — AI Code Sherlock, эксперт-разработчик и аналитик кода.":
            "You — AI Code Sherlock, expert developer and code analyst.",
    "Специализируешься на точечных хирургических изменениях кода и поиске причин ошибок.":
            "You specialize in targeted surgical code changes and finding the causes of errors.",
    "ФОРМАТ ОТВЕТА ДЛЯ ИЗМЕНЕНИЙ КОДА:":    "RESPONSE FORMAT FOR CODE CHANGES:",
    "Всегда используй ТОЧНО такой формат:": "Always use EXACTLY this format:",
    "<точный код для поиска — символ в символ, с пробелами>":
            "<exact search code — character to character, with spaces>",
    "<новый код замены>":                   "<new replacement code>",
    "КРИТИЧЕСКИЕ ПРАВИЛА:":                 "CRITICAL RULES:",
    "1. SEARCH_BLOCK должен ТОЧНО совпадать с кодом в файле (пробелы, отступы).":
            "1. SEARCH_BLOCK must EXACTLY match the code in the file (spaces, indentation).",
    "2. Включай только минимально необходимый кусок для замены — не весь файл.":
            "2. Include only the minimum required piece for replacement — not the whole file.",
    "3. Если нужно несколько замен — повтори блоки SEARCH_BLOCK/REPLACE_BLOCK.":
            "3. If multiple replacements are needed — repeat the blocks SEARCH_BLOCK/REPLACE_BLOCK.",
    "4. Никогда не переписывай весь файл — только точечные изменения.":
            "4. Never rewrite the entire file — only point changes.",
    "5. Объясни ЧТО и ПОЧЕМУ меняешь ПЕРЕД блоками патча.":
            "5. Explain WHAT and WHY you change BEFORE the patch blocks.",
    "6. Отвечай на языке пользователя.":    "6. Answer in the user's language.",
    "ВАЖНО — РЕЖИМ ОТВЕТА:":                "IMPORTANT — REPLY MODE:",
    "• Если пользователь задаёт ВОПРОС (не просит изменить код) — отвечай ОБЫЧНЫМ ТЕКСТОМ без патчей.":
            "• If a user asks a QUESTION (does not ask to change the code) — answer in REGULAR TEXT without patches.",
    "  Примеры вопросов: \"как работает...\", \"что такое...\", \"почему...\", \"объясни...\", \"расскажи...\"":
            "  Sample questions: \"how it works...\", \"what's happened...\", \"Why...\", \"explain...\", \"Tell...\"",
    "• Если пользователь просит ИЗМЕНИТЬ КОД — используй формат [SEARCH_BLOCK]/[REPLACE_BLOCK].":
            "• If the user asks to CHANGE THE CODE — use the format [SEARCH_BLOCK]/[REPLACE_BLOCK].",
    "• Никогда не генерируй пустые патчи или патчи-заглушки если изменений не требуется.":
            "• Never generate empty patches or stub patches if no changes are required..",
    "Ты — браузерный агент. Получаешь задачу и список элементов страницы.":
            "You — browser agent. You receive a task and a list of page elements.",
    "Формат: 'cx,cy|tag*|\"текст\"|ph:placeholder|a:aria-label|n:name|t:type|→href'":
            "Format: 'cx,cy|tag*|\"text\"|ph:placeholder|a:aria-label|n:name|t:type|→href'",
    "* после tag = интерактивный (кликабельный)":
            "* after tag = interactive (clickable)",
    "cx,cy = координаты ЦЕНТРА элемента для клика — используй ТОЛЬКО их!":
            "cx,cy = coordinates of the CENTER of the element to click — ONLY use them!",
    "ПРАВИЛА:":                             "RULES:",
    "1. click_xy: клик по cx,cy — основной способ взаимодействия":
            "1. click_xy: click on cx,cy — main way of interaction",
    "2. type_text: target='cx,cy' (координаты поля ввода), value='текст'":
            "2. type_text: target='cx,cy' (input field coordinates), value='text'",
    "3. Для поиска: найди поле с ph: или a: содержащим 'поиск/search/find' → клик → ввод":
            "3. To search: find the field with ph: or a: containing 'search/search/find' → cry → input",
    "4. Кнопки подтверждения обычно рядом с полем ввода (ниже или справа)":
            "4. Confirmation buttons are usually next to the input field (below or to the right)",
    "5. После navigate подожди 2 сек (wait_seconds)":
            "5. After navigate Wait 2 sec (wait_seconds)",
    "Отвечай ТОЛЬКО JSON-массивом:":        "Answer ONLY JSON-array:",
    "[{\"action\":\"click_xy\",\"target\":\"400,200\"},{\"action\":\"type_text\",\"target\":\"400,200\",\"value\":\"текст\"}]Отвечай ТОЛЬКО JSON-списком действий:":
            "[{\"action\":\"click_xy\",\"target\":\"400,200\"},{\"action\":\"type_text\",\"target\":\"400,200\",\"value\":\"text\"}]Answer ONLY JSON-list of actions:",
    "  {\"action\":\"type_text\",\"target\":\"input[name=\"q\"]\",\"value\":\"текст\"},":
            "  {\"action\":\"type_text\",\"target\":\"input[name=\"q\"]\",\"value\":\"text\"},",
    "ДОСТУПНЫЕ action:":                    "AVAILABLE action:",
    "- click_xy — клик по координатам (x,y) из DOM. ИСПОЛЬЗУЙ ЭТО по умолчанию для кликов!":
            "- click_xy — click on coordinates (x,y) from DOM. USE THIS as default for clicks!",
    "- click — клик по CSS-селектору (только если точно знаешь селектор)":
            "- click — click on CSS-selector (only if you know the selector for sure)",
    "- double_click_xy — двойной клик по координатам":
            "- double_click_xy — double click on coordinates",
    "- right_click_xy — правый клик по координатам":
            "- right_click_xy — right click on coordinates",
    "- hover_xy — наведение на координаты": "- hover_xy — pointing to coordinates",
    "- type_text — ввод текста. ФОРМАТ: target='x,y' (координаты) ИЛИ target='CSS-селектор'. value=текст":
            "- type_text — text input. FORMAT: target='x,y' (coordinates) OR target='CSS-selector'. value=text",
    "  ПРИМЕР: {'action':'type_text','target':'500,300','value':'CodesSherlock'} — сначала кликнет по координатам, потом введёт текст":
            "  EXAMPLE: {'action':'type_text','target':'500,300','value':'CodesSherlock'} — first click on the coordinates, then enter text",
    "- clear_field — очистить поле":        "- clear_field — clear field",
    "- get_text — получить текст элемента": "- get_text — get element text",
    "- navigate — переход по URL":          "- navigate — transition by URL",
    "- wait_seconds — пауза в секундах (value='2')":
            "- wait_seconds — pause in seconds (value='2')",
    "- scroll_page — прокрутка (value='500' пикселей)":
            "- scroll_page — scrolling (value='500' pixels)",
    "ПРАВИЛА:":                             "RULES:",
    "1. Для кликов ВСЕГДА используй click_xy с координатами из (cx,cy) — они надежнее селекторов":
            "1. For clicks ALWAYS use click_xy with coordinates from (cx,cy) — they are more reliable than selectors",
    "2. Если элемент не найден — попробуй ближайшие координаты ±10 пикселей":
            "2. If the element is not found — try the nearest coordinates ±10 pixels",
    "3. После navigate подожди 2 секунды (wait_seconds)":
            "3. After navigate Wait 2 seconds (wait_seconds)",
    "4. Для поиска используй click_xy на поле ввода, затем type_text, затем клик по кнопке":
            "4. To search use click_xy on the input field, then type_text, then клик по кнопке",
    "5. Не используй ID вроде [4] как селекторы — они не работают!":
            "5. Don't use ID like [4] like selectors — they don't work!",
    "Уведомление по завершении":            "Notification upon completion",
    "Уведомление при ошибке":               "Error notification",
    "Уведомление при старте":               "Notification at start",
    "Удаление БД":                          "Deleting a database",
    "Удаление настроек":                    "Removing settings",
    "Удаление списка":                      "Delete a list",
    "Удаление списка из контекстного меню.":
            "Removing a list from the context menu.",
    "Удаление таблицы":                     "Deleting a table",
    "Удаление таблицы из контекстного меню.":
            "Removing a table from the context menu.",
    "Удалено из '":                         "Removed from '",
    "Удалить браузер из трея и скрыть панель если пусто":
            "Remove browser from tray and hide panel if empty",
    "Удалить все списки ({count} шт.)?":    "Delete all lists ({count} pcs.)?",
    "Удалить все таблицы ({count} шт.)?":   "Delete all tables ({count} pcs.)?",
    "Удалить дублирующиеся строки":         "Remove duplicate rows",
    "Удалить настройки проекта?":           "Delete Project Settings?",
    "Удалить подключение «":                "Delete connection «",
    "Удалить проект (остановить если запущен).":
            "Delete project (stop if running).",
    "Удалить список «":                     "Delete list «",
    "Удалить список «{name}»?":             "Delete list «{name}»?",
    "Удалить таблицу":                      "Delete table",
    "Удалить таблицу «":                    "Delete table «",
    "Удалить таблицу «{name}»?":            "Delete table «{name}»?",
    "Укажите путь к файлу.":                "Specify the path to the file.",
    "Указанная область":                    "Specified area",
    "Улучшение структуры и читаемости кода":
            "Improving code structure and readability",
    "Уменьшить PNG (PIL если установлен, иначе возвращаем как есть).":
            "Decrease PNG (PIL if installed, otherwise we return it as is).",
    "Умная миниатюра браузера — скриншот только при изменении контента.":
            "Smart Browser Thumbnail — screenshot only when content changes.",
    "    Проверяет DOM/URL/title каждую секунду, скриншотит только при изменениях.":
            "    Checks DOM/URL/title every second, takes a screenshot only when there are changes.",
    "Управляет параллельным выполнением проектов.":
            "Manages parallel execution of projects.",
    "    Лимит одновременных проектов — из GlobalSettings.":
            "    Limit of simultaneous projects — from GlobalSettings.",
    "    Для каждой модели — свой семафор (sequential / parallel).":
            "    For each model — your semaphore (sequential / parallel).",
    "Уровень лога:":                        "Log level:",
    "Условие остановки:":                   "Stop condition:",
    "Успех":                                "Success",
    "Успехи":                               "Success",
    "Устанавливаются в os.environ перед стартом.":
            "Installed in os.environ before the start.",
    "Поддерживает {переменные} в значениях":
            "Supports {variables} in meanings",
    "Установи зависимости:":                "Install dependencies:",
    "Установить project_root в текущий активный таб.":
            "Install project_root to the current active tab.",
    "Установить значение глобальной переменной (доступно всем потокам через shared context).":
            "Set the value of a global variable (available to all threads via shared context).",
    "Установить ноду как стартовое действие.":
            "Set node as start action.",
    "Установить ноду как стартовую.":       "Set the node as the starting node.",
    "Установить ссылки на внешние сервисы.":
            "Set links to external services.",
    "Устаревший метод - делегируем локальной активации":
            "Deprecated method - delegate to local activation",
    "Учитывай метрики из лога при принятии решений.":
            "Consider metrics from the log when making decisions.",
    "Файл данных (аккаунты/список):":       "Data file (accounts/list):",
    "Файл данных:":                         "Data file:",
    "Файл модели:":                         "Model file:",
    "Файл результатов:":                    "Results file:",
    "Файл сохранения результатов":          "Results saving file",
    "Файл цели:":                           "Target file:",
    "Файлов в контексте:":                  "Files in context:",
    "Файлы лежат в плоской папке.":         "The files are in a flat folder.",
    "Фамилия:":                             "Surname:",
    "Фокус на улучшении числовых метрик из лога":
            "Focus on improving numerical metrics from logs",
    "Формат вывода:":                       "Output Format:",
    "Формат результата:":                   "Result Format:",
    "Формат файла:":                        "File Format:",
    "Форматы: host:port  или  user:pass@host:port  или  socks5://host:port":
            "Formats: host:port  or  user:pass@host:port  or  socks5://host:port",
    "Хост:":                                "Host:",
    "Хосты через запятую, для которых прокси не используется":
            "Hosts separated by commas, for which a proxy is not used",
    "Цвет старта":                          "Start color",
    "Центральная область":                  "Central region",
    "Часть заголовка для поиска окна. Пусто = автопоиск":
            "Part of the window search title. Empty = auto search",
    "Читаем последнее записанное действие из браузера.":
            "Reading the last recorded action from the browser.",
    "Что делать после выбора файла":        "What to do after selecting a file",
    "Что получить:":                        "What to get:",
    "ШЕРЛОКА":                              "SHERLOCK",
    "Шаблон картинки:":                     "Picture template:",
    "Шаблон:":                              "Sample:",
    "Шаблоны:":                             "Templates:",
    "Ширина × Высота пикселей. Пример: 1920x1080":
            "Width × Pixel height. Example: 1920x1080",
    "Экспоненциальная задержка повторов":   "Exponential retry delay",
    "Экспорт всех списков и таблиц в JSON файл.":
            "Export all lists and tables to JSON file.",
    "Экспорт списков и таблиц":             "Exporting lists and tables",
    "Экспорт стратегий":                    "Export strategies",
    "Экспортировать в файл...":             "Export to file...",
    "Элемент (по селектору)":               "Element (by selector)",
    "Эмулировать WebRTC-устройства":        "Emulate WebRTC-devices",
    "Эмулирует очередь: взял — удалил":     "Emulates a queue: took — deleted",
    "Эмуляция скорости сети:":              "Network speed emulation:",
    "Эти переменные доступны из всех потоков при многопоточном запуске через менеджер.":
            "These variables are available from all threads when running multi-threaded through the manager.",
    "Эти файлы НЕ выполняются, но AI МОЖЕТ предлагать патчи для них.":
            "These files are NOT executed, But AI MAY offer patches for them.",
    "Используй `[SEARCH_BLOCK]` / `[REPLACE_BLOCK]` как обычно.":
            "Use `[SEARCH_BLOCK]` / `[REPLACE_BLOCK]` as usual.",
    "Язык браузера:":                       "Browser language:",
    "аеёиоуыэюяАЕЁИОУЫЭЮЯ":                 "aeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "активных</span>":                      "active</span>",
    "алг":                                  "alg",
    "алгоритм":                             "algorithm",
    "базовый":                              "base",
    "байт b64)":                            "byte b64)",
    "байт. Установи openpyxl для полного чтения]":
            "byte. Install openpyxl for full reading]",
    "без изменений":                        "no changes",
    "бот, парсер, регистрация...":          "bot, parser, registration...",
    "браузеров, instance_id не задан. Добавьте поле 'ID инстанса' в действие с переменной из BROWSER_LAUNCH.":
            "browsers, instance_id not specified. Add a field 'ID instance' into action with a variable from BROWSER_LAUNCH.",
    "в чем":                                "what",
    "в чём":                                "what",
    "валидация":                            "validation",
    "введи":                                "enter",
    "вернул код 0, но в логах найдены критические ошибки — считаю провалом":
            "returned the code 0, but critical errors were found in the logs — I consider it a failure",
    "вероятность":                          "probability",
    "восстановлено из трея":                "restored from tray",
    "врм":                                  "vrm",
    "встроен в панель":                     "built into the panel",
    "встроен в панель браузеров":           "built into the browser bar",
    "выборка":                              "sample",
    "выбрал модель #":                      "chose the model #",
    "выбран (":                             "selected (",
    "вырезано":                             "cut out",
    "где":                                  "Where",
    "голосов из":                           "votes from",
    "дополнительный":                       "additional",
    "завершено":                            "completed",
    "завершён (QThread)":                   "completed (QThread)",
    "завершён —":                           "completed —",
    "загружено":                            "loaded",
    "закрыт (fallback)":                    "closed (fallback)",
    "закрыты (close_browser_on_finish)":    "closed (close_browser_on_finish)",
    "запущен в режиме рабочего стола":      "launched in desktop mode",
    "зачем":                                "For what",
    "зпр":                                  "zpr",
    "из целей патчинга":                    "for patching purposes",
    "индекс":                               "index",
    "инициализация":                        "initialization",
    "исключение":                           "exception",
    "исправлено":                           "fixed",
    "итераций выполнено":                   "iterations completed",
    "итераций •":                           "iterations •",
    "итерация 1-2":                         "iteration 1-2",
    "к]":                                   "To]",
    "кавычек":                              "quotation marks",
    "какая":                                "which",
    "какое":                                "which",
    "какой":                                "Which",
    "канал":                                "channel",
    "клиент":                               "client",
    "колонок)":                             "speakers)",
    "компонент":                            "component",
    "конфигурация":                         "configuration",
    "ктк":                                  "KPC",
    "макс":                                 "Max",
    "максимум":                             "maximum",
    "мдл":                                  "mdl",
    "моделей...":                           "models...",
    "моделей:":                             "models:",
    "можешь ли":                            "can you",
    "можно ли":                             "is it possible",
    "мт":                                   "mt",
    "найди":                                "find",
    "невидимых":                            "invisible",
    "невидимых символов":                   "invisible characters",
    "независимых вариантов ответа. Это ВАРИАНТ 1. Дай конкретный, самостоятельный ответ.":
            "independent answer options. THIS IS AN OPTION 1. Give me specific, independent answer.",
    "несохранённых проект(ов):":            "unsaved project(ov):",
    "нет изменений":                        "no changes",
    "нодов +":                              "nodes +",
    "нодов,":                               "nodes,",
    "нормализованы отступы":                "indentation normalized",
    "нормализованы переносы строк":         "line breaks are normalized",
    "обж":                                  "obzh",
    "обновлено":                            "updated",
    "обрб":                                 "obrb",
    "обучение":                             "education",
    "объясни":                              "explain",
    "одинаковых строк подряд).":            "identical lines in a row).",
    "ожидает глобальный слот...":           "waiting for global slot...",
    "окружение":                            "environment",
    "оставлены открытыми":                  "left open",
    "остановлено":                          "stopped",
    "от текущей позиции":                   "from current position",
    "откатов •":                            "kickbacks •",
    "открой":                               "open",
    "оценка":                               "grade",
    "пакет":                                "plastic bag",
    "память":                               "memory",
    "параметров":                           "parameters",
    "патч(ей) за итерацию.":                "patch(to her) per iteration.",
    "патч(ей) получили ≥":                  "patch(to her) received ≥",
    "патч(ей),":                            "patch(to her),",
    "патчей •":                             "patches •",
    "патчи не применялись":                 "no patches applied",
    "перейди":                              "go over",
    "пкт":                                  "pct",
    "повторяющимся ошибкам в логе":         "repeated errors in the log",
    r"подожди\s+(\d+)|wait\s+(\d+)":        r"Wait\s+(\d+)|wait\s+(\d+)",
    "показано":                             "shown",
    "попыток.":                             "attempts.",
    "попыток. Последняя ошибка:":           "attempts. Last mistake:",
    "почему":                               "Why",
    "поясни":                               "explain",
    "прд":                                  "prd",
    "предотвращён, возвращён под курсор":   "averted, returned under the cursor",
    "предсказание":                         "prediction",
    "предупреждение":                       "warning",
    "предупреждений:":                      "warnings:",
    "предупреждения":                       "warnings",
    "признак":                              "sign",
    "признаки":                             "signs",
    "прогн":                                "prog",
    "прогноз":                              "forecast",
    "проект(ов) из менеджера?":             "project(ov) from manager?",
    "(Файлы не удаляются)":                 "(Files are not deleted)",
    "проект(ов) из папки":                  "project(ov) from folder",
    "проект(ов) из файлов":                 "project(ov) из файлov",
    "проектов (":                           "projects (",
    "прошли — вызываю AI с полным контекстом":
            "passed — I call AI with full context",
    "прц":                                  "prts",
    "пток":                                 "ptok",
    "р ×":                                  "r ×",
    "раз подряд**:":                        "once in a row**:",
    "расскажи":                             "Tell",
    "реализация":                           "implementation",
    "с (~":                                 "With (~",
    "сервис":                               "service",
    "сес":                                  "ses",
    "сессия":                               "session",
    "символов вырезано] ...":               "characters cut out] ...",
    "скорость":                             "speed",
    "скрыто (auto_embed)":                  "hidden (auto_embed)",
    "скрыто в трей":                        "hidden in tray",
    "сломал валидатор":                     "broken validator",
    "сломал синтаксис":                     "broke the syntax",
    "смс":                                  "sms",
    "совп.":                                "coincidence.",
    "срв":                                  "srv",
    "срвс":                                 "srvs",
    "среднее":                              "average",
    "стлб":                                 "stlb",
    "стоп":                                 "stop",
    "строк (always)":                       "lines (always)",
    "строк | Ошибок:":                      "lines | Errors:",
    "строк | ошибок:":                      "lines | errors:",
    "строк ×":                              "lines ×",
    "строк в '":                            "lines in '",
    "строк из '":                           "lines from '",
    "строк из файла для '":                 "lines from file for '",
    "строк пропущено] ...":                 "lines missing] ...",
    "строк → Сжато до:":                    "lines → Compressed to:",
    "строк) →":                             "lines) →",
    "строк]":                               "lines]",
    "тире":                                 "dash",
    "токенов в промпте)":                   "tokens in the prompt)",
    "точность":                             "accuracy",
    "транзакция":                           "transaction",
    "трейсбеков:":                          "tracebacks:",
    "тренировка":                           "training",
    "трнз":                                 "trnz",
    "уже выполняется, пропускаем":          "already running, skip",
    "уже запущен, пропускаем дублирующий запуск":
            "already launched, skip duplicate launch",
    "уникальных патч(ей) из":               "unique patch(to her) from",
    "уникальных):**":                       "unique):**",
    "упали)":                               "fell)",
    "успехов,":                             "success,",
    "файл восстановлен к":                  "file restored to",
    "фн":                                   "fn",
    "функции":                              "functions",
    "функция":                              "function",
    "через...":                             "through...",
    "экз":                                  "copy",
    "экземпляр":                            "copy",
    "элементов)":                           "elements)",
    "элементов,":                           "elements,",
    "эп":                                   "ep",
    "эпох":                                 "eras",
    "эпоха":                                "era",
    "эпохи":                                "era",
    "— AI не вызывается (":                 "— AI not called (",
    "— HWND не найден":                     "— HWND not found",
    "— запускаю основной скрипт":           "— I run the main script",
    "— из контекста проекта (browser_instance_id) —":
            "— from the project context (browser_instance_id) —",
    "— откат к лучшему":                    "— rollback for the better",
    "— пропускаю итерацию (":               "— skipping iteration (",
    "ℹ️  INFO — основные события":          "ℹ️  INFO — main events",
    "→ Обычный старт (_launch_for_tray=":   "→ Normal start (_launch_for_tray=",
    "→ Обычный старт (трей отменён: start_in_tray=":
            "→ Normal start (tray canceled: start_in_tray=",
    "↕ Сорт.":                              "↕ Variety.",
    "↩ Откатить":                           "↩ Rollback",
    "↩ откачен":                            "↩ pumped out",
    "↩️ Откат патчей, вызвавших зацикливание...":
            "↩️ Rolling back patches, causing looping...",
    "↪️ Перейти к BAD END":                 "↪️ Go to BAD END",
    "∞ Бесконечно":                         "∞ Endlessly",
    "⌨️ Ввод текста":                       "⌨️ Entering text",
    "⌨️ Нажатие клавиш":                    "⌨️ Keystrokes",
    "⏱ Program Agent: таймаут":             "⏱ Program Agent: time-out",
    "⏳ DOM пустой, повторная попытка через 2 сек...":
            "⏳ DOM empty, retry in 2 sec...",
    "⏳ Ждать появления":                    "⏳ Wait for the appearance",
    "⏳ Задержка старта:":                   "⏳ Start delay:",
    "⏳ Ожидание bottleneck семафора...":    "⏳ Expectation bottleneck semaphore...",
    "⏳ Ожидание изменений...":              "⏳ Waiting for changes...",
    "⏳ Повтор запроса к AI (":              "⏳ Repeat request to AI (",
    "⏳ Поток #":                            "⏳ Flow #",
    "⏳ Скрытие окна в трей (ожидание появления)...":
            "⏳ Hiding a window in the tray (waiting for the appearance)...",
    "⏸  Пауза":                             "⏸  Pause",
    "⏹  Остановить":                        "⏹  Stop",
    "⏹ Все проекты остановлены":            "⏹ All projects have been stopped",
    "⏹ Остановить все проекты":             "⏹ Stop all projects",
    "⏹ Стоп запись":                        "⏹ Stop recording",
    "⏺ Идёт запись действий браузера...":   "⏺ Browser activity is being recorded...",
    "── Проектные списки ──":               "── Project lists ──",
    "── Проектные таблицы ──":              "── Project tables ──",
    "── ⚙️ Дополнительные аргументы ──────────────":
            "── ⚙️ Additional Arguments ──────────────",
    "── ✏️ Переназначить поля профиля ──────────────":
            "── ✏️ Reassign profile fields ──────────────",
    "── 🌐 Браузер ──────────────────────────────":
            "── 🌐 Browser ──────────────────────────────",
    "── 📂 Путь ─────────────────────────────────────":
            "── 📂 Path ─────────────────────────────────────",
    "── 📄 Данные / входной файл ─────────────────":
            "── 📄 Data / input file ─────────────────",
    "── 📋 Логирование ───────────────────────────":
            "── 📋 Logging ───────────────────────────",
    "── 📤 Результат ─────────────────────────────────":
            "── 📤 Result ─────────────────────────────────",
    "── 📦 Переменные окружения ──────────────────":
            "── 📦 Environment Variables ──────────────────",
    "── 📦 Переменные ────────────────────────────────":
            "── 📦 Variables ────────────────────────────────",
    "── 📷 WebRTC / Медиа-устройства ────────────":
            "── 📷 WebRTC / Media devices ────────────",
    "── 🔄 Обновление профиля ────────────────────────":
            "── 🔄 Profile update ────────────────────────",
    "── 🔌 Прокси ────────────────────────────────────":
            "── 🔌 Proxy ────────────────────────────────────",
    "── 🔌 Сеть и прокси ─────────────────────────":
            "── 🔌 Network and proxy ─────────────────────────",
    "── 🔐 Капча-сервис ──────────────────────────":
            "── 🔐 Captcha service ──────────────────────────",
    "── 🔔 Уведомления ───────────────────────────":
            "── 🔔 Notifications ───────────────────────────",
    "── 🔢 Выполнение и ограничения ─────────────":
            "── 🔢 Execution and restrictions ─────────────",
    "── 🖼 Что загружать в браузере ─────────":
            "── 🖼 What to load in the browser ─────────",
    "── 🚀 Режим выполнения ──────────────────────":
            "── 🚀 Execution Mode ──────────────────────",
    "── 🥷 Антидетект ────────────────────────":
            "── 🥷 Antidetect ────────────────────────",
    "── 🪪 Идентификация ─────────────────────────":
            "── 🪪 Identification ─────────────────────────",
    "═══ ОТВЕТ AI — ИТЕРАЦИЯ":              "═══ ANSWER AI — ITERATION",
    "═══ ПРОМПТ ИТЕРАЦИИ":                  "═══ PROMPT ITERATION",
    "═══ ФИНАЛЬНЫЙ ОТВЕТ AI ═══":           "═══ FINAL ANSWER AI ═══",
    "▶ PROJECT_START: точка входа — выполняет стартовую логику по настройкам.":
            "▶ PROJECT_START: entry point — performs startup logic based on settings.",
    "▶ СТАРТ: режим =":                     "▶ START: mode =",
    "▶ Старт проекта":                      "▶ Start of the project",
    "▶ Стартовое действие:":                "▶ Starting action:",
    "▶ Установить как стартовое":           "▶ Set as starter",
    "▶ Холодный старт (без действий)":      "▶ Cold start (no action)",
    "▶| С текущей позиции каждого проекта": "▶| From the current position of each project",
    "▶️  Возобновить":                      "▶️  Resume",
    "▶️  Запустить":                        "▶️  Launch",
    "▶️  Обычный старт (без AI)":           "▶️  Normal start (without AI)",
    "▶️ Запуск проекта:":                   "▶️ Project launch:",
    "▶️ Запустить":                         "▶️ Launch",
    "▶️ Поток #":                           "▶️ Flow #",
    "▶️ СТАРТ — точка входа в проект":      "▶️ START — entry point to the project",
    "○ Мониторинг остановлен":              "○ Monitoring stopped",
    "● Авто-обновление каждые 4 сек":       "● Auto-update every 4 sec",
    "● Мониторинг активен":                 "● Monitoring active",
    "● Обновлено:":                         "● Updated:",
    "★ фокус":                              "★ focus",
    "♻️ Всегда читать из файла при обращении":
            "♻️ Always read from file when accessed",
    "♻️ Закрываем предыдущий браузер":      "♻️ Close the previous browser",
    "♻️ Перезапустить проект":              "♻️ Restart project",
    "♻️ Переиспользуем сохраненный HWND:":  "♻️ Let's reuse the saved one HWND:",
    "⚙️  Настройки...":                     "⚙️  Settings...",
    "⚙️ Входные настройки / BotUI":         "⚙️ Input settings / BotUI",
    "⚙️ Настройки проекта":                 "⚙️ Project Settings",
    "⚠ AI на старте:":                      "⚠ AI at the start:",
    "⚠ Pillow не установлен, сохранено как PNG":
            "⚠ Pillow not installed, saved as PNG",
    "⚠ Валидатор":                          "⚠ Validator",
    "⚠ Комментарии удалены для экономии токенов. SEARCH_BLOCK: копируй код ТОЧНО как в файле (с оригинальными отступами).":
            "⚠ Comments removed to save tokens. SEARCH_BLOCK: copy the code EXACTLY as in the file (with original indents).",
    "⚠ Метрики не улучшились — пересматриваю подход":
            "⚠ Metrics have not improved — I'm reconsidering my approach",
    "⚠ Не удалось загрузить workflow из":   "⚠ Failed to load workflow from",
    "⚠ Не удалось переместить за экран:":   "⚠ Failed to move off screen:",
    "⚠ Не указано имя проектного списка":   "⚠ Project list name not specified",
    "⚠ Не указано имя проектной таблицы":   "⚠ Project table name not specified",
    "⚠ Нет активной модели":                "⚠ No active model",
    "⚠ Ошибка Bad End:":                    "⚠ Error Bad End:",
    "⚠ Ошибка Good End:":                   "⚠ Error Good End:",
    "⚠ Ошибка автозапуска браузера:":       "⚠ Browser autostart error:",
    "⚠ Ошибка вставки блока:":              "⚠ Block insertion error:",
    "⚠ Ошибка вставки:":                    "⚠ Insertion error:",
    "⚠ Ошибка загрузки списка '":           "⚠ Error loading list '",
    "⚠ Ошибка загрузки таблицы '":          "⚠ Error loading table '",
    "⚠ Ошибка загрузки файла:":             "⚠ File download error:",
    "⚠ Ошибка закрытия браузеров:":         "⚠ Error closing browsers:",
    "⚠ Ошибка клика:":                      "⚠ Click error:",
    "⚠ Ошибка синхронизации списка в metadata:":
            "⚠ Error synchronizing list in metadata:",
    "⚠ Ошибка синхронизации таблицы в metadata:":
            "⚠ Table synchronization error in metadata:",
    "⚠ Ошибка сохранения состояния менеджера:":
            "⚠ Error saving manager state:",
    "⚠ Проект":                             "⚠ Project",
    "⚠ Проектная таблица '":                "⚠ Design table '",
    "⚠ СКЕЛЕТ: только сигнатуры функций. SEARCH_BLOCK должен совпадать с РЕАЛЬНЫМ кодом файла.":
            "⚠ SKELETON: function signatures only. SEARCH_BLOCK must match the REAL file code.",
    "Если не знаешь точный код — попроси: 'Покажи строки X-Y из файла'":
            "If you don't know the exact code — ask: 'Show the lines X-Y from file'",
    "⚠ У таблицы '":                        "⚠ At the table '",
    "⚠ Файл списка не найден:":             "⚠ List file not found:",
    "⚠ Файл таблицы не найден:":            "⚠ Table file not found:",
    "⚠ Шаблон не найден (попыток:":         "⚠ Template not found (attempts:",
    "⚠️  WARNING — предупреждения":         "⚠️  WARNING — warnings",
    "⚠️ ActionChains не сработал:":         "⚠️ ActionChains didn't work:",
    "⚠️ BROWSER_CLICK_IMAGE: шаблон не задан — откройте настройки сниппета и выберите область":
            "⚠️ BROWSER_CLICK_IMAGE: template not specified — open snippet settings and select area",
    "⚠️ BROWSER_CLICK_IMAGE: шаблон не найден (попыток:":
            "⚠️ BROWSER_CLICK_IMAGE: template not found (attempts:",
    "⚠️ BROWSER_SCREENSHOT: пустой скриншот":
            "⚠️ BROWSER_SCREENSHOT: blank screenshot",
    "⚠️ WndProc guard не установлен:":      "⚠️ WndProc guard not installed:",
    "⚠️ Workflow не найден при закрытии браузеров":
            "⚠️ Workflow not found when closing browsers",
    "⚠️ clear() не сработал:":              "⚠️ clear() didn't work:",
    "⚠️ Браузер на пустой странице! Добавьте Browser Action → navigate перед Browser Agent":
            "⚠️ Browser on a blank page! Add Browser Action → navigate before Browser Agent",
    "⚠️ Браузер не запущен (instance_id='": "⚠️ Browser is not running (instance_id='",
    "⚠️ Браузер не создан:":                "⚠️ Browser not created:",
    "⚠️ Достигнут лимит параллельных проектов (":
            "⚠️ The limit of parallel projects has been reached (",
    "⚠️ Не удалось встроить браузер":       "⚠️ Failed to embed browser",
    "⚠️ Не удалось закрыть предыдущий:":    "⚠️ Failed to close previous:",
    "⚠️ Не удалось перейти:":               "⚠️ Failed to go:",
    "⚠️ Не удалось скрыть браузер [":       "⚠️ Failed to hide browser [",
    "⚠️ Не удалось скрыть окно":            "⚠️ Failed to hide window",
    "⚠️ Невалидный HWND:":                  "⚠️ Invalid HWND:",
    "⚠️ Невозможно показать окно: невалидный HWND":
            "⚠️ Can't show window: invalid HWND",
    "⚠️ Открыто":                           "⚠️ Open",
    "⚠️ Ошибка tray callback:":             "⚠️ Error tray callback:",
    "⚠️ Ошибка при закрытии браузеров:":    "⚠️ Error when closing browsers:",
    "⚠️ Поток #":                           "⚠️ Flow #",
    "⚠️ При загрузке такого профиля переменные будут перезаписаны":
            "⚠️ When loading such a profile, the variables will be overwritten",
    "⚠️ Проект":                            "⚠️ Project",
    "⚠️ Пропускаем не-объект:":             "⚠️ Skip non-object:",
    "⚠️ Скрипт зациклился на ошибке: `":    "⚠️ The script got stuck on an error: `",
    "⚠️ Страница не загружена (about:blank)! Нужен navigate перед Browser Agent":
            "⚠️ Page not loaded (about:blank)! Needed navigate before Browser Agent",
    "⚠️ Таймаут ожидания загрузки:":        "⚠️ Load waiting timeout:",
    "⚠️ Узкое горлышко (Bottleneck)":       "⚠️ Narrow neck (Bottleneck)",
    "⚠️ Установите opencv-python или Pillow: pip install opencv-python":
            "⚠️ Install opencv-python or Pillow: pip install opencv-python",
    "⚠️ Установите opencv-python или Pillow: pip install opencv-python Pillow pywin32":
            "⚠️ Install opencv-python or Pillow: pip install opencv-python Pillow pywin32",
    "⚠️ Файл не найден, продолжаем с пустым профилем:":
            "⚠️ File not found, continue with an empty profile:",
    "⚠️ Файл профиля не найден, будет создан новый:":
            "⚠️ Profile file not found, a new one will be created:",
    "⚠️ Файл профиля не найден:":           "⚠️ Profile file not found:",
    "⚠️ Элемент [":                         "⚠️ Element [",
    "⚡  Скрипт (Python/JS без модели)":     "⚡  Script (Python/JS without model)",
    "⚡ Выполняю стартовый скрипт...":       "⚡ Executing the startup script...",
    "⚡ Запущено":                           "⚡ Launched",
    "⚡ Простой — запуск без модели":        "⚡ Simple — launch without model",
    "⚡ С начала всех проектов":             "⚡ Since the beginning of all projects",
    "⛔ Валидатор сломался после патча (":   "⛔ Validator broke after patch (",
    "⛔ Валидаторы:":                        "⛔ Validators:",
    "⛔ Обнаружен бесконечный цикл ошибок (":
            "⛔ Infinite loop of errors detected (",
    "⛔ Остановить":                         "⛔ Stop",
    "⛔ Ошибка":                             "⛔ Error",
    "⛔ не запущен":                         "⛔ not running",
    "✅ BROWSER_CLICK_IMAGE: найдено (":     "✅ BROWSER_CLICK_IMAGE: found (",
    "✅ Fallback нашёл":                     "✅ Fallback found",
    "✅ Авто-вызов Good End:":               "✅ Auto call Good End:",
    "✅ Браузер [":                          "✅ Browser [",
    "✅ Браузер закрыт (fallback, первый активный)":
            "✅ Browser is closed (fallback, first active)",
    "✅ Валидаторы:":                        "✅ Validators:",
    "✅ Введён текст:":                      "✅ Text entered:",
    "✅ Выполнено":                          "✅ Done",
    "✅ Использовать выделение":             "✅ Use selection",
    "✅ Клик (":                             "✅ Cry (",
    "✅ Найдено и кликнуто: (":              "✅ Found and clicked: (",
    "✅ Новый профиль сгенерирован:":        "✅ New profile generated:",
    "✅ Парсинг: JSON из текста,":           "✅ Parsing: JSON from the text,",
    "✅ Парсинг: JSON-список,":              "✅ Parsing: JSON-list,",
    "✅ Парсинг: вложенный список actions,": "✅ Parsing: nested list actions,",
    "✅ Парсинг: найдено":                   "✅ Parsing: found",
    "✅ Парсинг: одиночное действие":        "✅ Parsing: single action",
    "✅ Перешли на:":                        "✅ Switched to:",
    "✅ Программа запущена (PID:":           "✅ The program has started (PID:",
    "✅ Скриншот:":                          "✅ Screenshot:",
    "✅ Стартовое действие":                 "✅ Starting action",
    "✅ Страница загружена":                 "✅ Page loaded",
    "✅ Текст введён через ActionChains:":   "✅ Text entered via ActionChains:",
    "✅ Текст введён через JavaScript:":     "✅ Text entered via JavaScript:",
    "✅ Текстовый парсинг:":                 "✅ Text parsing:",
    "✅ Только проверить наличие":           "✅ Just check availability",
    "✅ Цикл завершён:":                     "✅ The cycle is complete:",
    "✅ Шаблон загружен":                    "✅ Template loaded",
    "✅ Шаблон:":                            "✅ Sample:",
    "✏ Открыть":                            "✏ Open",
    "✏️  Переназначить поля профиля":       "✏️  Reassign profile fields",
    "✏️  Редактировать":                    "✏️  Edit",
    "✏️ Нет изменений":                     "✏️ No changes",
    "✏️ Пользовательские стратегии AI":     "✏️ Custom Strategies AI",
    "✏️ Поля переназначены:":               "✏️ Fields reassigned:",
    "✏️ Поля профиля переназначены:":       "✏️ Profile fields reassigned:",
    "✓ Патч →":                             "✓ Patch →",
    "✖ Закрыть все":                        "✖ Close all",
    "✗ Код":                                "✗ Code",
    "✗ ОШИБКИ":                             "✗ ERRORS",
    "✗ Патч не применён:":                  "✗ Patch not applied:",
    "❌ BROWSER_CLICK_IMAGE: нет активного браузера":
            "❌ BROWSER_CLICK_IMAGE: no active browser",
    "❌ BROWSER_SCREENSHOT: браузер не найден":
            "❌ BROWSER_SCREENSHOT: browser not found",
    "❌ ERROR — только ошибки":              "❌ ERROR — only errors",
    "❌ Fallback тоже не нашёл элементов":   "❌ Fallback I didn't find any elements either",
    "❌ HWND не найден — запустите Program Open перед Program Agent":
            "❌ HWND not found — run Program Open before Program Agent",
    "❌ Screenshot ошибка:":                 "❌ Screenshot error:",
    "❌ Screenshot: не удалось получить изображение":
            "❌ Screenshot: failed to get image",
    "❌ Screenshot: нет активного инстанса браузера":
            "❌ Screenshot: no active browser instance",
    "❌ click_xy: невалидные координаты (":  "❌ click_xy: invalid coordinates (",
    "❌ Валидаторы:":                        "❌ Validators:",
    "❌ Ждать исчезновения":                 "❌ Wait for it to disappear",
    "❌ Задача не задана — заполните поле 'Задача для AI'":
            "❌ Task not specified — fill in the field 'Task for AI'",
    "❌ Модель AI не настроена":             "❌ Model AI not configured",
    "❌ Не выбрана AI-модель для Program Agent":
            "❌ Not selected AI-model for Program Agent",
    "❌ Не удалось загрузить":               "❌ Failed to load",
    "❌ Не удалось сделать скриншот окна":   "❌ Failed to take a screenshot of the window",
    "❌ Не указан путь к программе":         "❌ The path to the program is not specified",
    "❌ Нет активного инстанса":             "❌ No active instance",
    "❌ Нет активного инстанса для отображения профиля":
            "❌ No active instance to display profile",
    "❌ Нет инстанса для обновления профиля":
            "❌ No instance to update profile",
    "❌ Ошибка base64":                      "❌ Error base64",
    "❌ Ошибка ввода:":                      "❌ Input error:",
    "❌ Ошибка встраивания:":                "❌ Embedding error:",
    "❌ Ошибка загрузки профиля:":           "❌ Error loading profile:",
    "❌ Ошибка запуска с профиль-папкой:":   "❌ Launch error with profile folder:",
    "❌ Ошибка подключения профиль-папки:":  "❌ Error connecting profile folder:",
    "❌ Ошибка скрипта:":                    "❌ Script error:",
    "❌ Ошибка сохранения профиль-папки:":   "❌ Error saving profile folder:",
    "❌ Ошибка сохранения профиля:":         "❌ Error saving profile:",
    "❌ Переназначение: нет активного инстанса":
            "❌ Reassignment: no active instance",
    "❌ Профиль-папка не найдена:":          "❌ Profile folder not found:",
    "❌ Профиль-папка: нет активного инстанса":
            "❌ Profile-folder: no active instance",
    "❌ Профиль: нет активного инстанса браузера":
            "❌ Profile: no active browser instance",
    "❌ Условие ЛОЖНО":                      "❌ Condition is FALSE",
    "❌ Файл профиля не найден:":            "❌ Profile file not found:",
    "❌ Шаблон не задан — откройте настройки сниппета и выберите область на скриншоте программы":
            "❌ Template not specified — open the snippet settings and select the area in the program screenshot",
    "❓ Неизвестная операция профиля:":      "❓ Unknown profile operation:",
    "➕ Добавить запрет":                    "➕ Add a ban",
    "➕ Добавить поле":                      "➕ Add a field",
    "➕ Добавить попытки":                   "➕ Add attempts",
    "➕ Добавить список":                    "➕ Add list",
    "➕ Добавить таблицу":                   "➕ Add table",
    "➕ Добавлено":                          "➕ Added",
    "➕ Проект добавлен:":                   "➕ Project added:",
    "➕ Развернуть":                         "➕ Expand",
    "➕ Строка":                             "➕ Line",
    "➖ Минимизировать":                     "➖ Minimize",
    "🌍 Глобальные":                        "🌍 Global",
    "🌍 Глобальные переменные (общие между потоками)":
            "🌍 Global Variables (common between threads)",
    "🌍 Язык обновлён":                     "🌍 Language updated",
    "🌐 BROWSER_AGENT: ожидание загрузки страницы...":
            "🌐 BROWSER_AGENT: waiting for page to load...",
    "🌐 ID браузеров":                      "🌐 ID browsers",
    "🌐 ID открытых браузеров":             "🌐 ID open browsers",
    "🌐 ProjectBrowserManager на глобальном BrowserManager (project=":
            "🌐 ProjectBrowserManager on the global BrowserManager (project=",
    "🌐 Автозапуск браузера из PROJECT_START...":
            "🌐 Autostart browser from PROJECT_START...",
    "🌐 Автоматический переход на google.com...":
            "🌐 Automatic transition to google.com...",
    "🌐 Браузер:":                          "🌐 Browser:",
    "🌐 Браузеров: <b>":                    "🌐 Browsers: <b>",
    "🌐 Браузеры оставлены открытыми (настройка проекта)":
            "🌐 Browsers left open (project setup)",
    "🌐 Браузеры потока #":                 "🌐 Flow Browsers #",
    "🌐 Все открытые браузеры":             "🌐 All open browsers",
    "🌐 Используем браузер проекта (tab.browser_manager, owned=":
            "🌐 Using the project browser (tab.browser_manager, owned=",
    "🌐 Переход на стартовый URL:":         "🌐 Go to start URL:",
    "🎬 Анимация выполнения:":              "🎬 Execution Animation:",
    "🎯 PROGRAM ACTION — действие в программе":
            "🎯 PROGRAM ACTION — action in the program",
    "🎯 Действие в окне программы.":        "🎯 Action in the program window.",
    "🎯 Действие в программе":              "🎯 Action in the program",
    "🎯 Точный PID браузера получен от Selenium:":
            "🎯 Accurate PID browser received from Selenium:",
    "🏷 Метки":                             "🏷 Tags",
    "👁 Окно браузера":                     "👁 Browser window",
    "👁 Показать все":                      "👁 Show all",
    "👁 Показать текущий профиль":          "👁 Show current profile",
    "👁 Текущий профиль:":                  "👁 Current profile:",
    "👁 видим":                             "👁 we see",
    "👻 Headless (без окна)":               "👻 Headless (without window)",
    "💾 Профиль сохранён:":                 "💾 Profile saved:",
    "💾 Сохранить профиль (файл .csprofile)":
            "💾 Save profile (file .csprofile)",
    "💾 Сохранить стратегию":               "💾 Save strategy",
    "💾 Сохранять содержимое в файле проекта":
            "💾 Save content in project file",
    "💾 Только в файл":                     "💾 Only to file",
    "💾 Экспорт JSON":                      "💾 Export JSON",
    "📁 Авто-путь из инстанса:":            "📁 Auto-path from instance:",
    "📁 Авто-путь проекта:":                "📁 Auto project path:",
    "📁 Из папки...":                       "📁 From folder...",
    "📁 Подхвачен профиль из контекста:":   "📁 Profile picked up from context:",
    "📁 Профиль-папка сохранена:":          "📁 Profile folder saved:",
    "📁 Создана новая профиль-папка:":      "📁 A new profile folder has been created:",
    "📁 Сохранить профиль-папку":           "📁 Save profile folder",
    "📂  Открыть в редакторе":              "📂  Open in editor",
    "📂 Загрузить профиль (файл .csprofile)":
            "📂 Upload profile (file .csprofile)",
    "📂 Запустить инстанс с профиль-папкой":
            "📂 Launch an instance with a profile folder",
    "📂 Из файла":                          "📂 From file",
    "📂 Импорт JSON":                       "📂 Import JSON",
    "📂 Инстанс использует профиль-папку:": "📂 The instance uses a profile folder:",
    "📂 Инстанс привязан к профиль-папке:": "📂 The instance is linked to a profile folder:",
    "📂 Открыть в редакторе":               "📂 Open in editor",
    "📂 Профиль загружен:":                 "📂 Profile loaded:",
    "📂 Профиль-папка подключена:":         "📂 Profile folder connected:",
    "📃 Regex не найден в '":               "📃 Regex not found in '",
    "📃 Автозагрузка:":                     "📃 Autoload:",
    "📃 Взять строку из проектного списка → переменная":
            "📃 Take a line from the project list → variable",
    "📃 Добавить строку в проектный список":
            "📃 Add line to project list",
    "📃 Загрузить весь проектный список в переменную":
            "📃 Load the entire project list into a variable",
    "📃 Имена списков проекта":             "📃 Project list names",
    "📃 Имя проектного списка:":            "📃 Project list name:",
    "📃 Инициализировано списков:":         "📃 Initialized lists:",
    "📃 Не найдено в '":                    "📃 Not found in '",
    "📃 Очистить проектный список":         "📃 Clear project list",
    "📃 Передано списков:":                 "📃 Transferred lists:",
    "📃 Перечитан '":                       "📃 Reread '",
    "📃 Получить кол-во строк проектного списка":
            "📃 Get the number of lines in the project list",
    "📃 Проектный список '":                "📃 Project list '",
    "📃 Синхронизировано в metadata: '":    "📃 Synced to metadata: '",
    "📃 Сохранить переменную в проектный список":
            "📃 Save variable to project list",
    "📃 Списки":                            "📃 Lists",
    "📃 Списки проекта":                    "📃 Project Lists",
    "📃 Список:":                           "📃 List:",
    "📃 Удалить строку из проектного списка":
            "📃 Remove line from project list",
    "📄 Из файла(ов)...":                   "📄 From file(ov)...",
    "📅 Запуск по расписанию:":             "📅 Scheduled launch:",
    "📅 Настройки расписания":              "📅 Schedule settings",
    "📅 Расписание":                        "📅 Schedule",
    "📊 DOM статистика: всего=":            "📊 DOM statistics: total=",
    "📊 Автозагрузка:":                     "📊 Autoload:",
    "📊 Взять столбец из проектной таблицы в список":
            "📊 Take a column from a design table into a list",
    "📊 Взять строку из проектной таблицы → переменная":
            "📊 Get a row from the design table → variable",
    "📊 Добавить строку в проектную таблицу":
            "📊 Add a row to the design table",
    "📊 Загрузить проектную таблицу в переменную":
            "📊 Load the design table into a variable",
    "📊 Записать ячейку в проектную таблицу":
            "📊 Write cell to design table",
    "📊 Имена таблиц проекта":              "📊 Project table names",
    "📊 Имя проектной таблицы:":            "📊 Project table name:",
    "📊 Инициализировано таблиц:":          "📊 Initialized tables:",
    "📊 Менеджер проектов — AI Code Sherlock":
            "📊 Project Manager — AI Code Sherlock",
    "📊 Очистить проектную таблицу":        "📊 Clear design table",
    "📊 Передано таблиц:":                  "📊 Transferred tables:",
    "📊 Перечитана '":                      "📊 Re-read '",
    "📊 Получить кол-во строк проектной таблицы":
            "📊 Get the number of rows in the design table",
    "📊 Проектная таблица '":               "📊 Design table '",
    "📊 Прочитать ячейку из проектной таблицы":
            "📊 Read cell from design table",
    "📊 Синхронизировано в metadata: '":    "📊 Synced to metadata: '",
    "📊 Сохранено в '":                     "📊 Saved in '",
    "📊 Строка не найдена в '":             "📊 Row not found in '",
    "📊 Таблица:":                          "📊 Table:",
    "📊 Таблицы":                           "📊 Tables",
    "📊 Таблицы проекта":                   "📊 Project tables",
    "📊 Удалить строку из проектной таблицы":
            "📊 Delete a row from a project table",
    "📋  Все (":                            "📋  All (",
    "📋  Все (0)":                          "📋  All (0)",
    "📋 DEBUG — всё подробно":              "📋 DEBUG — everything in detail",
    "📋 DOM повторно:":                     "📋 DOM again:",
    "📋 Все узлы графа (сниппеты)":         "📋 All graph nodes (snippets)",
    "📋 Задания":                           "📋 Quests",
    "📋 Из открытых вкладок":               "📋 From open tabs",
    "📋 Копировать {{{var}}}":              "📋 Copy {{{var}}}",
    "📋 Только в переменную (base64)":      "📋 Only in a variable (base64)",
    "📋 Фокус на окно":                     "📋 Focus on the window",
    "📋+💾 Переменную и файл":              "📋+💾 Variable and file",
    "📌  Скрыть все в трей":                "📌  Hide everything in tray",
    "📌 В трей":                            "📌 To tray",
    "📌 Встроить в панель браузеров":       "📌 Embed in browser bar",
    "📌 Окно браузера":                     "📌 Browser window",
    "📌 Режим трей-панели: explicit=":      "📌 Tray panel mode: explicit=",
    "📌 Режим трей-панели: старт за пределами экрана":
            "📌 Tray panel mode: start off screen",
    "📌 Скрыть все":                        "📌 Hide all",
    "📌 Старт за пределами экрана (для трей-панели)":
            "📌 Start off screen (for tray panel)",
    "📌 в трее":                            "📌 in the tray",
    "📎 Загрузить файл на сервер":          "📎 Upload file to server",
    "        - Флаг \"не возвращать значение\"":
            "        - Flag \"do not return a value\"",
    "📝 Имена переменных проекта":          "📝 Project Variable Names",
    "📝 Синхронизировано с проектом:":      "📝 Synchronized with project:",
    "📝 Создана новая переменная:":         "📝 New variable created:",
    "📝 Создана переменная проекта:":       "📝 Project variable created:",
    "📝 Список сохранён:":                  "📝 List saved:",
    "📝 Статически (только ручной ввод)":   "📝 Statically (manual input only)",
    "📡 Отправляю запрос к AI":             "📡 I am sending a request to AI",
    "📤 Промпт отправлен: ~":               "📤 Prompt sent: ~",
    "📤 Экспортировано в":                  "📤 Exported to",
    "📥 AI ответил:":                       "📥 AI replied:",
    "📥 Загрузить из файла сейчас":         "📥 Load from file now",
    "📥 Импортировано из":                  "📥 Imported from",
    "📦 Окно скрыто за экран (":            "📦 The window is hidden behind the screen (",
    "📦 Программа перемещена за экран (":   "📦 The program has been moved off the screen (",
    "📷 Скриншот браузера":                 "📷 Browser screenshot",
    "📷 Скриншот программы":                "📷 Screenshot of the program",
    "📷 нет превью":                        "📷 no preview",
    "📸 Browser Screenshot — скриншот страницы":
            "📸 Browser Screenshot — screenshot of the page",
    "📸 PROGRAM SCREENSHOT — скриншот окна программы":
            "📸 PROGRAM SCREENSHOT — screenshot of the program window",
    "📸 Сделать скриншот браузера":         "📸 Take a browser screenshot",
    "📸 Сделать скриншот области":          "📸 Take a screenshot of the area",
    "📸 Скриншот в переменную":             "📸 Screenshot to variable",
    "📸 Скриншот окна программы.":          "📸 Screenshot of the program window.",
    "📸 Скриншот программы":                "📸 Screenshot of the program",
    "📸 Скриншот программы (":              "📸 Screenshot of the program (",
    "📸 Скриншот сохранён в переменную:":   "📸 The screenshot is saved to a variable:",
    "📸 Скриншот сохранён в файл:":         "📸 Screenshot saved to file:",
    "📸 Скриншот сохранён:":                "📸 Screenshot saved:",
    "📸 Скриншот страницы":                 "📸 Screenshot of the page",
    "📸 Скриншот:":                         "📸 Screenshot:",
    "📸 нет скриншота":                     "📸 no screenshot",
    "🔀 Switch: нет совпадений → Default (":
            "🔀 Switch: no matches → Default (",
    "🔀 Генерация нового профиля...":       "🔀 Generating a new profile...",
    "🔀 Кейсы для сравнения:":              "🔀 Cases for comparison:",
    "🔀 Поток #":                           "🔀 Flow #",
    "🔀 Профиль сгенерирован:":             "🔀 Profile generated:",
    "🔀 Режим:":                            "🔀 Mode:",
    "🔀 Сгенерирован новый профиль:":       "🔀 New profile generated:",
    "🔀 Сгенерировать новый профиль":       "🔀 Generate new profile",
    "🔁  Гибридный (AI + скрипт)":          "🔁  Hybrid (AI + script)",
    "🔁 Loop: ОДИН шаг цикла. Каждый вызов = одна итерация.":
            "🔁 Loop: ONE cycle step. Every call = one iteration.",
    "        Возврат в цикл осуществляется через граф (красная стрелка → тело → обратно в Loop).":
            "        Return to the loop is carried out through the graph (red arrow → body → back to Loop).",
    "        Завершение цикла — выход по зелёной стрелке (ON_SUCCESS/ALWAYS).":
            "        Completing the cycle — exit by green arrow (ON_SUCCESS/ALWAYS).",
    "🔁 Выход по условию (итерация":        "🔁 Exit by condition (iteration",
    "🔁 Дубли":                             "🔁 Doubles",
    "🔁 Продолжить":                        "🔁 Continue",
    "🔁 Цикл завершён (":                   "🔁 The cycle is complete (",
    "🔄  Сбросить статистику":              "🔄  Reset statistics",
    "🔄 Fallback: пробуем Selenium find_elements...":
            "🔄 Fallback: let's try Selenium find_elements...",
    "🔄 type_text с координатами: клик (":  "🔄 type_text with coordinates: cry (",
    "🔄 Автоконвертация: click → click_xy (":
            "🔄 Auto conversion: click → click_xy (",
    "🔄 Восстановить":                      "🔄 Restore",
    "🔄 Восстановление проектов":           "🔄 Project recovery",
    "🔄 ЗАЦИКЛИВАНИЕ (откат)":              "🔄 Looping (rollback)",
    "🔄 Загрузить из файла при старте проекта":
            "🔄 Load from file at project start",
    "🔄 Конвертация: [":                    "🔄 Conversion: [",
    "🔄 Обновить профиль (новая версия браузера)":
            "🔄 Update profile (new browser version)",
    "🔄 Обновить скрины":                   "🔄 Update screenshots",
    "🔄 Обновление профиля (поиск новой версии браузера)...":
            "🔄 Profile update (searching for a new browser version)...",
    "🔄 Обновление профиля — поиск новой версии браузера...":
            "🔄 Profile update — searching for a new browser version...",
    "🔄 Перезапустить узел":                "🔄 Restart node",
    "🔄 Переменные сброшены к дефолтным (PROJECT_START)":
            "🔄 Variables are reset to default (PROJECT_START)",
    "🔄 Профиль обновлён (был UA:":         "🔄 Profile updated (was UA:",
    "🔄 Профиль обновлён (старый UA:":      "🔄 Profile updated (old UA:",
    "🔄 Текстовый парсинг...":              "🔄 Text parsing...",
    "🔇 Промежуточный браузер (без профиля, без embed) — минимальный режим":
            "🔇 Intermediate browser (no profile, without embed) — minimum mode",
    "🔍 HWND для Program Click Image:":     "🔍 HWND For Program Click Image:",
    "🔍 HWND из metadata workflow:":        "🔍 HWND from metadata workflow:",
    "🔍 HWND найден по PID":                "🔍 HWND found by PID",
    "🔍 Валидаторы первыми — запуск проверок...":
            "🔍 Validators first — launching checks...",
    "🔍 Запуск валидаторов перед AI...":    "🔍 Run validators before AI...",
    "🔍 Запуск валидаторов после патча...": "🔍 Launching validators after the patch...",
    "🔍 Найдено поле ввода по умолчанию:":  "🔍 Default input field found:",
    "🔍 Отладка DOM: bodyExists=":          "🔍 Debugging DOM: bodyExists=",
    "🔍 Проверка _launch_for_tray:":        "🔍 Examination _launch_for_tray:",
    "🔍 РЕЖИМ ШЕРЛОКА АКТИВЕН:":            "🔍 SHERLOCK MODE ACTIVE:",
    "Анализируй логи ошибок и код для поиска первопричин.":
            "Analyze error logs and code to find root causes.",
    "Подход:":                              "Approach:",
    "1. Точно определи тип и место ошибки": "1. Accurately determine the type and location of the error",
    "2. Мысленно проследи стек вызовов":    "2. Mentally trace the call stack",
    "3. Выдвини гипотезы (сначала наиболее вероятные)":
            "3. Make hypotheses (most likely first)",
    "4. Дай МИНИМАЛЬНЫЙ патч — чини причину, не симптом":
            "4. Give me a MINIMUM patch — fix the reason, not a symptom",
    "5. Объясни логику как детектив: \"Улики указывают на...\"":
            "5. Explain logic like a detective: \"Evidence points to...\"",
    "6. Оцени уверенность: ВЫСОКАЯ / СРЕДНЯЯ / НИЗКАЯ":
            "6. Rate your confidence: HIGH / AVERAGE / LOW",
    "🔍 Фильтр по ID, профилю, URL…":       "🔍 Filter by ID, profile, URL…",
    "🔎 Project Info — информация о проекте":
            "🔎 Project Info — project information",
    "🔎 Project Info — системная информация о проекте.":
            "🔎 Project Info — system information about the project.",
    "🔎 Браузеров открыто:":                "🔎 Browsers open:",
    "🔎 Браузеры:":                         "🔎 Browsers:",
    "🔎 Инфо о проекте":                    "🔎 Project information",
    "🔎 Информация о проекте":              "🔎 Project information",
    "🔎 Информация о проекте сохранена":    "🔎 Project information saved",
    "🔎 Неизвестный тип:":                  "🔎 Unknown type:",
    "🔎 Переменных:":                       "🔎 Variables:",
    "🔎 Скиллов:":                          "🔎 Skills:",
    "🔎 Списков:":                          "🔎 Lists:",
    "🔎 Таблиц:":                           "🔎 Tables:",
    "🔎 Узлов:":                            "🔎 Knots:",
    "🔒 Ожидание блокировки запуска браузера...":
            "🔒 Waiting for the browser to be blocked from launching...",
    "🔓 Блокировка запуска браузера снята": "🔓 Browser launch block removed",
    "🔓 Блокировка получена, запускаем браузер...":
            "🔓 Lock received, launch the browser...",
    "🔗 Вставлен:":                         "🔗 Inserted:",
    "🔗 Текущий URL перед сканированием:":  "🔗 Current URL before scanning:",
    "🔗 Текущий URL:":                      "🔗 Current URL:",
    "🔧 Имена скиллов проекта":             "🔧 Project skill names",
    "🔲  Сводка всех браузеров":            "🔲  Summary of all browsers",
    "🔲 Все браузеры":                      "🔲 All browsers",
    "🔴 Браузеры потока #":                 "🔴 Flow Browsers #",
    "🔴 Все браузеры проекта закрыты по завершении workflow":
            "🔴 All project browsers are closed upon completion workflow",
    "🔴 Закрываю браузер по завершении workflow...":
            "🔴 I close the browser when finished workflow...",
    "🖥 PROGRAM OPEN — открыть программу":  "🖥 PROGRAM OPEN — open the program",
    "🖥 Браузер":                           "🖥 Browser",
    "🖥 Запуск:":                           "🖥 Launch:",
    "🖥 Открыть программу":                 "🖥 Open program",
    "🖥 Открыть программу, найти окно, управлять.":
            "🖥 Open program, find the window, manage.",
    "🖥 Показать на рабочем столе":         "🖥 Show on desktop",
    "🖥 Программы":                         "🖥 Programs",
    "🖥 Путь к программе:":                 "🖥 Path to the program:",
    "🖥🧠 AI-агент управления окном программы через скриншоты.":
            "🖥🧠 AI-program window management agent via screenshots.",
    "🖥🧠 PROGRAM AGENT — AI-управление программой":
            "🖥🧠 PROGRAM AGENT — AI-program management",
    "🖱 Клик (левый)":                      "🖱 Cry (left)",
    "🖱 Клик по координатам (":             "🖱 Click on coordinates (",
    "🖱 Левый клик":                        "🖱 Left click",
    "🖱 Навести курсор":                    "🖱 Hover over",
    "🖱 Перетаскивание (drag)":             "🖱 Drag and drop (drag)",
    "🖱 Скролл":                            "🖱 Scroll",
    "🖱➡ Навести (hover)":                  "🖱➡ Visit (hover)",
    "🖱➡ Правый клик":                      "🖱➡ Right click",
    "🖼 Browser Click Image — клик по картинке":
            "🖼 Browser Click Image — click on the picture",
    "🖼 PROGRAM CLICK IMAGE — клик по картинке":
            "🖼 PROGRAM CLICK IMAGE — click on the picture",
    "🖼 Выделите область для клика":        "🖼 Select the area to click",
    "🖼 Ищу шаблон в окне программы (HWND:":
            "🖼 I'm looking for a template in the program window (HWND:",
    "🖼 Клик по картинке":                  "🖼 Click on the picture",
    "🖼 Клик по шаблону картинки в окне программы (base64 шаблон + скриншот через HWND).":
            "🖼 Click on the picture template in the program window (base64 sample + screenshot via HWND).",
    "🗂 Всё сразу (JSON)":                  "🗂 All at once (JSON)",
    "🗄 Подключение к базе данных":         "🗄 Connecting to the database",
    "🗄 Редактировать:":                    "🗄 Edit:",
    "🗑  Удалить":                          "🗑  Delete",
    "🗑 Строку":                            "🗑 String",
    "🗑️  Удалить":                         "🗑️  Delete",
    "🗑️ Все списки удалены":               "🗑️ All lists have been deleted",
    "🗑️ Все таблицы удалены":              "🗑️ All tables have been deleted",
    "🗑️ Закрыть без сохранения":           "🗑️ Close without saving",
    "🗑️ Удалить и пропустить":             "🗑️ Delete and skip",
    "🛑 Авто-вызов Bad End:":               "🛑 Auto call Bad End:",
    "🛡️ Телепорт":                         "🛡️ Teleport",
    "🛡️ Телепорт блока предотвращён, возвращён под курсор":
            "🛡️ Block teleport prevented, returned under the cursor",
    "🤖  С AI-моделью":                     "🤖  WITH AI-model",
    "🤖 AI на старте (модель:":             "🤖 AI at the start (model:",
    "🤖 С моделью — начать с AI-агента":    "🤖 With a model — start with AI-agent",
    "🤝 Консенсус:":                        "🤝 Consensus:",
    "🪪 Browser Profile — операции с профилем":
            "🪪 Browser Profile — profile operations",
    "🪪 Операции с профилем":               "🪪 Profile Operations",
    # ── 🕸️ Browser Parse ─────────────────────────────────────────────
    "🕸️ Browser Parse — парсинг текста из браузера":
        "🕸️ Browser Parse — extract text from browser",
    "🕸️ Browser Parse":                     "🕸️ Browser Parse",
    "Извлекает текст с веб-страницы. Поддерживает ручной выбор элемента "
    "(клик по нужному блоку), CSS/XPath-селектор и универсальный AI-парсер. "
    "Результат → переменная или список проекта.":
        "Extracts text from a web page. Supports interactive element selection, "
        "CSS/XPath selectors, and a universal AI parser. Result → variable or project list.",
    "Инстанс браузера ({var}):":            "Browser instance ({var}):",
    "Переменная с ID открытого браузера":   "Variable with the ID of the open browser",
    "Режим выбора элемента:":               "Element selection mode:",
    "🖱 Интерактивный выбор (клик по элементу)": "🖱 Interactive selection (click on element)",
    "🔤 CSS-селектор":                      "🔤 CSS selector",
    "📍 XPath":                             "📍 XPath",
    "📄 Весь текст страницы":               "📄 Full page text",
    "📊 Таблицы на странице":               "📊 Tables on the page",
    "🤖 Универсальный AI-парсер":           "🤖 Universal AI parser",
    "CSS-селектор:":                        "CSS selector:",
    "Пример: div.price, #content h1, .article-body p":
        "Example: div.price, #content h1, .article-body p",
    "XPath:":                               "XPath:",
    "Пример: //div[@class=\"price\"]//span":
        "Example: //div[@class=\"price\"]//span",
    "Задача для AI-парсера:":               "Task for AI parser:",
    "Опишите что нужно найти: \"цена товара\", \"заголовок статьи\". "
    "Работает даже при изменении структуры сайта.":
        "Describe what to find: \"product price\", \"article title\". "
        "Works even when the site structure changes.",
    "Что брать:":                           "What to take:",
    "Первый найденный":                     "First match",
    "Все совпадения":                       "All matches",
    "Текст + атрибуты":                     "Text + attributes",
    "🖱 Выбрать элемент на странице:":      "🖱 Select element on the page:",
    "Нажмите \"Открыть пикер\", кликните по нужному тексту на скриншоте браузера — "
    "CSS-селектор сохранится автоматически":
        "Press \"Open picker\", click the desired text on the browser screenshot — "
        "the CSS selector will be saved automatically",
    "Фолбэк: AI-парсер если элемент не найден":
        "Fallback: AI parser if element not found",
    "При изменении структуры сайта попытается найти нужные данные через AI":
        "If the site structure changes, will attempt to find the data via AI",
    "→ Переменная:":                        "→ Variable:",
    "Имя переменной для результата":        "Variable name for result",
    "→ Список:":                            "→ List:",
    "Имя списка (для \"все совпадения\")":  "List name (for \"all matches\")",
    "→ Таблица:":                           "→ Table:",
    "Имя таблицы (для таблиц на странице)":"Table name (for page tables)",
    "Ожидание загрузки (мс):":             "Load wait (ms):",
    "Подождать N мс перед парсингом (для динамического контента)":
        "Wait N ms before parsing (for dynamic content)",
    # ── Picker dialog strings ────────────────────────────────────────
    "🖱 Открыть пикер":                     "🖱 Open picker",
    "🖱 Выбор элемента — кликните по нужному тексту на странице":
        "🖱 Element picker — click the desired text on the page",
    "👆 Зажмите ЛКМ и выделите область с нужным текстом, "
    "или ПКМ по тексту → «Использовать этот элемент». "
    "Жёлтая рамка = найденный элемент.":
        "👆 Hold LMB and drag over the desired text, "
        "or RMB on text → 'Use this element'. "
        "Yellow frame = found element.",
    "⬆ Кликните по элементу выше":         "⬆ Click on the element above",
    "🔄 Обновить скриншот":                 "🔄 Refresh screenshot",
    "🔄 Скриншот обновлён. Кликните по элементу.":
        "🔄 Screenshot refreshed. Click on the element.",
    "🖱 Использовать этот элемент для парсинга":
        "🖱 Use this element for parsing",
    "⚠ Элемент не найден — попробуйте другую область":
        "⚠ Element not found — try a different area",
    "Элемент не выбран":                    "Element not selected",
    # ── Program Launch extra strings ────────────────────────────────
    "⚙️ Запуск программы — внешние утилиты и скрипты":
        "⚙️ Program Launch — external tools and scripts",
    "Запуск .exe, .bat, Python-скриптов, ffmpeg, ImageMagick и т.д. Переменные: {var_name}":
        "Launch .exe, .bat, Python scripts, ffmpeg, ImageMagick, etc. Variables: {var_name}",
    "🛑 Программа остановлена по сигналу Stop":
        "🛑 Program stopped by Stop signal",
    "⏱ Таймаут":                            "⏱ Timeout",
    "🛑 Программа остановлена вручную":     "🛑 Program stopped manually",
    "⏱ Программа остановлена по таймауту": "⏱ Program stopped by timeout",
    "⚠ Не удалось запустить процесс:":     "⚠ Failed to start process:",
    "Ошибка запуска программы:":            "Program launch error:",
    "📁 Обнаружены файлы:":                 "📁 Files detected:",
    # ── 🔬 Program Inspector ─────────────────────────────────────────────
    "🔬 Program Inspector — инспекция открытой программы":
        "🔬 Program Inspector — open program inspection",
    "Читает все элементы открытой программы: кнопки, текстовые поля, "
    "лейблы, чекбоксы, координаты. Полная автоматизация без скриншотов. "
    "Результат → переменные, списки или таблица.":
        "Reads all elements of the open program: buttons, text fields, "
        "labels, checkboxes, coordinates. Full automation without screenshots. "
        "Result → variables, lists or table.",
    "Источник окна:":                       "Window source:",
    "По переменной HWND":                   "By HWND variable",
    "По заголовку окна":                    "By window title",
    "По PID процесса":                      "By process PID",
    "Активное окно":                        "Active window",
    "Переменная HWND:":                     "HWND variable:",
    "Переменная содержащая handle окна":    "Variable containing window handle",
    "Заголовок окна (поиск):":              "Window title (search):",
    "Часть заголовка для поиска. Пример: Notepad, Chrome":
        "Part of title to search. Example: Notepad, Chrome",
    "Переменная PID:":                      "PID variable:",
    "Переменная содержащая PID процесса":   "Variable containing process PID",
    "Что читать:":                          "What to read:",
    "🔬 Полный дамп всех элементов":        "🔬 Full dump of all elements",
    "🔘 Только кнопки":                     "🔘 Buttons only",
    "📝 Только текстовые поля":             "📝 Text fields only",
    "🏷 Только лейблы и статичный текст":   "🏷 Labels and static text only",
    "☑ Чекбоксы и радиокнопки":            "☑ Checkboxes and radio buttons",
    "📋 Меню и пункты меню":               "📋 Menus and menu items",
    "🪟 Список всех дочерних окон":         "🪟 List of all child windows",
    "📊 В виде таблицы элементов":          "📊 As element table",
    "Фильтр по классу (Win32):":            "Class filter (Win32):",
    "Пример: Button, Edit, Static. Пусто = все классы":
        "Example: Button, Edit, Static. Empty = all classes",
    "Сохранять координаты (x, y, w, h)":   "Save coordinates (x, y, w, h)",
    "Добавить позицию и размер каждого элемента":
        "Add position and size of each element",
    "Сохранять состояние (enabled/checked)":
        "Save state (enabled/checked)",
    "Добавить флаги: активен, отмечен, видим":
        "Add flags: enabled, checked, visible",
    "Читать текст элементов":               "Read element text",
    "Прочитать содержимое каждого контрола через WinAPI":
        "Read each control content via WinAPI",
    "Глубина дерева элементов:":            "Element tree depth:",
    "Сколько уровней вложенности читать. Больше = медленнее.":
        "How many nesting levels to read. More = slower.",
    "AI-интерпретация дампа":               "AI dump interpretation",
    "Отправить дамп в AI для создания удобной структуры":
        "Send dump to AI for structured output",
    "Что нужно найти/сделать с данными. Пример: \"координаты кнопки ОК\"":
        "What to find/do with data. Example: \"coordinates of OK button\"",
    "Сохранить в:":                         "Save to:",
    "📝 Переменную (JSON)":                 "📝 Variable (JSON)",
    "→ Переменная (JSON):":                 "→ Variable (JSON):",
    "JSON-строка со всеми элементами":      "JSON string with all elements",
    "Таблица: class | text | x | y | w | h | enabled | checked":
        "Table: class | text | x | y | w | h | enabled | checked",
    "→ Список текстов:":                    "→ Text list:",
    "Просто список текстовых значений всех найденных элементов":
        "Simple list of text values of all found elements",
    "🔬 Инспекция программы":              "🔬 Program Inspection",
    # ── 📦 Project In Project ─────────────────────────────────────────────
    "📦 Проект в проекте":                  "📦 Project in Project",
    "Запускает внешний проект как подпроект. Переменные передаются "
    "туда и обратно по заданному сопоставлению.":
        "Runs an external project as a subproject. Variables are passed "
        "in and out by the defined mapping.",
    "Путь к проекту (.json):":              "Path to project (.json):",
    "Сопоставлять переменные с одинаковыми именами":
        "Map variables with matching names",
    "Не возвращать значения при неудаче":   "Do not return values on failure",
    "Если включено — изменения переменных во вложенном проекте игнорируются при ошибке":
        "If enabled — subproject variable changes are ignored on error",
    "Передавать project.Context (C# объекты)":
        "Pass project.Context (C# objects)",
    "Сопоставление переменных (по одному на строку):":
        "Variable mapping (one per line):",
    "# Формат: внешняя_переменная = внутренняя_переменная\n# Пример:\n# login = user_login\n# password = user_pass":
        "# Format: outer_variable = inner_variable\n# Example:\n# login = user_login\n# password = user_pass",
    "Ручное сопоставление имеет приоритет над \"одинаковые имена\"":
        "Manual mapping takes priority over \"matching names\"",
    # ── Browser palette button ───────────────────────────────────────────
    "🕸️ Парсинг текста из браузера":        "🕸️ Parse text from browser",
    # ── 🟨 JS Tester tab content ─────────────────────────────────────────
    "Проверка JS-кода локального выполнения. "
    "Тестер покажет результат и готовый фрагмент для вставки в сниппет.":
        "Test local JavaScript execution. "
        "The tester shows the result and a ready snippet to paste into the action.",
    "1. Код для проверки:":                 "1. Code to test:",
    "2. Формат для экшена JS:":             "2. Format for JS action:",
    "Как есть (raw)":                       "As-is (raw)",
    "Одна строка (escaped)":                "Single line (escaped)",
    "📋 Копировать для вставки":            "📋 Copy for paste",
    "3. Результат выполнения:":             "3. Execution result:",
    "Node.js не найден. Установите node.js для выполнения JS-кода.":
        "Node.js not found. Install node.js to execute JS code.",
    # ── 🔣 X/JSON Path tab content ───────────────────────────────────────
    "Проверка XPath и JSONPath выражений. "
    "Вставьте XML/JSON в поле Данные, введите выражение и нажмите Тест.":
        "Test XPath and JSONPath expressions. "
        "Paste XML/JSON into the Data field, enter an expression and press Test.",
    "1. Данные (XML / JSON):":              "1. Data (XML / JSON):",
    "2. Выражение:":                        "2. Expression:",
    "✨ Beautify":                           "✨ Beautify",
    "3. Результат:":                        "3. Result:",
    "Заполните Данные и Выражение.":        "Fill in Data and Expression.",
    "Установите: pip install jsonpath-ng":  "Install: pip install jsonpath-ng",
    "Или используйте режим XPath для XML.": "Or use XPath mode for XML.",
    "Установите: pip install lxml":         "Install: pip install lxml",
}

# Build reverse table for completeness
_EN_TO_RU: dict[str, str] = {v: k for k, v in _RU_TO_EN.items()}


# =====================================================================
#  Public API
# =====================================================================

def set_language(lang: str) -> None:
    """Set active language ('ru' or 'en'). Notifies all registered listeners."""
    global _current_lang
    with _lock:
        _current_lang = lang
        listeners = list(_listeners)
    for cb in listeners:
        try:
            cb(lang)
        except Exception:
            pass


def get_language() -> str:
    return _current_lang


def tr(text: str) -> str:
    """
    Translate *text* to the current language.
    If translation is missing the original is returned unchanged.
    In debug mode, missing keys are logged and prefixed with a marker.
    """
    if _current_lang == "ru":
        return text

    if _current_lang == "en":
        translated = _RU_TO_EN.get(text)
        if translated is not None:
            return translated

        # Key not found — track it
        if text and text not in _missing_keys:
            _missing_keys.add(text)
            if _debug_missing:
                print(f"[i18n] MISSING KEY: {text!r}", file=sys.stderr)

        # In debug mode, prefix with marker so devs see untranslated strings
        if _debug_missing and text:
            return f"{_missing_key_marker}{text}"
        return text

    return text


def tr_plural(n: int, *forms: str, include_number: bool = True) -> str:
    """
    Pluralize a word for the current language.

    Usage with explicit forms (Russian: singular, 2-4 form, 5+ form):
        tr_plural(5, "файл", "файла", "файлов")  ->  "5 файлов"
        tr_plural(1, "файл", "файла", "файлов")  ->  "1 файл"

    Usage with built-in plural table (just pass the base form):
        tr_plural(5, "файл")   ->  "5 файлов" (ru) / "5 files" (en)
        tr_plural(1, "патч")   ->  "1 патч"   (ru) / "1 patch"  (en)

    Set include_number=False to get just the word without the count.
    """
    key = forms[0] if forms else ""

    if _current_lang == "ru":
        if len(forms) >= 3:
            idx = _ru_plural_idx(n)
            word = forms[idx]
        elif key in _PLURAL_FORMS:
            ru_forms = _PLURAL_FORMS[key]["ru"]
            idx = _ru_plural_idx(n)
            word = ru_forms[idx]
        else:
            word = key
    elif _current_lang == "en":
        if key in _PLURAL_FORMS:
            en_forms = _PLURAL_FORMS[key]["en"]
            idx = _en_plural_idx(n)
            word = en_forms[idx]
        elif len(forms) >= 3:
            idx = _ru_plural_idx(n)
            ru_form = forms[idx]
            word = _RU_TO_EN.get(ru_form, ru_form)
        else:
            word = tr(key)
    else:
        word = key

    if include_number:
        return f"{n} {word}"
    return word


def register_listener(callback: Callable) -> None:
    """Register a callable(lang: str) called whenever language changes."""
    with _lock:
        if callback not in _listeners:
            _listeners.append(callback)


def unregister_listener(callback: Callable) -> None:
    with _lock:
        _listeners[:] = [c for c in _listeners if c != callback]


def get_missing_keys() -> set[str]:
    """Return set of keys that were requested but not found in translations."""
    return set(_missing_keys)


def clear_missing_keys() -> None:
    """Clear the missing keys tracker."""
    _missing_keys.clear()


def enable_debug_missing(enabled: bool = True) -> None:
    """
    Enable/disable missing key debugging.
    When enabled:
      - Missing keys are printed to stderr
      - Untranslated strings get a warning prefix in UI
    """
    global _debug_missing
    _debug_missing = enabled


# =====================================================================
#  Deep Widget Retranslation
# =====================================================================

def retranslate_widget(widget, *, _visited: set | None = None) -> None:
    """
    Recursively walk the widget tree and retranslate all text-bearing
    properties to the current language.

    Handles:
      - QPushButton:     text, tooltip
      - QLabel:          text, tooltip
      - QCheckBox:       text, tooltip
      - QGroupBox:       title, tooltip
      - QTabWidget:      tab texts, tab tooltips
      - QComboBox:       item texts (preserves itemData and current index)
      - QListWidget:     item texts, item tooltips
      - QLineEdit:       placeholder text, tooltip
      - QPlainTextEdit:  placeholder text
      - QTextEdit:       placeholder text (non-html)
      - QAction:         text, tooltip, statusTip
      - QMenu:           title, action texts
      - QSpinBox etc:    tooltip, suffix, prefix

    Avoids infinite loops via visited set.
    Does NOT retranslate children discovered through findChildren()
    to avoid duplicate traversal — uses children() instead.
    """
    if _visited is None:
        _visited = set()

    wid = id(widget)
    if wid in _visited:
        return
    _visited.add(wid)

    try:
        from PyQt6.QtWidgets import (
            QPushButton, QLabel, QCheckBox, QGroupBox,
            QTabWidget, QComboBox, QListWidget, QListWidgetItem,
            QLineEdit, QPlainTextEdit, QTextEdit, QMenu,
            QSpinBox, QDoubleSpinBox, QWidget as _QW, QToolButton,
        )
    except ImportError:
        return

    def _tr_attr(w, getter: str, setter: str) -> None:
        try:
            original = getattr(w, getter)()
            if original:
                translated = tr(original)
                if translated != original:
                    getattr(w, setter)(translated)
        except Exception:
            pass

    def _tr_tooltip(w) -> None:
        try:
            tip = w.toolTip()
            if tip:
                translated = tr(tip)
                if translated != tip:
                    w.setToolTip(translated)
        except Exception:
            pass

    # -- Tooltip is universal
    _tr_tooltip(widget)

    if isinstance(widget, QPushButton):
        _tr_attr(widget, "text", "setText")

    elif isinstance(widget, QLabel):
        _tr_attr(widget, "text", "setText")

    elif isinstance(widget, QCheckBox):
        _tr_attr(widget, "text", "setText")

    elif isinstance(widget, QGroupBox):
        _tr_attr(widget, "title", "setTitle")

    elif isinstance(widget, QTabWidget):
        for i in range(widget.count()):
            orig = widget.tabText(i)
            t = tr(orig)
            if t != orig:
                widget.setTabText(i, t)
            tip = widget.tabToolTip(i)
            if tip:
                tt = tr(tip)
                if tt != tip:
                    widget.setTabToolTip(i, tt)

    elif isinstance(widget, QComboBox):
        widget.blockSignals(True)
        current_idx = widget.currentIndex()
        for i in range(widget.count()):
            orig = widget.itemText(i)
            t = tr(orig)
            if t != orig:
                widget.setItemText(i, t)
            try:
                tip = widget.itemData(i, 3)  # ToolTipRole
                if isinstance(tip, str) and tip:
                    tt = tr(tip)
                    if tt != tip:
                        widget.setItemData(i, tt, 3)
            except Exception:
                pass
        widget.setCurrentIndex(current_idx)
        widget.blockSignals(False)

    elif isinstance(widget, QListWidget):
        for i in range(widget.count()):
            item = widget.item(i)
            if item:
                orig = item.text()
                t = tr(orig)
                if t != orig:
                    item.setText(t)
                tip = item.toolTip()
                if tip:
                    tt = tr(tip)
                    if tt != tip:
                        item.setToolTip(tt)

    elif isinstance(widget, QLineEdit):
        _tr_attr(widget, "placeholderText", "setPlaceholderText")

    elif isinstance(widget, QPlainTextEdit):
        _tr_attr(widget, "placeholderText", "setPlaceholderText")

    elif isinstance(widget, QTextEdit):
        try:
            ph = widget.placeholderText()
            if ph:
                t = tr(ph)
                if t != ph:
                    widget.setPlaceholderText(t)
        except Exception:
            pass

    elif isinstance(widget, QMenu):
        _tr_attr(widget, "title", "setTitle")
        try:
            for action in widget.actions():
                orig = action.text()
                if orig:
                    t = tr(orig)
                    if t != orig:
                        action.setText(t)
                tip = action.toolTip()
                if tip:
                    tt = tr(tip)
                    if tt != tip:
                        action.setToolTip(tt)
        except Exception:
            pass

    elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        try:
            sfx = widget.suffix()
            if sfx:
                t = tr(sfx)
                if t != sfx:
                    widget.setSuffix(t)
            pfx = widget.prefix()
            if pfx:
                t = tr(pfx)
                if t != pfx:
                    widget.setPrefix(t)
        except Exception:
            pass

    # -- Recurse into direct children
    try:
        for child in widget.children():
            if isinstance(child, _QW):
                retranslate_widget(child, _visited=_visited)
    except Exception:
        pass
