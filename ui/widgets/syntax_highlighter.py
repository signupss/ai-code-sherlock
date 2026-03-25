"""
Multi-language syntax highlighter — 19 languages.

Upgrades:
  * Theme-aware colors — reads from theme_manager palette at init time
  * Lexical caching — pre-compiled QRegularExpression + format objects
  * Multi-opener multiline — handles multiple multiline blocks per line
    (e.g. ending a docstring and starting a comment on same line)
  * Block state machine — uses setCurrentBlockState for proper
    incremental re-highlighting (Qt only rehighlights changed blocks)
  * Semantic dimming API — set_dimmed_ranges() for unused-var highlighting

Supports: Python, JS/TS, JSON, YAML, SQL, Bash, Markdown,
          C/C++, C#, Java, Go, Rust, Ruby, PHP, Kotlin, Swift, TOML.
"""
from __future__ import annotations
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument


# ──────────────────────────────────────────────────────────
#  Theme-aware Color Palette
# ──────────────────────────────────────────────────────────

def _get_highlight_colors() -> dict[str, str]:
    """Attempt to load colors from theme_manager, fallback to Tokyo Night."""
    try:
        from ui.theme_manager import get_color, get_theme
        theme = get_theme()
    except ImportError:
        theme = "dark"

    # Syntax colors — consistent across themes for readability
    # (only the comment color adapts to theme brightness)
    if theme == "light":
        return {
            "keyword": "#0033B3", "builtin": "#7B3FB7", "string": "#067D17",
            "comment": "#8C8C8C", "number": "#1750EB", "func": "#00627A",
            "class_": "#A66F00", "deco": "#A66F00", "operator": "#0033B3",
            "self_": "#C51916", "const": "#1750EB", "prop": "#248F8F",
            "type_": "#00627A", "preproc": "#AF1219", "escape": "#C51916",
            "dimmed": "#B0B0B0",
        }
    else:
        return {
            "keyword": "#7AA2F7", "builtin": "#BB9AF7", "string": "#9ECE6A",
            "comment": "#565f89", "number": "#FF9E64", "func": "#61AFEF",
            "class_": "#E0AF68", "deco": "#E0AF68", "operator": "#89DDFF",
            "self_": "#F7768E", "const": "#FF9E64", "prop": "#73DACA",
            "type_": "#2AC3DE", "preproc": "#FF9E64", "escape": "#F7768E",
            "dimmed": "#3B4261",
        }


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


# ──────────────────────────────────────────────────────────
#  Base Highlighter
# ──────────────────────────────────────────────────────────

class BaseHighlighter(QSyntaxHighlighter):
    """
    Base with:
      - Pre-compiled regex rule list
      - Multi-state multiline block handling
      - Semantic dimming support
    """

    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self._colors = _get_highlight_colors()
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._multiline: list[tuple[QRegularExpression, QRegularExpression, QTextCharFormat, int]] = []
        self._overlays: list[tuple[QRegularExpression, QTextCharFormat]] = [] # <--- ДОБАВЛЕНО
        self._dimmed_format = _fmt(self._colors["dimmed"], italic=True)
        self._dimmed_ranges: dict[int, list[tuple[int, int]]] = {}
        self._setup_rules()

    # ── Convenience for subclasses ─────────────────────────

    def _add_overlay(self, pat: str, fmt: QTextCharFormat):
        """Правила, которые красятся поверх основного цвета (например, \n в строках)"""
        self._overlays.append((QRegularExpression(pat), fmt))

    def _c(self, name: str) -> str:
        """Get color by semantic name."""
        return self._colors.get(name, "#CDD6F4")

    def _add(self, pat: str, fmt: QTextCharFormat,
             flags: QRegularExpression.PatternOption = QRegularExpression.PatternOption(0)):
        rx = QRegularExpression(pat)
        if flags:
            rx.setPatternOptions(flags)
        self._rules.append((rx, fmt))

    def _ml(self, start: str, end: str, fmt: QTextCharFormat, state: int):
        self._multiline.append((
            QRegularExpression(start),
            QRegularExpression(end),
            fmt,
            state,
        ))

    def _setup_rules(self):
        """Override in subclass to add rules."""
        pass

    # ── Semantic dimming ───────────────────────────────────

    def set_dimmed_ranges(self, ranges: dict[int, list[tuple[int, int]]]) -> None:
        """
        Set ranges to display dimmed (e.g. unused variables).
        ranges: {block_number: [(char_start, char_length), ...]}
        """
        self._dimmed_ranges = ranges
        self.rehighlight()

    def clear_dimmed(self) -> None:
        self._dimmed_ranges.clear()
        self.rehighlight()

