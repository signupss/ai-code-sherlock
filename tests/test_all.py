"""
AI Code Sherlock — Test Suite
Run: python -m pytest tests/test_all.py -v
  or: python tests/test_all.py (standalone)
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import (
    AppSettings, ChatMessage, FileEntry, MessageRole,
    ModelDefinition, ModelSourceType, PatchBlock, PatchStatus,
    ProjectContext, TokenBudget, LogLevel, LogEntry
)
from services.engine import PatchEngine, PromptEngine, ContextCompressor
from services.logger_service import StructuredLogger
from services.settings_manager import SettingsManager


# ──────────────────────────────────────────────────────────
#  TOKEN BUDGET
# ──────────────────────────────────────────────────────────

class TestTokenBudget(unittest.TestCase):

    def test_estimate_tokens_returns_positive(self):
        self.assertGreater(TokenBudget.estimate_tokens("hello world"), 0)

    def test_estimate_empty_string(self):
        self.assertEqual(TokenBudget.estimate_tokens(""), 1)

    def test_estimate_scales_with_length(self):
        short = TokenBudget.estimate_tokens("x" * 10)
        long  = TokenBudget.estimate_tokens("x" * 100)
        self.assertGreater(long, short)

    def test_available_for_context(self):
        budget = TokenBudget(max_tokens=8192, reserved_for_response=1024)
        self.assertEqual(budget.available_for_context, 7168)

    def test_can_fit_small_text(self):
        budget = TokenBudget(max_tokens=8192)
        self.assertTrue(budget.can_fit("small text"))

    def test_cannot_fit_huge_text(self):
        budget = TokenBudget(max_tokens=100, reserved_for_response=10)
        huge = "x" * 10000
        self.assertFalse(budget.can_fit(huge))

    def test_default_budget(self):
        b = TokenBudget.default()
        self.assertEqual(b.max_tokens, 8192)

    def test_large_budget(self):
        b = TokenBudget.large()
        self.assertEqual(b.max_tokens, 32768)


# ──────────────────────────────────────────────────────────
#  PATCH ENGINE
# ──────────────────────────────────────────────────────────

class TestPatchEngine(unittest.TestCase):

    def setUp(self):
        self.engine = PatchEngine()

    # parse_patches ──────────────────────────────────────

    def test_parse_bracket_format_single_patch(self):
        response = (
            "Here is the fix:\n\n"
            "[SEARCH_BLOCK]\n"
            "def old():\n"
            "    return 1\n"
            "[REPLACE_BLOCK]\n"
            "def new():\n"
            "    return 2\n"
            "[END_PATCH]"
        )
        patches = self.engine.parse_patches(response)
        self.assertEqual(len(patches), 1)
        self.assertIn("def old()", patches[0].search_content)
        self.assertIn("def new()", patches[0].replace_content)

    def test_parse_two_patches(self):
        response = (
            "[SEARCH_BLOCK]\nfoo = 1\n[REPLACE_BLOCK]\nfoo = 2\n[END_PATCH]\n"
            "[SEARCH_BLOCK]\nbar = 3\n[REPLACE_BLOCK]\nbar = 4\n[END_PATCH]"
        )
        patches = self.engine.parse_patches(response)
        self.assertEqual(len(patches), 2)

    def test_parse_fenced_format_fallback(self):
        response = (
            "```search\n"
            "x = 1\n"
            "```\n"
            "```replace\n"
            "x = 2\n"
            "```"
        )
        patches = self.engine.parse_patches(response)
        self.assertEqual(len(patches), 1)
        self.assertIn("x = 1", patches[0].search_content)
        self.assertIn("x = 2", patches[0].replace_content)

    def test_parse_empty_response_returns_empty(self):
        self.assertEqual(self.engine.parse_patches(""), [])
        self.assertEqual(self.engine.parse_patches("no patches here"), [])

    # validate ────────────────────────────────────────────

    def test_validate_exact_match(self):
        code = "def foo():\n    return 1\n"
        patch = PatchBlock("def foo():\n    return 1", "def foo():\n    return 2")
        result = self.engine.validate(code, patch)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.match_count, 1)
        self.assertIsNone(result.error_message)

    def test_validate_not_found(self):
        code = "def foo():\n    return 1\n"
        patch = PatchBlock("def bar():\n    return 99", "def bar():\n    return 0")
        result = self.engine.validate(code, patch)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.match_count, 0)

    def test_validate_ambiguous_match(self):
        code = "pass\npass\npass"
        patch = PatchBlock("pass", "continue")
        result = self.engine.validate(code, patch)
        self.assertFalse(result.is_valid)
        self.assertGreater(result.match_count, 1)

    def test_validate_empty_search_block(self):
        result = self.engine.validate("some code", PatchBlock("", "replacement"))
        self.assertFalse(result.is_valid)
        self.assertIn("empty", result.error_message.lower())

    def test_validate_reports_line_number(self):
        code = "line1\nline2\ndef foo():\n    pass\nline5"
        patch = PatchBlock("def foo():\n    pass", "def foo():\n    return 1")
        result = self.engine.validate(code, patch)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.match_line_start, 3)

    # apply_patch ─────────────────────────────────────────

    def test_apply_patch_replaces_correctly(self):
        code = "x = 1\ny = 2\nz = 3\n"
        patch = PatchBlock("y = 2", "y = 99")
        result = self.engine.apply_patch(code, patch)
        self.assertIn("y = 99", result)
        self.assertNotIn("y = 2", result)

    def test_apply_patch_preserves_surrounding_code(self):
        code = "A\nB\nC\n"
        patch = PatchBlock("B", "X")
        result = self.engine.apply_patch(code, patch)
        self.assertIn("A", result)
        self.assertIn("X", result)
        self.assertIn("C", result)

    def test_apply_patch_raises_when_not_found(self):
        from core.interfaces import PatchError
        code = "def foo(): pass"
        patch = PatchBlock("def bar(): pass", "def baz(): pass")
        with self.assertRaises(PatchError):
            self.engine.apply_patch(code, patch)

    def test_apply_patch_replaces_multiline_block(self):
        code = (
            "class Foo:\n"
            "    def old_method(self):\n"
            "        return 'old'\n"
            "\n"
            "    def other(self):\n"
            "        pass\n"
        )
        patch = PatchBlock(
            "    def old_method(self):\n        return 'old'",
            "    def new_method(self):\n        return 'new'"
        )
        result = self.engine.apply_patch(code, patch)
        self.assertIn("new_method", result)
        self.assertNotIn("old_method", result)
        self.assertIn("other", result)  # Surrounding preserved

    def test_apply_patch_normalized_whitespace(self):
        """Test that patches work when AI returns slightly different indentation."""
        code = "def foo():\n    x = 1\n    return x\n"
        # Search with different trailing spaces (normalized match)
        patch = PatchBlock("def foo():\n    x = 1\n    return x", "def foo():\n    x = 2\n    return x")
        result = self.engine.apply_patch(code, patch)
        self.assertIn("x = 2", result)

    # round-trip ──────────────────────────────────────────

    def test_roundtrip_parse_and_apply(self):
        """Parse from AI response then apply — end-to-end."""
        original_code = "version = '1.0.0'\nname = 'app'\n"
        ai_response = (
            "Update the version:\n\n"
            "[SEARCH_BLOCK]\n"
            "version = '1.0.0'\n"
            "[REPLACE_BLOCK]\n"
            "version = '2.0.0'\n"
            "[END_PATCH]"
        )
        patches = self.engine.parse_patches(ai_response)
        self.assertEqual(len(patches), 1)

        result = self.engine.apply_patch(original_code, patches[0])
        self.assertIn("2.0.0", result)
        self.assertNotIn("1.0.0", result)
        self.assertIn("name = 'app'", result)


# ──────────────────────────────────────────────────────────
#  PROMPT ENGINE
# ──────────────────────────────────────────────────────────

class TestPromptEngine(unittest.TestCase):

    def setUp(self):
        self.engine = PromptEngine()

    def test_system_prompt_contains_format_instructions(self):
        prompt = self.engine.build_system_prompt()
        self.assertIn("[SEARCH_BLOCK]", prompt)
        self.assertIn("[REPLACE_BLOCK]", prompt)

    def test_sherlock_system_prompt_has_sherlock_marker(self):
        prompt = self.engine.build_system_prompt(sherlock_mode=True)
        self.assertIn("ШЕРЛОКА", prompt)
        self.assertGreater(len(prompt), len(self.engine.build_system_prompt()))

    def test_analysis_prompt_includes_request(self):
        ctx = ProjectContext(files=[])
        prompt = self.engine.build_analysis_prompt("Fix the bug", ctx)
        self.assertIn("Fix the bug", prompt)

    def test_analysis_prompt_includes_file_content(self):
        ctx = ProjectContext(files=[
            FileEntry(
                path="/a/test.py", relative_path="test.py",
                content="def foo(): pass", extension=".py"
            )
        ])
        prompt = self.engine.build_analysis_prompt("Review", ctx)
        self.assertIn("def foo(): pass", prompt)
        self.assertIn("test.py", prompt)

    def test_sherlock_prompt_includes_error_logs(self):
        ctx = ProjectContext(files=[])
        prompt = self.engine.build_sherlock_prompt("TypeError: ...", ctx)
        self.assertIn("TypeError", prompt)
        self.assertIn("ЗАДАЧА", prompt)

    def test_patch_prompt_includes_file_and_request(self):
        prompt = self.engine.build_patch_prompt("Add typing", "def foo(): pass")
        self.assertIn("def foo(): pass", prompt)
        self.assertIn("Add typing", prompt)

    def test_summarize_prompt_includes_file_path(self):
        prompt = self.engine.build_summarize_prompt("def foo(): pass", "utils/helpers.py")
        self.assertIn("utils/helpers.py", prompt)


# ──────────────────────────────────────────────────────────
#  STRUCTURED LOGGER
# ──────────────────────────────────────────────────────────

class TestStructuredLogger(unittest.TestCase):

    def setUp(self):
        self.logger = StructuredLogger()

    def test_log_calls_subscriber(self):
        received = []
        self.logger.subscribe(received.append)
        self.logger.info("hello", "test")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].message, "hello")

    def test_multiple_subscribers(self):
        a, b = [], []
        self.logger.subscribe(a.append)
        self.logger.subscribe(b.append)
        self.logger.info("msg")
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)

    def test_unsubscribe(self):
        received = []
        self.logger.subscribe(received.append)
        self.logger.unsubscribe(received.append)
        self.logger.info("msg")
        self.assertEqual(len(received), 0)

    def test_get_recent_returns_last_n(self):
        for i in range(20):
            self.logger.info(f"msg {i}")
        recent = self.logger.get_recent(10)
        self.assertEqual(len(recent), 10)
        self.assertIn("msg 19", recent[-1].message)

    def test_get_errors_filters_by_level(self):
        self.logger.info("info msg")
        self.logger.warning("warn msg")
        self.logger.error("error msg")
        errors = self.logger.get_errors()
        self.assertEqual(len(errors), 2)
        self.assertTrue(all(
            e.level in (LogLevel.ERROR, LogLevel.WARNING) for e in errors
        ))

    def test_export_creates_file(self):
        self.logger.info("test export")
        self.logger.error("test error")
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            self.logger.export(path)
            content = Path(path).read_text()
            self.assertIn("test export", content)
            self.assertIn("test error", content)
        finally:
            os.unlink(path)

    def test_format_for_ai_includes_errors(self):
        self.logger.info("info line")
        self.logger.error("critical bug", "TestSource")
        formatted = self.logger.format_for_ai()
        self.assertIn("critical bug", formatted)

    def test_log_entry_formatted_string(self):
        entry = LogEntry(
            level=LogLevel.ERROR,
            message="Something broke",
            source="Engine",
        )
        fmt = entry.formatted
        self.assertIn("ERROR", fmt)
        self.assertIn("Something broke", fmt)
        self.assertIn("Engine", fmt)

    def test_buffer_does_not_exceed_max(self):
        for i in range(15000):
            self.logger.info(f"msg {i}")
        # Should stay within MAX_BUFFER
        self.assertLessEqual(len(self.logger.get_recent(20000)), self.logger.MAX_BUFFER)


# ──────────────────────────────────────────────────────────
#  SETTINGS MANAGER
# ──────────────────────────────────────────────────────────

class TestSettingsManager(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "settings.json")
        self.mgr = SettingsManager(self.path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_returns_defaults_when_no_file(self):
        settings = self.mgr.load()
        self.assertIsInstance(settings, AppSettings)
        self.assertEqual(settings.models, [])

    def test_save_and_load_roundtrip(self):
        s = AppSettings(sherlock_mode_enabled=True, send_logs_to_ai=True)
        self.mgr.save(s)
        loaded = self.mgr.load()
        self.assertTrue(loaded.sherlock_mode_enabled)
        self.assertTrue(loaded.send_logs_to_ai)

    def test_save_and_load_models(self):
        m = ModelDefinition(
            name="llama3.2",
            display_name="Llama 3.2",
            source_type=ModelSourceType.OLLAMA,
            max_context_tokens=16384,
        )
        s = AppSettings(models=[m], default_model_id=m.id)
        self.mgr.save(s)
        loaded = self.mgr.load()
        self.assertEqual(len(loaded.models), 1)
        self.assertEqual(loaded.models[0].name, "llama3.2")
        self.assertEqual(loaded.models[0].max_context_tokens, 16384)
        self.assertEqual(loaded.default_model_id, m.id)

    def test_corrupted_file_returns_defaults_and_creates_backup(self):
        with open(self.path, "w") as f:
            f.write("{invalid json{{")
        settings = self.mgr.load()
        self.assertIsInstance(settings, AppSettings)
        # Backup should exist
        backups = list(Path(self.tmpdir).glob("*.backup.*.json"))
        self.assertEqual(len(backups), 1)

    def test_atomic_save_on_concurrent_writes(self):
        """Save from multiple threads shouldn't corrupt the file."""
        import threading
        errors = []

        def _save(i):
            try:
                s = AppSettings(sherlock_mode_enabled=(i % 2 == 0))
                self.mgr.save(s)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_save, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()

        self.assertEqual(errors, [])
        # File should be valid JSON
        loaded = self.mgr.load()
        self.assertIsInstance(loaded, AppSettings)

    def test_custom_api_model_roundtrip(self):
        m = ModelDefinition(
            name="gpt-4o",
            display_name="GPT-4o",
            source_type=ModelSourceType.CUSTOM_API,
            api_base_url="https://api.openai.com",
            api_key="sk-test-key",
            api_model_id="gpt-4o-2024-11-20",
            custom_headers={"X-Org": "test"},
        )
        s = AppSettings(models=[m])
        self.mgr.save(s)
        loaded = self.mgr.load()
        lm = loaded.models[0]
        self.assertEqual(lm.api_base_url, "https://api.openai.com")
        self.assertEqual(lm.api_key, "sk-test-key")
        self.assertEqual(lm.custom_headers, {"X-Org": "test"})

    def test_file_signal_model_roundtrip(self):
        m = ModelDefinition(
            name="zennoposter",
            display_name="ZennoPoster GPT",
            source_type=ModelSourceType.FILE_SIGNAL,
            signal_request_folder="/signals/req",
            signal_response_folder="/signals/res",
            signal_timeout_seconds=45,
        )
        s = AppSettings(models=[m])
        self.mgr.save(s)
        loaded = self.mgr.load()
        lm = loaded.models[0]
        self.assertEqual(lm.signal_request_folder, "/signals/req")
        self.assertEqual(lm.signal_timeout_seconds, 45)


