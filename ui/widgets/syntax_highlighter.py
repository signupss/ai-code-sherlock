"""
Multi-language syntax highlighter for QPlainTextEdit / QTextEdit.
Supports: Python, JavaScript/TypeScript, JSON, YAML, SQL, Bash, Generic.
"""
from __future__ import annotations
import re
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import (
    QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument
)


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


# ── Tokyonight palette ──────────────────────────────────
C_KEYWORD   = "#7AA2F7"   # blue
C_BUILTIN   = "#BB9AF7"   # purple
C_STRING    = "#9ECE6A"   # green
C_COMMENT   = "#565f89"   # muted purple
C_NUMBER    = "#FF9E64"   # orange
C_FUNC      = "#61AFEF"   # light blue
C_CLASS     = "#E0AF68"   # amber
C_DECORATOR = "#E0AF68"   # amber
C_OPERATOR  = "#89DDFF"   # cyan
C_SELF      = "#F7768E"   # red/pink
C_CONSTANT  = "#FF9E64"   # orange
C_PROPERTY  = "#73DACA"   # teal
C_TAG       = "#F7768E"
C_ATTR      = "#E0AF68"


class BaseHighlighter(QSyntaxHighlighter):
    """Base class — subclasses define _rules and _multiline_rules."""

    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._multiline: list[tuple[QRegularExpression, QRegularExpression, QTextCharFormat, int]] = []
        self._setup_rules()

    def _add(self, pattern: str, fmt: QTextCharFormat, flags: QRegularExpression.PatternOption = QRegularExpression.PatternOption(0)):
        rx = QRegularExpression(pattern)
        if flags:
            rx.setPatternOptions(flags)
        self._rules.append((rx, fmt))

    def _add_multiline(self, start: str, end: str, fmt: QTextCharFormat, state: int):
        self._multiline.append((
            QRegularExpression(start),
            QRegularExpression(end),
            fmt,
            state,
        ))

    def _setup_rules(self): ...

    def highlightBlock(self, text: str):
        # Check if we're inside a multiline block from previous block
        for i, (start_rx, end_rx, fmt, state) in enumerate(self._multiline):
            if self.previousBlockState() == state:
                end_match = end_rx.match(text)
                if not end_match.hasMatch():
                    self.setFormat(0, len(text), fmt)
                    self.setCurrentBlockState(state)
                    return
                else:
                    end = end_match.capturedEnd()
                    self.setFormat(0, end, fmt)
                    self.setCurrentBlockState(-1)
                    text = text[end:]
                    # Continue with single-line rules for remainder

        self.setCurrentBlockState(-1)

        # Single-line rules
        for rx, fmt in self._rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        # Check for start of multiline blocks
        for start_rx, end_rx, fmt, state in self._multiline:
            start_match = start_rx.match(text)
            if start_match.hasMatch():
                start_pos = start_match.capturedStart()
                end_match = end_rx.match(text, start_match.capturedEnd())
                if not end_match.hasMatch():
                    self.setFormat(start_pos, len(text) - start_pos, fmt)
                    self.setCurrentBlockState(state)
                else:
                    end_pos = end_match.capturedEnd()
                    self.setFormat(start_pos, end_pos - start_pos, fmt)


# ──────────────────────────────────────────────────────────
#  PYTHON
# ──────────────────────────────────────────────────────────