# ── Core highlight ─────────────────────────────────────

    def highlightBlock(self, text: str):
        self.setCurrentBlockState(-1)
        qt_text_len = len(text.encode('utf-16-le')) // 2

        # Step 1: Handle continuation of multiline from previous block
        offset = 0
        for (start_rx, end_rx, fmt, state) in self._multiline:
            if self.previousBlockState() == state:
                em = end_rx.match(text)
                if not em.hasMatch():
                    self.setFormat(0, qt_text_len, fmt)
                    self.setCurrentBlockState(state)
                    self._apply_dimming(text)
                    return
                offset = em.capturedEnd()
                self.setFormat(0, offset, fmt)
                break

        # Step 2: Сбор всех совпадений (лексерный подход Maximum Munch)
        matches = []
        
        for rx, fmt in self._rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                s, l = m.capturedStart(), m.capturedLength()
                if s >= offset:
                    matches.append((s, l, fmt, False, None, None))

        for entry in self._multiline:
            start_rx, end_rx, fmt, state = entry
            it = start_rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                s, l = m.capturedStart(), m.capturedLength()
                if s >= offset:
                    matches.append((s, l, fmt, True, end_rx, state))

        # Сортируем: сначала те, что начались раньше, при равном старте — берем длинные
        matches.sort(key=lambda x: (x[0], -x[1]))

        # Step 3: Применяем совпадения строго слева-направо без наложений
        pos = offset
        for s, l, fmt, is_ml, end_rx, state in matches:
            if s < pos:
                continue  # Пропускаем всё, что находится ВНУТРИ уже закрашенного блока

            if not is_ml:
                self.setFormat(s, l, fmt)
                pos = s + l
            else:
                em = end_rx.match(text, s + l)
                if not em.hasMatch():
                    self.setFormat(s, qt_text_len - s, fmt)
                    self.setCurrentBlockState(state)
                    pos = qt_text_len
                    break
                else:
                    end_pos = em.capturedEnd()
                    self.setFormat(s, end_pos - s, fmt)
                    pos = end_pos

        # Step 4: Применяем оверлеи (эскейп-символы поверх уже закрашенных строк)
        for rx, fmt in self._overlays:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        # Step 5: Apply semantic dimming
        self._apply_dimming(text)

    def _apply_dimming(self, text: str) -> None:
        """Overlay dimmed format on marked ranges for this block."""
        block_num = self.currentBlock().blockNumber()
        ranges = self._dimmed_ranges.get(block_num)
        if ranges:
            for start, length in ranges:
                if start < len(text):
                    # AST/сторонние инструменты дают индексы Python (символы).
                    # Здесь переводим их в UTF-16, так как setFormat работает с Qt-индексами.
                    q_st = len(text[:start].encode('utf-16-le')) // 2
                    q_ln = len(text[start:start+length].encode('utf-16-le')) // 2
                    self.setFormat(q_st, q_ln, self._dimmed_format)


# ══════════════════════════════════════════════════════════
#  Language-specific Highlighters
# ══════════════════════════════════════════════════════════

class PythonHighlighter(BaseHighlighter):
    KW = (r"\b(False|None|True|and|as|assert|async|await|break|class|continue|def|del|elif|"
          r"else|except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|"
          r"raise|return|try|while|with|yield)\b")
    BI = (r"\b(abs|all|any|bin|bool|bytes|callable|chr|dict|dir|divmod|enumerate|eval|exec|"
          r"filter|float|format|frozenset|getattr|globals|hasattr|hash|help|hex|id|input|int|"
          r"isinstance|issubclass|iter|len|list|locals|map|max|min|next|object|oct|open|ord|"
          r"pow|print|property|range|repr|reversed|round|set|setattr|slice|sorted|staticmethod|"
          r"str|sum|super|tuple|type|vars|zip|__name__|__file__|__doc__|__class__)\b")
    
    def _setup_rules(self):
        c = self._c
        self._add(r"@[\w.]+", _fmt(c("deco")))
        self._add(self.KW, _fmt(c("keyword"), bold=True))
        self._add(self.BI, _fmt(c("builtin")))
        self._add(r"\b__[a-zA-Z0-9_]+__\b", _fmt(c("builtin")))
        self._add(r"\b(int|float|str|bool|bytes|list|dict|set|tuple|type|None|Optional|Union|List|Dict|Set|Tuple|Any|Callable|Type|Final)\b", _fmt(c("type_")))
        self._add(r"\b(self|cls)\b", _fmt(c("self_")))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(c("class_")))
        self._add(r"(?<=def\s)(\w+)", _fmt(c("func"), bold=True))
        self._add(r"(?<=class\s)(\w+)", _fmt(c("class_"), bold=True))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(c("func")))
        
        # Эстетика Notepad++ / VS Code
        self._add(r"(?<=\.)[a-zA-Z_]\w*\b", _fmt(c("prop")))
        self._add(r"\b[a-zA-Z_]\w*(?=\s*:)", _fmt(c("prop"), italic=True))
        self._add(r"\b(0x[0-9A-Fa-f]+|0b[01]+|0o[0-7]+|\d+\.?\d*([eE][+-]?\d+)?)\b", _fmt(c("number")))
        self._add(r"[+\-*/%=<>!&|^~:]+", _fmt(c("operator")))
        self._add_overlay(r"\\[nrtbfv\\'\"0abx]", _fmt(c("escape")))
        
        # === ЖЕСТКИЕ ПРАВИЛА ДЛЯ СТРОК ===
        # Строгая группа префиксов вместо звездочки (избавляет от багов PCRE2)
        PFX = r"(?:f|r|b|fr|rf|br|rb|F|R|B|FR|RF|BR|RB)?"
        
        # 1. Многострочные строки (должны идти первыми)
        self._ml(PFX + r'"""', r'"""', _fmt(c("string")), 1)
        self._ml(PFX + r"'''", r"'''", _fmt(c("string")), 2)
        
        # 2. Однострочные строки со строгим запретом (?!...) захвата тройных кавычек!
        self._add(PFX + r'"(?!"")(?:[^"\\]|\\.)*"', _fmt(c("string")))
        self._add(PFX + r"'(?!'')(?:[^'\\]|\\.)*'", _fmt(c("string")))
        
        self._add(r"#[^\n]*", _fmt(c("comment"), italic=True))


