"""
Multi-language syntax highlighter — 19 languages, TokyoNight palette.
Supports: Python, JS/TS, JSON, YAML, SQL, Bash, Markdown,
          C/C++, C#, Java, Go, Rust, Ruby, PHP, Kotlin, Swift, TOML.
"""
from __future__ import annotations
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold: f.setFontWeight(QFont.Weight.Bold)
    if italic: f.setFontItalic(True)
    return f

C_KEYWORD  = "#7AA2F7"; C_BUILTIN  = "#BB9AF7"; C_STRING   = "#9ECE6A"
C_COMMENT  = "#565f89"; C_NUMBER   = "#FF9E64"; C_FUNC     = "#61AFEF"
C_CLASS    = "#E0AF68"; C_DECO     = "#E0AF68"; C_OPERATOR = "#89DDFF"
C_SELF     = "#F7768E"; C_CONST    = "#FF9E64"; C_PROP     = "#73DACA"
C_TYPE     = "#2AC3DE"; C_PREPROC  = "#FF9E64"; C_ESCAPE   = "#F7768E"


class BaseHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self._rules: list[tuple] = []
        self._multiline: list[tuple] = []
        self._setup_rules()

    def _add(self, pat, fmt, flags=QRegularExpression.PatternOption(0)):
        rx = QRegularExpression(pat)
        if flags: rx.setPatternOptions(flags)
        self._rules.append((rx, fmt))

    def _ml(self, start, end, fmt, state):
        self._multiline.append((QRegularExpression(start), QRegularExpression(end), fmt, state))

    def _setup_rules(self): pass

    def highlightBlock(self, text: str):
        self.setCurrentBlockState(-1)
        offset = 0  # end of any multiline block prefix on this line

        # Step 1: Handle continuation of multiline from previous line
        for (start_rx, end_rx, fmt, state) in self._multiline:
            if self.previousBlockState() == state:
                em = end_rx.match(text)
                if not em.hasMatch():
                    # Whole line is still inside multiline block
                    self.setFormat(0, len(text), fmt)
                    self.setCurrentBlockState(state)
                    return
                # Multiline ends mid-line
                offset = em.capturedEnd()
                self.setFormat(0, offset, fmt)
                break

        # Step 2: Apply single-line rules only to part after multiline prefix
        for rx, fmt in self._rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                s, l = m.capturedStart(), m.capturedLength()
                if s >= offset:
                    self.setFormat(s, l, fmt)

        # Step 3: Paint new multiline blocks starting from offset (wins over single-line)
        for (start_rx, end_rx, fmt, state) in self._multiline:
            sm = start_rx.match(text, offset)
            if not sm.hasMatch():
                continue
            sp = sm.capturedStart()
            em = end_rx.match(text, sm.capturedEnd())
            if not em.hasMatch():
                self.setFormat(sp, len(text) - sp, fmt)
                self.setCurrentBlockState(state)
            else:
                self.setFormat(sp, em.capturedEnd() - sp, fmt)
            break  # only first opener per line


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
        self._add(r"@[\w.]+", _fmt(C_DECO))
        self._add(self.KW, _fmt(C_KEYWORD, bold=True))
        self._add(self.BI, _fmt(C_BUILTIN))
        self._add(r"\b(int|float|str|bool|bytes|list|dict|set|tuple|type|None|Optional|Union|List|Dict|Set|Tuple|Any|Callable|Type|Final)\b", _fmt(C_TYPE))
        self._add(r"\b(self|cls)\b", _fmt(C_SELF))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(C_CLASS))
        self._add(r"(?<=def\s)(\w+)", _fmt(C_FUNC, bold=True))
        self._add(r"(?<=class\s)(\w+)", _fmt(C_CLASS, bold=True))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(C_FUNC))
        self._add(r"\b(0x[0-9A-Fa-f]+|0b[01]+|0o[0-7]+|\d+\.?\d*([eE][+-]?\d+)?)\b", _fmt(C_NUMBER))
        self._add(r"[+\-*/%=<>!&|^~:]+", _fmt(C_OPERATOR))
        self._add(r"\\[nrtbfv\\'\"0abx]", _fmt(C_ESCAPE))
        self._add(r'[fFrRbB]*"[^"\\]*"', _fmt(C_STRING))
        self._add(r"[fFrRbB]*'[^'\\]*'", _fmt(C_STRING))
        self._add(r"#[^\n]*", _fmt(C_COMMENT, italic=True))
        self._ml('"""', '"""', _fmt(C_STRING), 1)
        self._ml("'''", "'''", _fmt(C_STRING), 2)