class PythonHighlighter(BaseHighlighter):

    KEYWORDS = (
        r"\b(False|None|True|and|as|assert|async|await|break|class|continue|"
        r"def|del|elif|else|except|finally|for|from|global|if|import|in|is|"
        r"lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield)\b"
    )
    BUILTINS = (
        r"\b(abs|all|any|bin|bool|bytes|callable|chr|dict|dir|divmod|enumerate|"
        r"eval|exec|filter|float|format|frozenset|getattr|globals|hasattr|hash|"
        r"help|hex|id|input|int|isinstance|issubclass|iter|len|list|locals|map|"
        r"max|memoryview|min|next|object|oct|open|ord|pow|print|property|range|"
        r"repr|reversed|round|set|setattr|slice|sorted|staticmethod|str|sum|"
        r"super|tuple|type|vars|zip|__name__|__file__|__doc__|__class__)\b"
    )

    def _setup_rules(self):
        # Decorators (before functions)
        self._add(r"@[\w.]+", _fmt(C_DECORATOR))
        # Keywords
        self._add(self.KEYWORDS, _fmt(C_KEYWORD, bold=True))
        # Built-ins
        self._add(self.BUILTINS, _fmt(C_BUILTIN))
        # self / cls
        self._add(r"\b(self|cls)\b", _fmt(C_SELF))
        # Class names (PascalCase)
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(C_CLASS))
        # Function definition name
        self._add(r"(?<=def\s)(\w+)", _fmt(C_FUNC, bold=True))
        # Class definition name
        self._add(r"(?<=class\s)(\w+)", _fmt(C_CLASS, bold=True))
        # Function calls
        self._add(r"\b(\w+)(?=\s*\()", _fmt(C_FUNC))
        # Numbers
        self._add(r"\b(0x[0-9A-Fa-f]+|0b[01]+|0o[0-7]+|\d+\.?\d*([eE][+-]?\d+)?)\b", _fmt(C_NUMBER))
        # Operators
        self._add(r"[+\-*/%=<>!&|^~:]+", _fmt(C_OPERATOR))
        # f-strings (simplified)
        self._add(r'f"[^"\\]*"', _fmt(C_STRING))
        self._add(r"f'[^'\\]*'", _fmt(C_STRING))
        # Single-line strings
        self._add(r'"[^"\\]*"', _fmt(C_STRING))
        self._add(r"'[^'\\]*'", _fmt(C_STRING))
        # Single-line comments
        self._add(r"#[^\n]*", _fmt(C_COMMENT, italic=True))
        # Triple-quoted multiline strings
        self._add_multiline('"""', '"""', _fmt(C_STRING), state=1)
        self._add_multiline("'''", "'''", _fmt(C_STRING), state=2)


# ──────────────────────────────────────────────────────────
#  JAVASCRIPT / TYPESCRIPT
# ──────────────────────────────────────────────────────────

class JavaScriptHighlighter(BaseHighlighter):

    KEYWORDS = (
        r"\b(break|case|catch|class|const|continue|debugger|default|delete|do|"
        r"else|export|extends|finally|for|function|if|import|in|instanceof|let|"
        r"new|of|return|static|super|switch|this|throw|try|typeof|var|void|"
        r"while|with|yield|async|await|from|as|interface|type|enum|declare|"
        r"namespace|abstract|implements|readonly|override|satisfies)\b"
    )
    CONSTANTS = r"\b(true|false|null|undefined|NaN|Infinity)\b"

    def _setup_rules(self):
        self._add(self.KEYWORDS, _fmt(C_KEYWORD, bold=True))
        self._add(self.CONSTANTS, _fmt(C_CONSTANT))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(C_CLASS))
        self._add(r"(?<=function\s)(\w+)", _fmt(C_FUNC, bold=True))
        self._add(r"\b(\w+)(?=\s*[=(,]\s*(?:async\s*)?\()", _fmt(C_FUNC))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(C_FUNC))
        self._add(r"\.\b(\w+)\b", _fmt(C_PROPERTY))
        self._add(r"\b(0x[0-9A-Fa-f]+|\d+\.?\d*([eE][+-]?\d+)?)\b", _fmt(C_NUMBER))
        self._add(r"`[^`]*`", _fmt(C_STRING))
        self._add(r'"[^"\\]*"', _fmt(C_STRING))
        self._add(r"'[^'\\]*'", _fmt(C_STRING))
        self._add(r"//[^\n]*", _fmt(C_COMMENT, italic=True))
        self._add_multiline(r"/\*", r"\*/", _fmt(C_COMMENT, italic=True), state=1)


# ──────────────────────────────────────────────────────────
#  JSON
# ──────────────────────────────────────────────────────────

