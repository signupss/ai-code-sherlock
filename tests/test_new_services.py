"""
Tests for new services: VersionControl, ErrorMap, ResponseFilter, ProjectManager
Run: python tests/test_new_services.py
"""
from __future__ import annotations
import ast
import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.version_control import VersionControlService, FileVersion, ProjectVersionSnapshot
from services.error_map import ErrorMapService, ErrorRecord, AvoidPattern
from services.response_filter import (
    ResponseFilter, FilterConfig, clean_ai_response,
    has_invisible_chars, count_invisible_chars
)
from services.project_manager import (
    ProjectManager, ProjectMode, PythonSkeletonExtractor, GenericSkeletonExtractor
)


# ══════════════════════════════════════════════════════
#  VERSION CONTROL
# ══════════════════════════════════════════════════════

class TestVersionControl(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vc = VersionControlService(self.tmpdir)
        # Create a test file
        self.test_file = os.path.join(self.tmpdir, "test.py")
        Path(self.test_file).write_text("x = 1\ny = 2\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_backup_creates_file(self):
        version = self.vc.backup_file(self.test_file, description="initial")
        self.assertTrue(Path(version.backup_path).exists())
        content = Path(version.backup_path).read_text(encoding="utf-8")
        self.assertEqual(content, "x = 1\ny = 2\n")

    def test_backup_stores_metadata(self):
        version = self.vc.backup_file(self.test_file, description="test backup",
                                      patch_search="x = 1", patch_replace="x = 99")
        self.assertEqual(version.description, "test backup")
        self.assertEqual(version.patch_search, "x = 1")
        self.assertGreater(version.lines_before, 0)

    def test_get_versions_returns_history(self):
        self.vc.backup_file(self.test_file, description="v1")
        Path(self.test_file).write_text("x = 99\n", encoding="utf-8")
        self.vc.backup_file(self.test_file, description="v2")
        versions = self.vc.get_versions(self.test_file)
        self.assertGreaterEqual(len(versions), 2)
        # Newest first
        self.assertEqual(versions[0].description, "v2")

    def test_restore_version(self):
        original = "x = 1\ny = 2\n"
        self.vc.backup_file(self.test_file, description="before change")
        v1 = self.vc.get_versions(self.test_file)[0]

        # Modify file
        Path(self.test_file).write_text("x = 999\ny = 888\n", encoding="utf-8")

        # Restore
        restored = self.vc.restore_version(v1)
        self.assertEqual(restored, original)
        current = Path(self.test_file).read_text(encoding="utf-8")
        self.assertEqual(current, original)

    def test_restore_creates_backup_of_current(self):
        self.vc.backup_file(self.test_file, description="v1")
        v1 = self.vc.get_versions(self.test_file)[0]
        Path(self.test_file).write_text("modified\n", encoding="utf-8")

        versions_before = len(self.vc.get_versions(self.test_file))
        self.vc.restore_version(v1)
        versions_after = len(self.vc.get_versions(self.test_file))

        # Should have created an auto-backup of the modified state
        self.assertGreater(versions_after, versions_before)

    def test_get_version_content(self):
        self.vc.backup_file(self.test_file, description="snapshot")
        version = self.vc.get_versions(self.test_file)[0]
        content = self.vc.get_version_content(version)
        self.assertEqual(content, "x = 1\ny = 2\n")

    def test_diff_versions(self):
        self.vc.backup_file(self.test_file, description="old")
        version = self.vc.get_versions(self.test_file)[0]
        diff = self.vc.diff_versions(version, "x = 1\ny = 99\n")
        self.assertTrue(any("-y = 2" in line for line in diff) or
                        any("y = 2" in line for line in diff))

    def test_create_snapshot_multiple_files(self):
        file2 = os.path.join(self.tmpdir, "other.py")
        Path(file2).write_text("a = 1\n", encoding="utf-8")

        snap = self.vc.create_snapshot("test_snap", "desc", [self.test_file, file2])
        self.assertEqual(snap.name, "test_snap")
        self.assertEqual(len(snap.file_versions), 2)

    def test_list_snapshots(self):
        import time
        file2 = os.path.join(self.tmpdir, "f2.py")
        Path(file2).write_text("b = 1", encoding="utf-8")
        self.vc.create_snapshot("snap1", "d1", [self.test_file])
        time.sleep(1.1)  # snapshot IDs are timestamp-based — need different seconds
        self.vc.create_snapshot("snap2", "d2", [file2])
        snaps = self.vc.list_snapshots()
        self.assertGreaterEqual(len(snaps), 2)

    def test_restore_snapshot(self):
        original = Path(self.test_file).read_text()
        snap = self.vc.create_snapshot("before", "", [self.test_file])
        Path(self.test_file).write_text("changed\n", encoding="utf-8")
        restored = self.vc.restore_snapshot(snap)
        self.assertIn(self.test_file, restored)
        self.assertEqual(Path(self.test_file).read_text(), original)

    def test_cleanup_keeps_n_versions(self):
        for i in range(25):
            Path(self.test_file).write_text(f"x = {i}\n", encoding="utf-8")
            self.vc.backup_file(self.test_file, description=f"v{i}")
        deleted = self.vc.cleanup_old_versions(keep_last=10)
        remaining = self.vc.get_versions(self.test_file)
        self.assertLessEqual(len(remaining), 10)

    def test_index_persists_across_instances(self):
        self.vc.backup_file(self.test_file, description="persist test")
        # Create new instance — should load index
        vc2 = VersionControlService(self.tmpdir)
        versions = vc2.get_versions(self.test_file)
        self.assertGreater(len(versions), 0)
        self.assertEqual(versions[0].description, "persist test")

    def test_storage_size_returns_positive(self):
        self.vc.backup_file(self.test_file)
        size = self.vc.get_storage_size()
        self.assertGreater(size, 0)

    def test_version_display_time(self):
        version = self.vc.backup_file(self.test_file)
        dt = version.display_time
        self.assertIn(".", dt)  # DD.MM.YYYY format

    def test_update_lines_after(self):
        version = self.vc.backup_file(self.test_file)
        self.vc.update_lines_after(version, "a\nb\nc\n")
        self.assertEqual(version.lines_after, 3)


# ══════════════════════════════════════════════════════
#  ERROR MAP
# ══════════════════════════════════════════════════════

class TestErrorMap(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.em = ErrorMapService(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_record_error_creates_entry(self):
        rec = self.em.record_error(
            "TypeError: 'NoneType' object is not subscriptable",
            error_type="TypeError",
            file_path="main.py",
            line_number=42,
        )
        self.assertIsNotNone(rec.error_id)
        self.assertEqual(rec.error_type, "TypeError")
        self.assertEqual(rec.occurrences, 1)
        self.assertEqual(rec.status, "open")

    def test_same_error_increments_count(self):
        self.em.record_error("TypeError: bad type", error_type="TypeError")
        self.em.record_error("TypeError: bad type", error_type="TypeError")
        records = self.em.all_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].occurrences, 2)

    def test_mark_resolved(self):
        rec = self.em.record_error("SomeError occurred")
        self.em.mark_resolved(
            rec.error_id,
            root_cause="Missing null check",
            solution="Added guard clause",
            patch_search="if x:",
            patch_replace="if x is not None:",
        )
        updated = self.em.all_records()[0]
        self.assertTrue(updated.is_resolved)
        self.assertEqual(updated.root_cause, "Missing null check")
        self.assertEqual(updated.patch_search, "if x:")

    def test_find_similar_exact_match(self):
        self.em.record_error("AttributeError: 'NoneType' has no attribute 'x'",
                             error_type="AttributeError")
        results = self.em.find_similar(
            "AttributeError: 'NoneType' has no attribute 'x'",
            "AttributeError"
        )
        self.assertEqual(len(results), 1)

    def test_find_similar_fuzzy(self):
        self.em.record_error("KeyError: 'user_id' not found in session", error_type="KeyError")
        results = self.em.find_similar("KeyError session user_id missing")
        self.assertGreater(len(results), 0)

    def test_add_avoid_pattern(self):
        pattern = self.em.add_avoid_pattern(
            description="Adding global vars",
            error_context="threading bug",
            bad_approach="Using global variables for shared state",
            better_approach="Use threading.Lock() or queue.Queue()",
        )
        self.assertIsNotNone(pattern.pattern_id)
        self.assertEqual(len(self.em.get_avoid_patterns()), 1)

    def test_avoid_pattern_no_duplicates(self):
        for _ in range(3):
            self.em.add_avoid_pattern(
                "same desc", "ctx", "same bad approach", "same better"
            )
        self.assertEqual(len(self.em.get_avoid_patterns()), 1)

    def test_build_context_block_includes_resolved(self):
        rec = self.em.record_error("ImportError: no module named X")
        self.em.mark_resolved(rec.error_id, root_cause="wrong venv",
                              solution="activate venv")
        block = self.em.build_context_block()
        self.assertIn("КАРТА ОШИБОК", block)

    def test_build_context_block_includes_avoid(self):
        self.em.add_avoid_pattern("bad", "ctx", "global vars", "use locks")
        block = self.em.build_context_block()
        self.assertIn("ЗАПРЕЩЁННЫЕ", block)

    def test_get_open_errors(self):
        self.em.record_error("error 1")
        rec2 = self.em.record_error("error 2")
        self.em.mark_resolved(rec2.error_id)
        open_errs = self.em.get_open_errors()
        self.assertEqual(len(open_errs), 1)
        self.assertFalse(open_errs[0].is_resolved)

    def test_stats(self):
        self.em.record_error("e1")
        rec2 = self.em.record_error("e2")
        self.em.mark_resolved(rec2.error_id)
        self.em.add_avoid_pattern("d", "c", "b", "g")
        s = self.em.stats()
        self.assertEqual(s["total_errors"], 2)
        self.assertEqual(s["resolved"], 1)
        self.assertEqual(s["open"], 1)
        self.assertEqual(s["avoid_patterns"], 1)

    def test_persists_across_instances(self):
        self.em.record_error("persistent error", error_type="RuntimeError")
        em2 = ErrorMapService(self.tmpdir)
        records = em2.all_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].error_type, "RuntimeError")

    def test_extract_error_type_from_message(self):
        from services.error_map import ErrorMapService
        t = ErrorMapService._extract_error_type
        self.assertEqual(t("TypeError: bad"), "TypeError")
        self.assertEqual(t("AttributeError in foo"), "AttributeError")
        self.assertEqual(t("some random error"), "Error")

    def test_normalize_signature_strips_addresses(self):
        from services.error_map import ErrorMapService
        n = ErrorMapService._normalize_signature
        s1 = n("E", "error at 0xDEADBEEF line 42")
        s2 = n("E", "error at 0x12345678 line 99")
        self.assertEqual(s1, s2)


