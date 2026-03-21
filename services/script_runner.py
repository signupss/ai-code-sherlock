"""
Script Runner — executes scripts with real-time output capture.

Features:
- Real-time stdout/stderr streaming via callbacks
- Interactive stdin — send text to running script at any time from any thread
- Queue-based stdin pump (no race conditions, no closed-pipe issues)
- Auto stdin input sequences (answer prompts automatically)
- Timeout support (up to 999 hours)
- Environment variable injection
- Working directory control
- Exit code + elapsed time tracking

Language support (stdin works for all):
  Python (.py), JavaScript (.js .mjs), TypeScript (.ts),
  Ruby (.rb), PHP (.php), Go (.go), Lua (.lua), Perl (.pl), R (.r),
  Bash/Shell (.sh .bash), Batch (.bat .cmd), PowerShell (.ps1),
  Julia (.jl), + generic executables (shebang / chmod+x)
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


# ──────────────────────────────────────────────────────────
#  Data Models
# ──────────────────────────────────────────────────────────

@dataclass
class AutoInput:
    """Defines automatic stdin responses for interactive prompts."""
    sequences: list[str] = field(default_factory=list)
    delay_seconds: float = 0.5
    repeat_last: bool = True


@dataclass
class ScriptResult:
    script_path: str
    exit_code: int
    stdout: str
    stderr: str
    combined_log: str
    elapsed_seconds: float
    started_at: datetime
    finished_at: datetime
    timed_out: bool = False
    error_message: str = ""

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.error_message

    @property
    def has_errors(self) -> bool:
        return bool(self.stderr.strip()) or self.exit_code != 0

    @property
    def short_name(self) -> str:
        return Path(self.script_path).name

    def summary_line(self) -> str:
        status = "✓ OK" if self.success else f"✗ код {self.exit_code}"
        if self.timed_out:
            status = "⏱ TIMEOUT"
        return (f"[{self.started_at.strftime('%H:%M:%S')}] "
                f"{self.short_name} — {status} "
                f"({self.elapsed_seconds:.1f}s)")


# ──────────────────────────────────────────────────────────
#  ScriptRunner
# ──────────────────────────────────────────────────────────

class ScriptRunner:

    def __init__(self, logger=None):
        self._logger = logger
        self._current_proc: asyncio.subprocess.Process | None = None
        self._current_loop: asyncio.AbstractEventLoop | None = None
        # asyncio.Queue lives on the worker event loop; populated from main thread
        self._stdin_queue: asyncio.Queue | None = None

    # ── Public API (main-thread safe) ──────────────────────

    def kill_current(self) -> None:
        """Kill the currently running subprocess if any."""
        try:
            if self._current_proc and self._current_proc.returncode is None:
                self._current_proc.kill()
        except Exception:
            pass

    def send_stdin(self, text: str) -> None:
        """
        Send a line of text to the running script's stdin.
        Safe to call from the Qt main thread at any time.
        Works for ALL languages — Python input(), bash read,
        Node readline, Ruby gets, PHP fgets(STDIN), etc.

        Automatically appends \\n if missing.
        """
        if not text.endswith("\n"):
            text += "\n"

        loop  = self._current_loop
        queue = self._stdin_queue
        if loop is None or queue is None:
            return
        try:
            # Schedule queue.put on the worker event loop (thread-safe)
            asyncio.run_coroutine_threadsafe(queue.put(text), loop)
        except Exception:
            pass

    # ── Async runner ───────────────────────────────────────

    async def run_async(
        self,
        script_path: str,
        args: list[str] | None = None,
        working_dir: str | None = None,
        env_vars: dict[str, str] | None = None,
        timeout_seconds: int = 600,
        on_line: Callable[[str, str], None] | None = None,
        auto_input: AutoInput | None = None,
    ) -> ScriptResult:
        path = Path(script_path).resolve()
        if not path.exists():
            return ScriptResult(
                script_path=script_path, exit_code=-1,
                stdout="", stderr="", combined_log="",
                elapsed_seconds=0,
                started_at=datetime.now(), finished_at=datetime.now(),
                error_message=f"Файл не найден: {path}"
            )

        cmd = self._build_command(path, args or [])
        cwd = working_dir or str(path.parent)

        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"

        # Capture the running event loop while we are inside a coroutine
        self._current_loop = asyncio.get_running_loop()
        self._stdin_queue  = asyncio.Queue()

        # Pre-populate queue with auto_input sequences (if any)
        if auto_input and auto_input.sequences:
            for seq in auto_input.sequences:
                line = seq if seq.endswith("\n") else seq + "\n"
                await self._stdin_queue.put(line)

        started_at    = datetime.now()
        start_time    = time.monotonic()
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        combined_lines: list[str] = []

        if self._logger:
            self._logger.info(
                f"Запуск: {path.name} (timeout={timeout_seconds}s)",
                source="ScriptRunner"
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Always keep stdin open so interactive input works for any language
                stdin=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
            self._current_proc = proc

            # ── stdin pump: queue → process stdin ─────────────
            async def _stdin_pump():
                """
                Drains the stdin queue and writes each item to the process.
                Runs concurrently with the output readers.
                Stops when the process exits OR a None sentinel is received.
                """
                while True:
                    # Stop if process already finished
                    if proc.returncode is not None:
                        break
                    try:
                        item = await asyncio.wait_for(
                            self._stdin_queue.get(), timeout=0.15
                        )
                    except asyncio.TimeoutError:
                        continue   # no input yet — keep polling

                    if item is None:
                        break      # sentinel → clean exit

                    if proc.stdin is None:
                        break

                    try:
                        proc.stdin.write(item.encode("utf-8"))
                        await proc.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        break
                    except Exception:
                        break

            # ── stdout / stderr readers ────────────────────────
            async def _read_stream(stream, stream_name: str, target: list):
                async for raw_line in stream:
                    try:
                        line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
                    except Exception:
                        line = repr(raw_line)
                    ts     = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    tagged = f"[{ts}][{stream_name}] {line}"
                    target.append(line)
                    combined_lines.append(tagged)
                    if on_line:
                        on_line(line, stream_name)

            # Run everything concurrently under the global timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        _read_stream(proc.stdout, "OUT", stdout_lines),
                        _read_stream(proc.stderr, "ERR", stderr_lines),
                        _stdin_pump(),
                    ),
                    timeout=timeout_seconds
                )
                await proc.wait()
                timed_out = False
                exit_code = proc.returncode or 0

            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                timed_out = True
                exit_code = -9

            finally:
                # Stop the stdin pump cleanly via sentinel
                try:
                    if self._stdin_queue:
                        self._stdin_queue.put_nowait(None)
                except Exception:
                    pass
                self._current_proc = None
                self._current_loop = None
                self._stdin_queue  = None

        except Exception as e:
            elapsed = time.monotonic() - start_time
            return ScriptResult(
                script_path=str(path), exit_code=-1,
                stdout="", stderr="", combined_log="",
                elapsed_seconds=elapsed,
                started_at=started_at, finished_at=datetime.now(),
                error_message=str(e)
            )

        elapsed = time.monotonic() - start_time
        result = ScriptResult(
            script_path=str(path),
            exit_code=exit_code,
            stdout="\n".join(stdout_lines),
            stderr="\n".join(stderr_lines),
            combined_log="\n".join(combined_lines),
            elapsed_seconds=elapsed,
            started_at=started_at,
            finished_at=datetime.now(),
            timed_out=timed_out,
        )

        if self._logger:
            level = "info" if result.success else "warning"
            getattr(self._logger, level)(result.summary_line(), source="ScriptRunner")

        return result

    def run_sync(
        self,
        script_path: str,
        args: list[str] | None = None,
        working_dir: str | None = None,
        timeout_seconds: int = 600,
        auto_input: AutoInput | None = None,
    ) -> ScriptResult:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.run_async(script_path, args, working_dir,
                               timeout_seconds=timeout_seconds,
                               auto_input=auto_input)
            )
        finally:
            loop.close()

    # ── Command builder ────────────────────────────────────

    @staticmethod
    def _build_command(path: Path, args: list[str]) -> list[str]:
        """
        Build the OS command list for any script language.
        Falls back to shebang detection and direct execution.
        """
        ext = path.suffix.lower()

        # ── Python ────────────────────────────────────────────
        if ext == ".py":
            # -u = force unbuffered so print() shows instantly
            return [sys.executable, "-u", str(path)] + args

        # ── JavaScript / Node ─────────────────────────────────
        elif ext in (".js", ".mjs", ".cjs"):
            node = shutil.which("node") or shutil.which("nodejs") or "node"
            return [node, str(path)] + args

        # ── TypeScript ────────────────────────────────────────
        elif ext == ".ts":
            ts_node = shutil.which("ts-node") or shutil.which("ts-node-esm")
            if ts_node:
                return [ts_node, str(path)] + args
            return ["npx", "--yes", "ts-node", str(path)] + args

        # ── Ruby ──────────────────────────────────────────────
        elif ext == ".rb":
            ruby = shutil.which("ruby") or "ruby"
            return [ruby, str(path)] + args

        # ── PHP ───────────────────────────────────────────────
        elif ext == ".php":
            php = shutil.which("php") or "php"
            return [php, str(path)] + args

        # ── Perl ──────────────────────────────────────────────
        elif ext in (".pl", ".pm"):
            perl = shutil.which("perl") or "perl"
            return [perl, str(path)] + args

        # ── Lua ───────────────────────────────────────────────
        elif ext == ".lua":
            lua = (shutil.which("lua") or shutil.which("lua5.4")
                   or shutil.which("lua5.3") or "lua")
            return [lua, str(path)] + args

        # ── R ─────────────────────────────────────────────────
        elif ext in (".r", ".rscript"):
            rscript = shutil.which("Rscript") or shutil.which("rscript") or "Rscript"
            return [rscript, str(path)] + args

        # ── Julia ─────────────────────────────────────────────
        elif ext == ".jl":
            julia = shutil.which("julia") or "julia"
            return [julia, str(path)] + args

        # ── Go (interpreted mode) ─────────────────────────────
        elif ext == ".go":
            return ["go", "run", str(path)] + args

        # ── Java (single-file, Java 11+) ──────────────────────
        elif ext == ".java":
            java = shutil.which("java") or "java"
            return [java, str(path)] + args

        # ── Shell ─────────────────────────────────────────────
        elif ext in (".sh", ".bash"):
            bash = shutil.which("bash") or shutil.which("sh") or "bash"
            return [bash, str(path)] + args

        elif ext in (".bat", ".cmd"):
            return ["cmd", "/c", str(path)] + args

        elif ext == ".ps1":
            return [
                "powershell", "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", str(path),
            ] + args

        # ── Generic fallback ──────────────────────────────────
        else:
            if os.access(str(path), os.X_OK):
                return [str(path)] + args
            interp = _detect_shebang(path)
            if interp:
                return interp + [str(path)] + args
            return [str(path)] + args


# ──────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────

def _detect_shebang(path: Path) -> list[str] | None:
    """
    Read first line looking for #!/usr/bin/env python3 etc.
    Returns interpreter list or None.
    """
    try:
        with open(path, "rb") as f:
            first = f.readline(256).decode("utf-8", errors="ignore").strip()
        if first.startswith("#!"):
            parts = first[2:].strip().split()
            if parts:
                return parts
    except Exception:
        pass
    return None
