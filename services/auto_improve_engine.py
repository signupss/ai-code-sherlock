"""
Auto-Improve Engine — autonomous improvement pipeline orchestrator.
Supports 8 AI strategies for intelligent optimization.
"""
from __future__ import annotations

import asyncio
import glob
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from core.models import ChatMessage, MessageRole, TokenBudget, PatchBlock
from services.engine import PatchEngine, PromptEngine, ModelManager
from services.log_compressor import LogCompressor, CompressionConfig
from services.file_converter import FileConverter
from services.script_runner import ScriptRunner, ScriptResult, AutoInput
from services.version_control import VersionControlService
from services.error_map import ErrorMapService
from services.pipeline_models import (
    PipelineConfig, PipelineRun, IterationResult,
    PipelineStatus, PipelineStopCondition, ScriptRole,
    AIStrategy, AI_STRATEGY_DESCRIPTIONS
)


class PipelineEvent:
    def __init__(self, event_type: str, data: dict):
        self.event_type = event_type
        self.data = data
        self.timestamp = datetime.now()


# ── Strategy system prompts ───────────────────────────────────────────────────

STRATEGY_PROMPTS = {
    AIStrategy.CONSERVATIVE: """
СТРАТЕГИЯ: КОНСЕРВАТИВНАЯ
- Исправляй ТОЛЬКО явные ошибки из лога
- Не меняй логику без крайней необходимости
- Патч должен быть минимальным — 1-3 строки максимум
- Если ошибок нет — напиши GOAL_ACHIEVED
""",
    AIStrategy.BALANCED: """
СТРАТЕГИЯ: СБАЛАНСИРОВАННАЯ
- Исправляй ошибки + делай умеренные улучшения
- Можно менять алгоритмические параметры для достижения цели
- Ориентируйся на метрики из лога
- Каждый патч должен иметь чёткое обоснование
""",
    AIStrategy.AGGRESSIVE: """
СТРАТЕГИЯ: АГРЕССИВНАЯ
- Максимальные улучшения для достижения цели
- Можно рефакторить алгоритмическую логику
- Экспериментируй с параметрами, порогами, архитектурой
- Несколько патчей за итерацию — норма
- Цель важнее осторожности
""",
    AIStrategy.EXPLORER: """
СТРАТЕГИЯ: ИССЛЕДОВАТЕЛЬ
- Каждую итерацию пробуй принципиально ДРУГОЙ подход
- Смотри на предыдущие патчи — НЕ повторяй их
- Ищи неочевидные точки улучшения
- Документируй в анализе какую гипотезу проверяешь
""",
    AIStrategy.EXPLOIT: """
СТРАТЕГИЯ: ЭКСПЛУАТАЦИЯ
- Смотри на предыдущие успешные патчи
- Углубляй и усиливай то, что уже дало улучшение
- Если патч X улучшил метрику — попробуй X*2 или аналогичный подход
- Игнорируй подходы которые не дали результата
""",
    AIStrategy.SAFE_RATCHET: """
СТРАТЕГИЯ: БЕЗОПАСНЫЙ ХРАПОВИК
- Сравни метрики ДО и ПОСЛЕ предыдущего патча
- Если метрики улучшились — продолжай в том же направлении
- Если метрики ухудшились — предложи откат + иной подход
- Никогда не допускай регрессию результатов
""",
    AIStrategy.HYPOTHESIS: """
СТРАТЕГИЯ: ГИПОТЕЗА
Структурируй ответ так:
1. ГИПОТЕЗА: что именно и почему не работает
2. ПРЕДСКАЗАНИЕ: что изменится после патча
3. ПАТЧ: [SEARCH_BLOCK]/[REPLACE_BLOCK]
4. ПРОВЕРКА: как валидировать результат
- Следующую итерацию начни с оценки правильности гипотезы
""",
    AIStrategy.ENSEMBLE: """
СТРАТЕГИЯ: АНСАМБЛЬ
Предложи ТРИ варианта патча:
ВАРИАНТ А: [консервативный]
ВАРИАНТ Б: [умеренный]
ВАРИАНТ В: [агрессивный]
Затем выбери ОДИН наиболее обоснованный и оформи его как [SEARCH_BLOCK]/[REPLACE_BLOCK].
Объясни почему выбрал именно его.
""",
}



import re as _re

# ── Character sets ────────────────────────────────────────────────────────────
_VOWELS_EN = frozenset('aeiouAEIOU')
_VOWELS_RU = frozenset('аеёиоуыэюяАЕЁИОУЫЭЮЯ')
_VOWELS = _VOWELS_EN | _VOWELS_RU

def _is_vowel(ch: str) -> bool:
    return ch in _VOWELS

