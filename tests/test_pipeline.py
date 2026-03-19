"""
Tests for pipeline services: ScriptRunner, LogCompressor, FileConverter, PipelineModels
Run: python tests/test_pipeline.py
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.script_runner import ScriptRunner, ScriptResult
from services.log_compressor import (
    LogCompressor, CompressionConfig, CompressedLog, compress_log
)
from services.file_converter import FileConverter
from services.pipeline_models import (
    PipelineConfig, ScriptConfig, ScriptRole,
    PipelineStopCondition, IterationResult, PipelineRun, PipelineStatus
)


# ══════════════════════════════════════════════════════
#  SCRIPT RUNNER
# ══════════════════════════════════════════════════════

class TestScriptRunner(unittest.TestCase):

    def setUp(self):
        self.runner = ScriptRunner()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_script(self, content: str) -> str:
        p = Path(self.tmpdir) / "test_script.py"
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_run_simple_script(self):
        fp = self._write_script('print("hello world")\n')
        result = self.runner.run_sync(fp, timeout_seconds=10)
        self.assertTrue(result.success)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("hello world", result.stdout)

    def test_run_captures_stderr(self):
        fp = self._write_script('import sys\nsys.stderr.write("error msg\\n")\n')
        result = self.runner.run_sync(fp, timeout_seconds=10)
        self.assertIn("error msg", result.stderr)

    def test_run_exit_nonzero(self):
        fp = self._write_script('import sys\nsys.exit(42)\n')
        result = self.runner.run_sync(fp, timeout_seconds=10)
        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, 42)

    def test_run_missing_file(self):
        result = self.runner.run_sync("/nonexistent/path/script.py", timeout_seconds=5)
        self.assertFalse(result.success)
        self.assertNotEqual(result.error_message, "")

    def test_run_timeout(self):
        fp = self._write_script('import time\ntime.sleep(60)\n')
        result = self.runner.run_sync(fp, timeout_seconds=1)
        self.assertTrue(result.timed_out)
        self.assertFalse(result.success)

    def test_run_multiline_output(self):
        fp = self._write_script(
            'for i in range(10):\n    print(f"line {i}")\n'
        )
        result = self.runner.run_sync(fp, timeout_seconds=10)
        self.assertTrue(result.success)
        lines = result.stdout.strip().splitlines()
        self.assertEqual(len(lines), 10)

    def test_run_with_env_vars(self):
        fp = self._write_script('import os\nprint(os.environ.get("TEST_VAR", "missing"))\n')

        async def _run():
            return await self.runner.run_async(
                fp, env_vars={"TEST_VAR": "hello_env"}, timeout_seconds=10
            )

        result = asyncio.run(_run())
        self.assertIn("hello_env", result.stdout)

    def test_combined_log_has_timestamps(self):
        fp = self._write_script('print("test")\n')
        result = self.runner.run_sync(fp, timeout_seconds=10)
        # combined_log should have timestamps
        self.assertIn("[OUT]", result.combined_log)

    def test_elapsed_time_positive(self):
        fp = self._write_script('import time\ntime.sleep(0.1)\nprint("done")\n')
        result = self.runner.run_sync(fp, timeout_seconds=10)
        self.assertGreater(result.elapsed_seconds, 0.05)

    def test_summary_line(self):
        fp = self._write_script('print("ok")\n')
        result = self.runner.run_sync(fp, timeout_seconds=10)
        summary = result.summary_line()
        self.assertIn("✓ OK", summary)
        self.assertIn("test_script.py", summary)

    def test_run_async_with_on_line_callback(self):
        lines_received = []

        async def _run():
            fp = self._write_script(
                'print("line1")\nprint("line2")\nprint("line3")\n'
            )
            return await self.runner.run_async(
                fp,
                timeout_seconds=10,
                on_line=lambda line, stream: lines_received.append(line),
            )

        result = asyncio.run(_run())
        self.assertTrue(result.success)
        self.assertGreaterEqual(len(lines_received), 3)
        self.assertIn("line1", lines_received)


# ══════════════════════════════════════════════════════
#  LOG COMPRESSOR
# ══════════════════════════════════════════════════════

class TestLogCompressor(unittest.TestCase):

    def setUp(self):
        # Use small limits for testing
        self.cfg = CompressionConfig(
            max_output_chars=2000,
            keep_first_lines=5,
            keep_last_lines=5,
            metric_sample_every=3,
        )
        self.lc = LogCompressor(self.cfg)

    def _make_long_log(self, normal_lines=100, add_error=True, add_traceback=True):
        lines = ["Starting script...", "Loading data..."]
        for i in range(normal_lines):
            lines.append(f"Processing batch {i}: loss=0.{900-i:03d}")
        if add_traceback:
            lines += [
                "Traceback (most recent call last):",
                '  File "train.py", line 42, in train',
                "    result = model.predict(X)",
                "AttributeError: 'NoneType' object has no attribute 'predict'",
            ]
        if add_error:
            lines.append("ERROR: Training failed with exit code 1")
        lines += ["Script completed.", "Exit code: 1"]
        return "\n".join(lines)

    def test_short_log_not_compressed(self):
        short = "line1\nline2\nline3"
        result = self.lc.compress(short)
        self.assertFalse(result.was_compressed)
        self.assertEqual(result.text, short)

    def test_long_log_compressed(self):
        log = self._make_long_log(normal_lines=200)
        result = LogCompressor(CompressionConfig(
            max_output_chars=1000, keep_first_lines=3, keep_last_lines=3
        )).compress(log)
        self.assertTrue(result.was_compressed)
        self.assertLess(result.kept_lines, result.original_lines)

    def test_errors_always_kept(self):
        log = self._make_long_log(normal_lines=200)
        result = LogCompressor(CompressionConfig(
            max_output_chars=500, keep_first_lines=2, keep_last_lines=2
        )).compress(log)
        self.assertTrue(result.has_errors)
        # Error content should be in the compressed text
        self.assertTrue(
            any("AttributeError" in e or "ERROR" in e for e in result.error_lines)
        )

    def test_traceback_kept(self):
        log = self._make_long_log(normal_lines=50)
        result = LogCompressor(CompressionConfig(
            max_output_chars=500, keep_first_lines=2, keep_last_lines=2
        )).compress(log)
        self.assertTrue(any("Traceback" in l or "AttributeError" in l
                            for l in result.error_lines))

    def test_warnings_kept(self):
        log = "line1\nline2\n" * 50 + "WARNING: Low precision: 0.65 < 0.70\n" + "line3\n" * 50
        result = LogCompressor(CompressionConfig(
            max_output_chars=500, keep_first_lines=2, keep_last_lines=2
        )).compress(log)
        self.assertIn("WARNING", result.text)

    def test_first_lines_always_kept(self):
        log = "STARTUP_MARKER\n" + "normal line\n" * 100
        result = LogCompressor(CompressionConfig(
            max_output_chars=200, keep_first_lines=3, keep_last_lines=1
        )).compress(log)
        self.assertIn("STARTUP_MARKER", result.text)

    def test_last_lines_always_kept(self):
        log = "normal line\n" * 100 + "FINAL_RESULT_MARKER\n"
        result = LogCompressor(CompressionConfig(
            max_output_chars=200, keep_first_lines=1, keep_last_lines=3
        )).compress(log)
        self.assertIn("FINAL_RESULT_MARKER", result.text)

    def test_compress_for_ai_adds_header(self):
        log = "Starting\n" + "normal\n" * 200 + "Done\n"
        result = LogCompressor(CompressionConfig(max_output_chars=500)).compress_for_ai(
            log, "my_script.py"
        )
        self.assertIn("my_script.py", result)
        self.assertIn("Оригинал:", result)

    def test_compress_log_convenience(self):
        # Use enough lines to trigger char limit
        log = "processing item\n" * 1000  # ~16000 chars
        result = compress_log(log, max_chars=500, script_name="test.py")
        self.assertLessEqual(len(result), 700)  # with header overhead

    def test_file_output_lines_kept(self):
        log = "Training...\n" * 50 + "Saved model to output/best_model.pkl\n" + "Training...\n" * 50
        result = LogCompressor(CompressionConfig(
            max_output_chars=500, keep_first_lines=2, keep_last_lines=2
        )).compress(log)
        self.assertIn("best_model.pkl", result.text)

    def test_metric_lines_sampled(self):
        lines = ["Starting"]
        for i in range(100):
            lines.append(f"epoch {i}/100 loss={0.9-i*0.005:.3f} acc={0.5+i*0.004:.3f}")
        lines.append("Done")
        log = "\n".join(lines)
        result = LogCompressor(CompressionConfig(
            max_output_chars=3000, keep_first_lines=2, keep_last_lines=2,
            metric_sample_every=5
        )).compress(log)
        # Should have kept some but not all metric lines
        metric_count = sum(1 for l in result.text.splitlines() if "epoch" in l)
        self.assertLess(metric_count, 80)  # compressed
        self.assertGreater(metric_count, 0)  # but some kept


# ══════════════════════════════════════════════════════
#  FILE CONVERTER
# ══════════════════════════════════════════════════════

class TestFileConverter(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fc = FileConverter()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name: str, content: str) -> str:
        p = Path(self.tmpdir) / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    def _write_bytes(self, name: str, content: bytes) -> str:
        p = Path(self.tmpdir) / name
        p.write_bytes(content)
        return str(p)

    def test_convert_text_file(self):
        fp = self._write("test.txt", "hello\nworld\n")
        result = self.fc.convert(fp)
        self.assertEqual(result.file_type, "text")
        self.assertIn("hello", result.content)

    def test_convert_python_file(self):
        fp = self._write("model.py", "def train():\n    pass\n")
        result = self.fc.convert(fp)
        self.assertIn("def train", result.content)

    def test_convert_json_pretty(self):
        fp = self._write("results.json", '{"accuracy": 0.87, "loss": 0.23}')
        result = self.fc.convert(fp)
        self.assertEqual(result.file_type, "json")
        self.assertIn("accuracy", result.content)
        self.assertIn("0.87", result.content)

    def test_convert_csv(self):
        fp = self._write("metrics.csv",
                         "epoch,loss,accuracy\n1,0.9,0.5\n2,0.8,0.6\n3,0.7,0.7\n")
        result = self.fc.convert(fp)
        self.assertEqual(result.file_type, "csv")
        self.assertIn("epoch", result.content)
        self.assertIn("0.9", result.content)

    def test_convert_missing_file(self):
        result = self.fc.convert("/nonexistent/file.txt")
        self.assertEqual(result.file_type, "missing")
        self.assertIn("не найден", result.content)

    def test_convert_for_ai_adds_header(self):
        fp = self._write("output.json", '{"score": 0.95}')
        ctx = self.fc.convert_for_ai(fp)
        self.assertIn("output.json", ctx)
        self.assertIn("json", ctx)
        self.assertIn("score", ctx)
        # Should be wrapped in code fences
        self.assertIn("```", ctx)

    def test_convert_large_text_truncated(self):
        fp = self._write("big.txt", "x" * 50000)
        result = self.fc.convert(fp, max_chars=1000)
        self.assertLessEqual(len(result.content), 1200)
        self.assertIn("вырезано", result.content)

    def test_convert_json_invalid_fallback(self):
        fp = self._write("broken.json", "{invalid json{{}")
        result = self.fc.convert(fp)
        # Should not crash, fallback to raw text
        self.assertIsInstance(result.content, str)
        self.assertGreater(len(result.content), 0)

    def test_convert_numpy_array(self):
        try:
            import numpy as np
            arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
            fp = str(Path(self.tmpdir) / "array.npy")
            np.save(fp, arr)
            result = self.fc.convert(fp)
            self.assertIn("shape", result.content)
        except ImportError:
            self.skipTest("numpy not installed")

    def test_convert_pickle_object(self):
        import pickle
        obj = {"key": "value", "numbers": [1, 2, 3]}
        fp = str(Path(self.tmpdir) / "data.pkl")
        with open(fp, "wb") as f:
            pickle.dump(obj, f)
        result = self.fc.convert(fp)
        self.assertEqual(result.file_type, "pickle")
        self.assertIn("dict", result.content)

    def test_human_size_formatting(self):
        self.assertIn("Б", FileConverter._human_size(500))
        self.assertIn("КБ", FileConverter._human_size(2000))
        self.assertIn("МБ", FileConverter._human_size(2_000_000))


# ══════════════════════════════════════════════════════
#  PIPELINE MODELS
# ══════════════════════════════════════════════════════

class TestPipelineModels(unittest.TestCase):

    def test_script_config_name(self):
        sc = ScriptConfig(script_path="/path/to/train.py")
        self.assertEqual(sc.name, "train.py")

    def test_script_config_roundtrip(self):
        sc = ScriptConfig(
            script_path="trainer.py",
            role=ScriptRole.PRIMARY,
            args=["--epochs", "100"],
            timeout_seconds=300,
            output_files=["results.csv"],
            output_patterns=["*.pkl", "output/*.json"],
            allow_patching=True,
            env_vars={"CUDA": "0"},
        )
        d = sc.to_dict()
        sc2 = ScriptConfig.from_dict(d)
        self.assertEqual(sc2.script_path, "trainer.py")
        self.assertEqual(sc2.role, ScriptRole.PRIMARY)
        self.assertEqual(sc2.args, ["--epochs", "100"])
        self.assertEqual(sc2.output_patterns, ["*.pkl", "output/*.json"])
        self.assertEqual(sc2.env_vars, {"CUDA": "0"})

    def test_pipeline_config_primary_validators(self):
        cfg = PipelineConfig()
        cfg.scripts = [
            ScriptConfig("train.py", role=ScriptRole.PRIMARY),
            ScriptConfig("validate.py", role=ScriptRole.VALIDATOR),
            ScriptConfig("train2.py", role=ScriptRole.PRIMARY),
        ]
        self.assertEqual(len(cfg.primary_scripts), 2)
        self.assertEqual(len(cfg.validator_scripts), 1)

    def test_pipeline_config_roundtrip(self):
        cfg = PipelineConfig(
            name="ML Optimizer",
            goal="Precision > 80%",
            max_iterations=15,
            stop_condition=PipelineStopCondition.GOAL_REACHED,
            auto_apply_patches=True,
            auto_rollback_on_error=True,
            retry_on_patch_failure=3,
        )
        sc = ScriptConfig("train.py", role=ScriptRole.PRIMARY,
                          output_patterns=["*.csv"])
        cfg.scripts.append(sc)

        d = cfg.to_dict()
        cfg2 = PipelineConfig.from_dict(d)
        self.assertEqual(cfg2.name, "ML Optimizer")
        self.assertEqual(cfg2.stop_condition, PipelineStopCondition.GOAL_REACHED)
        self.assertEqual(cfg2.max_iterations, 15)
        self.assertEqual(len(cfg2.scripts), 1)
        self.assertEqual(cfg2.scripts[0].output_patterns, ["*.csv"])

    def test_pipeline_run_counters(self):
        cfg = PipelineConfig(max_iterations=5)
        run = PipelineRun(config=cfg)
        self.assertEqual(run.current_iteration, 0)
        self.assertEqual(run.total_patches_applied, 0)

        run.iterations.append(IterationResult(
            iteration=1, script_results=[], patches_generated=3,
            patches_applied=2, patches_failed=1, rolled_back=False,
            ai_analysis="", goal_achieved=False
        ))
        self.assertEqual(run.current_iteration, 1)
        self.assertEqual(run.total_patches_applied, 2)

    def test_iteration_result_success(self):
        ok = IterationResult(
            iteration=1, script_results=[], patches_generated=1,
            patches_applied=1, patches_failed=0, rolled_back=False,
            ai_analysis="", goal_achieved=False
        )
        self.assertTrue(ok.success)

        failed = IterationResult(
            iteration=2, script_results=[], patches_generated=1,
            patches_applied=0, patches_failed=0, rolled_back=True,
            ai_analysis="", goal_achieved=False
        )
        self.assertFalse(failed.success)

    def test_all_stop_conditions(self):
        for sc in PipelineStopCondition:
            cfg = PipelineConfig(stop_condition=sc)
            d = cfg.to_dict()
            cfg2 = PipelineConfig.from_dict(d)
            self.assertEqual(cfg2.stop_condition, sc)

    def test_all_script_roles(self):
        for role in ScriptRole:
            sc = ScriptConfig("x.py", role=role)
            d = sc.to_dict()
            sc2 = ScriptConfig.from_dict(d)
            self.assertEqual(sc2.role, role)


# ══════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  AI Code Sherlock — Pipeline Services Tests")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestScriptRunner,
        TestLogCompressor,
        TestFileConverter,
        TestPipelineModels,
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
