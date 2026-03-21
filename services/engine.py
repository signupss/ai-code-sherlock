"""
Application services — all business logic lives here.
"""
from __future__ import annotations
import asyncio
import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from core.interfaces import (
    IAiModelProvider, IContextCompressor, IPatchEngine,
    IPromptEngine, ISettingsManager, PatchError
)
from core.models import (
    AppSettings, ChatMessage, CodePatch, FileEntry,
    MessageRole, ModelDefinition, ModelSourceType,
    PatchBlock, PatchStatus, PatchValidationResult,
    ProjectContext, TokenBudget
)

if TYPE_CHECKING:
    from services.logger_service import StructuredLogger


# ══════════════════════════════════════════════════════
#  PATCH ENGINE
# ══════════════════════════════════════════════════════

class PatchEngine(IPatchEngine):
    """
    Parses [SEARCH_BLOCK]/[REPLACE_BLOCK] pairs from AI output
    and applies them with exact or normalized matching.
    """

    # Primary format: [SEARCH_BLOCK] ... [REPLACE_BLOCK] ... [END_PATCH]
    _BRACKET_RE = re.compile(
        r"\[SEARCH_BLOCK\]\s*\n(.*?)\n\s*\[REPLACE_BLOCK\]\s*\n(.*?)(?=\[SEARCH_BLOCK\]|\[END_PATCH\]|$)",
        re.DOTALL,
    )

    # Fenced code block format: ```search ... ``` ```replace ... ```
    _FENCED_RE = re.compile(
        r"```(?:search|find)\s*\n(.*?)```\s*\n```(?:replace|with)\s*\n(.*?)```",
        re.DOTALL,
    )

    def parse_patches(self, ai_response: str) -> list[PatchBlock]:
        if not ai_response:
            return []

        patches: list[PatchBlock] = []

        # Strategy 1: bracket format
        for m in self._BRACKET_RE.finditer(ai_response):
            search = m.group(1).strip()
            replace = m.group(2).strip()
            if search:
                patches.append(PatchBlock(search_content=search, replace_content=replace))

        # Strategy 2: fenced format (fallback)
        if not patches:
            for m in self._FENCED_RE.finditer(ai_response):
                search = m.group(1).strip()
                replace = m.group(2).strip()
                if search:
                    patches.append(PatchBlock(search_content=search, replace_content=replace))

        return patches

    def validate(self, file_content: str, patch: PatchBlock) -> PatchValidationResult:
        if not patch.search_content:
            return PatchValidationResult(
                is_valid=False, match_count=0, match_line_start=-1,
                error_message="Search block is empty"
            )

        # Exact match
        count = file_content.count(patch.search_content)
        if count == 1:
            idx = file_content.index(patch.search_content)
            line_no = file_content[:idx].count("\n") + 1
            return PatchValidationResult(is_valid=True, match_count=1, match_line_start=line_no)

        if count > 1:
            return PatchValidationResult(
                is_valid=False, match_count=count, match_line_start=-1,
                error_message=f"Ambiguous: {count} identical matches found. "
                              "Add more surrounding context to the search block."
            )

        # Normalized whitespace fallback
        if self._normalized_match_count(file_content, patch.search_content) == 1:
            return PatchValidationResult(
                is_valid=True, match_count=1, match_line_start=-1,
                error_message="Matched with whitespace normalization"
            )

        return PatchValidationResult(
            is_valid=False, match_count=0, match_line_start=-1,
            error_message="Search block not found. Check whitespace or if code was already modified."
        )

    def apply_patch(self, file_content: str, patch: PatchBlock) -> str:
        result = self.validate(file_content, patch)

        if not result.is_valid:
            raise PatchError(
                f"Cannot apply patch: {result.error_message} "
                f"(matches: {result.match_count})"
            )

        # Exact match
        if file_content.count(patch.search_content) == 1:
            return file_content.replace(patch.search_content, patch.replace_content, 1)

        # Normalized match — find actual block and replace
        return self._apply_normalized(file_content, patch)

    def _apply_normalized(self, content: str, patch: PatchBlock) -> str:
        lines = content.splitlines(keepends=True)
        search_lines = patch.search_content.splitlines()

        for i in range(len(lines) - len(search_lines) + 1):
            window = lines[i : i + len(search_lines)]
            if all(
                self._norm(a) == self._norm(b)
                for a, b in zip(window, search_lines)
            ):
                actual_block = "".join(window).rstrip("\n")
                return content.replace(actual_block, patch.replace_content, 1)

        raise PatchError("Normalized patch application failed — no match found.")

    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip())

    @staticmethod
    def _normalized_match_count(content: str, search: str) -> int:
        norm_content = " ".join(content.split())
        norm_search = " ".join(search.split())
        return norm_content.count(norm_search)


