"""
Abstract interfaces — all concrete implementations depend on these.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import (
        ChatMessage, ModelDefinition, PatchBlock,
        PatchValidationResult, ProjectContext, TokenBudget,
        AppSettings, LogEntry
    )


class IAiModelProvider(ABC):
    """Universal AI provider abstraction."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model(self) -> "ModelDefinition": ...

    @abstractmethod
    async def complete(
        self,
        messages: list["ChatMessage"],
    ) -> str:
        """Non-streaming completion."""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list["ChatMessage"],
    ) -> AsyncGenerator[str, None]:
        """Streaming completion — yields token chunks."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Health check."""
        ...


class IPatchEngine(ABC):

    @abstractmethod
    def parse_patches(self, ai_response: str) -> list["PatchBlock"]:
        """Extract all SEARCH/REPLACE blocks from AI text."""
        ...

    @abstractmethod
    def apply_patch(self, file_content: str, patch: "PatchBlock") -> str:
        """Apply patch. Raises PatchError on failure."""
        ...

    @abstractmethod
    def validate(self, file_content: str, patch: "PatchBlock") -> "PatchValidationResult":
        """Check applicability without modifying content."""
        ...


class IContextCompressor(ABC):

    @abstractmethod
    async def compress(
        self,
        context: "ProjectContext",
        budget: "TokenBudget",
    ) -> "ProjectContext":
        ...


class IPromptEngine(ABC):

    @abstractmethod
    def build_system_prompt(self, sherlock_mode: bool = False) -> str: ...

    @abstractmethod
    def build_analysis_prompt(self, request: str, context: "ProjectContext") -> str: ...

    @abstractmethod
    def build_sherlock_prompt(
        self, error_logs: str, context: "ProjectContext", user_hint: str = ""
    ) -> str: ...

    @abstractmethod
    def build_patch_prompt(
        self, request: str, file_content: str, surrounding: str = ""
    ) -> str: ...

    @abstractmethod
    def build_summarize_prompt(self, file_content: str, file_path: str) -> str: ...


class ISettingsManager(ABC):

    @abstractmethod
    def load(self) -> "AppSettings": ...

    @abstractmethod
    def save(self, settings: "AppSettings") -> None: ...


class IStructuredLogger(ABC):

    @abstractmethod
    def log(self, entry: "LogEntry") -> None: ...

    @abstractmethod
    def get_recent(self, count: int = 100) -> list["LogEntry"]: ...

    @abstractmethod
    def export(self, file_path: str) -> None: ...

    @abstractmethod
    def subscribe(self, callback) -> None:
        """Register callback(LogEntry) for real-time log streaming."""
        ...


class IFileSignalService(ABC):

    @abstractmethod
    async def send_request(
        self,
        request_id: str,
        prompt: str,
        request_folder: str,
        response_folder: str,
        timeout_seconds: int,
    ) -> str:
        ...


class PatchError(Exception):
    pass