class JavaScriptHighlighter(BaseHighlighter):
    KW = (r"\b(break|case|catch|class|const|continue|debugger|default|delete|do|else|export|"
          r"extends|finally|for|function|if|import|in|instanceof|let|new|of|return|static|"
          r"super|switch|this|throw|try|typeof|var|void|while|with|yield|async|await|from|as|"
          r"interface|type|enum|declare|namespace|abstract|implements|readonly|override|public|private|protected|get|set)\b")
    def _setup_rules(self):
        c = self._c
        self._add(self.KW, _fmt(c("keyword"), bold=True))
        self._add(r"\b(true|false|null|undefined|NaN|Infinity)\b", _fmt(c("const")))
        self._add(r"\b(string|number|boolean|any|void|never|unknown|object|symbol|bigint|Array|Promise|Record|Partial|Required|Readonly|Pick|Omit)\b", _fmt(c("type_")))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(c("class_")))
        self._add(r"(?<=function\s)(\w+)", _fmt(c("func"), bold=True))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(c("func")))
        
        # Эстетика Notepad++ / VS Code для JS:
        self._add(r"(?<=\.)[a-zA-Z_]\w*\b", _fmt(c("prop")))  # Свойства (obj.value)
        self._add(r"\b[a-zA-Z_]\w*(?=\s*:)", _fmt(c("prop"), italic=True))  # Ключи и аргументы
        
        self._add(r"\b(0x[0-9A-Fa-f]+|\d+\.?\d*([eE][+-]?\d+)?n?)\b", _fmt(c("number")))
        self._add(r'"(?:[^"\\]|\\.)*"', _fmt(c("string")))
        self._add(r"'(?:[^'\\]|\\.)*'", _fmt(c("string")))
        self._add(r"//[^\n]*", _fmt(c("comment"), italic=True))
        self._ml(r"/\*", r"\*/", _fmt(c("comment"), italic=True), 1)
        
        # ИСПРАВЛЕНИЕ: Шаблонные строки в JS могут быть многострочными!
        self._ml(r"`", r"`", _fmt(c("string")), 2)


class JsonHighlighter(BaseHighlighter):
    def _setup_rules(self):
        c = self._c
        self._add(r'"[^"]*"(?=\s*:)', _fmt(c("prop"), bold=True))
        self._add(r'"[^"]*"', _fmt(c("string")))
        self._add(r"\b-?\d+\.?\d*([eE][+-]?\d+)?\b", _fmt(c("number")))
        self._add(r"\b(true|false|null)\b", _fmt(c("const"), bold=True))
        self._add(r"[{}\[\],:] ", _fmt(c("operator")))


class YamlHighlighter(BaseHighlighter):
    def _setup_rules(self):
        c = self._c
        self._add(r"^[\s-]*\b([\w.-]+)\s*:", _fmt(c("prop"), bold=True))
        self._add(r'"[^"]*"', _fmt(c("string")))
        self._add(r"'[^']*'", _fmt(c("string")))
        self._add(r"[&*]\w+", _fmt(c("deco")))
        self._add(r"\b(true|false|yes|no|null|~)\b", _fmt(c("const")))
        self._add(r"\b-?\d+\.?\d*\b", _fmt(c("number")))
        self._add(r"#[^\n]*", _fmt(c("comment"), italic=True))
        self._add(r"^---", _fmt(c("keyword"), bold=True))