# ══════════════════════════════════════════════════════
#  RESPONSE FILTER
# ══════════════════════════════════════════════════════

class TestResponseFilter(unittest.TestCase):

    def setUp(self):
        self.filter = ResponseFilter()

    def test_removes_zero_width_space(self):
        text = "hello\u200bworld"
        result = self.filter.filter(text)
        self.assertNotIn("\u200b", result.filtered)
        self.assertEqual(result.invisible_removed, 1)

    def test_removes_bom(self):
        text = "\ufeffhello world"
        result = self.filter.filter(text)
        self.assertNotIn("\ufeff", result.filtered)

    def test_replaces_nbsp_with_space(self):
        text = "hello\u00a0world"
        result = self.filter.filter(text)
        self.assertNotIn("\u00a0", result.filtered)
        self.assertIn(" ", result.filtered)

    def test_fixes_smart_quotes(self):
        text = "\u201chello\u201d and \u2018world\u2019"
        result = self.filter.filter(text)
        self.assertNotIn("\u201c", result.filtered)
        self.assertNotIn("\u201d", result.filtered)
        self.assertIn('"hello"', result.filtered)
        self.assertIn("'world'", result.filtered)
        self.assertGreater(result.quotes_fixed, 0)

    def test_normalizes_crlf(self):
        text = "line1\r\nline2\r\nline3"
        result = self.filter.filter(text)
        self.assertNotIn("\r\n", result.filtered)
        self.assertEqual(result.filtered.count("\n"), 2)
        self.assertTrue(result.newlines_normalized)

    def test_normalizes_bare_cr(self):
        text = "line1\rline2"
        result = self.filter.filter(text)
        self.assertNotIn("\r", result.filtered)

    def test_limits_consecutive_newlines(self):
        text = "a\n\n\n\n\n\nb"
        cfg = FilterConfig(max_consecutive_newlines=2)
        f = ResponseFilter(cfg)
        result = f.filter(text)
        self.assertNotIn("\n\n\n", result.filtered)

    def test_fixes_dashes_in_code_blocks(self):
        text = "text\n```python\nx \u2013 y\n```\nmore"
        result = self.filter.filter(text)
        # Em dash inside code block should be replaced
        self.assertNotIn("\u2013", result.filtered)

    def test_does_not_fix_dashes_outside_code(self):
        text = "This is an en\u2013dash in prose"
        result = self.filter.filter(text)
        # Outside code block, en dash stays (only fixed inside code)
        self.assertIn("\u2013", result.filtered)

    def test_expand_tabs_in_code_blocks(self):
        text = "```python\n\tdef foo():\n\t\tpass\n```"
        result = self.filter.filter(text)
        self.assertNotIn("\t", result.filtered)

    def test_was_changed_property(self):
        clean = "hello world"
        dirty = "hello\u200bworld"
        r1 = self.filter.filter(clean)
        r2 = self.filter.filter(dirty)
        self.assertFalse(r1.was_changed)
        self.assertTrue(r2.was_changed)

    def test_summary_property(self):
        text = "hello\u200bworld\u201ctesting\u201d"
        result = self.filter.filter(text)
        summary = result.summary
        self.assertIn("невидимых", summary)
        self.assertIn("кавычек", summary)

    def test_has_invisible_chars(self):
        self.assertTrue(has_invisible_chars("hello\u200bworld"))
        self.assertTrue(has_invisible_chars("\ufeffstart"))
        self.assertFalse(has_invisible_chars("clean text\nwith newlines\t"))

    def test_count_invisible_chars(self):
        text = "a\u200bb\u200cc\u200dd"
        count = count_invisible_chars(text)
        self.assertEqual(count, 3)

    def test_clean_ai_response_convenience(self):
        text = "hello\u200b\u200c world\u201ctest\u201d"
        cleaned = clean_ai_response(text)
        self.assertNotIn("\u200b", cleaned)
        self.assertNotIn("\u201c", cleaned)

    def test_filter_patch_blocks(self):
        text = "[SEARCH_BLOCK]\ndef\u200b foo():\n    pass\n[REPLACE_BLOCK]\ndef foo():\n    return 1"
        cleaned = self.filter.filter_patch_blocks(text)
        self.assertNotIn("\u200b", cleaned)

    def test_preserves_code_content(self):
        code = "def process(data: list[str]) -> dict:\n    return {'result': data[0]}\n"
        result = self.filter.filter(code)
        self.assertIn("def process", result.filtered)
        self.assertIn("list[str]", result.filtered)
        self.assertIn("dict", result.filtered)

    def test_empty_string(self):
        result = self.filter.filter("")
        self.assertEqual(result.filtered, "")
        self.assertFalse(result.was_changed)

    def test_use_tabs_config(self):
        cfg = FilterConfig(use_tabs=True, tab_width=4)
        f = ResponseFilter(cfg)
        text = "```python\n    def foo():\n        pass\n```"
        result = f.filter(text)
        # 4 spaces → 1 tab
        self.assertIn("\t", result.filtered)