# ══════════════════════════════════════════════════════
#  PROMPT ENGINE
# ══════════════════════════════════════════════════════

class PromptEngine(IPromptEngine):

    def build_system_prompt(self, sherlock_mode: bool = False) -> str:
        base = """Ты — AI Code Sherlock, эксперт-разработчик и аналитик кода.
Специализируешься на точечных хирургических изменениях кода и поиске причин ошибок.

ФОРМАТ ОТВЕТА ДЛЯ ИЗМЕНЕНИЙ КОДА:
Всегда используй ТОЧНО такой формат:

[SEARCH_BLOCK]
<точный код для поиска — символ в символ, с пробелами>
[REPLACE_BLOCK]
<новый код замены>
[END_PATCH]

КРИТИЧЕСКИЕ ПРАВИЛА:
1. SEARCH_BLOCK должен ТОЧНО совпадать с кодом в файле (пробелы, отступы).
2. Включай только минимально необходимый кусок для замены — не весь файл.
3. Если нужно несколько замен — повтори блоки SEARCH_BLOCK/REPLACE_BLOCK.
4. Никогда не переписывай весь файл — только точечные изменения.
5. Объясни ЧТО и ПОЧЕМУ меняешь ПЕРЕД блоками патча.
6. Отвечай на языке пользователя.

ВАЖНО — РЕЖИМ ОТВЕТА:
• Если пользователь задаёт ВОПРОС (не просит изменить код) — отвечай ОБЫЧНЫМ ТЕКСТОМ без патчей.
  Примеры вопросов: "как работает...", "что такое...", "почему...", "объясни...", "расскажи..."
• Если пользователь просит ИЗМЕНИТЬ КОД — используй формат [SEARCH_BLOCK]/[REPLACE_BLOCK].
• Никогда не генерируй пустые патчи или патчи-заглушки если изменений не требуется."""

        if sherlock_mode:
            base += """

🔍 РЕЖИМ ШЕРЛОКА АКТИВЕН:
Анализируй логи ошибок и код для поиска первопричин.
Подход:
1. Точно определи тип и место ошибки
2. Мысленно проследи стек вызовов
3. Выдвини гипотезы (сначала наиболее вероятные)
4. Дай МИНИМАЛЬНЫЙ патч — чини причину, не симптом
5. Объясни логику как детектив: "Улики указывают на..."
6. Оцени уверенность: ВЫСОКАЯ / СРЕДНЯЯ / НИЗКАЯ"""

        return base

    @staticmethod
    def _is_question(request: str) -> bool:
        """Detect if user is asking a question vs requesting a code change."""
        req_lower = request.lower().strip()
        if req_lower.endswith("?"):
            return True
        question_starts = (
            "как ", "что ", "почему ", "зачем ", "когда ", "где ", "кто ",
            "расскажи", "объясни", "опиши", "поясни", "в чём", "в чем",
            "какой", "какая", "какое", "можно ли", "можешь ли",
            "how ", "what ", "why ", "when ", "where ", "who ",
            "explain", "describe", "tell me", "what is", "can you",
        )
        if any(req_lower.startswith(w) for w in question_starts):
            return True
        return False

    def build_analysis_prompt(self, request: str, context: ProjectContext) -> str:
        parts = [f"## ЗАПРОС ПОЛЬЗОВАТЕЛЯ\n{request}\n"]

        # Hint to AI about response mode based on request type
        if self._is_question(request):
            parts.append(
                "**РЕЖИМ: ВОПРОС** — Ответь развёрнутым текстом. "
                "Патчи [SEARCH_BLOCK]/[REPLACE_BLOCK] НЕ нужны.\n"
            )
        else:
            parts.append(
                "**РЕЖИМ: ИЗМЕНЕНИЕ КОДА** — Используй формат [SEARCH_BLOCK]/[REPLACE_BLOCK].\n"
            )

        if context.focused_file_path:
            parts.append(f"**Основной файл:** `{context.focused_file_path}`\n")

        if context.files:
            parts.append("## КОД ПРОЕКТА")
            for f in context.files:
                tag = " *(сжато)*" if f.is_compressed else ""
                parts.append(f"### `{f.relative_path}`{tag}")
                parts.append(f"```\n{f.content}\n```\n")

        if context.error_logs:
            parts.append(f"## ЛОГИ ОШИБОК\n```\n{context.error_logs}\n```\n")

        return "\n".join(parts)

    def build_sherlock_prompt(
        self, error_logs: str, context: ProjectContext, user_hint: str = ""
    ) -> str:
        parts = [f"## ЛОГИ ОШИБОК\n```\n{error_logs.strip()}\n```\n"]

        if user_hint:
            parts.append(f"## ПОДСКАЗКА ПОЛЬЗОВАТЕЛЯ\n{user_hint}\n")

        parts.append("## РЕЛЕВАНТНЫЙ КОД")
        for f in context.files:
            tag = " *(сжато)*" if f.is_compressed else ""
            parts.append(f"### `{f.relative_path}`{tag}")
            parts.append(f"```\n{f.content}\n```\n")

        parts.append("""## ЗАДАЧА
1. Определи первопричину ошибки (с указанием строк если возможно)
2. Объясни цепочку событий: что вызвало что
3. Дай МИНИМАЛЬНЫЙ патч в формате [SEARCH_BLOCK]/[REPLACE_BLOCK]
4. Оцени уверенность: ВЫСОКАЯ / СРЕДНЯЯ / НИЗКАЯ и объясни почему""")

        return "\n".join(parts)

    def build_patch_prompt(
        self, request: str, file_content: str, surrounding: str = ""
    ) -> str:
        parts = []
        if surrounding:
            parts.append(
                f"## КОНТЕКСТ ОКРУЖЕНИЯ (только для понимания — НЕ изменяй)\n```\n{surrounding}\n```\n"
            )
        parts.append(f"## ФАЙЛ ДЛЯ ИЗМЕНЕНИЯ\n```\n{file_content}\n```\n")
        parts.append(f"## ЗАДАЧА\n{request}\n")
        parts.append(
            "Используй формат [SEARCH_BLOCK]/[REPLACE_BLOCK] для ВСЕХ изменений.\n"
            "SEARCH_BLOCK должен ТОЧНО совпадать с содержимым файла."
        )
        return "\n".join(parts)

    def build_summarize_prompt(self, file_content: str, file_path: str) -> str:
        preview = file_content[:6000]
        return f"""Кратко опиши этот файл для использования как контекст при анализе большого проекта.
Файл: {file_path}

Сосредоточься на:
- Назначение файла (что делает)
- Публичные классы/функции и их сигнатуры
- Ключевые зависимости/импорты
- Важные паттерны или проблемы

Не более 150 слов. Только технические факты, без деталей реализации.

КОД:
```
{preview}
```"""