class SqlHighlighter(BaseHighlighter):
    KW = (r"\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|ON|GROUP|BY|ORDER|HAVING|"
          r"LIMIT|OFFSET|UNION|ALL|DISTINCT|AS|AND|OR|NOT|IN|IS|NULL|LIKE|BETWEEN|EXISTS|"
          r"INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|ALTER|DROP|TABLE|INDEX|VIEW|TRIGGER|"
          r"FUNCTION|PROCEDURE|BEGIN|END|IF|THEN|ELSE|CASE|WHEN|DECLARE|CURSOR|FETCH|RETURNS|"
          r"INT|INTEGER|VARCHAR|TEXT|BOOLEAN|DATE|TIMESTAMP|FLOAT|DECIMAL|BIGINT|SERIAL|"
          r"PRIMARY|KEY|FOREIGN|REFERENCES|UNIQUE|DEFAULT|CHECK|CONSTRAINT|"
          r"ASC|DESC|COUNT|SUM|AVG|MIN|MAX|COALESCE|CAST|CONVERT|"
          r"COMMIT|ROLLBACK|TRANSACTION|GRANT|REVOKE|WITH|RECURSIVE|"
          r"EXPLAIN|ANALYZE|PARTITION|WINDOW|OVER|ROW_NUMBER|RANK|DENSE_RANK)\b")
    def _setup_rules(self):
        c = self._c
        self._add(self.KW, _fmt(c("keyword"), bold=True),
                  QRegularExpression.PatternOption.CaseInsensitiveOption)
        self._add(r"\b(TRUE|FALSE|NULL)\b", _fmt(c("const")),
                  QRegularExpression.PatternOption.CaseInsensitiveOption)
        self._add(r"\b\d+\.?\d*\b", _fmt(c("number")))
        self._add(r"'[^']*'", _fmt(c("string")))
        self._add(r'"[^"]*"', _fmt(c("string")))
        self._add(r"--[^\n]*", _fmt(c("comment"), italic=True))
        self._ml(r"/\*", r"\*/", _fmt(c("comment"), italic=True), 1)


class BashHighlighter(BaseHighlighter):
    KW = (r"\b(if|then|else|elif|fi|for|while|do|done|case|esac|in|function|return|"
          r"local|export|source|alias|unalias|readonly|declare|typeset|set|unset|"
          r"shift|trap|exit|exec|eval|true|false|test|echo|printf|read|cd|pwd|ls)\b")
    def _setup_rules(self):
        c = self._c
        self._add(self.KW, _fmt(c("keyword"), bold=True))
        self._add(r"\$\{?\w+\}?", _fmt(c("self_")))
        self._add(r'"[^"]*"', _fmt(c("string")))
        self._add(r"'[^']*'", _fmt(c("string")))
        self._add(r"\b\d+\b", _fmt(c("number")))
        self._add(r"#[^\n]*", _fmt(c("comment"), italic=True))


class CppHighlighter(BaseHighlighter):
    KW = (r"\b(alignas|alignof|and|and_eq|asm|auto|bitand|bitor|bool|break|case|catch|char|"
          r"char8_t|char16_t|char32_t|class|co_await|co_return|co_yield|compl|concept|const|"
          r"consteval|constexpr|constinit|const_cast|continue|decltype|default|delete|do|double|"
          r"dynamic_cast|else|enum|explicit|export|extern|false|float|for|friend|goto|if|inline|"
          r"int|long|mutable|namespace|new|noexcept|not|not_eq|nullptr|operator|or|or_eq|private|"
          r"protected|public|register|reinterpret_cast|requires|return|short|signed|sizeof|static|"
          r"static_assert|static_cast|struct|switch|template|this|throw|true|try|typedef|typeid|"
          r"typename|union|unsigned|using|virtual|void|volatile|wchar_t|while|xor|xor_eq)\b")
    def _setup_rules(self):
        c = self._c
        self._add(r"#\s*(include|define|undef|ifdef|ifndef|if|elif|else|endif|pragma|error|warning)\b", _fmt(c("preproc"), bold=True))
        self._add(self.KW, _fmt(c("keyword"), bold=True))
        self._add(r"\b(size_t|ptrdiff_t|int8_t|int16_t|int32_t|int64_t|uint8_t|uint16_t|uint32_t|uint64_t|"
                  r"string|vector|map|set|list|array|unique_ptr|shared_ptr|optional|variant|pair|tuple)\b", _fmt(c("type_")))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(c("class_")))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(c("func")))
        self._add(r"(?:::|->\.|\.)\b(\w+)\b", _fmt(c("prop")))
        self._add(r"\b(0x[0-9A-Fa-f]+|0b[01]+|\d+\.?\d*([eE][+-]?\d+)?[fFlLuU]*)\b", _fmt(c("number")))
        self._add(r'"(?:[^"\\]|\\.)*"', _fmt(c("string")))
        self._add(r"'(?:[^'\\]|\\.)'", _fmt(c("string")))
        self._add(r"//[^\n]*", _fmt(c("comment"), italic=True))
        self._ml(r"/\*", r"\*/", _fmt(c("comment"), italic=True), 1)


