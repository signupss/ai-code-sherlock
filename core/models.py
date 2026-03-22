"""
Core domain models — pure dataclasses, zero external dependencies.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────
#  Enums
# ─────────────────────────────────────────────

class ModelSourceType(str, Enum):
    OLLAMA      = "ollama"
    CUSTOM_API  = "custom_api"
    FILE_SIGNAL = "file_signal"   # ZennoPoster / web model IPC


class MessageRole(str, Enum):
    SYSTEM    = "system"
    USER      = "user"
    ASSISTANT = "assistant"


class PatchStatus(str, Enum):
    PENDING  = "pending"
    PREVIEWED = "previewed"
    APPLIED  = "applied"
    REJECTED = "rejected"
    FAILED   = "failed"


class LogLevel(str, Enum):
    DEBUG   = "DEBUG"
    INFO    = "INFO"
    WARNING = "WARNING"
    ERROR   = "ERROR"


# ─────────────────────────────────────────────
#  Value Objects
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class PatchBlock:
    """Immutable SEARCH/REPLACE pair parsed from AI response."""
    search_content: str
    replace_content: str
    file_path: Optional[str] = None
    description: Optional[str] = None


@dataclass(frozen=True)
class TokenBudget:
    max_tokens: int
    reserved_for_response: int = 1024

    @property
    def available_for_context(self) -> int:
        return self.max_tokens - self.reserved_for_response

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough: 1 token ≈ 4 chars for code/English."""
        return max(1, len(text or "") // 4)

    def can_fit(self, text: str) -> bool:
        return self.estimate_tokens(text) <= self.available_for_context

    @classmethod
    def default(cls) -> "TokenBudget":
        return cls(max_tokens=8192)

    @classmethod
    def large(cls) -> "TokenBudget":
        return cls(max_tokens=32768, reserved_for_response=2048)


@dataclass(frozen=True)
class PatchValidationResult:
    is_valid: bool
    match_count: int        # 0=not found, >1=ambiguous
    match_line_start: int   # -1 if unknown
    error_message: Optional[str] = None


# ─────────────────────────────────────────────
#  Entities
# ─────────────────────────────────────────────

@dataclass
class ChatMessage:
    role: MessageRole
    content: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    model_name: Optional[str] = None
    is_error: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass
class ModelDefinition:
    name: str
    display_name: str
    source_type: ModelSourceType
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Ollama
    ollama_base_url: str = "http://localhost:11434"

    # Custom API (OpenAI-compatible)
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_model_id: Optional[str] = None
    custom_headers: dict = field(default_factory=dict)

    # File Signal
    signal_request_folder: Optional[str] = None
    signal_response_folder: Optional[str] = None
    signal_timeout_seconds: int = 60

    # Shared
    max_context_tokens: int = 8192
    temperature: float = 0.2
    is_default: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "source_type": self.source_type.value,
            "ollama_base_url": self.ollama_base_url,
            "api_base_url": self.api_base_url,
            "api_key": self.api_key,
            "api_model_id": self.api_model_id,
            "custom_headers": self.custom_headers,
            "signal_request_folder": self.signal_request_folder,
            "signal_response_folder": self.signal_response_folder,
            "signal_timeout_seconds": self.signal_timeout_seconds,
            "max_context_tokens": self.max_context_tokens,
            "temperature": self.temperature,
            "is_default": self.is_default,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ModelDefinition":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", ""),
            display_name=d.get("display_name", ""),
            source_type=ModelSourceType(d.get("source_type", "ollama")),
            ollama_base_url=d.get("ollama_base_url", "http://localhost:11434"),
            api_base_url=d.get("api_base_url"),
            api_key=d.get("api_key"),
            api_model_id=d.get("api_model_id"),
            custom_headers=d.get("custom_headers", {}),
            signal_request_folder=d.get("signal_request_folder"),
            signal_response_folder=d.get("signal_response_folder"),
            signal_timeout_seconds=d.get("signal_timeout_seconds", 60),
            max_context_tokens=d.get("max_context_tokens", 8192),
            temperature=d.get("temperature", 0.2),
            is_default=d.get("is_default", False),
        )


@dataclass
class CodePatch:
    file_path: str
    original_content: str
    patched_content: str
    search_block: str
    replace_block: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: Optional[str] = None
    status: PatchStatus = PatchStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    applied_at: Optional[datetime] = None
    error_message: Optional[str] = None

    @property
    def lines_changed(self) -> int:
        return abs(
            len(self.replace_block.splitlines()) -
            len(self.search_block.splitlines())
        )