# ── Hand-curated abbreviation dictionary (≥5 chars only) ─────────────────────
_KNOWN: dict[str, str] = {
    # ── General / universal ───────────────────────────────────────
    'error':            'err',    'errors':          'errs',
    'warning':          'warn',   'warnings':        'warns',
    'debug':            'dbg',    'trace':           'trc',
    'critical':         'crit',   'fatal':           'fatal',
    'information':      'info',   'message':         'msg',
    'messages':         'msgs',   'output':          'out',
    'input':            'in',     'result':          'res',
    'results':          'res',    'status':          'stat',
    'success':          'ok',     'successfully':    'ok',
    'failure':          'fail',   'failed':          'fail',
    'complete':         'done',   'completed':       'done',
    'running':          'run',    'started':         'start',
    'stopped':          'stop',   'finished':        'fin',
    'loading':          'load',   'saving':          'save',
    'reading':          'read',   'writing':         'write',
    'creating':         'creat',  'deleting':        'del',
    'updating':         'upd',    'checking':        'chk',
    'skipping':         'skip',   'retrying':        'retry',
    # ── Code structure ────────────────────────────────────────────
    'function':         'fn',     'functions':       'fns',
    'method':           'mth',    'methods':         'mths',
    'class':            'cls',    'object':          'obj',
    'objects':          'objs',   'instance':        'inst',
    'attribute':        'attr',   'attributes':      'attrs',
    'parameter':        'param',  'parameters':      'params',
    'argument':         'arg',    'arguments':       'args',
    'variable':         'var',    'variables':       'vars',
    'exception':        'exc',    'exceptions':      'excs',
    'interface':        'ifc',    'implementation':  'impl',
    'abstract':         'abs',    'module':          'mod',
    'package':          'pkg',    'library':         'lib',
    'component':        'comp',   'service':         'svc',
    'handler':          'hdlr',   'middleware':      'mw',
    'callback':         'cb',     'listener':        'lstnr',
    'constructor':      'ctor',   'destructor':      'dtor',
    'prototype':        'proto',  'reference':       'ref',
    'pointer':          'ptr',    'buffer':          'buf',
    'context':          'ctx',    'environment':     'env',
    'configuration':    'cfg',    'settings':        'cfg',
    'directory':        'dir',    'temporary':       'tmp',
    'initialize':       'init',   'initialized':     'init',
    'initialization':   'init',
    # ── Types ─────────────────────────────────────────────────────
    'boolean':          'bool',   'integer':         'int',
    'string':           'str',    'character':       'char',
    'sequence':         'seq',    'collection':      'coll',
    'dictionary':       'dict',   'structure':       'struct',
    'undefined':        'undef',  'nullable':        'null',
    # ── Math / ML ─────────────────────────────────────────────────
    'maximum':          'max',    'minimum':         'min',
    'average':          'avg',    'number':          'num',
    'count':            'cnt',    'index':           'idx',
    'length':           'len',    'value':           'val',
    'values':           'vals',   'threshold':       'thr',
    'probability':      'prob',   'accuracy':        'acc',
    'precision':        'prec',   'recall':          'rec',
    'feature':          'feat',   'features':        'feats',
    'gradient':         'grad',   'optimizer':       'optim',
    'optimization':     'optim',  'training':        'train',
    'validation':       'val',    'evaluation':      'eval',
    'prediction':       'pred',   'predictions':     'preds',
    'learning':         'lrn',    'iteration':       'iter',
    'iterations':       'iters',  'epoch':           'ep',
    'epochs':           'eps',    'batch':           'btch',
    'sample':           'smp',    'samples':         'smps',
    'weight':           'wt',     'weights':         'wts',
    'dimension':        'dim',    'dimensions':      'dims',
    'checkpoint':       'ckpt',   'model':           'mdl',
    'layer':            'lyr',    'layers':          'lyrs',
    'activation':       'act',    'normalization':   'norm',
    'regularization':   'reg',    'performance':     'perf',
    'benchmark':        'bench',  'metric':          'mtr',
    'metrics':          'mtrs',   'statistic':       'stat',
    'statistics':       'stats',  'generate':        'gen',
    'generation':       'gen',    'algorithm':       'algo',
    'complexity':       'cplx',   'efficiency':      'eff',
    # ── System / network ──────────────────────────────────────────
    'process':          'proc',   'processes':       'procs',
    'thread':           'thr',    'goroutine':       'grtn',
    'memory':           'mem',    'allocation':      'alloc',
    'execution':        'exec',   'operation':       'op',
    'operations':       'ops',    'transaction':     'txn',
    'timestamp':        'ts',     'duration':        'dur',
    'interval':         'intv',   'frequency':       'freq',
    'bandwidth':        'bw',     'throughput':      'tput',
    'latency':          'lat',    'timeout':         'to',
    'connection':       'conn',   'server':          'srv',
    'client':           'cli',    'request':         'req',
    'response':         'resp',   'channel':         'ch',
    'socket':           'sock',   'address':         'addr',
    'protocol':         'proto',  'authentication':  'auth',
    'authorization':    'authz',  'serialization':   'ser',
    'deserialization':  'deser',  'encryption':      'enc',
    'decryption':       'dec',    'compression':     'cmp',
    # ── Database / storage ────────────────────────────────────────
    'database':         'db',     'query':           'qry',
    'table':            'tbl',    'column':          'col',
    'record':           'rec',    'schema':          'sch',
    'migration':        'mig',    'constraint':      'cstr',
    'transaction':      'txn',
    # ── Go / Rust specific ────────────────────────────────────────
    'receiver':         'rcv',    'sender':          'snd',
    'ownership':        'own',    'borrowing':       'brw',
    'lifetime':         'lt',     'closure':         'cls',
    'iterator':         'iter',   'struct':          'st',
    # ── JS/TS specific ────────────────────────────────────────────
    'promise':          'prm',    'async':           'asnc',
    'await':            'awt',    'extends':         'ext',
    'implements':       'impl',
    # ══ RUSSIAN ═══════════════════════════════════════════════════
    'значение':         'зн',     'значения':        'зн',
    'значений':         'зн',     'параметр':        'пар',
    'параметры':        'пар',    'параметров':      'пар',
    'итерация':         'ит',     'итерации':        'ит',
    'итераций':         'ит',     'количество':      'кол',
    'завершение':       'зав',    'выполнение':      'вып',
    'предупреждение':   'пред',   'предупреждения':  'пред',
    'ошибка':           'ош',     'ошибки':          'ош',
    'ошибок':           'ош',     'обучение':        'обуч',
    'обработка':        'обр',    'результат':       'рез',
    'результаты':       'рез',    'функция':         'фн',
    'функции':          'фн',     'конфигурация':    'конф',
    'инициализация':    'инит',   'сообщение':       'смс',
    'переменная':       'пер',    'переменные':      'пер',
    'переменных':       'пер',    'максимум':        'макс',
    'минимум':          'мин',    'среднее':         'ср',
    'точность':         'точн',   'модель':          'мдл',
    'шаг':              'ш',      'эпоха':           'эп',
    'эпохи':            'эп',     'эпох':            'эп',
    'пакет':            'пкт',    'выборка':         'выб',
    'признак':          'пр',     'признаки':        'пр',
    'начало':           'нач',    'конец':           'кон',
    'загрузка':         'загр',   'сохранение':      'сохр',
    'строка':           'стр',    'столбец':         'стлб',
    'индекс':           'инд',    'создание':        'созд',
    'удаление':         'удал',   'обновление':      'обн',
    'проверка':         'пров',   'валидация':       'вал',
    'тренировка':       'трен',   'оценка':          'оцен',
    'предсказание':     'прд',    'прогноз':         'прогн',
    'вероятность':      'вер',    'порог':           'пор',
    'скорость':         'скор',   'память':          'пам',
    'время':            'вр',     'размер':          'разм',
    'запрос':           'зпр',    'ответ':           'отв',
    'соединение':       'соед',   'сервер':          'срв',
    'клиент':           'кл',     'процесс':         'прц',
    'поток':            'пток',   'канал':           'кн',
    'буфер':            'буф',    'контекст':        'ктк',
    'окружение':        'окр',    'настройки':       'нст',
    'сессия':           'сес',    'запись':          'зап',
    'чтение':           'чт',     'запись':          'зап',
    'обработчик':       'обрб',   'генерация':       'ген',
    'алгоритм':         'алг',    'операция':        'оп',
    'транзакция':       'трнз',   'исключение':      'иск',
    'атрибут':          'атр',    'метод':           'мт',
    'объект':           'обж',    'экземпляр':       'экз',
    'интерфейс':        'инт',    'реализация':      'реал',
    'компонент':        'комп',   'сервис':          'срвс',
    'библиотека':       'библ',   'модуль':          'мод',
    'пакет':            'пкт',    'файл':            'ф',
    'папка':            'пп',     'директория':      'дир',
    'временный':        'врм',    'базовый':         'баз',
    'основной':         'осн',    'дополнительный':  'доп',
    'успешно':          'ок',     'неудача':         'ош',
    'запущено':         'запущ',  'остановлено':     'стоп',
    'завершено':        'зав',    'найдено':         'найд',
    'создано':          'созд',   'удалено':         'удал',
    'обновлено':        'обн',    'загружено':       'загр',
    'сохранено':        'сохр',
}


