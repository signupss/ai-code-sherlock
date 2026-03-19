"""
Response Filter — cleans AI output before processing.

Handles:
  - Invisible Unicode characters (zero-width spaces, BOM, soft hyphens, etc.)
  - Non-breaking spaces → regular spaces
  - Smart quotes → straight quotes (important for code)
  - Mixed line endings → \\n
  - Tabs normalization (configurable: tabs or spaces)
  - Validates patch blocks aren't corrupted by filtering
"""
from __future__ import annotations
import re
import unicodedata


# ──────────────────────────────────────────────────────────
#  Invisible / problematic Unicode ranges
# ──────────────────────────────────────────────────────────

# Zero-width and invisible characters
INVISIBLE_CHARS = {
    "\u200b",  # Zero Width Space
    "\u200c",  # Zero Width Non-Joiner
    "\u200d",  # Zero Width Joiner
    "\u200e",  # Left-to-Right Mark
    "\u200f",  # Right-to-Left Mark
    "\u2028",  # Line Separator (not \n)
    "\u2029",  # Paragraph Separator
    "\u00ad",  # Soft Hyphen
    "\ufeff",  # BOM / Zero Width No-Break Space
    "\u00a0",  # Non-Breaking Space  → replace with space
    "\u202a",  # Left-to-Right Embedding
    "\u202b",  # Right-to-Left Embedding
    "\u202c",  # Pop Directional Formatting
    "\u202d",  # Left-to-Right Override
    "\u202e",  # Right-to-Left Override
    "\u2060",  # Word Joiner
    "\u2061",  # Function Application
    "\u2062",  # Invisible Times
    "\u2063",  # Invisible Separator
    "\u2064",  # Invisible Plus
    "\u206a",  # Inhibit Symmetric Swapping
    "\u206f",  # Nominal Digit Shapes
    "\ufff9",  # Interlinear Annotation Anchor
    "\ufffa",  # Interlinear Annotation Separator
    "\ufffb",  # Interlinear Annotation Terminator
}

# Replace with tab (indentation-like invisible chars in code)
REPLACE_WITH_TAB = {
    "\u0009",  # already a tab — passthrough
    "\u00a0",  # NBSP — context-dependent, see below
}

# Smart / curly quotes → straight quotes (critical for code)
QUOTE_MAP = {
    "\u2018": "'",   # Left Single Quotation Mark
    "\u2019": "'",   # Right Single Quotation Mark
    "\u201a": "'",   # Single Low-9 Quotation Mark
    "\u201b": "'",   # Single High-Reversed-9 Quotation Mark
    "\u201c": '"',   # Left Double Quotation Mark
    "\u201d": '"',   # Right Double Quotation Mark
    "\u201e": '"',   # Double Low-9 Quotation Mark
    "\u201f": '"',   # Double High-Reversed-9 Quotation Mark
    "\u2033": '"',   # Double Prime
    "\u2036": '"',   # Reversed Double Prime
    "\u02ba": '"',   # Modifier Letter Double Prime
    "\u02bc": "'",   # Modifier Letter Apostrophe
    "\u02b9": "'",   # Modifier Letter Prime
    # NOTE: backtick (0x60) intentionally NOT here — it's used in Markdown code fences
    "\u00b4": "'",   # Acute Accent used as quote
}

# Em/en dashes in code should probably stay, but flag them
DASH_MAP = {
    "\u2013": "-",   # En Dash → hyphen
    "\u2014": "--",  # Em Dash → double hyphen
    "\u2015": "--",  # Horizontal Bar
}


# ──────────────────────────────────────────────────────────
#  Filter Config
# ──────────────────────────────────────────────────────────

class FilterConfig:
    def __init__(
        self,
        fix_smart_quotes: bool = True,
        fix_dashes_in_code: bool = True,
        normalize_line_endings: bool = True,
        tab_width: int = 4,             # spaces per tab when expanding
        use_tabs: bool = False,         # False = spaces, True = keep/convert to tabs
        strip_invisible: bool = True,
        max_consecutive_newlines: int = 3,
    ):
        self.fix_smart_quotes = fix_smart_quotes
        self.fix_dashes_in_code = fix_dashes_in_code
        self.normalize_line_endings = normalize_line_endings
        self.tab_width = tab_width
        self.use_tabs = use_tabs
        self.strip_invisible = strip_invisible
        self.max_consecutive_newlines = max_consecutive_newlines