# ══════════════════════════════════════════════════════
#  CONTEXT COMPRESSOR
# ══════════════════════════════════════════════════════

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".cs", ".cpp", ".c", ".h", ".swift", ".kt", ".rb", ".php",
    ".sql", ".json", ".yaml", ".yml", ".toml", ".xml", ".md"
}

IGNORED_DIRS = {
    ".git", "node_modules", "bin", "obj", "__pycache__", ".pytest_cache",
    "dist", "build", ".venv", "venv", "env", ".idea", ".vs",
}


class ContextCompressor(IContextCompressor):

    def __init__(self, provider: IAiModelProvider, prompt_engine: IPromptEngine, logger=None):
        self._provider = provider
        self._prompt = prompt_engine
        self._logger = logger

    async def compress(
        self,
        context: ProjectContext,
        budget: TokenBudget,
    ) -> ProjectContext:
        if self._fits(context, budget):
            return context  # No compression needed

        if self._logger:
            self._logger.info(
                f"Compressing {len(context.files)} files "
                f"(~{context.total_token_estimate} tokens → budget {budget.available_for_context})",
                source="ContextCompressor"
            )

        # Step 1: Separate focused (never compress) from others
        focused = [f for f in context.files if f.is_focused]
        others = [f for f in context.files if not f.is_focused]

        # Step 2: Score others by relevance to focused file
        focused_terms = self._extract_terms(
            " ".join(f.content for f in focused)
        )
        scored = sorted(others, key=lambda f: self._score(f, focused_terms), reverse=True)

        # Step 3: Fill budget greedily
        used_tokens = sum(TokenBudget.estimate_tokens(f.content) for f in focused) + 200
        included: list[FileEntry] = []
        to_summarize: list[FileEntry] = []

        for f in scored:
            ft = TokenBudget.estimate_tokens(f.content)
            if used_tokens + ft <= int(budget.available_for_context * 0.75):
                included.append(f)
                used_tokens += ft
            else:
                to_summarize.append(f)

        # Step 4: Parallel summarization (max 4 concurrent)
        semaphore = asyncio.Semaphore(4)
        summarized = await asyncio.gather(
            *[self._summarize(f, semaphore) for f in to_summarize]
        )

        final_files = focused + included + list(summarized)

        if self._logger:
            self._logger.info(
                f"Compressed: {len(included)} full + {len(summarized)} summarized",
                source="ContextCompressor"
            )

        return ProjectContext(
            files=final_files,
            root_path=context.root_path,
            focused_file_path=context.focused_file_path,
            error_logs=context.error_logs,
        )

    async def _summarize(
        self, file: FileEntry, semaphore: asyncio.Semaphore
    ) -> FileEntry:
        async with semaphore:
            try:
                prompt = self._prompt.build_summarize_prompt(file.content, file.relative_path)
                msgs = [ChatMessage(role=MessageRole.USER, content=prompt)]
                summary = await self._provider.complete(msgs)
                compressed = f"// [SUMMARY: {file.relative_path}]\n{summary.strip()}"
            except Exception as e:
                if self._logger:
                    self._logger.warning(
                        f"Failed to summarize {file.relative_path}: {e}",
                        source="ContextCompressor"
                    )
                compressed = self._extract_signatures(file.content, file.extension)

            return FileEntry(
                path=file.path,
                relative_path=file.relative_path,
                content=compressed,
                extension=file.extension,
                is_focused=False,
                is_compressed=True,
                summary=compressed,
            )

    @staticmethod
    def _fits(context: ProjectContext, budget: TokenBudget) -> bool:
        combined = "\n".join(f.content for f in context.files)
        return budget.can_fit(combined)

    @staticmethod
    def _extract_terms(text: str) -> set[str]:
        tokens = re.findall(r"\b([A-Z][a-zA-Z0-9]+|[a-z][a-zA-Z0-9]{3,})\b", text)
        return set(t for t in tokens if len(t) >= 3)

    def _score(self, file: FileEntry, terms: set[str]) -> float:
        file_terms = self._extract_terms(file.content)
        overlap = len(terms & file_terms)
        tokens = TokenBudget.estimate_tokens(file.content)
        penalty = max(0, (tokens - 5000) / 1000)
        ext_bonus = 1.0 if file.extension in CODE_EXTENSIONS else 0.0
        return overlap * 2.0 + ext_bonus - penalty

    @staticmethod
    def _extract_signatures(content: str, ext: str) -> str:
        """Fallback: extract function/class definitions."""
        lines = content.splitlines()
        if ext == ".py":
            sigs = [
                l for l in lines
                if l.strip().startswith(("def ", "class ", "async def ", "@"))
            ]
            return f"# [AUTO-SIGNATURES: {ext}]\n" + "\n".join(sigs[:80])
        # Generic: first 40 lines
        return "# [TRUNCATED — FIRST 40 LINES]\n" + "\n".join(lines[:40])