def compress_word(word: str) -> str:
    """Compress a single word using dictionary + formula fallback."""
    if len(word) <= 4:
        return word
    # Don't touch: numbers, CamelCase identifiers, special tokens
    if any(c.isdigit() for c in word):
        return word
    if word[0].isupper() and any(c.isupper() for c in word[1:]):
        return word  # CamelCase — don't touch
    if word.startswith(('__', '0x', '0b')):
        return word

    n = len(word)
    lower = word.lower()

    # Dictionary lookup
    if lower in _KNOWN:
        abbr = _KNOWN[lower]
        if word[0].isupper():
            return abbr[0].upper() + abbr[1:]
        return abbr

    # Formula fallback
    if n <= 6:
        # Remove middle vowels: keep first 2 + non-vowels from middle + last 1
        mid = ''.join(c for c in word[2:-1] if not _is_vowel(c))
        result = word[:2] + mid + word[-1]
        return result if len(result) < n else word

    if n <= 10:
        # Keep first 3 + remove middle vowels (max 2 kept) + last 2
        mid = ''.join(c for c in word[3:-2] if not _is_vowel(c))[:2]
        result = word[:3] + mid + word[-2:]
        return result if len(result) < n - 1 else word

    # 11+ chars: first 3 + first inner vowel + up to 2 mid consonants + last 3
    inner = word[3:-3]
    first_v = next((c for c in inner if _is_vowel(c)), '')
    mid_c = ''.join(c for c in inner if not _is_vowel(c))[:2]
    result = word[:3] + first_v + mid_c + word[-3:]
    return result if len(result) < n - 2 else word[:5] + word[-3:]


# ── Log line detector — which languages/patterns to process ──────────────────
_LOG_PATTERN = _re.compile(
    r'('
    # Python
    r'(logger|logging|log)\s*\.(info|warning|error|debug|critical|warn|fatal)\s*[.(]'
    r'|print\s*\('
    # JS/TS
    r'|console\s*\.(log|warn|error|info|debug)\s*\('
    # Go
    r'|log\s*\.(Printf|Println|Print|Fatalf|Panicf|Errorf)\s*\('
    r'|fmt\s*\.(Printf|Println|Print|Fprintf|Sprintf)\s*\('
    # Rust
    r'|(println|eprintln|print|eprint|info|warn|error|debug|trace)!\s*\('
    # Java/C#
    r'|System\.out\.(println|print|printf)\s*\('
    r'|Console\.(Write|WriteLine)\s*\('
    r'|\b(log4j|slf4j|logback|nlog|serilog).*\.'
    # Generic
    r'|\bLOGGER\b|\bLOG\b'
    r')',
    _re.IGNORECASE
)

_STRING_PATTERN = _re.compile(r'(f?["\'])((?:[^"\'\\]|\\.)*)(\1)')


def _compress_string(m: _re.Match) -> str:
    """Compress words inside a matched string literal."""
    quote, content, _ = m.group(1), m.group(2), m.group(3)
    # Split on word boundaries, compress alpha-only words
    parts = _re.split(r'(\b[a-zA-Zа-яёА-ЯЁ]{5,}\b)', content)
    compressed = ''.join(
        compress_word(p) if _re.match(r'^[a-zA-Zа-яёА-ЯЁ]{5,}$', p) else p
        for p in parts
    )
    return quote + compressed + quote


def _abbreviate_line(line: str) -> str:
    """Compress string literals inside log/print calls in any language."""
    if not _LOG_PATTERN.search(line):
        return line
    return _STRING_PATTERN.sub(_compress_string, line)


