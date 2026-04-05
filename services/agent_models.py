"""
Agent Constructor — Data Models

Core models for the visual AI agent workflow system:
  - Skill: a capability that an agent can use (code generation, image analysis, etc.)
  - AgentNode: a single agent in the workflow graph with model/skills/settings
  - AgentEdge: a directed connection between two agents with condition logic
  - AgentWorkflow: the complete workflow graph (serializable to JSON)
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────────────────
#  Enums
# ──────────────────────────────────────────────────────────

class AgentType(str, Enum):
    """What kind of work this agent does."""
    CODE_WRITER    = "code_writer"       # Generates / patches code
    CODE_REVIEWER  = "code_reviewer"     # Reviews code, finds bugs
    TESTER         = "tester"            # Runs tests, validates output
    PLANNER        = "planner"           # Plans architecture, breaks tasks
    IMAGE_GEN      = "image_gen"         # Generates images via AI
    IMAGE_ANALYST  = "image_analyst"     # Analyzes screenshots / images
    FILE_MANAGER   = "file_manager"      # Creates/reads/organizes files
    SCRIPT_RUNNER  = "script_runner"     # Executes scripts, captures output
    VERIFIER       = "verifier"          # Cross-checks output with another model
    ORCHESTRATOR   = "orchestrator"      # Calls other agents dynamically
    PATCHER        = "patcher"           # Fixes code based on error logs
    CODE_SNIPPET   = "code_snippet"      # Runs user-defined code directly (no AI)
    IF_CONDITION   = "if_condition"      # Conditional branch based on expression
    LOOP           = "loop"              # Repeats next nodes N times or until condition
    VARIABLE_SET   = "variable_set"      # Sets variable in shared context
    HTTP_REQUEST   = "http_request"      # Makes HTTP request, stores result
    DELAY          = "delay"             # Waits N seconds
    LOG_MESSAGE    = "log_message"       # Logs message to execution log
    SWITCH         = "switch"            # Multiple-choice branch by variable value
    GOOD_END       = "good_end"          # Successful workflow completion with reporting
    BAD_END        = "bad_end"           # Error workflow completion with logging/recovery
    NOTIFICATION   = "notification"      # User notification (log, popup, file)
    JS_SNIPPET     = "js_snippet"        # Execute JavaScript code
    PROGRAM_LAUNCH = "program_launch"    # Launch external program/script
    LIST_OPERATION = "list_operation"    # Operations on lists (add, remove, sort, etc.)
    TABLE_OPERATION = "table_operation"  # Operations on tables (CSV, rows, columns, cells)
    FILE_OPERATION  = "file_operation"   # Read, write, copy, move, delete files
    DIR_OPERATION   = "dir_operation"    # Create, copy, move, delete, list directories
    TEXT_PROCESSING = "text_processing"  # Regex, replace, split, spintax, trim, encode
    JSON_XML        = "json_xml"         # Parse, query (JsonPath/XPath), transform JSON/XML
    VARIABLE_PROC   = "variable_proc"    # Set, increment, decrement, clear variables
    RANDOM_GEN      = "random_gen"       # Generate random numbers, strings, logins
    NOTE           = "note"              # Visual note on canvas (not executed)
    CUSTOM         = "custom"            # User-defined with custom prompt
    # ── Браузер ──────────────────────────────────────────────────────────────
    BROWSER_LAUNCH = "browser_launch"    # Запустить браузер (инстанс)
    BROWSER_ACTION = "browser_action"    # Действие браузера (клик, ввод и т.д.)
    BROWSER_CLOSE  = "browser_close"     # Закрыть браузер / инстанс
    BROWSER_AGENT  = "browser_agent"     # Новый AI-агент с пониманием DOM + контекст Planner
    BROWSER_SCREENSHOT  = "browser_screenshot"
    BROWSER_CLICK_IMAGE = "browser_click_image"   # Клик по шаблону картинки
    BROWSER_PROFILE_OP  = "browser_profile_op"
    PROJECT_INFO        = "project_info"
    PROJECT_START       = "project_start"
    # ── Программы (автоматизация внешних приложений) ──
    PROGRAM_OPEN        = "program_open"
    PROGRAM_ACTION      = "program_action"
    PROGRAM_CLICK_IMAGE = "program_click_image"
    PROGRAM_SCREENSHOT  = "program_screenshot"
    PROGRAM_AGENT       = "program_agent"       # AI-агент управления программой
    BROWSER_PARSE       = "browser_parse"       # Парсинг текста с браузера (интерактивный)
    PROGRAM_INSPECTOR   = "program_inspector"   # Чтение всех элементов открытой программы
    PROJECT_IN_PROJECT  = "project_in_project"  # Выполнить вложенный проект как подпроект


class EdgeCondition(str, Enum):
    """When to follow this edge."""
    ALWAYS       = "always"          # Always follow after agent completes
    ON_SUCCESS   = "on_success"      # Only if agent succeeded
    ON_FAILURE   = "on_failure"      # Only if agent failed
    ON_CONDITION = "on_condition"     # Custom condition expression


class SkillCategory(str, Enum):
    CODE        = "code"
    TESTING     = "testing"
    DESIGN      = "design"
    DATA        = "data"
    DEVOPS      = "devops"
    WRITING     = "writing"
    ANALYSIS    = "analysis"
    CUSTOM      = "custom"


class WorkflowStatus(str, Enum):
    DRAFT     = "draft"
    READY     = "ready"
    RUNNING   = "running"
    PAUSED    = "paused"
    COMPLETED = "completed"
    FAILED    = "failed"


# ──────────────────────────────────────────────────────────
#  Skill
# ──────────────────────────────────────────────────────────

@dataclass
class Skill:
    """A capability that an agent can use."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    category: SkillCategory = SkillCategory.CUSTOM
    system_prompt: str = ""         # Injected into the agent's system prompt
    example_input: str = ""         # Example of what this skill expects
    example_output: str = ""        # Example of what this skill produces
    required_tools: list[str] = field(default_factory=list)  # e.g. ["script_runner", "file_io"]
    icon: str = "🔧"
    version: str = "1.0"
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Skill:
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        if "category" in valid and isinstance(valid["category"], str):
            valid["category"] = SkillCategory(valid["category"])
        return cls(**valid)