class CSharpHighlighter(BaseHighlighter):
    KW = (r"\b(abstract|as|base|bool|break|byte|case|catch|char|checked|class|const|continue|"
          r"decimal|default|delegate|do|double|else|enum|event|explicit|extern|false|finally|"
          r"fixed|float|for|foreach|goto|if|implicit|in|int|interface|internal|is|lock|long|"
          r"namespace|new|null|object|operator|out|override|params|private|protected|public|"
          r"readonly|ref|return|sbyte|sealed|short|sizeof|stackalloc|static|string|struct|switch|"
          r"this|throw|true|try|typeof|uint|ulong|unchecked|unsafe|ushort|using|var|virtual|void|"
          r"volatile|while|async|await|dynamic|nameof|when|record|init|required|yield)\b")
    def _setup_rules(self):
        c = self._c
        self._add(r"#\s*(if|elif|else|endif|region|endregion|pragma)\b", _fmt(c("preproc")))
        self._add(r"\[[\w.]+\]", _fmt(c("deco")))
        self._add(self.KW, _fmt(c("keyword"), bold=True))
        self._add(r"\b(List|Dictionary|HashSet|Queue|Stack|Task|Action|Func|Tuple|Span|Memory|IEnumerable|IList|ICollection|IDisposable)\b", _fmt(c("type_")))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(c("class_")))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(c("func")))
        self._add(r"\.\b(\w+)\b", _fmt(c("prop")))
        self._add(r"\b\d+\.?\d*[fFdDmMlLuU]*\b", _fmt(c("number")))
        self._add(r'@?"(?:[^"\\]|\\.)*"', _fmt(c("string")))
        self._add(r"'(?:[^'\\]|\\.)'", _fmt(c("string")))
        self._add(r"//[^\n]*", _fmt(c("comment"), italic=True))
        self._ml(r"/\*", r"\*/", _fmt(c("comment"), italic=True), 1)


class JavaHighlighter(BaseHighlighter):
    KW = (r"\b(abstract|assert|boolean|break|byte|case|catch|char|class|const|continue|default|"
          r"do|double|else|enum|extends|final|finally|float|for|goto|if|implements|import|"
          r"instanceof|int|interface|long|native|new|null|package|private|protected|public|"
          r"return|short|static|strictfp|super|switch|synchronized|this|throw|throws|transient|"
          r"try|void|volatile|while|var|yield|record|sealed|permits|non-sealed)\b")
    def _setup_rules(self):
        c = self._c
        self._add(r"@\w+", _fmt(c("deco")))
        self._add(self.KW, _fmt(c("keyword"), bold=True))
        self._add(r"\b(true|false)\b", _fmt(c("const")))
        self._add(r"\b(String|Integer|Boolean|Long|Double|Float|Character|Object|List|Map|Set|Optional|Stream|CompletableFuture|BiFunction|Supplier|Consumer|Predicate)\b", _fmt(c("type_")))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(c("class_")))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(c("func")))
        self._add(r"\.\b(\w+)\b", _fmt(c("prop")))
        self._add(r"\b\d+[\d_]*\.?[\d_]*[fFdDlL]?\b", _fmt(c("number")))
        self._add(r'"(?:[^"\\]|\\.)*"', _fmt(c("string")))
        self._add(r"'(?:[^'\\]|\\.)'", _fmt(c("string")))
        self._add(r"//[^\n]*", _fmt(c("comment"), italic=True))
        self._ml(r"/\*", r"\*/", _fmt(c("comment"), italic=True), 1)