class JavaScriptHighlighter(BaseHighlighter):
    KW = (r"\b(break|case|catch|class|const|continue|debugger|default|delete|do|else|export|"
          r"extends|finally|for|function|if|import|in|instanceof|let|new|of|return|static|"
          r"super|switch|this|throw|try|typeof|var|void|while|with|yield|async|await|from|as|"
          r"interface|type|enum|declare|namespace|abstract|implements|readonly|override|public|private|protected|get|set)\b")
    def _setup_rules(self):
        self._add(self.KW, _fmt(C_KEYWORD, bold=True))
        self._add(r"\b(true|false|null|undefined|NaN|Infinity)\b", _fmt(C_CONST))
        self._add(r"\b(string|number|boolean|any|void|never|unknown|object|symbol|bigint|Array|Promise|Record|Partial|Required|Readonly|Pick|Omit)\b", _fmt(C_TYPE))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(C_CLASS))
        self._add(r"(?<=function\s)(\w+)", _fmt(C_FUNC, bold=True))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(C_FUNC))
        self._add(r"\.\b(\w+)\b", _fmt(C_PROP))
        self._add(r"\b(0x[0-9A-Fa-f]+|\d+\.?\d*([eE][+-]?\d+)?n?)\b", _fmt(C_NUMBER))
        self._add(r"`[^`]*`", _fmt(C_STRING))
        self._add(r'"[^"\\]*"', _fmt(C_STRING))
        self._add(r"'[^'\\]*'", _fmt(C_STRING))
        self._add(r"//[^\n]*", _fmt(C_COMMENT, italic=True))
        self._ml(r"/\*", r"\*/", _fmt(C_COMMENT, italic=True), 1)


class JsonHighlighter(BaseHighlighter):
    def _setup_rules(self):
        self._add(r'"[^"]*"(?=\s*:)', _fmt(C_PROP, bold=True))
        self._add(r'"[^"]*"', _fmt(C_STRING))
        self._add(r"\b-?\d+\.?\d*([eE][+-]?\d+)?\b", _fmt(C_NUMBER))
        self._add(r"\b(true|false|null)\b", _fmt(C_CONST, bold=True))
        self._add(r"[{}\[\],:] ", _fmt(C_OPERATOR))


class YamlHighlighter(BaseHighlighter):
    def _setup_rules(self):
        self._add(r"^[\s-]*\b([\w.-]+)\s*:", _fmt(C_PROP, bold=True))
        self._add(r'"[^"]*"', _fmt(C_STRING)); self._add(r"'[^']*'", _fmt(C_STRING))
        self._add(r"[&*]\w+", _fmt(C_DECO))
        self._add(r"\b(true|false|yes|no|null|~)\b", _fmt(C_CONST))
        self._add(r"\b-?\d+\.?\d*\b", _fmt(C_NUMBER))
        self._add(r"#[^\n]*", _fmt(C_COMMENT, italic=True))
        self._add(r"^---", _fmt(C_KEYWORD, bold=True))