@dataclass
class FileEntry:
    path: str
    relative_path: str
    content: str
    extension: str
    is_focused: bool = False
    is_compressed: bool = False
    summary: Optional[str] = None

    @property
    def token_estimate(self) -> int:
        return TokenBudget.estimate_tokens(self.content)


@dataclass
class ProjectContext:
    files: list[FileEntry] = field(default_factory=list)
    root_path: Optional[str] = None
    focused_file_path: Optional[str] = None
    error_logs: Optional[str] = None
    summaries: dict[str, str] = field(default_factory=dict)

    @property
    def total_token_estimate(self) -> int:
        return sum(f.token_estimate for f in self.files)


@dataclass
class LogEntry:
    level: LogLevel
    message: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: Optional[str] = None
    exception: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    properties: dict = field(default_factory=dict)

    @property
    def formatted(self) -> str:
        src = f"[{self.source}] " if self.source else ""
        exc = f"\n  EXC: {self.exception}" if self.exception else ""
        return f"[{self.timestamp.strftime('%H:%M:%S.%f')[:-3]}] [{self.level.value}] {src}{self.message}{exc}"


@dataclass
class AppSettings:
    models: list[ModelDefinition] = field(default_factory=list)
    default_model_id: Optional[str] = None
    signal_request_folder: str = "signals/request"
    signal_response_folder: str = "signals/response"
    sherlock_mode_enabled: bool = False
    send_logs_to_ai: bool = False
    theme: str = "dark"
    recent_projects: dict[str, str] = field(default_factory=dict)
    window_geometry: Optional[dict] = None
    # Context & token settings
    compress_context: bool = True
    max_conversation_history: int = 12
    include_full_logs: bool = False
    max_file_chars: int = 6000
    max_log_chars: int = 8000
    # Manual chat AI request settings
    chat_timeout_seconds: int = 600   # seconds to wait for AI response in chat
    chat_retry_count: int = 3         # retries on empty/timeout response in chat
    # Appearance
    accent_color: str = "#7AA2F7"   # primary accent (buttons, highlights)
    ui_font_size: int = 11          # global UI font point size
    language: str = "ru"            # "ru" | "en"

    def to_dict(self) -> dict:
        return {
            "models": [m.to_dict() for m in self.models],
            "default_model_id": self.default_model_id,
            "signal_request_folder": self.signal_request_folder,
            "signal_response_folder": self.signal_response_folder,
            "sherlock_mode_enabled": self.sherlock_mode_enabled,
            "send_logs_to_ai": self.send_logs_to_ai,
            "theme": self.theme,
            "recent_projects": self.recent_projects,
            "window_geometry": self.window_geometry,
            "compress_context": self.compress_context,
            "max_conversation_history": self.max_conversation_history,
            "include_full_logs": self.include_full_logs,
            "max_file_chars": self.max_file_chars,
            "max_log_chars": self.max_log_chars,
            "chat_timeout_seconds": self.chat_timeout_seconds,
            "chat_retry_count": self.chat_retry_count,
            "accent_color": self.accent_color,
            "ui_font_size": self.ui_font_size,
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AppSettings":
        return cls(
            models=[ModelDefinition.from_dict(m) for m in d.get("models", [])],
            default_model_id=d.get("default_model_id"),
            signal_request_folder=d.get("signal_request_folder", "signals/request"),
            signal_response_folder=d.get("signal_response_folder", "signals/response"),
            sherlock_mode_enabled=d.get("sherlock_mode_enabled", False),
            send_logs_to_ai=d.get("send_logs_to_ai", False),
            theme=d.get("theme", "dark"),
            recent_projects=d.get("recent_projects", {}),
            window_geometry=d.get("window_geometry"),
            compress_context=d.get("compress_context", True),
            max_conversation_history=d.get("max_conversation_history", 12),
            include_full_logs=d.get("include_full_logs", False),
            max_file_chars=d.get("max_file_chars", 6000),
            max_log_chars=d.get("max_log_chars", 8000),
            chat_timeout_seconds=d.get("chat_timeout_seconds", 600),
            chat_retry_count=d.get("chat_retry_count", 3),
            accent_color=d.get("accent_color", "#7AA2F7"),
            ui_font_size=d.get("ui_font_size", 11),
            language=d.get("language", "ru"),
        )
