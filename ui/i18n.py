"""
i18n.py — Internationalization for AI Code Sherlock.

Usage:
    from ui.i18n import tr, set_language, get_language

    set_language("en")
    print(tr("Новый проект"))   # → "New Project"

Supported: "ru" (default, identity), "en"
"""
from __future__ import annotations
from typing import Callable

_current_lang: str = "ru"
_listeners: list[Callable] = []

# ─────────────────────────────────────────────────────────────
#  Translation table  ru → en
#  Keep keys exactly as they appear in the source code.
# ─────────────────────────────────────────────────────────────
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
    "Кастомные стратегии AI":        "Custom AI Strategies",
    "+ Создать":                     "+ Create",
    "✏ Изменить":                    "✏ Edit",
    "✕ Удалить":                     "✕ Delete",
    "Цвет темы (акцент)":            "Theme Color (accent)",
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


def set_language(lang: str) -> None:
    """Set active language ('ru' or 'en'). Notifies all registered listeners."""
    global _current_lang
    _current_lang = lang
    for cb in _listeners:
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
    """
    if _current_lang == "ru":
        return text
    if _current_lang == "en":
        return _RU_TO_EN.get(text, text)
    return text


def register_listener(callback: Callable) -> None:
    """Register a callable(lang: str) called whenever language changes."""
    if callback not in _listeners:
        _listeners.append(callback)


def unregister_listener(callback: Callable) -> None:
    _listeners[:] = [c for c in _listeners if c != callback]


def retranslate_widget(widget) -> None:
    """
    Walk the widget tree and attempt to retranslate all text-bearing widgets.
    Handles: QPushButton, QLabel, QCheckBox, QGroupBox, QTabBar, QLineEdit placeholder.
    """
    try:
        from PyQt6.QtWidgets import (
            QPushButton, QLabel, QCheckBox, QGroupBox,
            QTabWidget, QLineEdit, QPlainTextEdit
        )
        from PyQt6.QtWidgets import QWidget as _QW

        # Retranslate this widget
        if isinstance(widget, QPushButton):
            original = widget.text()
            translated = tr(original)
            if translated != original:
                widget.setText(translated)
        elif isinstance(widget, (QLabel, QCheckBox, QGroupBox)):
            original = widget.text()
            translated = tr(original)
            if translated != original:
                widget.setText(translated)
        elif isinstance(widget, QLineEdit):
            ph = widget.placeholderText()
            translated = tr(ph)
            if translated != ph:
                widget.setPlaceholderText(translated)
        elif isinstance(widget, QTabWidget):
            for i in range(widget.count()):
                orig = widget.tabText(i)
                t = tr(orig)
                if t != orig:
                    widget.setTabText(i, t)

        # Recurse into children
        for child in widget.findChildren(_QW):
            retranslate_widget(child)

    except Exception:
        pass