class SqlHighlighter(BaseHighlighter):
    KW = (r"\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|ON|GROUP|BY|ORDER|HAVING|"
          r"LIMIT|OFFSET|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|TABLE|VIEW|DROP|ALTER|"
          r"ADD|COLUMN|PRIMARY|KEY|FOREIGN|REFERENCES|NOT|NULL|DEFAULT|UNIQUE|CHECK|AND|OR|"
          r"IN|LIKE|BETWEEN|EXISTS|CASE|WHEN|THEN|ELSE|END|AS|DISTINCT|UNION|WITH|BEGIN|"
          r"COMMIT|ROLLBACK|TRANSACTION|IF|REPLACE|RETURNING)\b")
    FN = (r"\b(COUNT|SUM|AVG|MAX|MIN|COALESCE|NULLIF|CAST|CONVERT|UPPER|LOWER|TRIM|"
          r"SUBSTRING|CONCAT|LENGTH|NOW|CURRENT_DATE|ROW_NUMBER|RANK|DENSE_RANK|LAG|LEAD|"
          r"OVER|PARTITION|FLOOR|CEIL|ROUND|ISNULL|IFNULL|TO_CHAR|TO_DATE|DATEADD|DATEDIFF)\b")
    def _setup_rules(self):
        ci = QRegularExpression.PatternOption.CaseInsensitiveOption
        self._add(self.KW, _fmt(C_KEYWORD, bold=True), ci)
        self._add(self.FN, _fmt(C_BUILTIN), ci)
        self._add(r"\b(INT|INTEGER|BIGINT|VARCHAR|TEXT|BLOB|DATE|DATETIME|TIMESTAMP|BOOLEAN|FLOAT|DOUBLE|DECIMAL|JSON|UUID|SERIAL)\b", _fmt(C_TYPE), ci)
        self._add(r"'[^']*'", _fmt(C_STRING))
        self._add(r"\b\d+\.?\d*\b", _fmt(C_NUMBER))
        self._add(r"--[^\n]*", _fmt(C_COMMENT, italic=True))
        self._ml(r"/\*", r"\*/", _fmt(C_COMMENT, italic=True), 1)


class BashHighlighter(BaseHighlighter):
    def _setup_rules(self):
        self._add(r"\b(if|then|else|elif|fi|for|while|do|done|case|esac|function|return|exit|local|export|source|alias|break|continue|in|select|until|trap|eval|exec)\b", _fmt(C_KEYWORD, bold=True))
        self._add(r"\b(echo|printf|read|cd|ls|cp|mv|rm|mkdir|chmod|chown|grep|sed|awk|find|sort|cut|head|tail|cat|touch|test|which|set|declare|pwd|date|sleep|kill)\b", _fmt(C_BUILTIN))
        self._add(r"\$\{?[\w@#?$!*-]+\}?", _fmt(C_PROP))
        self._add(r'"[^"]*"', _fmt(C_STRING)); self._add(r"'[^']*'", _fmt(C_STRING))
        self._add(r"`[^`]*`", _fmt(C_CONST))
        self._add(r"\b\d+\b", _fmt(C_NUMBER))
        self._add(r"#[^\n]*", _fmt(C_COMMENT, italic=True))
        self._add(r"^#!.*", _fmt(C_DECO))
        self._add(r"[|&;><]+", _fmt(C_OPERATOR))


class CppHighlighter(BaseHighlighter):
    KW = (r"\b(auto|break|case|catch|class|const|constexpr|continue|decltype|default|delete|"
          r"do|else|enum|explicit|extern|false|for|friend|goto|if|inline|mutable|namespace|"
          r"new|noexcept|nullptr|operator|override|private|protected|public|return|sizeof|"
          r"static|struct|switch|template|this|throw|true|try|typedef|typename|union|"
          r"using|virtual|volatile|while|concept|requires|consteval|final|co_await|co_return)\b")
    TY = (r"\b(void|bool|char|short|int|long|float|double|unsigned|signed|size_t|string|"
          r"vector|map|set|list|deque|array|pair|tuple|optional|shared_ptr|unique_ptr|"
          r"weak_ptr|thread|mutex|atomic|int8_t|int16_t|int32_t|int64_t|uint8_t|uint16_t|uint32_t|uint64_t)\b")
    def _setup_rules(self):
        self._add(r"^\s*#\s*\w+.*", _fmt(C_PREPROC))
        self._add(self.KW, _fmt(C_KEYWORD, bold=True))
        self._add(self.TY, _fmt(C_TYPE))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(C_CLASS))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(C_FUNC))
        self._add(r"(?:::|->|\.)\s*(\w+)", _fmt(C_PROP))
        self._add(r"\b(0x[0-9A-Fa-f]+[lLuU]*|\d+\.?\d*[fFlL]?)\b", _fmt(C_NUMBER))
        self._add(r'"(?:[^"\\]|\\.)*"', _fmt(C_STRING))
        self._add(r"'(?:[^'\\]|\\.)*'", _fmt(C_STRING))
        self._add(r"[+\-*/%=<>!&|^~]+", _fmt(C_OPERATOR))
        self._add(r"//[^\n]*", _fmt(C_COMMENT, italic=True))
        self._ml(r"/\*", r"\*/", _fmt(C_COMMENT, italic=True), 1)