# ──────────────────────────────────────────────────────────
#  Agent Node
# ──────────────────────────────────────────────────────────

@dataclass
class AgentNode:
    """A single agent in the workflow."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "Новый агент"
    agent_type: AgentType = AgentType.CUSTOM
    description: str = ""

    # Position in the visual editor (pixels)
    x: float = 100.0
    y: float = 100.0
    width: float = 200.0
    height: float = 120.0

    # AI Model configuration
    model_id: str = ""                 # References ModelDefinition.id from AppSettings
    text_model_id: str = ""            # For text tasks
    vision_model_id: str = ""          # For image/screenshot tasks
    temperature: float = 0.2
    max_tokens: int = 4096

    # Skills assigned to this agent
    skill_ids: list[str] = field(default_factory=list)

    # Prompt configuration
    system_prompt: str = ""            # Custom system prompt (merged with skills)
    user_prompt_template: str = ""     # Template with {input}, {context}, {files} placeholders
    output_format: str = ""            # Expected output format hint

    # Execution settings
    timeout_seconds: int = 600
    retry_count: int = 2
    # ═══ Верификация (новая система) ═══
    verification_enabled: bool = False      # Включена ли верификация
    verification_mode: str = "self_check"   # "self_check", "another_model", "custom_agent"
    verification_prompt: str = ""         # Дополнительные инструкции для верификатора
    verification_model_id: str = ""       # Модель для верификации (если another_model)
    verification_strict: bool = False     # Останавливаться ли при провале верификации
    
    # ═══ Browser Agent Preprocessing (предобработка планера) ═══
    planner_preprocess: bool = False        # Разбивать план на задачи и выполнять по очереди
    planner_task_separator: str = "auto"    # "auto", "numbered", "bullet", "header", "regex"
    planner_task_regex: str = ""            # Кастомный regex для разделения (если separator="regex")
    delay_between_tasks: float = 0.5        # Пауза между задачами (сек)
    stop_on_task_error: bool = False        # Остановить при ошибке или продолжить
    
    # DEPRECATED: старые поля для совместимости
    auto_verify: bool = False          # Cross-check with verifier agent
    verifier_agent_id: str = ""        # Which agent verifies this one

    # Input/Output
    input_files: list[str] = field(default_factory=list)    # File paths this agent reads
    output_files: list[str] = field(default_factory=list)   # File paths this agent creates
    working_dir: str = ""

    # Visual
    color: str = "#7AA2F7"             # Node color in editor
    icon: str = "🤖"
    
    # ═══ Кастомизация визуала ═══
    custom_color: str = ""             # Пользовательский цвет ноды (hex, пустой = авто)
    comment: str = ""                  # Комментарий, отображается под нодой на канвасе
    note_content: str = ""             # Содержимое заметки (только для NOTE)
    note_color: str = "#E0AF68"        # Цвет фона заметки
    
    # ═══ Модели (специализация) ═══
    reasoning_model_id: str = ""      # Для сложных рассуждений (GPT-4, Claude)
    vision_model_id: str = ""         # Для анализа UI/скриншотов
    fast_model_id: str = ""           # Для простых задач (Haiku, 3.5-turbo)
    skill_analysis_model_id: str = "" # Для выбора скиллов перед стартом
    
    # ═══ Инструменты (Tools) ═══
    available_tools: list[str] = field(default_factory=list)  
    # ["file_read", "file_write", "shell_exec", "browser_navigate", 
    #  "browser_click", "browser_screenshot", "code_execute", "patch_apply"]
    tool_timeout: int = 300           # секунды
    sandbox_enabled: bool = False     # Изолированное выполнение кода
    
    # ═══ Выполнение (Execution) ═══
    execution_mode: str = "sequential"  # sequential, parallel, event_driven
    pre_condition: str = ""           # Python expression или LLM-prompt условия
    post_validation: str = ""         # Критерии успеха (может быть JSON schema)
    fallback_agent_id: str = ""       # Кто выполняет при ошибке
    retry_count: int = 2              # Повторы при неудаче
    backoff_strategy: str = "linear"  # linear, exponential, fixed
    
    # ═══ Автоматизация (Auto) ═══
    auto_test: bool = False           # Автотестирование результата
    auto_patch: bool = False          # Автопатчинг ошибок
    auto_improve: bool = False        # Самоулучшение промптов
    max_iterations: int = 3           # Лимит итераций самоулучшения
    
    # ═══ Контекст и Память ═══
    context_strategy: str = "full"    # full, sliding_window, summary, vector_db
    context_window: int = 128000      # Токены для контекста
    memory_enabled: bool = False      # Сохранять state между шагами
    checkpoint_enabled: bool = False  # Точки восстановления
    global_context_injection: str = "" # Дополнительный контекст для всех вызовов
    
    # ═══ Оркестрация (Flow Control) ═══
    orchestration_mode: str = "static"  # static, llm_router, conditional
    next_agent_selector: str = ""     # Prompt для LLM: "Кто следующий?"
    parallel_agents: list[str] = field(default_factory=list)  # Для parallel mode
    conditional_branches: list[dict] = field(default_factory=list)  
    # [{"condition": "result['status'] == 'success'", "target": "agent_id"}]
    
    # ═══ Валидация и Контроль ═══
    output_schema: dict = field(default_factory=dict)  # JSON Schema валидации
    strict_validation: bool = False   # Ошибка при невалидном выходе
    human_in_the_loop: bool = False   # Пауза для подтверждения
    breakpoint_enabled: bool = False  # Остановка перед стартом
    
    # ═══ Скиллы (Dynamic Loading) ═══
    auto_load_skills: bool = False    # Автоподбор скиллов по задаче
    skill_matching_threshold: float = 0.7  # Точность подбора скиллов
    dynamic_skill_injection: bool = False  # Может ли агент запросить новый скилл
    
    # ═══ Самомодификация ═══
    allow_self_modification: bool = False  # Может ли менять свой код
    patch_target_files: list[str] = field(default_factory=list)
    modification_scope: str = "none"  # none, prompt_only, full_agent
    
    # ═══ Визуализация Runtime ═══
    show_execution_preview: bool = True  # Показывать что будет делать
    execution_color: str = "#7AA2F7"  # Цвет при выполнении
    min_execution_time: int = 0       # Минимальное время показа (для UX)
    
    # ═══ Метаданные проекта ═══
    project_files: list[str] = field(default_factory=list)  # Связанные файлы
    generated_artifacts: list[str] = field(default_factory=list)  # Что создал
    test_cases: list[dict] = field(default_factory=list)  # Тесты для авто-проверки
    snippet_config: dict = field(default_factory=dict)     # Per-type настройки сниппета

    # Runtime state (not serialized)
    _status: str = "idle"              # idle / running / success / failed
    _last_output: str = ""
    _last_error: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        # Remove runtime state
        d.pop("_status", None)
        d.pop("_last_output", None)
        d.pop("_last_error", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> AgentNode:
        # Filter out runtime fields and unknown keys
        valid = {}
        for k, v in d.items():
            if k.startswith("_"):
                continue
            if k in cls.__dataclass_fields__:
                valid[k] = v
        if "agent_type" in valid and isinstance(valid["agent_type"], str):
            valid["agent_type"] = AgentType(valid["agent_type"])
        return cls(**valid)


# ──────────────────────────────────────────────────────────
#  Agent Edge
# ──────────────────────────────────────────────────────────

@dataclass
class AgentEdge:
    """A directed connection between two agents."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    source_id: str = ""                # AgentNode.id
    target_id: str = ""                # AgentNode.id
    condition: EdgeCondition = EdgeCondition.ALWAYS
    condition_expr: str = ""           # Python expression for ON_CONDITION
    label: str = ""                    # Visual label on the edge
    pass_output: bool = True           # Pass source output as target input
    priority: int = 0                  # Higher = evaluated first (for branching)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["condition"] = self.condition.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> AgentEdge:
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        if "condition" in valid and isinstance(valid["condition"], str):
            valid["condition"] = EdgeCondition(valid["condition"])
        return cls(**valid)


