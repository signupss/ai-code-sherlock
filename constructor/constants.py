"""Константы, цвета и типы нод."""
from services.agent_models import AgentType

# ══════════════════════════════════════════════════════════
#  AGENT TYPE CONFIGURATION
# ══════════════════════════════════════════════════════════

_AGENT_COLORS = {
    AgentType.CODE_WRITER:   "#7AA2F7",
    AgentType.CODE_REVIEWER: "#BB9AF7",
    AgentType.TESTER:        "#9ECE6A",
    AgentType.PLANNER:       "#E0AF68",
    AgentType.IMAGE_GEN:     "#F7768E",
    AgentType.IMAGE_ANALYST: "#FF9E64",
    AgentType.FILE_MANAGER:  "#73DACA",
    AgentType.SCRIPT_RUNNER: "#2AC3DE",
    AgentType.VERIFIER:      "#89DDFF",
    AgentType.ORCHESTRATOR:  "#E0AF68",
    AgentType.PATCHER:       "#FF6B6B",
    AgentType.CODE_SNIPPET:  "#C0CAF5",
    AgentType.IF_CONDITION:  "#FF9E64",
    AgentType.LOOP:          "#B4F9F8",
    AgentType.VARIABLE_SET:  "#C3E88D",
    AgentType.HTTP_REQUEST:  "#82AAFF",
    AgentType.DELAY:         "#A9B1D6",
    AgentType.LOG_MESSAGE:   "#565f89",
    AgentType.SWITCH:        "#BB9AF7",
    AgentType.GOOD_END:      "#9ECE6A",
    AgentType.BAD_END:       "#F7768E",
    AgentType.NOTIFICATION:  "#FF9E64",
    AgentType.JS_SNIPPET:    "#F7768E",
    AgentType.PROGRAM_LAUNCH:"#2AC3DE",
    AgentType.LIST_OPERATION:"#73DACA",
    AgentType.TABLE_OPERATION:"#89DDFF",
    AgentType.FILE_OPERATION: "#C3E88D",
    AgentType.DIR_OPERATION:  "#A9B1D6",
    AgentType.TEXT_PROCESSING:"#FF9E64",
    AgentType.JSON_XML:       "#BB9AF7",
    AgentType.VARIABLE_PROC:  "#7DCFFF",
    AgentType.RANDOM_GEN:     "#F7768E",
    AgentType.NOTE:          "#E0AF68",
    AgentType.CUSTOM:        "#565f89",
    # Браузер
    AgentType.BROWSER_LAUNCH:       "#43AEFF",
    AgentType.BROWSER_ACTION:       "#00BFFF",
    AgentType.BROWSER_CLOSE:        "#FF6B6B",
    AgentType.BROWSER_AGENT:        "#43AEFF",
    AgentType.BROWSER_CLICK_IMAGE:  "#00D4FF",
    AgentType.BROWSER_SCREENSHOT:   "#A9B1D6",
    AgentType.BROWSER_PROFILE_OP:   "#BB9AF7",
    AgentType.PROJECT_INFO:         "#E0AF68",
    AgentType.PROJECT_START:        "#9ECE6A",
    AgentType.PROGRAM_OPEN:         "#FF9E64",
    AgentType.PROGRAM_ACTION:       "#E0AF68",
    AgentType.PROGRAM_CLICK_IMAGE:  "#FF6B6B",
    AgentType.PROGRAM_SCREENSHOT:   "#A9B1D6",
    AgentType.PROGRAM_AGENT:        "#FF9E64",
    AgentType.BROWSER_PARSE:        "#00D4FF",
    AgentType.PROGRAM_INSPECTOR:    "#C3E88D",
    AgentType.PROJECT_IN_PROJECT:   "#E0AF68",
}

_AGENT_ICONS = {
    AgentType.CODE_WRITER:   "💻",
    AgentType.CODE_REVIEWER: "🔍",
    AgentType.TESTER:        "🧪",
    AgentType.PLANNER:       "🏗️",
    AgentType.IMAGE_GEN:     "🎨",
    AgentType.IMAGE_ANALYST: "👁️",
    AgentType.FILE_MANAGER:  "📁",
    AgentType.SCRIPT_RUNNER: "▶️",
    AgentType.VERIFIER:      "✅",
    AgentType.ORCHESTRATOR:  "🎯",
    AgentType.PATCHER:       "🩹",
    AgentType.CODE_SNIPPET:  "📜",
    AgentType.IF_CONDITION:  "❓",
    AgentType.LOOP:          "🔁",
    AgentType.VARIABLE_SET:  "📝",
    AgentType.HTTP_REQUEST:  "🌐",
    AgentType.DELAY:         "⏳",
    AgentType.LOG_MESSAGE:   "📋",
    AgentType.SWITCH:        "🔀",
    AgentType.GOOD_END:      "✅",
    AgentType.BAD_END:       "🛑",
    AgentType.NOTIFICATION:  "🔔",
    AgentType.JS_SNIPPET:    "🟨",
    AgentType.PROGRAM_LAUNCH:"⚙️",
    AgentType.LIST_OPERATION:"📃",
    AgentType.TABLE_OPERATION:"📊",
    AgentType.FILE_OPERATION: "📄",
    AgentType.DIR_OPERATION:  "📁",
    AgentType.TEXT_PROCESSING:"✂️",
    AgentType.JSON_XML:       "🔣",
    AgentType.VARIABLE_PROC:  "🔧",
    AgentType.RANDOM_GEN:     "🎲",
    AgentType.NOTE:          "📌",
    AgentType.CUSTOM:        "🤖",
    # Браузер
    AgentType.BROWSER_LAUNCH:       "🌐",
    AgentType.BROWSER_ACTION:       "🖱",
    AgentType.BROWSER_CLOSE:        "🔴",
    AgentType.BROWSER_AGENT:        "🌐🧠",
    AgentType.BROWSER_CLICK_IMAGE:  "🖼",
    AgentType.BROWSER_SCREENSHOT:   "📸",
    AgentType.BROWSER_PROFILE_OP:   "🪪",
    AgentType.PROJECT_INFO:         "🔎",
    AgentType.PROJECT_START:        "▶",
    AgentType.PROGRAM_OPEN:         "🖥",
    AgentType.PROGRAM_ACTION:       "🎯",
    AgentType.PROGRAM_CLICK_IMAGE:  "🖼",
    AgentType.PROGRAM_SCREENSHOT:   "📸",
    AgentType.PROGRAM_AGENT:        "🖥🧠",
    AgentType.BROWSER_PARSE:        "🕸️",
    AgentType.PROGRAM_INSPECTOR:    "🔬",
    AgentType.PROJECT_IN_PROJECT:   "📦",
}

