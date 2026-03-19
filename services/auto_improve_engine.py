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

        # ── Build prompt ──────────────────────────────────
        self._emit("ai_thinking", {"message": "Строю контекст для AI..."})
        prompt = self._build_prompt(cfg, iteration, primary_results,
                                    output_contexts, run.iterations, strategy)

        # ── Query AI ─────────────────────────────────────
        self._emit("ai_thinking", {"message": f"AI анализирует [{strategy.value}]..."})
        ai_response = await self._query_ai(prompt, cfg)
        result.ai_analysis = ai_response

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

        # ── SAFE_RATCHET: check metrics before applying ───
        if strategy == AIStrategy.SAFE_RATCHET and run.iterations:
            last_metrics = run.iterations[-1].metrics_extracted
            if not self._metrics_improved(last_metrics, result.metrics_extracted):
                self._emit("ai_thinking", {
                    "message": "⚠ Метрики не улучшились — пересматриваю подход"
                })
                # Ask AI for alternative after regression
                rollback_prompt = self._build_regression_prompt(
                    cfg, last_metrics, result.metrics_extracted, ai_response
                )
                ai_response2 = await self._query_ai(rollback_prompt, cfg)
                patches = self._patch.parse_patches(ai_response2)
                result.ai_analysis += "\n\n[REVISION]\n" + ai_response2

        # ── Apply patches ─────────────────────────────────
        if cfg.auto_apply_patches and patches:
            applied, failed, rolled_back = await self._apply_patches_safe(
                patches, cfg, primary_results)
            result.patches_applied = applied
            result.patches_failed = failed
            result.rolled_back = rolled_back

            if rolled_back:
                self._emit("rollback", {"reason": "Синтаксическая ошибка после патча",
                                        "iteration": iteration})
                self._em.add_avoid_pattern(
                    description=f"Патч итерации {iteration} сломал синтаксис",
                    error_context=self._extract_errors(primary_results),
                    bad_approach=str(patches[0].search_content[:200] if patches else ""),
                    better_approach="Более осторожный точечный патч",
                )

        # ── Run validators ────────────────────────────────
        if cfg.validator_scripts and not result.rolled_back:
            self._emit("ai_thinking", {"message": "Запуск валидаторов..."})
            val_results = await self._run_validators(cfg)
            result.script_results.extend(val_results)
            val_ctxs = self._collect_output_files(cfg, cfg.validator_scripts)
            output_contexts.extend(val_ctxs)

        result.finished_at = datetime.now()
        return result

    # ── Strategy selection ────────────────────────────────

    def _get_current_strategy(
        self, cfg: PipelineConfig, history: list[IterationResult]
    ) -> AIStrategy:
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

        # Current script content
        parts.append("## ТЕКУЩИЙ КОД\n")
        for sc in cfg.primary_scripts:
            if sc.allow_patching and Path(sc.script_path).exists():
                content = Path(sc.script_path).read_text(encoding="utf-8", errors="replace")
                token_est = TokenBudget.estimate_tokens(content)
                budget_for_code = cfg.max_context_tokens // 4
                if token_est > budget_for_code:
                    from services.project_manager import PythonSkeletonExtractor
                    skeleton = PythonSkeletonExtractor().extract(content)
                    parts.append(f"### `{sc.name}` (скелет ~{token_est} tok):\n"
                                 f"```python\n{skeleton}\n```\n")
                    parts.append("*Полный файл слишком большой — SEARCH_BLOCK должен точно совпадать с кодом*\n")
                else:
                    parts.append(f"### `{sc.name}`:\n```python\n{content}\n```\n")

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
                "success": sr.success, "role": "validator"
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