class CSharpHighlighter(BaseHighlighter):
    KW = (r"\b(abstract|as|base|bool|break|byte|case|catch|char|checked|class|const|continue|"
          r"decimal|default|delegate|do|double|else|enum|event|explicit|extern|false|finally|"
          r"fixed|float|for|foreach|goto|if|implicit|in|int|interface|internal|is|lock|long|"
          r"namespace|new|null|object|operator|out|override|params|private|protected|public|"
          r"readonly|ref|return|sbyte|sealed|short|sizeof|static|string|struct|switch|this|"
          r"throw|true|try|typeof|uint|ulong|unchecked|unsafe|ushort|using|virtual|void|"
          r"volatile|while|async|await|var|dynamic|yield|nameof|when|record|init|with|required|file|global)\b")
    def _setup_rules(self):
        self._add(r"\[[\w.,\s()]+\]", _fmt(C_DECO))
        self._add(r"^\s*#\s*\w+.*", _fmt(C_PREPROC))
        self._add(self.KW, _fmt(C_KEYWORD, bold=True))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(C_CLASS))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(C_FUNC))
        self._add(r"\.\b(\w+)\b", _fmt(C_PROP))
        self._add(r"\b(0x[0-9A-Fa-f]+[lLuU]*|\d+\.?\d*[fFdDmM]?[lL]?)\b", _fmt(C_NUMBER))
        self._add(r'@?"(?:[^"\\]|\\.)*"', _fmt(C_STRING))
        self._add(r"'(?:[^'\\]|\\.)'", _fmt(C_STRING))
        self._add(r"///[^\n]*", _fmt(C_PROP, italic=True))
        self._add(r"//[^\n]*", _fmt(C_COMMENT, italic=True))
        self._ml(r"/\*", r"\*/", _fmt(C_COMMENT, italic=True), 1)


class JavaHighlighter(BaseHighlighter):
    KW = (r"\b(abstract|assert|boolean|break|byte|case|catch|char|class|const|continue|"
          r"default|do|double|else|enum|extends|final|finally|float|for|goto|if|implements|"
          r"import|instanceof|int|interface|long|native|new|package|private|protected|public|"
          r"return|short|static|strictfp|super|switch|synchronized|this|throw|throws|"
          r"transient|try|var|void|volatile|while|record|sealed|permits|yield|null|true|false)\b")
    def _setup_rules(self):
        self._add(r"@\w+", _fmt(C_DECO))
        self._add(self.KW, _fmt(C_KEYWORD, bold=True))
        self._add(r"\b(String|Integer|Long|Double|Float|Boolean|Object|Number|List|Map|Set|Optional|Stream|Void|Collection)\b", _fmt(C_TYPE))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(C_CLASS))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(C_FUNC))
        self._add(r"\.\b(\w+)\b", _fmt(C_PROP))
        self._add(r"\b(0x[0-9A-Fa-f]+[lL]?|\d+\.?\d*[fFdDlL]?)\b", _fmt(C_NUMBER))
        self._add(r'"(?:[^"\\]|\\.)*"', _fmt(C_STRING))
        self._add(r"'(?:[^'\\]|\\.)'", _fmt(C_STRING))
        self._add(r"//[^\n]*", _fmt(C_COMMENT, italic=True))
        self._ml(r"/\*", r"\*/", _fmt(C_COMMENT, italic=True), 1)