# ══════════════════════════════════════════════════════════
#  Разделение типов: AI-агенты vs Сниппеты vs Заметки
# ══════════════════════════════════════════════════════════

SNIPPET_TYPES = {
    AgentType.CODE_SNIPPET, AgentType.IF_CONDITION, AgentType.LOOP,
    AgentType.VARIABLE_SET, AgentType.HTTP_REQUEST, AgentType.DELAY,
    AgentType.LOG_MESSAGE, AgentType.SWITCH, AgentType.GOOD_END,
    AgentType.BAD_END, AgentType.NOTIFICATION, AgentType.JS_SNIPPET,
    AgentType.PROGRAM_LAUNCH, AgentType.LIST_OPERATION, AgentType.TABLE_OPERATION,
    AgentType.FILE_OPERATION, AgentType.DIR_OPERATION, AgentType.TEXT_PROCESSING,
    AgentType.JSON_XML, AgentType.VARIABLE_PROC, AgentType.RANDOM_GEN,
    # Браузер
    AgentType.BROWSER_LAUNCH, AgentType.BROWSER_ACTION, AgentType.BROWSER_CLOSE,
    AgentType.BROWSER_CLICK_IMAGE, AgentType.BROWSER_SCREENSHOT,
    AgentType.BROWSER_PROFILE_OP,
    AgentType.PROJECT_INFO,
    AgentType.PROGRAM_OPEN,
    AgentType.PROGRAM_ACTION,
    AgentType.PROGRAM_CLICK_IMAGE,
    AgentType.PROGRAM_SCREENSHOT,
    AgentType.BROWSER_PARSE,
    AgentType.PROGRAM_INSPECTOR,
    AgentType.PROJECT_IN_PROJECT,
}

NOTE_TYPES = {AgentType.NOTE, AgentType.PROJECT_START}

AI_AGENT_TYPES = set(AgentType) - SNIPPET_TYPES - NOTE_TYPES

_SNIPPET_ICONS = {
    AgentType.CODE_SNIPPET:  "📜",
    AgentType.IF_CONDITION:  "❓",
    AgentType.LOOP:          "🔁",
    AgentType.VARIABLE_SET:  "📝",
    AgentType.SWITCH:        "🔀",
    AgentType.GOOD_END:      "✅",
    AgentType.BAD_END:       "🛑",
    AgentType.NOTIFICATION:  "🔔",
    AgentType.JS_SNIPPET:    "🟨",
    AgentType.PROGRAM_LAUNCH:"⚙️",
    AgentType.LIST_OPERATION:"📃",
    AgentType.TABLE_OPERATION:"📊",
    AgentType.FILE_OPERATION: "📄",
    AgentType.DIR_OPERATION:  "📁",
    AgentType.TEXT_PROCESSING:"✂️",
    AgentType.JSON_XML:       "🔣",
    AgentType.VARIABLE_PROC:  "🔧",
    AgentType.RANDOM_GEN:     "🎲",
    # Браузер
    AgentType.BROWSER_LAUNCH:       "🌐",
    AgentType.BROWSER_ACTION:       "🖱",
    AgentType.BROWSER_CLOSE:        "🔴",
    AgentType.BROWSER_CLICK_IMAGE:  "🖼",
    AgentType.BROWSER_SCREENSHOT:   "📸",
    AgentType.BROWSER_PROFILE_OP:   "🪪",
    AgentType.PROJECT_INFO:         "🔎",
    AgentType.PROGRAM_OPEN:         "🖥",
    AgentType.PROGRAM_ACTION:       "🎯",
    AgentType.PROGRAM_CLICK_IMAGE:  "🖼",
    AgentType.PROGRAM_SCREENSHOT:   "📸",
    AgentType.BROWSER_PARSE:        "🕸️",
    AgentType.PROGRAM_INSPECTOR:    "🔬",
    AgentType.PROJECT_IN_PROJECT:   "📦",
}


def get_node_category(agent_type: AgentType) -> str:
    """Определить категорию ноды: 'ai', 'snippet', 'note'."""
    if agent_type in NOTE_TYPES:
        return 'note'
    if agent_type in SNIPPET_TYPES:
        return 'snippet'
    return 'ai'