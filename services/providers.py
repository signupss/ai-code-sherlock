"""
AI Model Providers — Ollama, Custom API (OpenAI-compatible), File Signal (ZennoPoster IPC)
"""
from __future__ import annotations
import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import aiohttp
import aiofiles

from core.interfaces import IAiModelProvider, IFileSignalService
from core.models import ChatMessage, ModelDefinition, ModelSourceType


# ══════════════════════════════════════════════════════
#  1. OLLAMA PROVIDER
# ══════════════════════════════════════════════════════

class OllamaProvider(IAiModelProvider):

    def __init__(self, model: ModelDefinition, logger=None):
        self._model = model
        self._logger = logger
        self._base_url = model.ollama_base_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "Ollama"

    @property
    def model(self) -> ModelDefinition:
        return self._model

    async def complete(self, messages: list[ChatMessage]) -> str:
        payload = self._build_payload(messages, stream=False)
        timeout = aiohttp.ClientTimeout(total=600)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{self._base_url}/api/chat",
                json=payload
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Ollama error {resp.status}: {text}")
                data = await resp.json()
                return data.get("message", {}).get("content", "")

    async def stream(self, messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
        import json as json_mod
        payload = self._build_payload(messages, stream=True)
        timeout = aiohttp.ClientTimeout(total=600)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{self._base_url}/api/chat",
                json=payload
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Ollama stream error {resp.status}: {text}")

                async for line in resp.content:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json_mod.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            break
                    except json_mod.JSONDecodeError:
                        continue

    async def is_available(self) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self._base_url}/api/tags") as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def list_local_models(self) -> list[str]:
        """Return models available in this Ollama instance."""
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self._base_url}/api/tags") as resp:
                    data = await resp.json()
                    return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def _build_payload(self, messages: list[ChatMessage], stream: bool) -> dict:
        return {
            "model": self._model.name,
            "messages": [
                {"role": m.role.value, "content": m.content}
                for m in messages
            ],
            "stream": stream,
            "options": {"temperature": self._model.temperature},
        }


# ══════════════════════════════════════════════════════
#  2. CUSTOM API PROVIDER (OpenAI-compatible)
# ══════════════════════════════════════════════════════

class CustomApiProvider(IAiModelProvider):

    def __init__(self, model: ModelDefinition, logger=None):
        if not model.api_base_url:
            raise ValueError("api_base_url is required for CustomApi provider")
        self._model = model
        self._logger = logger
        self._base_url = model.api_base_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "CustomAPI"

    @property
    def model(self) -> ModelDefinition:
        return self._model

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._model.api_key:
            h["Authorization"] = f"Bearer {self._model.api_key}"
        h.update(self._model.custom_headers)
        return h

    def _build_payload(self, messages: list[ChatMessage], stream: bool) -> dict:
        return {
            "model": self._model.api_model_id or self._model.name,
            "messages": [
                {"role": m.role.value, "content": m.content}
                for m in messages
            ],
            "temperature": self._model.temperature,
            "max_tokens": self._model.max_context_tokens // 2,
            "stream": stream,
        }

    async def complete(self, messages: list[ChatMessage]) -> str:
        payload = self._build_payload(messages, stream=False)
        # 900s = 15 min — must be larger than asyncio.wait_for timeout in _query_ai (600s)
        # so the asyncio layer fires first and gives a readable error message
        timeout = aiohttp.ClientTimeout(total=900)

        async with aiohttp.ClientSession(timeout=timeout, headers=self._headers()) as session:
            async with session.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(
                        f"API error {resp.status}: {body[:500]}"
                    )
                data = await resp.json()
                return (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )

    async def stream(self, messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
        import json as json_mod
        payload = self._build_payload(messages, stream=True)
        timeout = aiohttp.ClientTimeout(total=900)  # 15 min — larger than asyncio layer

        async with aiohttp.ClientSession(timeout=timeout, headers=self._headers()) as session:
            async with session.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"API stream error {resp.status}: {body[:300]}")

                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json_mod.loads(data_str)
                        delta = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if delta:
                            yield delta
                    except json_mod.JSONDecodeError:
                        continue

    async def is_available(self) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout, headers=self._headers()) as session:
                async with session.get(f"{self._base_url}/v1/models") as resp:
                    return resp.status < 500
        except Exception:
            return False