class GoHighlighter(BaseHighlighter):
    def _setup_rules(self):
        self._add(r"\b(break|case|chan|const|continue|default|defer|else|fallthrough|for|func|go|goto|if|import|interface|map|package|range|return|select|struct|switch|type|var)\b", _fmt(C_KEYWORD, bold=True))
        self._add(r"\b(append|cap|close|complex|copy|delete|imag|len|make|new|panic|print|println|real|recover|error|string|bool|byte|rune|int|int8|int16|int32|int64|uint|uint8|uint16|uint32|uint64|float32|float64|any)\b", _fmt(C_BUILTIN))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(C_CLASS))
        self._add(r"(?<=func\s)(\w+)", _fmt(C_FUNC, bold=True))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(C_FUNC))
        self._add(r"\.\b(\w+)\b", _fmt(C_PROP))
        self._add(r"\b(true|false|nil|iota)\b", _fmt(C_CONST))
        self._add(r"\b(0x[0-9A-Fa-f]+|\d+\.?\d*)\b", _fmt(C_NUMBER))
        self._add(r'`[^`]*`', _fmt(C_STRING))
        self._add(r'"(?:[^"\\]|\\.)*"', _fmt(C_STRING))
        self._add(r"'(?:[^'\\]|\\.)'", _fmt(C_STRING))
        self._add(r"//[^\n]*", _fmt(C_COMMENT, italic=True))
        self._ml(r"/\*", r"\*/", _fmt(C_COMMENT, italic=True), 1)


class RustHighlighter(BaseHighlighter):
    KW = (r"\b(as|async|await|break|const|continue|crate|dyn|else|enum|extern|false|fn|for|"
          r"if|impl|in|let|loop|match|mod|move|mut|pub|ref|return|self|Self|static|struct|"
          r"super|trait|true|type|union|unsafe|use|where|while|abstract|become|box|do|final|"
          r"macro|override|priv|try|typeof|unsized|virtual|yield)\b")
    TY = (r"\b(i8|i16|i32|i64|i128|isize|u8|u16|u32|u64|u128|usize|f32|f64|bool|char|str|"
          r"String|Vec|HashMap|HashSet|Option|Result|Box|Rc|Arc|Cell|RefCell|Mutex|"
          r"Iterator|From|Into|Display|Debug|Clone|Copy|Send|Sync|Default|Ord|PartialOrd|Eq|PartialEq|Drop|Fn|FnMut|FnOnce)\b")
    def _setup_rules(self):
        self._add(r"'\w+\b(?!')", _fmt(C_DECO))  # lifetimes
        self._add(r"\b\w+!", _fmt(C_BUILTIN))     # macros
        self._add(r"#!?\[.*?\]", _fmt(C_DECO))   # attributes
        self._add(self.KW, _fmt(C_KEYWORD, bold=True))
        self._add(self.TY, _fmt(C_TYPE))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(C_CLASS))
        self._add(r"(?<=fn\s)(\w+)", _fmt(C_FUNC, bold=True))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(C_FUNC))
        self._add(r"(?:::|\.)\b(\w+)\b", _fmt(C_PROP))
        self._add(r"\b(0x[0-9A-Fa-f_]+|0b[01_]+|\d[\d_]*\.?[\d_]*)\b", _fmt(C_NUMBER))
        self._add(r'r#?"(?:[^"\\]|\\.)*"', _fmt(C_STRING))
        self._add(r"b?'(?:[^'\\]|\\.)'", _fmt(C_STRING))
        self._add(r"///[^\n]*", _fmt(C_PROP, italic=True))
        self._add(r"//[^\n]*", _fmt(C_COMMENT, italic=True))
        self._ml(r"/\*", r"\*/", _fmt(C_COMMENT, italic=True), 1)