# ── Main compressor ───────────────────────────────────────────────────────────
def _smart_compress_code(source: str) -> str:
    """
    Compress Python source for AI context:
    1. Remove single-line comments entirely
    2. Shorten docstrings to first line
    3. Compress string literals in log/print calls
    4. Collapse consecutive blank lines to max 1
    Returns compressed source — all logic preserved, indentation intact.
    """
    lines = source.splitlines()
    result: list[str] = []
    in_docstring = False
    docstring_char = ''
    docstring_lines = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = line[: len(line) - len(line.lstrip())]

        if not in_docstring:
            # ── Docstring start ───────────────────────────────────
            found_doc = False
            for q in ('"""', "'''"):
                if stripped.startswith(q):
                    cnt = stripped.count(q)
                    # Closed on same line?
                    closed_same = cnt >= 2 and (stripped.endswith(q) and len(stripped) > len(q))
                    inner = stripped[len(q):].rstrip(q).strip() if closed_same else stripped[len(q):].strip()
                    short = (inner[:80] + '…') if len(inner) > 80 else inner
                    result.append(indent + q + short + q)
                    if not closed_same:
                        in_docstring = True
                        docstring_char = q
                        docstring_lines = 0
                    i += 1
                    found_doc = True
                    break
            if found_doc:
                continue

            # ── Single-line comment ───────────────────────────────
            if stripped.startswith('#'):
                i += 1
                continue

            # ── Inline comment strip ──────────────────────────────
            if '#' in line and not _re.search(r'["\'][^"\']*#', line):
                line = _re.sub(r'\s+#[^\n"\']*$', '', line)

            # ── Abbreviate log strings ────────────────────────────
            line = _abbreviate_line(line)

            # ── Blank line collapse ───────────────────────────────
            if not line.strip():
                if result and result[-1].strip():
                    result.append('')
                i += 1
                continue

            result.append(line)
            i += 1

        else:
            # Inside multi-line docstring — skip body
            docstring_lines += 1
            if docstring_char and docstring_char in stripped and docstring_lines > 0:
                in_docstring = False
                docstring_char = ''
            i += 1

    # Remove trailing blanks
    while result and not result[-1].strip():
        result.pop()

    return '\n'.join(result)

