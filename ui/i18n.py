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