class JsonHighlighter(BaseHighlighter):

    def _setup_rules(self):
        # Keys (quoted strings before colon)
        self._add(r'"[^"]*"(?=\s*:)', _fmt(C_PROPERTY, bold=True))
        # String values
        self._add(r'(?<=:\s)"[^"]*"', _fmt(C_STRING))
        # Bare strings in arrays
        self._add(r'"[^"]*"', _fmt(C_STRING))
        # Numbers
        self._add(r"\b-?\d+\.?\d*([eE][+-]?\d+)?\b", _fmt(C_NUMBER))
        # Booleans / null
        self._add(r"\b(true|false|null)\b", _fmt(C_CONSTANT, bold=True))
        # Braces / brackets
        self._add(r"[{}\[\]]", _fmt(C_OPERATOR))


# ──────────────────────────────────────────────────────────
#  YAML
# ──────────────────────────────────────────────────────────

class YamlHighlighter(BaseHighlighter):

    def _setup_rules(self):
        # Keys
        self._add(r"^[\s-]*\b([\w.-]+)\s*:", _fmt(C_PROPERTY, bold=True))
        # Strings
        self._add(r'"[^"]*"', _fmt(C_STRING))
        self._add(r"'[^']*'", _fmt(C_STRING))
        # Anchors / aliases
        self._add(r"[&*]\w+", _fmt(C_DECORATOR))
        # Special values
        self._add(r"\b(true|false|yes|no|null|~)\b", _fmt(C_CONSTANT))
        # Numbers
        self._add(r"\b-?\d+\.?\d*\b", _fmt(C_NUMBER))
        # Comments
        self._add(r"#[^\n]*", _fmt(C_COMMENT, italic=True))
        # YAML directives
        self._add(r"^---", _fmt(C_KEYWORD, bold=True))


# ──────────────────────────────────────────────────────────
#  SQL
# ──────────────────────────────────────────────────────────

class SqlHighlighter(BaseHighlighter):

    KEYWORDS = (
        r"\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|ON|GROUP|BY|"
        r"ORDER|HAVING|LIMIT|OFFSET|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|"
        r"TABLE|INDEX|VIEW|DROP|ALTER|ADD|COLUMN|PRIMARY|KEY|FOREIGN|REFERENCES|"
        r"NOT|NULL|DEFAULT|UNIQUE|CHECK|CONSTRAINT|AND|OR|IN|NOT|LIKE|BETWEEN|"
        r"EXISTS|CASE|WHEN|THEN|ELSE|END|AS|DISTINCT|ALL|UNION|INTERSECT|EXCEPT|"
        r"WITH|RECURSIVE|RETURNING|BEGIN|COMMIT|ROLLBACK|TRANSACTION)\b"
    )
    FUNCTIONS = (
        r"\b(COUNT|SUM|AVG|MAX|MIN|COALESCE|NULLIF|CAST|CONVERT|UPPER|LOWER|"
        r"TRIM|SUBSTRING|CONCAT|LENGTH|NOW|CURRENT_DATE|CURRENT_TIMESTAMP|"
        r"EXTRACT|DATE_TRUNC|ROW_NUMBER|RANK|DENSE_RANK|LAG|LEAD|OVER|PARTITION)\b"
    )

    def _setup_rules(self):
        flags = QRegularExpression.PatternOption.CaseInsensitiveOption
        self._add(self.KEYWORDS, _fmt(C_KEYWORD, bold=True), flags)
        self._add(self.FUNCTIONS, _fmt(C_BUILTIN), flags)
        self._add(r"'[^']*'", _fmt(C_STRING))
        self._add(r"\b\d+\.?\d*\b", _fmt(C_NUMBER))
        self._add(r"--[^\n]*", _fmt(C_COMMENT, italic=True))
        self._add_multiline(r"/\*", r"\*/", _fmt(C_COMMENT, italic=True), state=1)


# ──────────────────────────────────────────────────────────
#  BASH / Shell
# ──────────────────────────────────────────────────────────