class RubyHighlighter(BaseHighlighter):
    KW = (r"\b(BEGIN|END|alias|and|begin|break|case|class|def|defined|do|else|elsif|end|"
          r"ensure|false|for|if|in|module|next|nil|not|or|redo|rescue|retry|return|self|"
          r"super|then|true|undef|unless|until|when|while|yield|raise|puts|print|p|pp|"
          r"require|require_relative|include|extend|attr_reader|attr_writer|attr_accessor|"
          r"protected|private|public|freeze|frozen|new)\b")
    def _setup_rules(self):
        self._add(r":[a-zA-Z_]\w*", _fmt(C_CONST))
        self._add(r"@{1,2}\w+", _fmt(C_SELF))
        self._add(r"\$\w+", _fmt(C_PROP))
        self._add(self.KW, _fmt(C_KEYWORD, bold=True))
        self._add(r"\b([A-Z][a-zA-Z0-9_:]*)\b", _fmt(C_CLASS))
        self._add(r"(?<=def\s)(\w+[?!]?)", _fmt(C_FUNC, bold=True))
        self._add(r"\b(\w+[?!]?)(?=\s*\()", _fmt(C_FUNC))
        self._add(r"\b\d+[\d_]*\.?[\d_]*\b", _fmt(C_NUMBER))
        self._add(r'"(?:[^"\\]|\\.)*"', _fmt(C_STRING))
        self._add(r"'[^']*'", _fmt(C_STRING))
        self._add(r"#[^\n]*", _fmt(C_COMMENT, italic=True))
        self._ml("=begin", "=end", _fmt(C_COMMENT, italic=True), 1)


class PhpHighlighter(BaseHighlighter):
    KW = (r"\b(abstract|and|array|as|break|callable|case|catch|class|clone|const|continue|"
          r"declare|default|die|do|echo|else|elseif|empty|enum|extends|final|finally|fn|for|"
          r"foreach|function|global|goto|if|implements|import|instanceof|interface|isset|list|"
          r"match|namespace|new|null|or|print|private|protected|public|readonly|require|"
          r"return|static|switch|throw|trait|true|false|try|unset|use|var|while|yield)\b")
    def _setup_rules(self):
        self._add(r"<\?php|\?>", _fmt(C_PREPROC, bold=True))
        self._add(r"\$\w+", _fmt(C_SELF))
        self._add(self.KW, _fmt(C_KEYWORD, bold=True))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(C_CLASS))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(C_FUNC))
        self._add(r"(?:->|::)\b(\w+)\b", _fmt(C_PROP))
        self._add(r"\b\d+\.?\d*\b", _fmt(C_NUMBER))
        self._add(r'"(?:[^"\\]|\\.)*"', _fmt(C_STRING))
        self._add(r"'[^']*'", _fmt(C_STRING))
        self._add(r"//[^\n]*|#[^\n]*", _fmt(C_COMMENT, italic=True))
        self._ml(r"/\*", r"\*/", _fmt(C_COMMENT, italic=True), 1)


class KotlinHighlighter(BaseHighlighter):
    KW = (r"\b(abstract|actual|annotation|as|break|by|catch|class|companion|const|constructor|"
          r"continue|crossinline|data|defer|do|dynamic|else|enum|expect|external|false|final|"
          r"finally|for|fun|get|if|import|in|infix|init|inline|inner|interface|internal|is|it|"
          r"lateinit|noinline|null|object|open|operator|out|override|package|private|protected|"
          r"public|reified|return|sealed|set|super|suspend|tailrec|this|throw|true|try|typealias|"
          r"val|value|var|vararg|when|where|while)\b")
    def _setup_rules(self):
        self._add(r"@\w+", _fmt(C_DECO))
        self._add(self.KW, _fmt(C_KEYWORD, bold=True))
        self._add(r"\b(Int|Long|Short|Byte|Double|Float|Boolean|Char|String|Unit|Nothing|Any|Array|List|Map|Set|MutableList|MutableMap|MutableSet|Sequence|Flow|Deferred|Job|Pair|Triple)\b", _fmt(C_TYPE))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(C_CLASS))
        self._add(r"(?<=fun\s)(\w+)", _fmt(C_FUNC, bold=True))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(C_FUNC))
        self._add(r"\.\b(\w+)\b", _fmt(C_PROP))
        self._add(r"\b\d+[\d_]*\.?[\d_]*[fFLuU]?\b", _fmt(C_NUMBER))
        self._add(r'"[^"]*"', _fmt(C_STRING))
        self._add(r"'(?:[^'\\]|\\.)'", _fmt(C_STRING))
        self._add(r"//[^\n]*", _fmt(C_COMMENT, italic=True))
        self._ml(r"/\*", r"\*/", _fmt(C_COMMENT, italic=True), 1)
        self._ml('"""', '"""', _fmt(C_STRING), 2)