# ══════════════════════════════════════════════════════
#  3. FILE SIGNAL SERVICE  (ZennoPoster IPC)
# ══════════════════════════════════════════════════════

class FileSignalService(IFileSignalService):
    """
    IPC via filesystem:
      1. Write prompt to <request_folder>/<id>.txt
      2. Poll for <response_folder>/<id>.txt
      3. Read, clean up, return content
    """

    POLL_INTERVAL = 0.25  # seconds
    MAX_WRITE_RETRIES = 3

    async def send_request(
        self,
        request_id: str,
        prompt: str,
        request_folder: str,
        response_folder: str,
        timeout_seconds: int,
    ) -> str:
        req_dir = Path(request_folder)
        res_dir = Path(response_folder)
        req_dir.mkdir(parents=True, exist_ok=True)
        res_dir.mkdir(parents=True, exist_ok=True)

        req_file = req_dir / f"{request_id}.txt"
        res_file = res_dir / f"{request_id}.txt"

        # Clean stale response
        res_file.unlink(missing_ok=True)

        # Write request with retries
        await self._write_with_retry(req_file, prompt)

        # Poll for response
        return await self._wait_for_response(res_file, timeout_seconds)

    async def _write_with_retry(self, path: Path, content: str) -> None:
        for attempt in range(1, self.MAX_WRITE_RETRIES + 1):
            try:
                async with aiofiles.open(path, "w", encoding="utf-8") as f:
                    await f.write(content)
                return
            except OSError as e:
                if attempt == self.MAX_WRITE_RETRIES:
                    raise RuntimeError(
                        f"Failed to write signal file after {self.MAX_WRITE_RETRIES} attempts: {e}"
                    )
                await asyncio.sleep(0.5 * attempt)

    async def _wait_for_response(self, res_file: Path, timeout_seconds: int) -> str:
        deadline = asyncio.get_event_loop().time() + timeout_seconds

        while asyncio.get_event_loop().time() < deadline:
            if res_file.exists():
                content = await self._safe_read(res_file)
                if content and content.strip():
                    # Clean up
                    try:
                        res_file.unlink(missing_ok=True)
                    except OSError:
                        pass
                    return content.strip()

            await asyncio.sleep(self.POLL_INTERVAL)

        raise TimeoutError(
            f"FileSignal timed out after {timeout_seconds}s. "
            f"Expected response: {res_file}"
        )

    async def _safe_read(self, path: Path) -> str:
        """Read with sharing — file may still be written."""
        try:
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                return await f.read()
        except OSError:
            return ""


# ══════════════════════════════════════════════════════
#  4. FILE SIGNAL PROVIDER  (wraps service into provider)
# ══════════════════════════════════════════════════════

class FileSignalProvider(IAiModelProvider):

    def __init__(self, model: ModelDefinition, signal_service: FileSignalService, logger=None):
        if not model.signal_request_folder or not model.signal_response_folder:
            raise ValueError("signal_request_folder and signal_response_folder required")
        self._model = model
        self._service = signal_service
        self._logger = logger

    @property
    def provider_name(self) -> str:
        return "FileSignal"

    @property
    def model(self) -> ModelDefinition:
        return self._model

    async def complete(self, messages: list[ChatMessage]) -> str:
        request_id = uuid.uuid4().hex[:12]
        prompt = self._flatten_messages(messages)
        return await self._service.send_request(
            request_id=request_id,
            prompt=prompt,
            request_folder=self._model.signal_request_folder,
            response_folder=self._model.signal_response_folder,
            timeout_seconds=self._model.signal_timeout_seconds,
        )

    async def stream(self, messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
        # FileSignal is non-streaming by nature — return full response as single chunk
        result = await self.complete(messages)
        yield result

    async def is_available(self) -> bool:
        req = Path(self._model.signal_request_folder)
        res = Path(self._model.signal_response_folder)
        return req.exists() and res.exists()

    @staticmethod
    def _flatten_messages(messages: list[ChatMessage]) -> str:
        parts = []
        for m in messages:
            parts.append(f"### {m.role.value.upper()} ###\n{m.content}")
        return "\n\n".join(parts)