class BashHighlighter(BaseHighlighter):

    def _setup_rules(self):
        self._add(
            r"\b(if|then|else|elif|fi|for|while|do|done|case|esac|function|"
            r"return|exit|local|export|source|alias|unset|readonly|shift|"
            r"continue|break|in|select|until)\b",
            _fmt(C_KEYWORD, bold=True)
        )
        self._add(r"\$\{?[\w@#?$!*-]+\}?", _fmt(C_PROPERTY))
        self._add(r'"[^"]*"', _fmt(C_STRING))
        self._add(r"'[^']*'", _fmt(C_STRING))
        self._add(r"`[^`]*`", _fmt(C_CONSTANT))
        self._add(r"\b\d+\b", _fmt(C_NUMBER))
        self._add(r"#[^\n]*", _fmt(C_COMMENT, italic=True))
        self._add(r"^#!/.*", _fmt(C_DECORATOR))


# ──────────────────────────────────────────────────────────
#  Generic / Markdown
# ──────────────────────────────────────────────────────────

class MarkdownHighlighter(BaseHighlighter):

    def _setup_rules(self):
        # Headers
        self._add(r"^#{1,6}\s.*", _fmt(C_KEYWORD, bold=True))
        # Bold
        self._add(r"\*\*[^*]+\*\*", _fmt(C_CLASS, bold=True))
        # Italic
        self._add(r"\*[^*]+\*", _fmt(C_STRING, italic=True))
        # Code inline
        self._add(r"`[^`]+`", _fmt(C_CONSTANT))
        # Links
        self._add(r"\[([^\]]+)\]\([^\)]+\)", _fmt(C_FUNC))
        # Blockquotes
        self._add(r"^>\s.*", _fmt(C_COMMENT, italic=True))
        # Horizontal rule
        self._add(r"^[-*_]{3,}$", _fmt(C_OPERATOR))
        # List markers
        self._add(r"^\s*[-*+]\s", _fmt(C_BUILTIN))
        # Code blocks
        self._add_multiline("```", "```", _fmt(C_CONSTANT), state=1)


# ──────────────────────────────────────────────────────────
#  FACTORY
# ──────────────────────────────────────────────────────────

_EXTENSION_MAP: dict[str, type[BaseHighlighter]] = {
    ".py":    PythonHighlighter,
    ".pyw":   PythonHighlighter,
    ".js":    JavaScriptHighlighter,
    ".jsx":   JavaScriptHighlighter,
    ".ts":    JavaScriptHighlighter,
    ".tsx":   JavaScriptHighlighter,
    ".mjs":   JavaScriptHighlighter,
    ".cjs":   JavaScriptHighlighter,
    ".json":  JsonHighlighter,
    ".yaml":  YamlHighlighter,
    ".yml":   YamlHighlighter,
    ".sql":   SqlHighlighter,
    ".sh":    BashHighlighter,
    ".bash":  BashHighlighter,
    ".zsh":   BashHighlighter,
    ".md":    MarkdownHighlighter,
    ".markdown": MarkdownHighlighter,
}


def create_highlighter(
    document: QTextDocument,
    file_path: str,
) -> BaseHighlighter | None:
    """
    Create the appropriate highlighter for a file.
    Returns None for unsupported types (no highlighting).
    """
    from pathlib import Path
    ext = Path(file_path).suffix.lower()
    cls = _EXTENSION_MAP.get(ext)
    if cls:
        return cls(document)
    return None


def language_name(file_path: str) -> str:
    """Human-readable language name for status bar."""
    from pathlib import Path
    ext = Path(file_path).suffix.lower()
    names = {
        ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript (JSX)",
        ".ts": "TypeScript", ".tsx": "TypeScript (TSX)",
        ".json": "JSON", ".yaml": "YAML", ".yml": "YAML",
        ".sql": "SQL", ".sh": "Shell", ".bash": "Bash",
        ".md": "Markdown", ".cs": "C#", ".cpp": "C++",
        ".java": "Java", ".go": "Go", ".rs": "Rust",
        ".rb": "Ruby", ".php": "PHP", ".kt": "Kotlin",
        ".swift": "Swift", ".c": "C", ".h": "C/C++ Header",
    }
    return names.get(ext, "Plain Text")