class SwiftHighlighter(BaseHighlighter):
    KW = (r"\b(actor|as|associatedtype|async|await|break|case|catch|class|continue|convenience|"
          r"default|defer|deinit|do|dynamic|else|enum|extension|fallthrough|false|fileprivate|"
          r"final|for|func|get|guard|if|import|in|indirect|infix|init|inout|internal|is|lazy|"
          r"let|mutating|nil|nonmutating|open|operator|optional|override|postfix|prefix|private|"
          r"protocol|public|repeat|required|rethrows|return|self|Self|set|some|static|struct|"
          r"subscript|super|switch|throws|true|try|typealias|unowned|var|weak|where|while)\b")
    def _setup_rules(self):
        self._add(r"@\w+", _fmt(C_DECO))
        self._add(r"#\w+", _fmt(C_PREPROC))
        self._add(self.KW, _fmt(C_KEYWORD, bold=True))
        self._add(r"\b(Int|Int8|Int16|Int32|Int64|UInt|Float|Double|Bool|String|Character|Void|Optional|Array|Dictionary|Set|Any|AnyObject|Never|Result|Error)\b", _fmt(C_TYPE))
        self._add(r"\b([A-Z][a-zA-Z0-9_]*)\b", _fmt(C_CLASS))
        self._add(r"(?<=func\s)(\w+)", _fmt(C_FUNC, bold=True))
        self._add(r"\b(\w+)(?=\s*\()", _fmt(C_FUNC))
        self._add(r"\.\b(\w+)\b", _fmt(C_PROP))
        self._add(r"\b\d+\.?\d*\b", _fmt(C_NUMBER))
        self._add(r'"(?:[^"\\]|\\.)*"', _fmt(C_STRING))
        self._add(r"//[^\n]*", _fmt(C_COMMENT, italic=True))
        self._ml(r"/\*", r"\*/", _fmt(C_COMMENT, italic=True), 1)


class MarkdownHighlighter(BaseHighlighter):
    def _setup_rules(self):
        self._add(r"^#{1,6}\s.*", _fmt(C_KEYWORD, bold=True))
        self._add(r"\*\*[^*]+\*\*", _fmt(C_CLASS, bold=True))
        self._add(r"\*[^*]+\*", _fmt(C_STRING, italic=True))
        self._add(r"`[^`]+`", _fmt(C_CONST))
        self._add(r"\[([^\]]+)\]\([^\)]+\)", _fmt(C_FUNC))
        self._add(r"^>\s.*", _fmt(C_COMMENT, italic=True))
        self._add(r"^\s*[-*+]\s", _fmt(C_BUILTIN))
        self._add(r"^\s*\d+\.\s", _fmt(C_BUILTIN))
        self._ml("```", "```", _fmt(C_CONST), 1)


class TomlHighlighter(BaseHighlighter):
    def _setup_rules(self):
        self._add(r"^\[\[?[\w.]+\]?\]", _fmt(C_CLASS, bold=True))
        self._add(r"^\s*\w[\w.-]*\s*=", _fmt(C_PROP))
        self._add(r'"[^"]*"', _fmt(C_STRING)); self._add(r"'[^']*'", _fmt(C_STRING))
        self._add(r"\b(true|false)\b", _fmt(C_CONST))
        self._add(r"\b\d[\d_]*\.?[\d_]*\b", _fmt(C_NUMBER))
        self._add(r"#[^\n]*", _fmt(C_COMMENT, italic=True))


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
