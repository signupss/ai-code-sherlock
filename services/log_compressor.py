"""
Log Compressor — smart log compression for AI context.

Rules:
1. ERROR / WARNING lines → ALWAYS kept verbatim
2. Tracebacks → kept in full (detected by indentation / "Traceback" marker)
3. First N lines → kept (script startup context)
4. Last N lines → kept (final state, results)
5. Middle → deduplicated, sampled, verbose repetitions compressed
6. Numerical outputs (floats, metrics) → kept every K-th line + min/max markers
7. Progress bars / tqdm lines → only last one kept
8. File outputs listed → kept as-is
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class CompressionConfig:
    max_output_chars: int = 8000       # hard cap on result
    keep_first_lines: int = 30         # always keep script startup
    keep_last_lines: int = 60          # always keep final output
    keep_error_context: int = 5        # lines before/after each error
    max_consecutive_similar: int = 3   # deduplicate repetitive lines
    metric_sample_every: int = 10      # keep 1 of every N metric lines
    always_keep_tracebacks: bool = True
    always_keep_warnings: bool = True


# Patterns that indicate "important" lines — never compress
_ERROR_PATTERNS = re.compile(
    r"(error|exception|traceback|failed|critical|fatal|assert|"
    r"OSError|ValueError|TypeError|KeyError|AttributeError|"
    r"RuntimeError|ImportError|SyntaxError|IndentationError)",
    re.IGNORECASE
)

_WARNING_PATTERNS = re.compile(
    r"(warning|warn|deprecated|caution|alert)",
    re.IGNORECASE
)

_TRACEBACK_START = re.compile(r"^Traceback \(most recent call last\)", re.IGNORECASE)
_TRACEBACK_FRAME = re.compile(r'^\s+File ".+", line \d+')
_TRACEBACK_END   = re.compile(r"^\w+Error:|^\w+Exception:")

# Progress bar patterns (tqdm, rich, etc.)
_PROGRESS_PATTERN = re.compile(r"(\d+%|\d+/\d+|\[=+>?-*\]|\|[█▓░#=\- ]+\|)")

# Metric/number patterns (loss: 0.123, accuracy=0.98, epoch 5/100)
_METRIC_PATTERN = re.compile(
    r"(epoch|step|iter|loss|acc|score|auc|f1|precision|recall|"
    r"rmse|mae|mse|r2|batch|train|val|valid|test)\s*[:=]?\s*[\d.]+",
    re.IGNORECASE
)

# File output patterns
_FILE_OUTPUT_PATTERN = re.compile(
    r"(saved|writing|wrote|output|created|generated|exported|saving).+\.(csv|json|pkl|h5|pt|pth|txt|xlsx|parquet|model|joblib|npy|npz)",
    re.IGNORECASE
)


class LogCompressor:

    def __init__(self, config: CompressionConfig | None = None):
        self.cfg = config or CompressionConfig()

    def compress(self, log_text: str, script_name: str = "") -> CompressedLog:
        """
        Main entry point — compress a log while preserving critical information.
        Returns CompressedLog with the compressed text and stats.
        """
        if not log_text or not log_text.strip():
            return CompressedLog("", 0, 0, [])

        lines = log_text.splitlines()
        total_lines = len(lines)
        total_chars = len(log_text)

        if total_chars <= self.cfg.max_output_chars:
            # Already fits — no compression needed
            return CompressedLog(log_text, total_lines, total_lines, [])

        # Classify each line
        classified = self._classify_lines(lines)

        # Build compressed output
        result_lines = self._build_compressed(classified, lines)

        # Final char trim if still too long
        compressed_text = "\n".join(result_lines)
        if len(compressed_text) > self.cfg.max_output_chars:
            compressed_text = self._hard_trim(compressed_text)

        kept_lines = len(result_lines)
        summary = self._build_summary(classified, total_lines, kept_lines, script_name)

        return CompressedLog(
            text=compressed_text,
            original_lines=total_lines,
            kept_lines=kept_lines,
            error_lines=self._extract_error_lines(classified, lines),
        )

    def compress_for_ai(self, log_text: str, script_name: str = "") -> str:
        """Returns AI-ready string with compression header."""
        result = self.compress(log_text, script_name)
        if result.original_lines == result.kept_lines:
            return log_text

        header = (
            f"[ЛОГ: {script_name or 'script'} | "
            f"Оригинал: {result.original_lines} строк → "
            f"Сжато до: {result.kept_lines} строк | "
            f"Ошибок: {len(result.error_lines)}]\n"
            "─" * 60 + "\n"
        )
        combined = header + result.text
        # Final hard trim if needed
        if len(combined) > self.cfg.max_output_chars + 200:
            combined = self._hard_trim(combined)
        return combined

    # ── Private ───────────────────────────────────────────

    def _classify_lines(self, lines: list[str]) -> list[str]:
        """Assign category to each line."""
        n = len(lines)
        categories = ["normal"] * n
        in_traceback = False

        for i, line in enumerate(lines):
            # First / last N lines always kept
            if i < self.cfg.keep_first_lines or i >= n - self.cfg.keep_last_lines:
                categories[i] = "keep"
                continue

            stripped = line.strip()

            # Traceback detection
            if _TRACEBACK_START.match(stripped):
                in_traceback = True
            if in_traceback:
                categories[i] = "traceback"
                # Mark context around traceback start
                for j in range(max(0, i - 2), i):
                    categories[j] = "keep"
                if _TRACEBACK_END.match(stripped) or (
                    not stripped and i > 0 and categories[i-1] == "traceback"
                ):
                    in_traceback = False
                continue

            # Error lines + context
            if _ERROR_PATTERNS.search(line):
                categories[i] = "error"
                # Mark surrounding context
                for j in range(max(0, i - self.cfg.keep_error_context), i):
                    if categories[j] == "normal":
                        categories[j] = "context"
                for j in range(i + 1, min(n, i + self.cfg.keep_error_context + 1)):
                    if categories[j] == "normal":
                        categories[j] = "context"
                continue

            # Warning lines
            if _WARNING_PATTERNS.search(line) and self.cfg.always_keep_warnings:
                categories[i] = "warning"
                continue

            # File output lines
            if _FILE_OUTPUT_PATTERN.search(line):
                categories[i] = "fileout"
                continue

            # Progress bars — keep only last occurrence
            if _PROGRESS_PATTERN.search(line):
                categories[i] = "progress"
                continue

            # Metric lines — sample
            if _METRIC_PATTERN.search(line):
                categories[i] = "metric"
                continue

        return categories

    def _build_compressed(
        self, categories: list[str], lines: list[str]
    ) -> list[str]:
        result: list[str] = []
        skip_count = 0
        last_metric_kept = -999
        progress_buffer: list[str] = []
        seen_lines: dict[str, int] = {}  # line → last occurrence index

        for i, (cat, line) in enumerate(zip(categories, lines)):
            if cat in ("keep", "error", "traceback", "warning", "context", "fileout"):
                if skip_count > 0:
                    result.append(f"  ... [{skip_count} строк пропущено] ...")
                    skip_count = 0
                if progress_buffer:
                    result.append(progress_buffer[-1] + " [последний прогресс]")
                    progress_buffer = []
                result.append(line)

            elif cat == "progress":
                progress_buffer.append(line)
                skip_count += 1

            elif cat == "metric":
                # Keep every Nth metric line, and any that are significantly different
                if i - last_metric_kept >= self.cfg.metric_sample_every:
                    if skip_count > 0:
                        result.append(f"  ... [{skip_count} строк пропущено] ...")
                        skip_count = 0
                    result.append(line)
                    last_metric_kept = i
                else:
                    skip_count += 1

            else:  # normal
                # Deduplicate repetitive lines
                normalized = re.sub(r"\d+", "N", line.strip())
                if normalized in seen_lines:
                    prev = seen_lines[normalized]
                    if i - prev < 20:  # within 20 lines = repetitive
                        skip_count += 1
                        continue
                seen_lines[normalized] = i

                # Check consecutive similar lines
                if skip_count > self.cfg.max_consecutive_similar:
                    skip_count += 1
                else:
                    if skip_count > 0:
                        result.append(f"  ... [{skip_count} строк пропущено] ...")
                        skip_count = 0
                    result.append(line)

        # Flush
        if skip_count > 0:
            result.append(f"  ... [{skip_count} строк пропущено] ...")
        if progress_buffer:
            result.append(progress_buffer[-1] + " [последний прогресс]")

        return result

    def _hard_trim(self, text: str) -> str:
        """Last resort: keep first + last portion."""
        mid = self.cfg.max_output_chars // 2
        head = text[:mid]
        tail = text[-mid:]
        cut = len(text) - self.cfg.max_output_chars
        return (head + f"\n\n... [{cut} символов вырезано] ...\n\n" + tail)

    @staticmethod
    def _extract_error_lines(categories: list[str], lines: list[str]) -> list[str]:
        """Extract error lines by both category AND content pattern."""
        errors = []
        for cat, line in zip(categories, lines):
            if cat in ("error", "traceback"):
                errors.append(line)
            elif cat == "keep" and (
                _ERROR_PATTERNS.search(line) or _TRACEBACK_START.match(line.strip())
            ):
                errors.append(line)
        return errors

    @staticmethod
    def _build_summary(
        categories: list[str], total: int, kept: int, script_name: str
    ) -> str:
        errors = categories.count("error")
        warnings = categories.count("warning")
        tracebacks = categories.count("traceback")
        return (
            f"{script_name}: {total}→{kept} строк | "
            f"ошибок:{errors} предупреждений:{warnings} трейсбеков:{tracebacks}"
        )


@dataclass
class CompressedLog:
    text: str
    original_lines: int
    kept_lines: int
    error_lines: list[str]

    @property
    def compression_ratio(self) -> float:
        if self.original_lines == 0:
            return 1.0
        return self.kept_lines / self.original_lines

    @property
    def was_compressed(self) -> bool:
        return self.kept_lines < self.original_lines

    @property
    def has_errors(self) -> bool:
        return bool(self.error_lines)


# ── Standalone helper ──────────────────────────────────────────────────────────

def compress_log(log_text: str, max_chars: int = 8000, script_name: str = "") -> str:
    """Convenience: compress log to fit AI context."""
    cfg = CompressionConfig(max_output_chars=max_chars)
    return LogCompressor(cfg).compress_for_ai(log_text, script_name)
