"""
Script Runner — executes scripts with real-time output capture.

Features:
- Real-time stdout/stderr streaming via callbacks
- Auto stdin input sequences (answer prompts automatically)
- Timeout support (up to 999 hours)
- Environment variable injection
- Working directory control
- Exit code + elapsed time tracking
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


@dataclass
class AutoInput:
    """Defines automatic stdin responses for interactive prompts."""
    sequences: list[str] = field(default_factory=list)
    # e.g. ["Y\n", "\n", "yes\n"] — sent in order when script is waiting
    delay_seconds: float = 0.5    # wait before sending each input
    repeat_last: bool = True       # repeat last sequence if script asks more


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


class ScriptRunner:

    def __init__(self, logger=None):
        self._logger = logger

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

        # If auto_input provided, pre-build stdin bytes
        stdin_data: bytes | None = None
        if auto_input and auto_input.sequences:
            combined = ""
            for seq in auto_input.sequences:
                combined += seq
                if not seq.endswith("\n"):
                    combined += "\n"
            stdin_data = combined.encode("utf-8")

        started_at = datetime.now()
        start_time = time.monotonic()
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        combined_lines: list[str] = []

        if self._logger:
            self._logger.info(
                f"Запуск: {path.name} (timeout={timeout_seconds}s"
                + (f", auto-input={len(auto_input.sequences)} ответов)" if auto_input else ")"),
                source="ScriptRunner"
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if stdin_data else None,
                cwd=cwd,
                env=env,
            )

            # Send auto-input stdin upfront
            if stdin_data and proc.stdin:
                try:
                    proc.stdin.write(stdin_data)
                    await proc.stdin.drain()
                    proc.stdin.close()
                except Exception:
                    pass

            async def _read_stream(stream, stream_name: str, target: list):
                async for raw_line in stream:
                    try:
                        line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
                    except Exception:
                        line = repr(raw_line)
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    tagged = f"[{ts}][{stream_name}] {line}"
                    target.append(line)
                    combined_lines.append(tagged)
                    if on_line:
                        on_line(line, stream_name)

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        _read_stream(proc.stdout, "OUT", stdout_lines),
                        _read_stream(proc.stderr, "ERR", stderr_lines),
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

    def run_sync(self, script_path: str, args: list[str] | None = None,
                 working_dir: str | None = None, timeout_seconds: int = 600,
                 auto_input: AutoInput | None = None) -> ScriptResult:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.run_async(script_path, args, working_dir,
                               timeout_seconds=timeout_seconds,
                               auto_input=auto_input)
            )
        finally:
            loop.close()

    @staticmethod
    def _build_command(path: Path, args: list[str]) -> list[str]:
        ext = path.suffix.lower()
        if ext == ".py":
            return [sys.executable, str(path)] + args
        elif ext in (".bat", ".cmd"):
            return ["cmd", "/c", str(path)] + args
        elif ext == ".sh":
            return ["bash", str(path)] + args
        elif ext in (".ps1",):
            return ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(path)] + args
        else:
            return [str(path)] + args