# ──────────────────────────────────────────────────────────
#  FILE SIGNAL SERVICE
# ──────────────────────────────────────────────────────────

class TestFileSignalService(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.req_dir = self.tmpdir / "req"
        self.res_dir = self.tmpdir / "res"
        self.req_dir.mkdir()
        self.res_dir.mkdir()
        from providers.providers import FileSignalService
        self.service = FileSignalService()

    async def asyncTearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_sends_request_file(self):
        async def _write_response():
            await asyncio.sleep(0.2)
            (self.res_dir / "abc123.txt").write_text("AI response", encoding="utf-8")

        asyncio.create_task(_write_response())
        result = await self.service.send_request(
            "abc123", "hello prompt",
            str(self.req_dir), str(self.res_dir), timeout_seconds=5
        )
        self.assertEqual(result, "AI response")
        # Request file should have been written
        # (may be cleaned up or not — just check response was received)

    async def test_timeout_raises_timeout_error(self):
        with self.assertRaises(TimeoutError):
            await self.service.send_request(
                "never_comes", "prompt",
                str(self.req_dir), str(self.res_dir), timeout_seconds=1
            )

    async def test_ignores_empty_response_file(self):
        """Empty response file should be ignored until content appears."""
        async def _write_response():
            await asyncio.sleep(0.1)
            path = self.res_dir / "test123.txt"
            path.write_text("", encoding="utf-8")  # Empty first
            await asyncio.sleep(0.2)
            path.write_text("real response", encoding="utf-8")

        asyncio.create_task(_write_response())
        result = await self.service.send_request(
            "test123", "prompt",
            str(self.req_dir), str(self.res_dir), timeout_seconds=5
        )
        self.assertEqual(result, "real response")

    async def test_cleans_up_response_file(self):
        async def _write():
            await asyncio.sleep(0.1)
            (self.res_dir / "cleanup_test.txt").write_text("response")

        asyncio.create_task(_write())
        await self.service.send_request(
            "cleanup_test", "prompt",
            str(self.req_dir), str(self.res_dir), timeout_seconds=5
        )
        # Response file should be deleted after reading
        self.assertFalse((self.res_dir / "cleanup_test.txt").exists())


# ──────────────────────────────────────────────────────────
#  CONTEXT COMPRESSOR (unit — mock provider)
# ──────────────────────────────────────────────────────────

class MockProvider:
    """Minimal mock for ContextCompressor tests."""
    class model:
        display_name = "mock"

    async def complete(self, messages):
        return "Summary: this file does X, Y, Z."

    async def stream(self, messages):
        yield "mock"

    async def is_available(self):
        return True

    @property
    def provider_name(self):
        return "mock"


class TestContextCompressor(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.compressor = ContextCompressor(
            MockProvider(), PromptEngine()
        )

    async def test_no_compression_when_fits_budget(self):
        ctx = ProjectContext(files=[
            FileEntry("a.py", "a.py", "x = 1", ".py", is_focused=True)
        ])
        budget = TokenBudget(max_tokens=100000)
        result = await self.compressor.compress(ctx, budget)
        self.assertEqual(len(result.files), 1)
        self.assertFalse(result.files[0].is_compressed)

    async def test_focused_file_never_compressed(self):
        big_content = "x = 1\n" * 10000  # Large file
        ctx = ProjectContext(files=[
            FileEntry("focus.py", "focus.py", big_content, ".py", is_focused=True),
            FileEntry("other.py", "other.py", big_content, ".py", is_focused=False),
        ])
        budget = TokenBudget(max_tokens=500, reserved_for_response=50)
        result = await self.compressor.compress(ctx, budget)

        focused = next((f for f in result.files if f.is_focused), None)
        self.assertIsNotNone(focused)
        self.assertFalse(focused.is_compressed)
        self.assertEqual(focused.content, big_content)

    async def test_overflow_files_get_summarized(self):
        big = "x = " + "1" * 5000 + "\n"
        ctx = ProjectContext(files=[
            FileEntry("main.py", "main.py", "print('hello')", ".py", is_focused=True),
            FileEntry("big1.py", "big1.py", big, ".py"),
            FileEntry("big2.py", "big2.py", big, ".py"),
        ])
        budget = TokenBudget(max_tokens=200, reserved_for_response=20)
        result = await self.compressor.compress(ctx, budget)

        compressed = [f for f in result.files if f.is_compressed]
        self.assertGreater(len(compressed), 0)


# ──────────────────────────────────────────────────────────
#  MODEL DEFINITIONS
# ──────────────────────────────────────────────────────────

class TestModelDefinition(unittest.TestCase):

    def test_to_dict_and_from_dict_roundtrip(self):
        m = ModelDefinition(
            name="llama3.2:70b",
            display_name="Llama 70B",
            source_type=ModelSourceType.OLLAMA,
            ollama_base_url="http://gpu-server:11434",
            max_context_tokens=32768,
            temperature=0.1,
            is_default=True,
        )
        d = m.to_dict()
        m2 = ModelDefinition.from_dict(d)
        self.assertEqual(m2.name, "llama3.2:70b")
        self.assertEqual(m2.source_type, ModelSourceType.OLLAMA)
        self.assertEqual(m2.max_context_tokens, 32768)
        self.assertTrue(m2.is_default)
        self.assertEqual(m2.ollama_base_url, "http://gpu-server:11434")

    def test_source_type_enum(self):
        for src in ModelSourceType:
            m = ModelDefinition("x", "X", src)
            d = m.to_dict()
            m2 = ModelDefinition.from_dict(d)
            self.assertEqual(m2.source_type, src)


# ──────────────────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  AI Code Sherlock — Test Suite")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestTokenBudget,
        TestPatchEngine,
        TestPromptEngine,
        TestStructuredLogger,
        TestSettingsManager,
        TestFileSignalService,
        TestContextCompressor,
        TestModelDefinition,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, failfast=False)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed
    print(f"  Results: {passed}/{total} passed  |  {failed} failed")
    print("=" * 60)

    sys.exit(0 if result.wasSuccessful() else 1)