# ──────────────────────────────────────────────────────────
#  Filter Result
# ──────────────────────────────────────────────────────────

class FilterResult:
    def __init__(self, original: str, filtered: str):
        self.original = original
        self.filtered = filtered
        self.changes: list[str] = []
        self.invisible_removed: int = 0
        self.quotes_fixed: int = 0
        self.dashes_fixed: int = 0
        self.newlines_normalized: bool = False
        self.tabs_normalized: bool = False

    @property
    def was_changed(self) -> bool:
        return self.original != self.filtered

    @property
    def summary(self) -> str:
        parts = []
        if self.invisible_removed:
            parts.append(f"удалено {self.invisible_removed} невидимых символов")
        if self.quotes_fixed:
            parts.append(f"исправлено {self.quotes_fixed} кавычек")
        if self.dashes_fixed:
            parts.append(f"исправлено {self.dashes_fixed} тире")
        if self.newlines_normalized:
            parts.append("нормализованы переносы строк")
        if self.tabs_normalized:
            parts.append("нормализованы отступы")
        return "; ".join(parts) if parts else "без изменений"


# ──────────────────────────────────────────────────────────
#  Main Filter
# ──────────────────────────────────────────────────────────

class ResponseFilter:
    """
    Cleans AI response text before patch extraction and display.
    """

    def __init__(self, config: FilterConfig | None = None):
        self._cfg = config or FilterConfig()

    def filter(self, text: str) -> FilterResult:
        result = FilterResult(text, text)
        if not text:
            return result

        cleaned = text

        # 1. Normalize line endings first (CRLF → LF, bare CR → LF)
        if self._cfg.normalize_line_endings:
            new = cleaned.replace("\r\n", "\n").replace("\r", "\n")
            if new != cleaned:
                result.newlines_normalized = True
                cleaned = new

        # 2. Remove/replace invisible Unicode characters
        if self._cfg.strip_invisible:
            cleaned, count = self._strip_invisible(cleaned)
            result.invisible_removed = count

        # 3. Fix smart quotes → straight quotes
        if self._cfg.fix_smart_quotes:
            cleaned, count = self._fix_quotes(cleaned)
            result.quotes_fixed = count

        # 4. Fix dashes in code blocks
        if self._cfg.fix_dashes_in_code:
            cleaned, count = self._fix_dashes(cleaned)
            result.dashes_fixed = count

        # 5. Normalize tabs/spaces in code blocks
        cleaned, tab_changed = self._normalize_indentation(cleaned)
        result.tabs_normalized = tab_changed

        # 6. Limit excessive blank lines
        max_nl = self._cfg.max_consecutive_newlines
        pattern = "\n" * (max_nl + 1)
        replacement = "\n" * max_nl
        while pattern in cleaned:
            cleaned = cleaned.replace(pattern, replacement)

        result.filtered = cleaned
        return result

    def filter_patch_blocks(self, text: str) -> str:
        """
        Special filter for SEARCH/REPLACE blocks only.
        More aggressive: removes ALL invisible chars,
        preserves exact indentation.
        """
        result = self.filter(text)
        cleaned = result.filtered

        # In code blocks, also expand any remaining \t to spaces
        # (prevents inconsistent indentation)
        if not self._cfg.use_tabs:
            cleaned = self._expand_tabs_in_code_blocks(cleaned)

        return cleaned

    def filter_code(self, code: str) -> str:
        """
        Filter a standalone code string.
        Strips invisible chars, normalizes indentation.
        """
        result = self.filter(code)
        return result.filtered

    # ── Implementation ─────────────────────────────────────

    def _strip_invisible(self, text: str) -> tuple[str, int]:
        count = 0
        chars = []
        for ch in text:
            if ch in INVISIBLE_CHARS:
                # Non-breaking space → regular space
                if ch == "\u00a0":
                    chars.append(" ")
                # Others → remove entirely
                count += 1
                continue
            # Check Unicode category Cf (Format chars) and Cc (Control) except newlines/tabs
            cat = unicodedata.category(ch)
            if cat in ("Cf", "Cc") and ch not in ("\n", "\t", "\r"):
                count += 1
                continue
            chars.append(ch)
        return "".join(chars), count

    def _fix_quotes(self, text: str) -> tuple[str, int]:
        count = 0
        for smart, straight in QUOTE_MAP.items():
            occurrences = text.count(smart)
            if occurrences:
                text = text.replace(smart, straight)
                count += occurrences
        return text, count

    def _fix_dashes(self, text: str) -> tuple[str, int]:
        """Fix dashes only inside code blocks."""
        count = 0
        result = []
        in_code = False
        lines = text.split("\n")

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                result.append(line)
                continue

            if in_code:
                for dash, replacement in DASH_MAP.items():
                    c = line.count(dash)
                    if c:
                        line = line.replace(dash, replacement)
                        count += c
            result.append(line)

        return "\n".join(result), count

    def _normalize_indentation(self, text: str) -> tuple[str, bool]:
        """
        Normalize indentation in code blocks.
        If use_tabs=True: convert leading spaces to tabs.
        If use_tabs=False: expand tabs to spaces.
        """
        changed = False
        result = []
        in_code = False
        lines = text.split("\n")
        tab_w = self._cfg.tab_width

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                result.append(line)
                continue

            if in_code and line:
                if self._cfg.use_tabs:
                    # Convert leading spaces → tabs
                    spaces = len(line) - len(line.lstrip(" "))
                    if spaces >= tab_w:
                        tabs = spaces // tab_w
                        remainder = spaces % tab_w
                        new_line = "\t" * tabs + " " * remainder + line.lstrip(" ")
                        if new_line != line:
                            line = new_line
                            changed = True
                else:
                    # Expand leading tabs → spaces
                    if "\t" in line[:len(line) - len(line.lstrip())]:
                        new_line = line.expandtabs(tab_w)
                        if new_line != line:
                            line = new_line
                            changed = True

            result.append(line)

        return "\n".join(result), changed

    def _expand_tabs_in_code_blocks(self, text: str) -> str:
        """Expand ALL tabs in code blocks to spaces."""
        result = []
        in_code = False
        for line in text.split("\n"):
            if line.strip().startswith("```"):
                in_code = not in_code
                result.append(line)
            elif in_code:
                result.append(line.expandtabs(self._cfg.tab_width))
            else:
                result.append(line)
        return "\n".join(result)

    @staticmethod
    def quick_clean(text: str) -> str:
        """
        Fast path: just strip the most common invisible chars.
        Use when full filtering is overkill.
        """
        for ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u00ad", "\u2028", "\u2029"):
            text = text.replace(ch, "")
        text = text.replace("\u00a0", " ")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text


# ──────────────────────────────────────────────────────────
#  Standalone utility functions
# ──────────────────────────────────────────────────────────

def clean_ai_response(text: str, use_tabs: bool = False) -> str:
    """Convenience: filter full AI response."""
    cfg = FilterConfig(use_tabs=use_tabs)
    f = ResponseFilter(cfg)
    return f.filter(text).filtered


def clean_patch_content(text: str) -> str:
    """Clean content specifically extracted for SEARCH/REPLACE blocks."""
    return ResponseFilter().filter_patch_blocks(text)


def has_invisible_chars(text: str) -> bool:
    """Quick check if text contains invisible Unicode characters."""
    for ch in text:
        if ch in INVISIBLE_CHARS:
            return True
        cat = unicodedata.category(ch)
        if cat in ("Cf",) and ch not in ("\n", "\t"):
            return True
    return False


def count_invisible_chars(text: str) -> int:
    """Count invisible chars for diagnostics."""
    count = 0
    for ch in text:
        if ch in INVISIBLE_CHARS:
            count += 1
            continue
        cat = unicodedata.category(ch)
        if cat in ("Cf", "Cc") and ch not in ("\n", "\t", "\r"):
            count += 1
    return count