# ══════════════════════════════════════════════════════
#  PYTHON SKELETON EXTRACTOR
# ══════════════════════════════════════════════════════

class TestPythonSkeletonExtractor(unittest.TestCase):

    def setUp(self):
        self.extractor = PythonSkeletonExtractor()

    def test_extracts_function_signature(self):
        source = """
def calculate_total(items: list[float], tax: float = 0.1) -> float:
    '''Calculate total with tax.'''
    subtotal = sum(items)
    return subtotal * (1 + tax)
"""
        skeleton = self.extractor.extract(source)
        self.assertIn("def calculate_total", skeleton)
        self.assertIn("items: list[float]", skeleton)
        self.assertIn("...", skeleton)
        # Body should NOT be in skeleton
        self.assertNotIn("subtotal = sum(items)", skeleton)

    def test_extracts_class_with_methods(self):
        source = """
class UserService:
    '''Handles user operations.'''

    def __init__(self, db):
        self.db = db

    def get_user(self, user_id: int) -> dict:
        '''Fetch user by ID.'''
        return self.db.query(user_id)

    def _private_helper(self):
        pass
"""
        skeleton = self.extractor.extract(source)
        self.assertIn("class UserService", skeleton)
        self.assertIn("def __init__", skeleton)
        self.assertIn("def get_user", skeleton)
        self.assertIn("...", skeleton)
        # Body should be replaced
        self.assertNotIn("self.db.query(user_id)", skeleton)

    def test_keeps_imports(self):
        source = """
import os
from pathlib import Path
from typing import Optional

def foo(): pass
"""
        skeleton = self.extractor.extract(source)
        self.assertIn("import os", skeleton)
        self.assertIn("from pathlib import Path", skeleton)

    def test_keeps_constants(self):
        source = """
MAX_RETRY = 3
DEFAULT_TIMEOUT = 30.0
API_VERSION = "v2"

def foo(): pass
"""
        skeleton = self.extractor.extract(source)
        self.assertIn("MAX_RETRY", skeleton)
        self.assertIn("DEFAULT_TIMEOUT", skeleton)

    def test_extracts_async_function(self):
        source = """
async def fetch_data(url: str) -> dict:
    '''Async HTTP fetch.'''
    async with aiohttp.ClientSession() as session:
        return await session.get(url)
"""
        skeleton = self.extractor.extract(source)
        self.assertIn("async def fetch_data", skeleton)
        self.assertNotIn("aiohttp.ClientSession", skeleton)

    def test_extracts_decorator(self):
        source = """
@property
def name(self) -> str:
    return self._name

@staticmethod
def create():
    return cls()
"""
        skeleton = self.extractor.extract(source)
        self.assertIn("@property", skeleton)
        self.assertIn("@staticmethod", skeleton)

    def test_handles_syntax_error_gracefully(self):
        # Broken Python should fall back to regex
        broken = "def foo(\n    this is not valid python!!!\n"
        skeleton = self.extractor.extract(broken)
        # Should return something, not crash
        self.assertIsInstance(skeleton, str)

    def test_skeleton_is_shorter_than_original(self):
        source = """
class BigClass:
    def method_a(self):
        x = 1
        y = 2
        z = x + y
        return z * 100

    def method_b(self, data):
        for item in data:
            print(item)
        return len(data)
"""
        skeleton = self.extractor.extract(source)
        self.assertLess(len(skeleton), len(source))

    def test_skeleton_is_valid_python(self):
        source = """
import os

MAX = 100

class Config:
    '''Configuration class.'''
    def __init__(self, path: str):
        self.path = path
    def load(self) -> dict:
        '''Load config from file.'''
        with open(self.path) as f:
            return json.load(f)
"""
        skeleton = self.extractor.extract(source)
        # Skeleton should be parseable Python
        try:
            ast.parse(skeleton)
        except SyntaxError as e:
            self.fail(f"Skeleton is not valid Python: {e}\n{skeleton}")