class AutoImproveEngine:

    def __init__(
        self,
        model_manager: ModelManager,
        patch_engine: PatchEngine,
        prompt_engine: PromptEngine,
        version_ctrl: VersionControlService,
        error_map: ErrorMapService,
        logger=None,
    ):
        self._mm         = model_manager
        self._patch      = patch_engine
        self._prompt     = prompt_engine
        self._vc         = version_ctrl
        self._em         = error_map
        self._logger     = logger
        self._runner     = ScriptRunner(logger)
        self._converter  = FileConverter()
        self._cancel_requested = False
        self._current_run: PipelineRun | None = None
        self._event_callbacks: list[Callable[[PipelineEvent], None]] = []

    def subscribe(self, cb: Callable[[PipelineEvent], None]) -> None:
        self._event_callbacks.append(cb)

    def unsubscribe(self, cb: Callable[[PipelineEvent], None]) -> None:
        self._event_callbacks = [c for c in self._event_callbacks if c != cb]

    def cancel(self) -> None:
        self._cancel_requested = True
        self._emit("pipeline_cancel", {"message": "Отмена запрошена..."})
        # Kill the currently running subprocess immediately
        try:
            self._runner.kill_current()
        except Exception:
            pass

    @property
    def is_running(self) -> bool:
        return (self._current_run is not None and
                self._current_run.status == PipelineStatus.RUNNING)

    # ── Main entry ────────────────────────────────────────

    async def run_pipeline(self, config: PipelineConfig) -> PipelineRun:
        run = PipelineRun(config=config, status=PipelineStatus.RUNNING,
                          started_at=datetime.now())
        self._current_run = run
        self._cancel_requested = False

        self._emit("pipeline_start", {
            "name": config.name,
            "goal": config.goal,
            "max_iterations": config.max_iterations,
            "strategy": config.ai_strategy.value,
        })

        try:
            while not self._should_stop(run):
                iteration = run.current_iteration + 1
                self._emit("iteration_start", {"iteration": iteration})

                result = await self._run_iteration(run, iteration)
                run.iterations.append(result)

                self._emit("iteration_done", {
                    "iteration": iteration,
                    "success": result.success,
                    "patches_applied": result.patches_applied,
                    "rolled_back": result.rolled_back,
                    "goal_achieved": result.goal_achieved,
                    "elapsed": f"{result.elapsed:.1f}s",
                    "metrics": result.metrics_extracted,
                    "strategy": result.strategy_used.value,
                })

                if result.goal_achieved:
                    run.stop_reason = "Цель достигнута"
                    break
                if self._cancel_requested:
                    run.stop_reason = "Отменено пользователем"
                    break

                await asyncio.sleep(1)

        except Exception as e:
            run.status = PipelineStatus.ERROR
            run.stop_reason = str(e)
            self._emit("pipeline_error", {"error": str(e)})
            if self._logger:
                self._logger.error(f"Pipeline error: {e}", source="AutoImprove")
            raise
        finally:
            if run.status == PipelineStatus.RUNNING:
                run.status = PipelineStatus.FINISHED
            run.finished_at = datetime.now()
            self._emit("pipeline_done", {
                "iterations": run.current_iteration,
                "patches_applied": run.total_patches_applied,
                "rollbacks": run.total_rollbacks,
                "stop_reason": run.stop_reason,
                "best_metrics": run.best_metrics,
            })

        return run

    # ── Iteration ─────────────────────────────────────────

    async def _run_iteration(self, run: PipelineRun, iteration: int) -> IterationResult:
        cfg = run.config

        # Determine current strategy (EXPLORER auto-switches)
        strategy = self._get_current_strategy(cfg, run.iterations)

        result = IterationResult(
            iteration=iteration,
            script_results=[],
            patches_generated=0,
            patches_applied=0,
            patches_failed=0,
            rolled_back=False,
            ai_analysis="",
            goal_achieved=False,
            strategy_used=strategy,
        )

        # ── MODE "val_first": run validators BEFORE primary script ──────────
        patch_mode_early = getattr(cfg, "patch_mode", "immediate")
        if patch_mode_early == "val_first" and cfg.validator_scripts:
            self._emit("ai_thinking", {"message": "🔍 Валидаторы первыми — запуск проверок..."})
            early_val_results = await self._run_validators(cfg)
            result.script_results.extend(early_val_results)

            all_early_ok = all(sr.success for sr in early_val_results)
            passed_e = sum(1 for sr in early_val_results if sr.success)
            total_e  = len(early_val_results)

            if not all_early_ok:
                failed_e = [sr.short_name for sr in early_val_results if not sr.success]
                self._emit("ai_thinking", {
                    "message": f"⛔ Валидаторы: {passed_e}/{total_e} — "
                               f"пропускаю итерацию ({', '.join(failed_e)} упали)"
                })
                result.patches_applied = 0
                result.finished_at = datetime.now()
                return result
            else:
                self._emit("ai_thinking", {
                    "message": f"✅ Валидаторы: {passed_e}/{total_e} — запускаю основной скрипт"
                })

        # ── Cancel check after early validators ──────────
        if self._cancel_requested:
            result.finished_at = datetime.now()
            return result

        # ── Run primary scripts ───────────────────────────
        primary_results: list[ScriptResult] = []
        for sc in cfg.primary_scripts:
            self._emit("script_start", {"script": sc.name, "role": "primary",
                                        "iteration": iteration})

            auto_input = None
            if sc.auto_input.enabled and sc.auto_input.sequences:
                from services.script_runner import AutoInput as AI
                auto_input = AI(
                    sequences=sc.auto_input.sequences,
                    delay_seconds=sc.auto_input.delay_seconds,
                )

            sr = await self._runner.run_async(
                script_path=sc.script_path,
                args=sc.args,
                working_dir=sc.working_dir or None,
                env_vars=sc.env_vars or None,
                timeout_seconds=sc.timeout_seconds,
                on_line=lambda line, stream, name=sc.name: self._emit("log_line", {
                    "script": name, "line": line, "stream": stream
                }),
                auto_input=auto_input,
            )
            primary_results.append(sr)
            result.script_results.append(sr)
            self._emit("script_done", {
                "script": sc.name, "exit_code": sr.exit_code,
                "success": sr.success, "elapsed": f"{sr.elapsed_seconds:.1f}s"
            })

        # Extract metrics from logs
        for sr in primary_results:
            metrics = self._extract_metrics(sr.combined_log, cfg.metric_patterns)
            result.metrics_extracted.update(metrics)

        # ── Collect output files ──────────────────────────
        output_contexts = self._collect_output_files(cfg, cfg.primary_scripts)

        # ── Cancel check ──────────────────────────────────
        if self._cancel_requested:
            result.finished_at = datetime.now()
            return result

        # ══════════════════════════════════════════════════════════════════
        #  THREE PATCH MODES — controls WHEN validators run relative to AI
        #
        #  "immediate"  → Primary → AI → Apply → Validators
        #  "after_val"  → Primary → Validators → AI (sees both logs) → Apply
        #  "val_first"  → Validators → if OK → Primary → AI → Apply
        #                             → if fail → skip iteration
        # ══════════════════════════════════════════════════════════════════
        patch_mode = getattr(cfg, "patch_mode", "immediate")
        val_results_pre: list = []  # validators run before AI (after_val / val_first)

        # ── MODE "after_val" and "all_then_ai": validators BEFORE AI ────────
        if patch_mode in ("after_val", "all_then_ai") and cfg.validator_scripts:
            self._emit("ai_thinking", {"message": "🔍 Запуск валидаторов перед AI..."})
            val_results_pre = await self._run_validators(cfg)
            result.script_results.extend(val_results_pre)
            val_pre_ctxs = self._collect_output_files(cfg, cfg.validator_scripts)
            output_contexts.extend(val_pre_ctxs)

            all_ok = all(sr.success for sr in val_results_pre)
            passed = sum(1 for sr in val_results_pre if sr.success)
            total  = len(val_results_pre)

            if not all_ok:
                failed_names = [sr.short_name for sr in val_results_pre if not sr.success]
                self._emit("ai_thinking", {
                    "message": f"❌ Валидаторы: {passed}/{total} — "
                               f"AI не вызывается ({', '.join(failed_names)} упали)"
                })
                result.patches_applied = 0
                result.finished_at = datetime.now()
                return result
            else:
                self._emit("ai_thinking", {
                    "message": f"✅ Валидаторы: {passed}/{total} прошли — вызываю AI с полным контекстом"
                })

        # ── Cancel check after validators (after_val / all_then_ai) ──────
        if self._cancel_requested:
            result.finished_at = datetime.now()
            return result

        # ── MODE "val_first": validators completely BEFORE primary script ──
        # (validators already ran before primary in outer loop — handled below)

        # ── Build prompt (includes validator logs if after_val) ───────────
        self._emit("ai_thinking", {"message": "Строю контекст для AI..."})
        prompt = self._build_prompt(cfg, iteration, primary_results,
                                    output_contexts, run.iterations, strategy)

        # ── Query AI ──────────────────────────────────────────────────────
        strategy_label = (cfg.custom_strategy.name if cfg.custom_strategy
                          else strategy.value)
        self._emit("ai_thinking", {"message": f"AI анализирует [{strategy_label}]..."})
        # Emit full prompt so UI can show it
        self._emit("prompt_sent", {"prompt": prompt, "iteration": iteration, "strategy": strategy_label})

        if (cfg.consensus and cfg.consensus.enabled and cfg.consensus.model_ids):
            ai_response, consensus_notes = await self._query_consensus(cfg, prompt)
            result.ai_analysis = ai_response
            self._emit("consensus_result", {"notes": consensus_notes})
        else:
            ai_response = await self._query_ai(prompt, cfg)
            result.ai_analysis = ai_response
        # Emit full AI response text for logging
        self._emit("ai_full_response", {"response": ai_response, "iteration": iteration})

        patches = self._patch.parse_patches(ai_response)
        result.patches_generated = len(patches)

        self._emit("ai_response", {
            "patches_found": len(patches),
            "has_goal_signal": self._check_goal(ai_response),
            "strategy": strategy.value,
            "metrics": result.metrics_extracted,
        })

        if self._check_goal(ai_response):
            result.goal_achieved = True
            return result

        # ── SAFE_RATCHET: check metrics before applying ───────────────────
        if strategy == AIStrategy.SAFE_RATCHET and run.iterations:
            last_metrics = run.iterations[-1].metrics_extracted
            if not self._metrics_improved(last_metrics, result.metrics_extracted):
                self._emit("ai_thinking", {"message": "⚠ Метрики не улучшились — пересматриваю подход"})
                rollback_prompt = self._build_regression_prompt(
                    cfg, last_metrics, result.metrics_extracted, ai_response
                )
                ai_response2 = await self._query_ai(rollback_prompt, cfg)
                patches = self._patch.parse_patches(ai_response2)
                result.ai_analysis += "\n\n[REVISION]\n" + ai_response2

        # ── Apply patch ───────────────────────────────────────────────────
        # For "immediate" and "after_val": apply now (validators already ran / will run after)
        # For "val_first":                apply now (validators ran before primary)
        if cfg.auto_apply_patches and patches:
            if patch_mode in ("immediate", "after_val", "val_first", "all_then_ai"):
                applied, failed, rolled_back = await self._apply_patches_safe(
                    patches, cfg, primary_results)
                result.patches_applied = applied
                result.patches_failed  = failed
                result.rolled_back     = rolled_back
                if rolled_back:
                    self._emit("rollback", {"reason": "Синтаксическая ошибка после патча",
                                            "iteration": iteration})
                    self._em.add_avoid_pattern(
                        description=f"Патч итерации {iteration} сломал синтаксис",
                        error_context=self._extract_errors(primary_results),
                        bad_approach=str(patches[0].search_content[:200] if patches else ""),
                        better_approach="Более осторожный точечный патч",
                    )

        # ── Run validators AFTER patch (immediate mode only) ──────────────
        # In "all_then_ai" validators already ran before AI — don't run again
        if patch_mode == "immediate" and cfg.validator_scripts and not result.rolled_back:
            self._emit("ai_thinking", {"message": "🔍 Запуск валидаторов..."})
            val_results_post = await self._run_validators(cfg)
            result.script_results.extend(val_results_post)
            val_post_ctxs = self._collect_output_files(cfg, cfg.validator_scripts)
            output_contexts.extend(val_post_ctxs)
        result.finished_at = datetime.now()
        return result

    # ── Strategy selection ────────────────────────────────

    def _get_current_strategy(
        self, cfg: PipelineConfig, history: list[IterationResult]
    ) -> AIStrategy:
        # Custom strategy overrides the built-in one
        if cfg.custom_strategy:
            return cfg.ai_strategy  # keep enum for internal logic, prompt comes from custom

        base = cfg.ai_strategy

        if base == AIStrategy.EXPLORER:
            # Rotate through non-conservative strategies
            rotation = [
                AIStrategy.BALANCED, AIStrategy.AGGRESSIVE,
                AIStrategy.HYPOTHESIS, AIStrategy.EXPLOIT,
                AIStrategy.ENSEMBLE,
            ]
            idx = len(history) % len(rotation)
            return rotation[idx]

        if base == AIStrategy.EXPLOIT and len(history) >= 2:
            # Check if recent patches improved metrics
            recent = history[-2:]
            if all(r.patches_applied > 0 and not r.rolled_back for r in recent):
                return AIStrategy.AGGRESSIVE  # things are working — push harder
            return AIStrategy.BALANCED

        return base

    # ── Prompt building ───────────────────────────────────

    def _build_prompt(
        self, cfg: PipelineConfig, iteration: int,
        script_results: list[ScriptResult],
        output_contexts: list[str],
        history: list[IterationResult],
        strategy: AIStrategy,
    ) -> str:
        parts: list[str] = []
        lc = LogCompressor(CompressionConfig(max_output_chars=cfg.log_max_chars))

        # Header
        parts.append(f"## ЦЕЛЬ\n{cfg.goal}\n")
        parts.append(f"**Итерация:** {iteration} / {cfg.max_iterations}  |  "
                     f"**Стратегия:** {strategy.value}\n")

        # Best metrics so far
        if history:
            run_metrics = {}
            for it in history:
                for k, v in it.metrics_extracted.items():
                    if k not in run_metrics or v > run_metrics[k]:
                        run_metrics[k] = v
            if run_metrics:
                parts.append(f"**Лучшие метрики за все итерации:** {run_metrics}\n")

        # ── Smart code compression ────────────────────────────────────────────────
        # Strategy:
        #   Iter 1-2 : always full code (AI must understand the codebase first)
        #   Iter 3+  : compress only IF token budget exceeded AND patch history shows
        #              AI already knows the file (has applied patches before)
        #   Compression pipeline:
        #     1. Strip comments + docstrings (saves 15-40% without losing logic)
        #     2. Abbreviate common log/print strings (saves 5-10%)
        #     3. If still too big → AST skeleton (signatures + bodies as ...)
        #     4. Never skeleton if last 2+ patches failed (AI needs full code to match)
        parts.append("## ТЕКУЩИЙ КОД\n")

        # Detect if AI has ever successfully applied a patch to this file
        ever_applied = any(r.patches_applied > 0 for r in history)
        recent_failed = sum(1 for r in history[-3:] if r.patches_applied == 0 and not r.rolled_back)
        force_full = (iteration <= 2) or (recent_failed >= 2) or (not ever_applied)

        for sc in cfg.primary_scripts:
            if sc.allow_patching and Path(sc.script_path).exists():
                content = Path(sc.script_path).read_text(encoding="utf-8", errors="replace")
                token_est = TokenBudget.estimate_tokens(content)
                budget_for_code = cfg.max_context_tokens // 3  # 33% budget for code

                if force_full or token_est <= budget_for_code:
                    # Full code — no compression
                    parts.append(f"### `{sc.name}`:\n```python\n{content}\n```\n")
                    if force_full and token_est > budget_for_code:
                        parts.append(
                            f"*Полный код ({token_est} tok) — сжатие отключено: "
                            f"{'итерация 1-2' if iteration <= 2 else 'патчи не применялись'}*\n"
                        )
                else:
                    # Compression pipeline
                    compressed = _smart_compress_code(content)
                    comp_tokens = TokenBudget.estimate_tokens(compressed)

                    if comp_tokens <= budget_for_code:
                        # Comment-stripped version fits — use it
                        parts.append(
                            f"### `{sc.name}` (без коммент., {comp_tokens} tok):\n"
                            f"```python\n{compressed}\n```\n"
                        )
                        parts.append(
                            "⚠ Комментарии удалены для экономии токенов. "
                            "SEARCH_BLOCK: копируй код ТОЧНО как в файле (с оригинальными отступами).\n"
                        )
                    else:
                        # Still too big → AST skeleton
                        from services.project_manager import PythonSkeletonExtractor
                        skeleton = PythonSkeletonExtractor().extract(content)
                        skel_tokens = TokenBudget.estimate_tokens(skeleton)
                        parts.append(
                            f"### `{sc.name}` [СКЕЛЕТ API, {skel_tokens} tok / оригинал {token_est} tok]:\n"
                            f"```python\n{skeleton}\n```\n"
                        )
                        parts.append(
                            "⚠ СКЕЛЕТ: только сигнатуры функций. "
                            "SEARCH_BLOCK должен совпадать с РЕАЛЬНЫМ кодом файла.\n"
                            "Если не знаешь точный код — попроси: 'Покажи строки X-Y из файла'\n"
                        )

        # Logs
        parts.append("## ЛОГИ\n")
        for sr in script_results:
            raw = sr.combined_log or (sr.stdout + "\n" + sr.stderr)
            compressed = lc.compress_for_ai(raw, sr.short_name)
            status = "✓ OK" if sr.success else f"✗ Код {sr.exit_code}"
            parts.append(f"### `{sr.short_name}` [{status}, {sr.elapsed_seconds:.1f}s]\n"
                         f"```\n{compressed}\n```\n")

        # Output files
        if output_contexts:
            parts.append("## ВЫХОДНЫЕ ФАЙЛЫ\n")
            for ctx in output_contexts:
                parts.append(ctx)

        # History summary
        mem = min(len(history), cfg.memory_iterations)
        if cfg.include_previous_patches and mem > 0:
            parts.append(f"## ИСТОРИЯ ПОСЛЕДНИХ {mem} ИТЕРАЦИЙ\n")
            for prev in history[-mem:]:
                metrics_str = str(prev.metrics_extracted) if prev.metrics_extracted else "нет"
                outcome = "✓" if prev.success and not prev.rolled_back else "↩ откат"
                parts.append(
                    f"**Итерация {prev.iteration}** [{prev.strategy_used.value}] "
                    f"{outcome} | патчей={prev.patches_applied} | метрики={metrics_str}\n"
                )
                if prev.ai_analysis:
                    preview = prev.ai_analysis[:300] + ("..." if len(prev.ai_analysis) > 300 else "")
                    parts.append(f"Анализ: {preview}\n")

        # Error map
        err_ctx = self._em.build_context_block(self._extract_errors(script_results))
        if err_ctx:
            parts.append(f"\n{err_ctx}\n")

        # Strategy instruction
        # Strategy instruction — custom overrides built-in
        if cfg.custom_strategy:
            parts.append(f"\n{cfg.custom_strategy.build_prompt_block()}")
        else:
            parts.append(f"\n{STRATEGY_PROMPTS[strategy]}")

        # Final instructions
        parts.append("""
## ФОРМАТ ОТВЕТА
1. Краткий анализ (3-5 предложений) — что происходит, почему, что менять
2. Патчи в формате [SEARCH_BLOCK]/[REPLACE_BLOCK]
3. Если цель достигнута — напиши GOAL_ACHIEVED

SEARCH_BLOCK должен ТОЧНО совпадать с кодом файла (с пробелами и отступами).
""")
        return "\n".join(parts)

    def _build_regression_prompt(
        self, cfg: PipelineConfig,
        last_metrics: dict, current_metrics: dict, prev_analysis: str
    ) -> str:
        return f"""## РЕГРЕССИЯ МЕТРИК
Предыдущие: {last_metrics}
Текущие:    {current_metrics}

Предыдущий анализ AI:
{prev_analysis[:500]}

## ЗАДАЧА
Метрики ухудшились. Предложи АЛЬТЕРНАТИВНЫЙ подход который:
1. Не повторяет предыдущий патч
2. Восстановит и улучшит метрики
Используй формат [SEARCH_BLOCK]/[REPLACE_BLOCK].
Скрипты:
""" + "\n".join(
            f"### `{sc.name}`:\n```python\n"
            + Path(sc.script_path).read_text(encoding="utf-8", errors="replace")[:3000]
            + "\n```"
            for sc in cfg.primary_scripts if Path(sc.script_path).exists()
        )

    # ── AI Query ──────────────────────────────────────────

    async def _query_ai(self, prompt: str, cfg: PipelineConfig) -> str:
        if not self._mm.active_provider:
            raise RuntimeError("Нет активной модели AI")

        system = self._prompt.build_system_prompt(sherlock_mode=False)
        system += "\nРЕЖИМ: ТОЛЬКО ПАТЧИ [SEARCH/REPLACE] — не переписывай файл целиком\n"

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=system),
            ChatMessage(role=MessageRole.USER, content=prompt),
        ]
        return await self._mm.active_provider.complete(messages)

    async def _query_consensus(
        self, cfg: PipelineConfig, prompt: str
    ) -> tuple[str, str]:
        """Query multiple models via consensus engine. Returns (response, notes)."""
        from services.consensus_engine import ConsensusEngine
        engine = ConsensusEngine(
            model_manager=self._mm,
            patch_engine=self._patch,
            on_event=self._emit,
            logger=self._logger,
        )
        system = self._prompt.build_system_prompt(sherlock_mode=False)
        system += "\nРЕЖИМ: ТОЛЬКО ПАТЧИ [SEARCH/REPLACE]\n"

        result = await engine.run(cfg.consensus, system, prompt)

        # Annotate response with consensus info
        annotated = (
            f"[КОНСЕНСУС: {result.mode.value} | {result.notes}]\n\n"
            + result.final_response
        )
        return annotated, result.notes

    # ── Patch Application ─────────────────────────────────

    async def _apply_patches_safe(
        self, patches: list[PatchBlock],
        config: PipelineConfig, script_results: list[ScriptResult]
    ) -> tuple[int, int, bool]:
        applied, failed = 0, 0
        patchable = {
            s.script_path: Path(s.script_path).read_text(encoding="utf-8", errors="replace")
            for s in config.primary_scripts
            if s.allow_patching and Path(s.script_path).exists()
        }
        versions_created = []

        for patch in patches:
            target = self._find_target(patch, patchable)
            if not target:
                failed += 1
                continue

            content = patchable[target]
            v = self._patch.validate(content, patch)
            if not v.is_valid:
                failed += 1
                self._emit("patch_failed", {"reason": v.error_message,
                                            "file": Path(target).name})
                continue

            try:
                version = self._vc.backup_file(
                    target,
                    description=f"auto-improve iter",
                    patch_search=patch.search_content,
                    patch_replace=patch.replace_content,
                )
                versions_created.append((target, version))
                new_content = self._patch.apply_patch(content, patch)
                patchable[target] = new_content
                Path(target).write_text(new_content, encoding="utf-8")
                self._vc.update_lines_after(version, new_content)
                applied += 1
                self._emit("patch_applied", {
                    "file": Path(target).name,
                    "lines_changed": (patch.replace_content.count("\n")
                                      - patch.search_content.count("\n")),
                    "search": patch.search_content,
                    "replace": patch.replace_content,
                    "file_path": str(target),
                })
            except Exception as e:
                failed += 1
                self._emit("patch_failed", {"reason": str(e), "file": target})

        # Syntax check
        if applied > 0 and config.auto_rollback_on_error:
            for path, _ in versions_created:
                if Path(path).suffix.lower() == ".py":
                    ok, err = self._check_syntax(path)
                    if not ok:
                        self._emit("patch_failed", {
                            "reason": f"Синтаксис: {err}", "file": Path(path).name
                        })
                        self._rollback(versions_created)
                        return 0, applied, True

        return applied, failed, False

    def _rollback(self, versions: list) -> None:
        for path, version in reversed(versions):
            try:
                self._vc.restore_version(version)
                self._emit("rollback_file", {"file": Path(path).name})
            except Exception as e:
                if self._logger:
                    self._logger.error(f"Rollback failed {path}: {e}", source="AutoImprove")

    @staticmethod
    def _check_syntax(path: str) -> tuple[bool, str]:
        try:
            import ast
            ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
            return True, ""
        except SyntaxError as e:
            return False, str(e)

    async def _run_validators(self, config: PipelineConfig) -> list[ScriptResult]:
        # Note: validators that require interactive input MUST have auto_input configured.
        # If a validator gets EOFError, it means its auto_input sequences are missing.
        # The validator will fail (exit code 1) — this is expected behavior.
        results = []
        for sc in config.validator_scripts:
            self._emit("script_start", {"script": sc.name, "role": "validator"})
            auto_input = None
            if sc.auto_input.enabled and sc.auto_input.sequences:
                from services.script_runner import AutoInput as AI
                auto_input = AI(sequences=sc.auto_input.sequences,
                                delay_seconds=sc.auto_input.delay_seconds)
            sr = await self._runner.run_async(
                script_path=sc.script_path, args=sc.args,
                working_dir=sc.working_dir or None,
                timeout_seconds=sc.timeout_seconds,
                on_line=lambda line, stream, name=sc.name: self._emit("log_line", {
                    "script": name, "line": line, "stream": stream
                }),
                auto_input=auto_input,
            )
            results.append(sr)
            self._emit("script_done", {
                "script": sc.name, "exit_code": sr.exit_code,
                "success": sr.success, "role": "validator",
                "elapsed": f"{sr.elapsed_seconds:.1f}s"
            })
        return results

    # ── Helpers ───────────────────────────────────────────

    def _collect_output_files(self, config: PipelineConfig, scripts: list) -> list[str]:
        contexts: list[str] = []
        max_chars = config.output_max_chars
        for sc in scripts:
            for fp in sc.output_files:
                if Path(fp).exists():
                    contexts.append(self._converter.convert_for_ai(fp, max_chars))
            base_dir = sc.working_dir or str(Path(sc.script_path).parent)
            for pattern in sc.output_patterns:
                full = str(Path(base_dir) / pattern)
                for fp in sorted(glob.glob(full))[:5]:
                    contexts.append(self._converter.convert_for_ai(fp, max_chars))
        return contexts

    @staticmethod
    def _extract_metrics(log_text: str, patterns: list[str]) -> dict:
        metrics = {}
        for pattern in patterns:
            try:
                for m in re.finditer(pattern, log_text, re.IGNORECASE):
                    key = pattern.split("[")[0].strip().rstrip("[:=\\s")[:20]
                    try:
                        val = float(m.group(1))
                        if key not in metrics or val > metrics[key]:
                            metrics[key] = val
                    except (ValueError, IndexError):
                        pass
            except re.error:
                pass
        return metrics

    @staticmethod
    def _metrics_improved(prev: dict, curr: dict) -> bool:
        if not prev or not curr:
            return True
        improved = 0
        for k in set(prev) & set(curr):
            if curr[k] > prev[k]:
                improved += 1
        return improved > 0

    def _should_stop(self, run: PipelineRun) -> bool:
        if self._cancel_requested:
            run.stop_reason = "Отменено"
            return True
        cfg = run.config
        if cfg.stop_condition == PipelineStopCondition.MAX_ITERATIONS:
            return run.current_iteration >= cfg.max_iterations
        if cfg.stop_condition == PipelineStopCondition.SUCCESS:
            if run.iterations:
                last = run.iterations[-1]
                return last.success and not last.rolled_back
        if cfg.stop_condition == PipelineStopCondition.GOAL_REACHED:
            return bool(run.iterations and run.iterations[-1].goal_achieved)
        return False

    @staticmethod
    def _check_goal(response: str) -> bool:
        return "GOAL_ACHIEVED" in response.upper()

    @staticmethod
    def _extract_errors(results: list[ScriptResult]) -> str:
        return "\n".join(r.stderr[:500] for r in results if r.stderr)

    @staticmethod
    def _find_target(patch: PatchBlock, scripts: dict[str, str]) -> Optional[str]:
        if patch.file_path:
            for path in scripts:
                if Path(path).name == Path(patch.file_path).name:
                    return path
        from services.engine import PatchEngine
        pe = PatchEngine()
        for path, content in scripts.items():
            if pe.validate(content, patch).is_valid:
                return path
        return next(iter(scripts), None)

    def _emit(self, event_type: str, data: dict) -> None:
        evt = PipelineEvent(event_type, data)
        for cb in self._event_callbacks:
            try:
                cb(evt)
            except Exception:
                pass