class GoHighlighter(BaseHighlighter):
    KW = (r"\b(break|case|chan|const|continue|default|defer|else|fallthrough|for|func|go|goto|"
          r"if|import|interface|map|package|range|return|select|struct|switch|type|var)\b")
    def _setup_rules(self):
        c = self._c
        self._add(self.KW, _fmt(c("keyword"), bold=True))
        self._add(r"\b(true|false|nil|iota)\b", _fmt(c("const")))
        self._add(r"\b(int|int8|int16|int32|int64|uint|uint8|uint16|uint32|uint64|float32|float64|complex64|complex128|bool|byte|rune|string|error|any|comparable)\b", _fmt(c("type_")))
        self._add(r"\b(append|cap|close|complex|copy|delete|imag|len|make|new|panic|print|println|real|recover)\b", _fmt(c("builtin")))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(c("class_")))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(c("func")))
        self._add(r"\.\b(\w+)\b", _fmt(c("prop")))
        self._add(r"\b(0x[0-9A-Fa-f]+|\d+\.?\d*([eE][+-]?\d+)?)\b", _fmt(c("number")))
        self._add(r'"[^"]*"', _fmt(c("string")))
        self._add(r"`[^`]*`", _fmt(c("string")))
        self._add(r"'[^']*'", _fmt(c("string")))
        self._add(r"//[^\n]*", _fmt(c("comment"), italic=True))
        self._ml(r"/\*", r"\*/", _fmt(c("comment"), italic=True), 1)


class RustHighlighter(BaseHighlighter):
    KW = (r"\b(as|async|await|break|const|continue|crate|dyn|else|enum|extern|false|fn|for|"
          r"if|impl|in|let|loop|match|mod|move|mut|pub|ref|return|self|Self|static|struct|"
          r"super|trait|true|type|union|unsafe|use|where|while|yield|macro_rules)\b")
    def _setup_rules(self):
        c = self._c
        self._add(r"#\[[\w:]+\]", _fmt(c("deco")))
        self._add(r"#!\[[\w:]+\]", _fmt(c("deco")))
        self._add(self.KW, _fmt(c("keyword"), bold=True))
        self._add(r"\b(i8|i16|i32|i64|i128|isize|u8|u16|u32|u64|u128|usize|f32|f64|bool|char|str|"
                  r"String|Vec|Box|Rc|Arc|Cell|RefCell|Option|Result|HashMap|HashSet|BTreeMap|BTreeSet|"
                  r"Cow|Pin|Future|Iterator|IntoIterator|Send|Sync|Sized|Copy|Clone|Drop)\b", _fmt(c("type_")))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(c("class_")))
        self._add(r"(?<=fn\s)(\w+)", _fmt(c("func"), bold=True))
        self._add(r"\b(\w+)(?=\s*[!(])", _fmt(c("func")))
        self._add(r"\.\b(\w+)\b", _fmt(c("prop")))
        self._add(r"\b(0x[0-9A-Fa-f_]+|0b[01_]+|0o[0-7_]+|\d[\d_]*\.?[\d_]*([eE][+-]?\d+)?)\b", _fmt(c("number")))
        self._add(r'"(?:[^"\\]|\\.)*"', _fmt(c("string")))
        self._add(r"'[^']*'", _fmt(c("string")))
        self._add(r"//[^\n]*", _fmt(c("comment"), italic=True))
        self._ml(r"/\*", r"\*/", _fmt(c("comment"), italic=True), 1)


class RubyHighlighter(BaseHighlighter):
    KW = (r"\b(BEGIN|END|alias|and|begin|break|case|class|def|defined|do|else|elsif|end|"
          r"ensure|false|for|if|in|module|next|nil|not|or|redo|rescue|retry|return|self|"
          r"super|then|true|undef|unless|until|when|while|yield|raise|puts|print|p|pp|"
          r"require|require_relative|include|extend|attr_reader|attr_writer|attr_accessor|"
          r"protected|private|public|freeze|frozen|new)\b")
    def _setup_rules(self):
        c = self._c
        self._add(r":[a-zA-Z_]\w*", _fmt(c("const")))
        self._add(r"@{1,2}\w+", _fmt(c("self_")))
        self._add(r"\$\w+", _fmt(c("prop")))
        self._add(self.KW, _fmt(c("keyword"), bold=True))
        self._add(r"\b([A-Z][a-zA-Z0-9_:]*)\b", _fmt(c("class_")))
        self._add(r"(?<=def\s)(\w+[?!]?)", _fmt(c("func"), bold=True))
        self._add(r"\b(\w+[?!]?)(?=\s*\()", _fmt(c("func")))
        self._add(r"\b\d+[\d_]*\.?[\d_]*\b", _fmt(c("number")))
        self._add(r'"(?:[^"\\]|\\.)*"', _fmt(c("string")))
        self._add(r"'[^']*'", _fmt(c("string")))
        self._add(r"#[^\n]*", _fmt(c("comment"), italic=True))
        self._ml("=begin", "=end", _fmt(c("comment"), italic=True), 1)


