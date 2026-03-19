"""
Pipeline Models — data classes for Auto-Improve Pipeline.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class PipelineStopCondition(str, Enum):
    MANUAL         = "manual"
    MAX_ITERATIONS = "max_iterations"
    SUCCESS        = "success"
    GOAL_REACHED   = "goal_reached"


class PipelineStatus(str, Enum):
    IDLE     = "idle"
    RUNNING  = "running"
    PAUSED   = "paused"
    FINISHED = "finished"
    ERROR    = "error"


class ScriptRole(str, Enum):
    PRIMARY   = "primary"
    VALIDATOR = "validator"


class AIStrategy(str, Enum):
    """How the AI approaches improvements."""
    CONSERVATIVE   = "conservative"   # Only fix errors, minimal changes
    BALANCED       = "balanced"       # Fix + moderate improvements
    AGGRESSIVE     = "aggressive"     # Maximum improvement, creative changes
    EXPLORER       = "explorer"       # Try different approaches each iteration
    EXPLOIT        = "exploit"        # Double down on what worked before
    SAFE_RATCHET   = "safe_ratchet"   # Only apply patches that improve metrics
    HYPOTHESIS     = "hypothesis"     # Form hypothesis, test, validate
    ENSEMBLE       = "ensemble"       # Try multiple approaches, pick best


AI_STRATEGY_DESCRIPTIONS = {
    AIStrategy.CONSERVATIVE:
        "Только исправляет ошибки. Минимальные изменения. "
        "Не трогает рабочий код без явной причины.",
    AIStrategy.BALANCED:
        "Исправляет ошибки + умеренные улучшения. "
        "Оптимальный баланс между стабильностью и прогрессом.",
    AIStrategy.AGGRESSIVE:
        "Максимальные улучшения, творческие изменения. "
        "Может рефакторить логику для достижения цели.",
    AIStrategy.EXPLORER:
        "Каждую итерацию пробует разный подход. "
        "Ищет неочевидные решения, избегает повторения.",
    AIStrategy.EXPLOIT:
        "Углубляет то что уже работало в предыдущих итерациях. "
        "Усиливает успешные паттерны.",
    AIStrategy.SAFE_RATCHET:
        "Применяет патч только если метрики улучшились. "
        "При ухудшении — откат + другой подход.",
    AIStrategy.HYPOTHESIS:
        "Формулирует гипотезу → патч → проверка → вывод. "
        "Научный подход к оптимизации.",
    AIStrategy.ENSEMBLE:
        "Генерирует 3 варианта патча, выбирает наиболее обоснованный. "
        "Медленнее, но точнее.",
}


@dataclass
class AutoInputConfig:
    """Automatic stdin responses for interactive scripts."""
    enabled: bool = False
    sequences: list[str] = field(default_factory=list)
    # e.g. ["y", "", "yes", "1"] — each becomes one line sent to stdin
    delay_seconds: float = 0.3

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "sequences": self.sequences,
            "delay_seconds": self.delay_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AutoInputConfig":
        return cls(
            enabled=d.get("enabled", False),
            sequences=d.get("sequences", []),
            delay_seconds=d.get("delay_seconds", 0.3),
        )


@dataclass
class ScriptConfig:
    script_path: str
    role: ScriptRole = ScriptRole.PRIMARY
    args: list[str] = field(default_factory=list)
    working_dir: str = ""
    timeout_seconds: int = 3600          # default 1 hour
    output_files: list[str] = field(default_factory=list)
    output_patterns: list[str] = field(default_factory=list)
    allow_patching: bool = True
    env_vars: dict[str, str] = field(default_factory=dict)
    auto_input: AutoInputConfig = field(default_factory=AutoInputConfig)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    @property
    def name(self) -> str:
        return Path(self.script_path).name if self.script_path else "unnamed"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "script_path": self.script_path,
            "role": self.role.value,
            "args": self.args,
            "working_dir": self.working_dir,
            "timeout_seconds": self.timeout_seconds,
            "output_files": self.output_files,
            "output_patterns": self.output_patterns,
            "allow_patching": self.allow_patching,
            "env_vars": self.env_vars,
            "auto_input": self.auto_input.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScriptConfig":
        return cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            script_path=d.get("script_path", ""),
            role=ScriptRole(d.get("role", "primary")),
            args=d.get("args", []),
            working_dir=d.get("working_dir", ""),
            timeout_seconds=d.get("timeout_seconds", 3600),
            output_files=d.get("output_files", []),
            output_patterns=d.get("output_patterns", []),
            allow_patching=d.get("allow_patching", True),
            env_vars=d.get("env_vars", {}),
            auto_input=AutoInputConfig.from_dict(d.get("auto_input", {})),
        )


@dataclass
class PipelineConfig:
    name: str = "Новый пайплайн"
    goal: str = ""
    scripts: list[ScriptConfig] = field(default_factory=list)

    # Stop condition
    stop_condition: PipelineStopCondition = PipelineStopCondition.MAX_ITERATIONS
    max_iterations: int = 10

    # Patch behavior
    auto_apply_patches: bool = True
    auto_rollback_on_error: bool = True
    retry_on_patch_failure: int = 2

    # AI strategy
    ai_strategy: AIStrategy = AIStrategy.BALANCED
    strategy_switch_after: int = 3   # iterations before auto-switching (EXPLORER mode)

    # Context limits
    log_max_chars: int = 12000
    output_max_chars: int = 6000
    max_context_tokens: int = 200000  # can set up to 2M for large models

    # History
    include_previous_patches: bool = True
    memory_iterations: int = 5   # how many past iterations to include in context

    # Metric extraction — patterns to auto-extract from logs
    metric_patterns: list[str] = field(default_factory=lambda: [
        r"precision[:\s=]+(\d+\.?\d*)",
        r"accuracy[:\s=]+(\d+\.?\d*)",
        r"loss[:\s=]+(\d+\.?\d*)",
        r"f1[:\s=]+(\d+\.?\d*)",
        r"auc[:\s=]+(\d+\.?\d*)",
    ])

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    @property
    def primary_scripts(self) -> list[ScriptConfig]:
        return [s for s in self.scripts if s.role == ScriptRole.PRIMARY]

    @property
    def validator_scripts(self) -> list[ScriptConfig]:
        return [s for s in self.scripts if s.role == ScriptRole.VALIDATOR]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "goal": self.goal,
            "scripts": [s.to_dict() for s in self.scripts],
            "stop_condition": self.stop_condition.value,
            "max_iterations": self.max_iterations,
            "auto_apply_patches": self.auto_apply_patches,
            "auto_rollback_on_error": self.auto_rollback_on_error,
            "retry_on_patch_failure": self.retry_on_patch_failure,
            "ai_strategy": self.ai_strategy.value,
            "strategy_switch_after": self.strategy_switch_after,
            "log_max_chars": self.log_max_chars,
            "output_max_chars": self.output_max_chars,
            "max_context_tokens": self.max_context_tokens,
            "include_previous_patches": self.include_previous_patches,
            "memory_iterations": self.memory_iterations,
            "metric_patterns": self.metric_patterns,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineConfig":
        return cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            name=d.get("name", "Pipeline"),
            goal=d.get("goal", ""),
            scripts=[ScriptConfig.from_dict(s) for s in d.get("scripts", [])],
            stop_condition=PipelineStopCondition(d.get("stop_condition", "max_iterations")),
            max_iterations=d.get("max_iterations", 10),
            auto_apply_patches=d.get("auto_apply_patches", True),
            auto_rollback_on_error=d.get("auto_rollback_on_error", True),
            retry_on_patch_failure=d.get("retry_on_patch_failure", 2),
            ai_strategy=AIStrategy(d.get("ai_strategy", "balanced")),
            strategy_switch_after=d.get("strategy_switch_after", 3),
            log_max_chars=d.get("log_max_chars", 12000),
            output_max_chars=d.get("output_max_chars", 6000),
            max_context_tokens=d.get("max_context_tokens", 200000),
            include_previous_patches=d.get("include_previous_patches", True),
            memory_iterations=d.get("memory_iterations", 5),
            metric_patterns=d.get("metric_patterns", []),
        )


@dataclass
class IterationResult:
    iteration: int
    script_results: list
    patches_generated: int
    patches_applied: int
    patches_failed: int
    rolled_back: bool
    ai_analysis: str
    goal_achieved: bool
    strategy_used: AIStrategy = AIStrategy.BALANCED
    metrics_extracted: dict = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    error: str = ""

    @property
    def success(self) -> bool:
        return not self.rolled_back and not self.error

    @property
    def elapsed(self) -> float:
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0


@dataclass
class PipelineRun:
    config: PipelineConfig
    status: PipelineStatus = PipelineStatus.IDLE
    iterations: list[IterationResult] = field(default_factory=list)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    stop_reason: str = ""

    @property
    def current_iteration(self) -> int:
        return len(self.iterations)

    @property
    def total_patches_applied(self) -> int:
        return sum(i.patches_applied for i in self.iterations)

    @property
    def total_rollbacks(self) -> int:
        return sum(1 for i in self.iterations if i.rolled_back)

    @property
    def best_metrics(self) -> dict:
        """Return best metric values seen across all iterations."""
        best = {}
        for it in self.iterations:
            for k, v in it.metrics_extracted.items():
                if k not in best or v > best[k]:
                    best[k] = v
        return best