# ══════════════════════════════════════════════════════
#  PROJECT MANAGER
# ══════════════════════════════════════════════════════

class TestProjectManager(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pm = ProjectManager()
        # Create some test files
        (Path(self.tmpdir) / "main.py").write_text(
            "import os\n\ndef main():\n    print('hello')\n", encoding="utf-8"
        )
        (Path(self.tmpdir) / "utils.py").write_text(
            "def helper(x): return x * 2\n", encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_project_new_mode(self):
        state = self.pm.create_project(self.tmpdir, "TestProject", ProjectMode.NEW_PROJECT)
        self.assertEqual(state.mode, ProjectMode.NEW_PROJECT)
        self.assertEqual(state.name, "TestProject")

    def test_open_project_scans_files(self):
        state = self.pm.open_project(self.tmpdir)
        self.assertGreater(len(state.tracked_files), 0)
        # Should find our .py files
        names = [Path(f).name for f in state.tracked_files]
        self.assertIn("main.py", names)
        self.assertIn("utils.py", names)

    def test_set_mode(self):
        self.pm.create_project(self.tmpdir)
        self.pm.set_mode(ProjectMode.EXISTING_PROJECT)
        self.assertEqual(self.pm.mode, ProjectMode.EXISTING_PROJECT)

    def test_state_persists(self):
        self.pm.create_project(self.tmpdir, "Persistent", ProjectMode.EXISTING_PROJECT)
        # New instance
        pm2 = ProjectManager()
        state = pm2.open_project(self.tmpdir)
        self.assertEqual(state.mode, ProjectMode.EXISTING_PROJECT)
        self.assertEqual(state.name, "Persistent")

    def test_load_file(self):
        self.pm.open_project(self.tmpdir)
        main_path = str(Path(self.tmpdir) / "main.py")
        content = self.pm.load_file(main_path)
        self.assertIn("def main()", content)

    def test_get_mode_system_addon_new(self):
        self.pm.create_project(self.tmpdir, mode=ProjectMode.NEW_PROJECT)
        addon = self.pm.get_mode_system_addon()
        self.assertIn("НОВЫЙ ПРОЕКТ", addon)
        self.assertIn("полные реализации", addon)

    def test_get_mode_system_addon_existing(self):
        self.pm.create_project(self.tmpdir, mode=ProjectMode.EXISTING_PROJECT)
        addon = self.pm.get_mode_system_addon()
        self.assertIn("СУЩЕСТВУЮЩИМ ПРОЕКТОМ", addon)
        self.assertIn("SEARCH_BLOCK", addon)
        self.assertIn("ЗАПРЕЩЕНО", addon)

    def test_build_context_focused_file_full(self):
        self.pm.open_project(self.tmpdir)
        main_path = str(Path(self.tmpdir) / "main.py")
        from core.models import TokenBudget
        ctx = self.pm.build_context([main_path], TokenBudget(max_tokens=100000))
        focused = next((f for f in ctx.files if f.is_focused), None)
        self.assertIsNotNone(focused)
        self.assertFalse(focused.is_compressed)
        self.assertIn("def main()", focused.content)

    def test_get_skeleton_python(self):
        self.pm.open_project(self.tmpdir)
        main_path = str(Path(self.tmpdir) / "main.py")
        skeleton = self.pm.get_skeleton(main_path)
        self.assertIn("def main", skeleton)
        self.assertIn("[SKELETON:", skeleton)
        # Should not contain function body
        self.assertNotIn("print('hello')", skeleton)

    def test_skeleton_cached(self):
        self.pm.open_project(self.tmpdir)
        main_path = str(Path(self.tmpdir) / "main.py")
        s1 = self.pm.get_skeleton(main_path)
        s2 = self.pm.get_skeleton(main_path)
        self.assertIs(s1, s2)  # Same object — from cache

    def test_ignored_dirs_not_scanned(self):
        (Path(self.tmpdir) / "node_modules").mkdir()
        (Path(self.tmpdir) / "node_modules" / "pkg.py").write_text("x = 1")
        (Path(self.tmpdir) / "__pycache__").mkdir()
        (Path(self.tmpdir) / "__pycache__" / "cached.py").write_text("x = 1")
        state = self.pm.open_project(self.tmpdir)
        for f in state.tracked_files:
            self.assertNotIn("node_modules", f)
            self.assertNotIn("__pycache__", f)


# ══════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  AI Code Sherlock — New Services Test Suite")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestVersionControl,
        TestErrorMap,
        TestResponseFilter,
        TestPythonSkeletonExtractor,
        TestProjectManager,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, failfast=False)
    result = runner.run(suite)

    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    print("\n" + "=" * 60)
    print(f"  Results: {total - failed}/{total} passed  |  {failed} failed")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