# ──────────────────────────────────────────────────────────
#  Agent Workflow
# ──────────────────────────────────────────────────────────

@dataclass
class AgentWorkflow:
    """Complete workflow graph — the main document."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "Новый проект"
    description: str = ""
    version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Graph
    nodes: list[AgentNode] = field(default_factory=list)
    edges: list[AgentEdge] = field(default_factory=list)

    # Global settings
    project_root: str = ""             # Working directory for the whole project
    entry_node_id: str = ""            # Which node starts execution
    global_context: str = ""           # Injected into all agents
    skill_preprocessing_model_id: str = ""  # Model to pre-process skills before execution
    
    # ═══ Переменные проекта (как в ZennoPoster) ═══
    project_variables: dict = field(default_factory=dict)
    # Формат: {"var_name": {"value": "...", "type": "string|int|list|json", "default": "...", "description": "..."}}
    
    # ═══ Заметки проекта ═══
    project_notes: list = field(default_factory=list)

    # ═══ Метаданные (списки, таблицы и прочее расширяемое) ═══
    metadata: dict = field(default_factory=dict)

    # Execution settings
    max_total_steps: int = 0  # 0 = бесконечный (только ручная остановка)
    max_parallel_agents: int = 3
    auto_improve: bool = False         # Auto-iterate on failures
    auto_improve_max: int = 5
 
    # ═══ Многопоточные настройки проекта (стиль ZennoPoster) ═══
    execution_max_threads: int = 1         # Макс потоков для этого проекта
    execution_total_runs: int = 1          # Сколько раз выполнить (-1 = ∞)
    execution_thread_mode: str = "sequential"  # sequential / parallel / semaphore_wait
    execution_priority: int = 5            # Приоритет 1-10
    execution_labels: list = field(default_factory=list)  # Метки/теги
    execution_bottleneck_id: str = ""      # ID узкого сниппета
    execution_bottleneck_limit: int = 1    # Лимит параллельности bottleneck
    execution_schedule_enabled: bool = False
    execution_schedule_cron: str = ""
    execution_stop_condition: str = "none" # none/on_first_error/on_n_errors/on_success_count/on_time_limit
    execution_stop_value: int = 0
    close_browser_on_finish: bool = True  # Закрывать браузер по завершении workflow

    # Status
    status: WorkflowStatus = WorkflowStatus.DRAFT

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": datetime.now().isoformat(),
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "project_root": self.project_root,
            "entry_node_id": self.entry_node_id,
            "global_context": self.global_context,
            "skill_preprocessing_model_id": self.skill_preprocessing_model_id,
            "max_total_steps": self.max_total_steps,
            "max_parallel_agents": self.max_parallel_agents,
            "auto_improve": self.auto_improve,
            "auto_improve_max": self.auto_improve_max,
            "execution_max_threads": self.execution_max_threads,
            "execution_total_runs": self.execution_total_runs,
            "execution_thread_mode": self.execution_thread_mode,
            "execution_priority": self.execution_priority,
            "execution_labels": self.execution_labels,
            "execution_bottleneck_id": self.execution_bottleneck_id,
            "execution_bottleneck_limit": self.execution_bottleneck_limit,
            "execution_schedule_enabled": self.execution_schedule_enabled,
            "execution_schedule_cron": self.execution_schedule_cron,
            "execution_stop_condition": self.execution_stop_condition,
            "execution_stop_value": self.execution_stop_value,
            "close_browser_on_finish": self.close_browser_on_finish,
            "status": self.status.value,
            "project_variables": self.project_variables,
            "project_notes": self.project_notes,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AgentWorkflow:
        return cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            name=d.get("name", "Workflow"),
            description=d.get("description", ""),
            version=d.get("version", "1.0"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            nodes=[AgentNode.from_dict(n) for n in d.get("nodes", [])],
            edges=[AgentEdge.from_dict(e) for e in d.get("edges", [])],
            project_root=d.get("project_root", ""),
            entry_node_id=d.get("entry_node_id", ""),
            global_context=d.get("global_context", ""),
            skill_preprocessing_model_id=d.get("skill_preprocessing_model_id", ""),
            max_total_steps=d.get("max_total_steps", 0),
            max_parallel_agents=d.get("max_parallel_agents", 3),
            auto_improve=d.get("auto_improve", False),
            auto_improve_max=d.get("auto_improve_max", 5),
            execution_max_threads=d.get("execution_max_threads", 1),
            execution_total_runs=d.get("execution_total_runs", 1),
            execution_thread_mode=d.get("execution_thread_mode", "sequential"),
            execution_priority=d.get("execution_priority", 5),
            execution_labels=d.get("execution_labels", []),
            execution_bottleneck_id=d.get("execution_bottleneck_id", ""),
            execution_bottleneck_limit=d.get("execution_bottleneck_limit", 1),
            execution_schedule_enabled=d.get("execution_schedule_enabled", False),
            execution_schedule_cron=d.get("execution_schedule_cron", ""),
            execution_stop_condition=d.get("execution_stop_condition", "none"),
            execution_stop_value=d.get("execution_stop_value", 0),
            close_browser_on_finish=d.get("close_browser_on_finish", True),
            status=WorkflowStatus(d.get("status", "draft")),
            project_variables=d.get("project_variables", {}),
            project_notes=d.get("project_notes", []),
            metadata=d.get("metadata", {}),
        )

    def save(self, path: str) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str) -> AgentWorkflow:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    # ── Graph helpers ──────────────────────────────────────

    def get_node(self, node_id: str) -> AgentNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def get_outgoing_edges(self, node_id: str) -> list[AgentEdge]:
        return sorted(
            [e for e in self.edges if e.source_id == node_id],
            key=lambda e: -e.priority,
        )

    def get_incoming_edges(self, node_id: str) -> list[AgentEdge]:
        return [e for e in self.edges if e.target_id == node_id]

    def get_entry_node(self) -> AgentNode | None:
        if self.entry_node_id:
            return self.get_node(self.entry_node_id)
        # Fallback: node with no incoming edges
        nodes_with_incoming = {e.target_id for e in self.edges}
        for node in self.nodes:
            if node.id not in nodes_with_incoming:
                return node
        return self.nodes[0] if self.nodes else None

    def add_node(self, node: AgentNode) -> None:
        self.nodes.append(node)
        if not self.entry_node_id and len(self.nodes) == 1:
            self.entry_node_id = node.id

    def remove_node(self, node_id: str) -> None:
        self.nodes = [n for n in self.nodes if n.id != node_id]
        self.edges = [e for e in self.edges
                      if e.source_id != node_id and e.target_id != node_id]
        if self.entry_node_id == node_id:
            self.entry_node_id = self.nodes[0].id if self.nodes else ""

    def add_edge(self, edge: AgentEdge) -> tuple[bool, str]:
        """Returns (success, error_message). Validates logic before creating."""
        # Нельзя связать с самим собой
        if edge.source_id == edge.target_id:
            return False, "Нельзя связать агента самого с собой"
        
        # Проверка существования узлов
        if not self.get_node(edge.source_id):
            return False, "Исходный агент не найден"
        if not self.get_node(edge.target_id):
            return False, "Целевой агент не найден"
        
        # Prevent exact duplicates (same source, target AND condition)
        for e in self.edges:
            if (e.source_id == edge.source_id and 
                e.target_id == edge.target_id and
                e.condition == edge.condition):
                return False, "Такая связь уже существует"
        
        # Циклы РАЗРЕШЕНЫ — нужны для паттерна ScriptRunner↔Patcher
        
        self.edges.append(edge)
        return True, ""
    
    def _would_create_cycle(self, new_edge: AgentEdge) -> bool:
        """Проверяет, создаст ли новая связь цикл в графе"""
        visited = set()
        queue = [new_edge.target_id]
        while queue:
            current = queue.pop(0)
            if current == new_edge.source_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            for edge in self.edges:
                if edge.source_id == current:
                    queue.append(edge.target_id)
            # Учитываем новую связь
            if new_edge.source_id == current:
                queue.append(new_edge.target_id)
        return False

    def remove_edge(self, edge_id: str) -> None:
        self.edges = [e for e in self.edges if e.id != edge_id]


# ──────────────────────────────────────────────────────────
#  Built-in Skills
# ──────────────────────────────────────────────────────────

BUILTIN_SKILLS: list[Skill] = [
    Skill(
        id="sk_code_gen", name="Генерация кода", icon="💻",
        category=SkillCategory.CODE,
        description="Создание нового кода по описанию задачи",
        system_prompt=(
            "Ты — опытный программист. Генерируй чистый, документированный код. "
            "Используй лучшие практики. Всегда добавляй обработку ошибок."
        ),
        tags=["python", "javascript", "code"],
    ),
    Skill(
        id="sk_code_review", name="Ревью кода", icon="🔍",
        category=SkillCategory.CODE,
        description="Анализ кода на баги, уязвимости и улучшения",
        system_prompt=(
            "Ты — code reviewer. Найди баги, уязвимости, антипаттерны. "
            "Предложи конкретные улучшения с примерами кода."
        ),
        tags=["review", "bugs", "quality"],
    ),
    Skill(
        id="sk_patching", name="Патчинг кода", icon="🔧",
        category=SkillCategory.CODE,
        description="Точечные исправления в существующем коде через SEARCH/REPLACE",
        system_prompt=(
            "Ты патчишь код. Используй формат [SEARCH_BLOCK]/[REPLACE_BLOCK]. "
            "SEARCH должен ТОЧНО совпадать с существующим кодом."
        ),
        tags=["patch", "fix", "modify"],
    ),
    Skill(
        id="sk_testing", name="Тестирование", icon="🧪",
        category=SkillCategory.TESTING,
        description="Создание и запуск тестов, анализ результатов",
        system_prompt=(
            "Ты — QA инженер. Создавай тесты для всех edge cases. "
            "Используй pytest. Проверяй граничные условия."
        ),
        tags=["test", "pytest", "qa"],
    ),
    Skill(
        id="sk_architecture", name="Архитектура", icon="🏗️",
        category=SkillCategory.ANALYSIS,
        description="Проектирование архитектуры и структуры проекта",
        system_prompt=(
            "Ты — архитектор ПО. Проектируй модульные, масштабируемые системы. "
            "Документируй решения. Рисуй схемы в Mermaid."
        ),
        tags=["architecture", "design", "planning"],
    ),
    Skill(
        id="sk_debug", name="Отладка", icon="🐛",
        category=SkillCategory.CODE,
        description="Поиск и исправление ошибок по логам и трейсбекам",
        system_prompt=(
            "Ты — отладчик. Анализируй логи, трейсбеки, поведение. "
            "Найди корневую причину и предложи минимальный фикс."
        ),
        tags=["debug", "fix", "logs"],
    ),
    Skill(
        id="sk_docs", name="Документация", icon="📝",
        category=SkillCategory.WRITING,
        description="Создание документации, README, комментариев",
        system_prompt=(
            "Ты — технический писатель. Пиши ясную, структурированную документацию. "
            "Используй примеры. Документируй API, параметры, возвращаемые значения."
        ),
        tags=["docs", "readme", "comments"],
    ),
    Skill(
        id="sk_image_analyze", name="Анализ изображений", icon="👁️",
        category=SkillCategory.ANALYSIS,
        description="Анализ скриншотов и изображений через vision модель",
        system_prompt=(
            "Ты анализируешь изображения. Описывай что видишь на скриншоте: "
            "элементы UI, текст, ошибки, состояние программы."
        ),
        required_tools=["vision"],
        tags=["image", "screenshot", "vision"],
    ),
    Skill(
        id="sk_file_ops", name="Файловые операции", icon="📁",
        category=SkillCategory.DEVOPS,
        description="Создание, чтение, организация файлов проекта",
        system_prompt=(
            "Ты управляешь файлами проекта. Создавай структуру директорий, "
            "перемещай файлы, организуй код по модулям."
        ),
        required_tools=["file_io"],
        tags=["files", "organize", "structure"],
    ),
    Skill(
        id="sk_data_analysis", name="Анализ данных", icon="📊",
        category=SkillCategory.DATA,
        description="Анализ CSV, JSON, логов, метрик",
        system_prompt=(
            "Ты — аналитик данных. Анализируй данные, находи паттерны, "
            "визуализируй результаты. Используй pandas, numpy."
        ),
        tags=["data", "csv", "analysis", "pandas"],
    ),
]