# ══════════════════════════════════════════════════════
#  MODEL MANAGER
# ══════════════════════════════════════════════════════

class ModelManager:

    def __init__(self, settings_manager: ISettingsManager, logger=None):
        self._settings_mgr = settings_manager
        self._logger = logger
        self._active_provider: Optional[IAiModelProvider] = None
        self._settings: Optional[AppSettings] = None

    @property
    def active_provider(self) -> Optional[IAiModelProvider]:
        return self._active_provider

    @property
    def active_model(self) -> Optional[ModelDefinition]:
        return self._active_provider.model if self._active_provider else None

    def load(self) -> AppSettings:
        self._settings = self._settings_mgr.load()
        return self._settings

    def save(self, settings: AppSettings) -> None:
        self._settings = settings
        self._settings_mgr.save(settings)

    async def switch_model(self, model: ModelDefinition) -> None:
        provider = self._create_provider(model)

        available = await provider.is_available()
        if not available and self._logger:
            self._logger.warning(
                f"Model '{model.display_name}' availability check failed.",
                source="ModelManager"
            )

        self._active_provider = provider
        if self._logger:
            self._logger.info(
                f"Active model: {model.display_name} [{model.source_type.value}]",
                source="ModelManager"
            )

    async def get_provider_by_id(self, model_id: str) -> Optional[IAiModelProvider]:
        """Create a provider for a model by its ID. Used by consensus engine."""
        if not self._settings:
            self._settings = self._settings_mgr.load()
        model = next((m for m in self._settings.models if m.id == model_id), None)
        if not model:
            return None
        return self._create_provider(model)

    def get_all_model_ids(self) -> list[tuple[str, str]]:
        """Returns list of (id, display_name) for all configured models."""
        if not self._settings:
            self._settings = self._settings_mgr.load()
        return [(m.id, m.display_name) for m in self._settings.models]

    def _create_provider(self, model: ModelDefinition) -> IAiModelProvider:
        from providers.providers import OllamaProvider, CustomApiProvider, FileSignalProvider, FileSignalService

        if model.source_type == ModelSourceType.OLLAMA:
            return OllamaProvider(model, self._logger)
        elif model.source_type == ModelSourceType.CUSTOM_API:
            return CustomApiProvider(model, self._logger)
        elif model.source_type == ModelSourceType.FILE_SIGNAL:
            svc = FileSignalService()
            return FileSignalProvider(model, svc, self._logger)
        else:
            raise ValueError(f"Unknown source type: {model.source_type}")