class PhpHighlighter(BaseHighlighter):
    KW = (r"\b(abstract|and|array|as|break|callable|case|catch|class|clone|const|continue|"
          r"declare|default|die|do|echo|else|elseif|empty|enum|extends|final|finally|fn|for|"
          r"foreach|function|global|goto|if|implements|import|instanceof|interface|isset|list|"
          r"match|namespace|new|null|or|print|private|protected|public|readonly|require|"
          r"return|static|switch|throw|trait|true|false|try|unset|use|var|while|yield)\b")
    def _setup_rules(self):
        c = self._c
        self._add(r"<\?php|\?>", _fmt(c("preproc"), bold=True))
        self._add(r"\$\w+", _fmt(c("self_")))
        self._add(self.KW, _fmt(c("keyword"), bold=True))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(c("class_")))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(c("func")))
        self._add(r"(?:->|::)\b(\w+)\b", _fmt(c("prop")))
        self._add(r"\b\d+\.?\d*\b", _fmt(c("number")))
        self._add(r'"(?:[^"\\]|\\.)*"', _fmt(c("string")))
        self._add(r"'[^']*'", _fmt(c("string")))
        self._add(r"//[^\n]*|#[^\n]*", _fmt(c("comment"), italic=True))
        self._ml(r"/\*", r"\*/", _fmt(c("comment"), italic=True), 1)


class KotlinHighlighter(BaseHighlighter):
    KW = (r"\b(abstract|actual|annotation|as|break|by|catch|class|companion|const|constructor|"
          r"continue|crossinline|data|defer|do|dynamic|else|enum|expect|external|false|final|"
          r"finally|for|fun|get|if|import|in|infix|init|inline|inner|interface|internal|is|it|"
          r"lateinit|noinline|null|object|open|operator|out|override|package|private|protected|"
          r"public|reified|return|sealed|set|super|suspend|tailrec|this|throw|true|try|typealias|"
          r"val|value|var|vararg|when|where|while)\b")
    def _setup_rules(self):
        c = self._c
        self._add(r"@\w+", _fmt(c("deco")))
        self._add(self.KW, _fmt(c("keyword"), bold=True))
        self._add(r"\b(Int|Long|Short|Byte|Double|Float|Boolean|Char|String|Unit|Nothing|Any|Array|List|Map|Set|MutableList|MutableMap|MutableSet|Sequence|Flow|Deferred|Job|Pair|Triple)\b", _fmt(c("type_")))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(c("class_")))
        self._add(r"(?<=fun\s)(\w+)", _fmt(c("func"), bold=True))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(c("func")))
        self._add(r"\.\b(\w+)\b", _fmt(c("prop")))
        self._add(r"\b\d+[\d_]*\.?[\d_]*[fFLuU]?\b", _fmt(c("number")))
        self._add(r'"[^"]*"', _fmt(c("string")))
        self._add(r"'(?:[^'\\]|\\.)'", _fmt(c("string")))
        self._add(r"//[^\n]*", _fmt(c("comment"), italic=True))
        self._ml(r"/\*", r"\*/", _fmt(c("comment"), italic=True), 1)
        self._ml('"""', '"""', _fmt(c("string")), 2)


class SwiftHighlighter(BaseHighlighter):
    KW = (r"\b(actor|as|associatedtype|async|await|break|case|catch|class|continue|convenience|"
          r"default|defer|deinit|do|dynamic|else|enum|extension|fallthrough|false|fileprivate|"
          r"final|for|func|get|guard|if|import|in|indirect|infix|init|inout|internal|is|lazy|"
          r"let|mutating|nil|nonmutating|open|operator|optional|override|postfix|prefix|private|"
          r"protocol|public|repeat|required|rethrows|return|self|Self|set|some|static|struct|"
          r"subscript|super|switch|throws|true|try|typealias|unowned|var|weak|where|while)\b")
    def _setup_rules(self):
        c = self._c
        self._add(r"@\w+", _fmt(c("deco")))
        self._add(r"#\w+", _fmt(c("preproc")))
        self._add(self.KW, _fmt(c("keyword"), bold=True))
        self._add(r"\b(Int|Int8|Int16|Int32|Int64|UInt|Float|Double|Bool|String|Character|Void|Optional|Array|Dictionary|Set|Any|AnyObject|Never|Result|Error)\b", _fmt(c("type_")))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(c("class_")))
        self._add(r"(?<=func\s)(\w+)", _fmt(c("func"), bold=True))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(c("func")))
        self._add(r"\.\b(\w+)\b", _fmt(c("prop")))
        self._add(r"\b\d+\.?\d*\b", _fmt(c("number")))
        self._add(r'"(?:[^"\\]|\\.)*"', _fmt(c("string")))
        self._add(r"//[^\n]*", _fmt(c("comment"), italic=True))
        self._ml(r"/\*", r"\*/", _fmt(c("comment"), italic=True), 1)