# ══════════════════════════════════════════════════════
#  SHERLOCK ANALYZER
# ══════════════════════════════════════════════════════

class SherlockResult:
    def __init__(
        self,
        analysis: str,
        patches: list[PatchBlock],
        tokens_used: int,
        model_name: str,
    ):
        self.analysis = analysis
        self.patches = patches
        self.tokens_used = tokens_used
        self.model_name = model_name


class SherlockRequest:
    def __init__(
        self,
        error_logs: str,
        context: ProjectContext,
        user_hint: str = "",
    ):
        self.error_logs = error_logs
        self.context = context
        self.user_hint = user_hint


class SherlockAnalyzer:

    def __init__(
        self,
        model_manager: ModelManager,
        compressor: IContextCompressor,
        prompt_engine: IPromptEngine,
        patch_engine: IPatchEngine,
        logger=None,
    ):
        self._mm = model_manager
        self._comp = compressor
        self._prompt = prompt_engine
        self._patch = patch_engine
        self._logger = logger

    async def analyze(
        self,
        request: SherlockRequest,
        progress_callback=None,
    ) -> SherlockResult:
        if not self._mm.active_provider:
            raise RuntimeError("No model selected")

        if self._logger:
            self._logger.info("Sherlock analysis started...", source="SherlockAnalyzer")

        if progress_callback:
            progress_callback("Сжимаю контекст...")

        # Compress context
        budget = TokenBudget(
            max_tokens=self._mm.active_model.max_context_tokens
            if self._mm.active_model else 8192
        )
        compressed = await self._comp.compress(request.context, budget)

        if progress_callback:
            progress_callback("Строю промпт...")

        # Build messages
        system = self._prompt.build_system_prompt(sherlock_mode=True)
        user_msg = self._prompt.build_sherlock_prompt(
            request.error_logs, compressed, request.user_hint
        )

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=system),
            ChatMessage(role=MessageRole.USER, content=user_msg),
        ]

        if progress_callback:
            progress_callback("Запрашиваю AI...")

        response = await self._mm.active_provider.complete(messages)
        patches = self._patch.parse_patches(response)

        if self._logger:
            self._logger.info(
                f"Analysis complete. {len(patches)} patch(es) found.",
                source="SherlockAnalyzer"
            )

        return SherlockResult(
            analysis=response,
            patches=patches,
            tokens_used=TokenBudget.estimate_tokens(user_msg),
            model_name=self._mm.active_model.display_name
            if self._mm.active_model else "Unknown",
        )