class MarkdownHighlighter(BaseHighlighter):
    def _setup_rules(self):
        c = self._c
        self._add(r"^#{1,6}\s.*", _fmt(c("keyword"), bold=True))
        self._add(r"\*\*[^*]+\*\*", _fmt(c("class_"), bold=True))
        self._add(r"\*[^*]+\*", _fmt(c("string"), italic=True))
        self._add(r"`[^`]+`", _fmt(c("const")))
        self._add(r"\[([^\]]+)\]\([^\)]+\)", _fmt(c("func")))
        self._add(r"^>\s.*", _fmt(c("comment"), italic=True))
        self._add(r"^\s*[-*+]\s", _fmt(c("builtin")))
        self._add(r"^\s*\d+\.\s", _fmt(c("builtin")))
        self._ml("```", "```", _fmt(c("const")), 1)


class TomlHighlighter(BaseHighlighter):
    def _setup_rules(self):
        c = self._c
        self._add(r"^\[\[?[\w.]+\]?\]", _fmt(c("class_"), bold=True))
        self._add(r"^\s*\w[\w.-]*\s*=", _fmt(c("prop")))
        self._add(r'"[^"]*"', _fmt(c("string")))
        self._add(r"'[^']*'", _fmt(c("string")))
        self._add(r"\b(true|false)\b", _fmt(c("const")))
        self._add(r"\b\d[\d_]*\.?[\d_]*\b", _fmt(c("number")))
        self._add(r"#[^\n]*", _fmt(c("comment"), italic=True))


# ══════════════════════════════════════════════════════════
#  Extension Map & Factory
# ══════════════════════════════════════════════════════════

_EXTENSION_MAP: dict[str, type] = {
    ".py": PythonHighlighter, ".pyw": PythonHighlighter, ".pyi": PythonHighlighter,
    ".js": JavaScriptHighlighter, ".jsx": JavaScriptHighlighter,
    ".ts": JavaScriptHighlighter, ".tsx": JavaScriptHighlighter,
    ".mjs": JavaScriptHighlighter, ".cjs": JavaScriptHighlighter,
    ".json": JsonHighlighter,
    ".yaml": YamlHighlighter, ".yml": YamlHighlighter,
    ".sql": SqlHighlighter,
    ".sh": BashHighlighter, ".bash": BashHighlighter, ".zsh": BashHighlighter, ".ksh": BashHighlighter,
    ".md": MarkdownHighlighter, ".markdown": MarkdownHighlighter,
    ".c": CppHighlighter, ".h": CppHighlighter,
    ".cpp": CppHighlighter, ".cxx": CppHighlighter, ".cc": CppHighlighter,
    ".hpp": CppHighlighter, ".hxx": CppHighlighter,
    ".cs": CSharpHighlighter,
    ".java": JavaHighlighter,
    ".go": GoHighlighter,
    ".rs": RustHighlighter,
    ".rb": RubyHighlighter,
    ".php": PhpHighlighter, ".phtml": PhpHighlighter,
    ".kt": KotlinHighlighter, ".kts": KotlinHighlighter,
    ".swift": SwiftHighlighter,
    ".toml": TomlHighlighter, ".ini": TomlHighlighter, ".cfg": TomlHighlighter,
}


def create_highlighter(document: QTextDocument, file_path: str) -> BaseHighlighter | None:
    from pathlib import Path
    cls = _EXTENSION_MAP.get(Path(file_path).suffix.lower())
    return cls(document) if cls else None


def language_name(file_path: str) -> str:
    from pathlib import Path
    return {
        ".py": "Python", ".pyi": "Python Stub",
        ".js": "JavaScript", ".jsx": "JS (JSX)",
        ".ts": "TypeScript", ".tsx": "TS (TSX)", ".mjs": "ESModule",
        ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".sql": "SQL",
        ".sh": "Shell", ".bash": "Bash", ".zsh": "Zsh",
        ".md": "Markdown", ".c": "C", ".h": "C Header",
        ".cpp": "C++", ".cxx": "C++", ".cc": "C++",
        ".cs": "C#", ".java": "Java", ".go": "Go",
        ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
        ".kt": "Kotlin", ".kts": "Kotlin Script", ".swift": "Swift",
        ".toml": "TOML", ".ini": "INI", ".cfg": "Config",
        ".xml": "XML", ".html": "HTML", ".css": "CSS",
        ".txt": "Plain Text", ".log": "Log",
    }.get(Path(file_path).suffix.lower(), "Plain Text")
