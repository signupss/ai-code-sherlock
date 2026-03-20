"""
Consensus Engine — queries multiple AI models and picks the best answer.

Modes:
  VOTE       — each model proposes patches, pick patches that ≥N models agree on
  BEST_OF_N  — pick response that has the most valid, non-overlapping patches
  MERGE      — take unique non-overlapping patches from all models
  JUDGE      — one model reads all responses and picks the best one
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional

from core.models import ChatMessage, MessageRole, PatchBlock
from services.engine import PatchEngine
from services.pipeline_models import ConsensusMode, ConsensusConfig


@dataclass
class ModelResponse:
    model_id: str
    response_text: str
    patches: list[PatchBlock]
    elapsed_ms: float
    error: str = ""

    @property
    def success(self) -> bool:
        return not self.error

    @property
    def patch_count(self) -> int:
        return len(self.patches)


@dataclass
class ConsensusResult:
    mode: ConsensusMode
    model_responses: list[ModelResponse]
    final_response: str
    final_patches: list[PatchBlock]
    winning_model_id: str = ""
    agreement_count: int = 0
    notes: str = ""


class ConsensusEngine:

    def __init__(
        self,
        model_manager,         # ModelManager
        patch_engine: PatchEngine,
        on_event: Callable[[str, dict], None] | None = None,
        logger=None,
    ):
        self._mm = model_manager
        self._patch = patch_engine
        self._on_event = on_event or (lambda e, d: None)
        self._logger = logger

    async def run(
        self,
        config: ConsensusConfig,
        system_prompt: str,
        user_prompt: str,
    ) -> ConsensusResult:
        """
        Query all configured models, then combine results per mode.
        """
        if not config.enabled or not config.model_ids:
            raise ValueError("ConsensusConfig not enabled or no model_ids set")

        self._on_event("consensus_start", {
            "mode": config.mode.value,
            "models": config.model_ids,
        })

        # ── Query all models in parallel ──────────────────────────────────────
        tasks = [
            self._query_model(mid, system_prompt, user_prompt,
                              config.timeout_per_model)
            for mid in config.model_ids
        ]
        responses: list[ModelResponse] = await asyncio.gather(*tasks, return_exceptions=False)

        # Filter out total failures
        good = [r for r in responses if r.success]
        if not good:
            errors = "; ".join(r.error for r in responses)
            raise RuntimeError(f"All consensus models failed: {errors}")

        self._on_event("consensus_responses", {
            "total": len(responses),
            "successful": len(good),
            "patches_per_model": {r.model_id: r.patch_count for r in good},
        })

        # ── Combine based on mode ─────────────────────────────────────────────
        if config.mode == ConsensusMode.VOTE:
            return self._vote(config, responses, good)
        elif config.mode == ConsensusMode.BEST_OF_N:
            return self._best_of_n(responses, good)
        elif config.mode == ConsensusMode.MERGE:
            return self._merge(responses, good)
        elif config.mode == ConsensusMode.JUDGE:
            return await self._judge(config, system_prompt, responses, good)
        else:
            return self._best_of_n(responses, good)

    # ── Strategies ────────────────────────────────────────────────────────────

    def _vote(
        self, config: ConsensusConfig,
        all_resp: list[ModelResponse], good: list[ModelResponse]
    ) -> ConsensusResult:
        """
        Find patches that appear in ≥ min_agreement responses.
        A patch "matches" if its search_content is identical or very similar.
        """
        if len(good) == 1:
            r = good[0]
            return ConsensusResult(
                mode=ConsensusMode.VOTE, model_responses=all_resp,
                final_response=r.response_text, final_patches=r.patches,
                winning_model_id=r.model_id, agreement_count=1,
                notes="Только одна модель ответила успешно — без голосования"
            )

        # Group patches by normalized search content
        patch_votes: dict[str, list[tuple[str, PatchBlock]]] = {}
        for resp in good:
            for patch in resp.patches:
                key = self._normalize_patch_key(patch)
                if key not in patch_votes:
                    patch_votes[key] = []
                patch_votes[key].append((resp.model_id, patch))

        # Pick patches with enough votes
        min_agree = min(config.min_agreement, len(good))
        agreed_patches: list[PatchBlock] = []
        for key, votes in patch_votes.items():
            if len(votes) >= min_agree:
                # Use the patch from the first vote
                _, patch = votes[0]
                agreed_patches.append(patch)

        if not agreed_patches:
            # No agreement — fall back to best_of_n
            result = self._best_of_n(all_resp, good)
            result.notes = f"Голосование: нет согласия при мин.={min_agree} — откат к лучшему"
            return result

        best = max(good, key=lambda r: r.patch_count)
        notes = (
            f"Голосование: {len(agreed_patches)} патч(ей) получили ≥{min_agree} голосов "
            f"из {len(good)} моделей"
        )
        return ConsensusResult(
            mode=ConsensusMode.VOTE, model_responses=all_resp,
            final_response=best.response_text,
            final_patches=agreed_patches,
            winning_model_id=best.model_id,
            agreement_count=min_agree,
            notes=notes,
        )

    def _best_of_n(
        self, all_resp: list[ModelResponse], good: list[ModelResponse]
    ) -> ConsensusResult:
        """Pick the response with the most valid patches."""
        best = max(good, key=lambda r: (r.patch_count, -r.elapsed_ms))
        notes = (
            f"Best-of-N: {best.model_id} выбран "
            f"({best.patch_count} патч(ей), {best.elapsed_ms:.0f}ms)"
        )
        return ConsensusResult(
            mode=ConsensusMode.BEST_OF_N, model_responses=all_resp,
            final_response=best.response_text, final_patches=best.patches,
            winning_model_id=best.model_id,
            notes=notes,
        )

    def _merge(
        self, all_resp: list[ModelResponse], good: list[ModelResponse]
    ) -> ConsensusResult:
        """Merge non-overlapping patches from all models."""
        seen_keys: set[str] = set()
        merged: list[PatchBlock] = []
        source_ids: list[str] = []

        for resp in sorted(good, key=lambda r: -r.patch_count):
            for patch in resp.patches:
                key = self._normalize_patch_key(patch)
                if key not in seen_keys:
                    seen_keys.add(key)
                    merged.append(patch)
                    if resp.model_id not in source_ids:
                        source_ids.append(resp.model_id)

        # Use the response text from the model that contributed most
        best = max(good, key=lambda r: r.patch_count)
        notes = (
            f"Merge: {len(merged)} уникальных патч(ей) "
            f"из {len(good)} моделей: {', '.join(source_ids)}"
        )
        return ConsensusResult(
            mode=ConsensusMode.MERGE, model_responses=all_resp,
            final_response=best.response_text, final_patches=merged,
            winning_model_id=best.model_id,
            notes=notes,
        )

    async def _judge(
        self, config: ConsensusConfig, system_prompt: str,
        all_resp: list[ModelResponse], good: list[ModelResponse]
    ) -> ConsensusResult:
        """Use a judge model to pick the best response."""
        # Build judge prompt
        judge_prompt_parts = [
            "## ЗАДАЧА СУДЬИ\n",
            "Тебе предоставлены ответы нескольких AI-моделей на одну задачу патчинга кода.\n",
            "Выбери ЛУЧШИЙ ответ по критериям:\n",
            "1. Точность — SEARCH_BLOCK точно совпадает с реальным кодом\n",
            "2. Минимальность — только необходимые изменения\n",
            "3. Правильность — патч решает заявленную проблему\n\n",
        ]

        for i, resp in enumerate(good):
            judge_prompt_parts.append(f"## ОТВЕТ МОДЕЛИ {i+1}: {resp.model_id}\n")
            judge_prompt_parts.append(f"Патчей: {resp.patch_count}\n")
            judge_prompt_parts.append(f"```\n{resp.response_text[:2000]}\n```\n\n")

        judge_prompt_parts.append(
            "\nОтветь в формате:\n"
            "WINNER: <номер модели, 1-N>\n"
            "REASON: <краткое обоснование>\n"
            "Затем воспроизведи только патчи победителя в формате [SEARCH_BLOCK]/[REPLACE_BLOCK]."
        )

        judge_prompt = "".join(judge_prompt_parts)

        # Query judge model
        judge_id = config.judge_model_id or (config.model_ids[0] if config.model_ids else "")
        self._on_event("consensus_judge", {"judge": judge_id})

        judge_resp = await self._query_model(
            judge_id, system_prompt, judge_prompt, config.timeout_per_model * 2
        )

        if not judge_resp.success:
            # Fallback to best_of_n
            result = self._best_of_n(all_resp, good)
            result.notes = f"Судья ({judge_id}) не ответил — откат к best-of-N"
            return result

        # Parse winner number from response
        winner_idx = 0
        for line in judge_resp.response_text.splitlines():
            if line.upper().startswith("WINNER:"):
                try:
                    winner_idx = int(line.split(":")[1].strip()) - 1
                    winner_idx = max(0, min(winner_idx, len(good) - 1))
                except (ValueError, IndexError):
                    pass
                break

        winner = good[winner_idx]
        # Use patches from judge response (it should reproduce them), fallback to winner
        final_patches = judge_resp.patches or winner.patches
        notes = f"Судья {judge_id} выбрал модель #{winner_idx+1}: {winner.model_id}"

        return ConsensusResult(
            mode=ConsensusMode.JUDGE, model_responses=all_resp,
            final_response=judge_resp.response_text,
            final_patches=final_patches,
            winning_model_id=winner.model_id,
            notes=notes,
        )

    # ── Model Query ───────────────────────────────────────────────────────────

    async def _query_model(
        self, model_id: str, system: str, user: str, timeout: int
    ) -> ModelResponse:
        """Query a specific model by ID."""
        import time
        t0 = time.monotonic()
        try:
            provider = await self._mm.get_provider_by_id(model_id)
            if not provider:
                return ModelResponse(
                    model_id=model_id, response_text="", patches=[],
                    elapsed_ms=0,
                    error=f"Модель '{model_id}' не найдена в настройках"
                )

            messages = [
                ChatMessage(role=MessageRole.SYSTEM, content=system),
                ChatMessage(role=MessageRole.USER, content=user),
            ]

            response = await asyncio.wait_for(
                provider.complete(messages),
                timeout=timeout
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            patches = self._patch.parse_patches(response)

            self._on_event("model_responded", {
                "model_id": model_id,
                "patches": len(patches),
                "elapsed_ms": round(elapsed_ms),
            })

            return ModelResponse(
                model_id=model_id,
                response_text=response,
                patches=patches,
                elapsed_ms=elapsed_ms,
            )

        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - t0) * 1000
            return ModelResponse(
                model_id=model_id, response_text="", patches=[],
                elapsed_ms=elapsed_ms,
                error=f"Timeout после {timeout}s"
            )
        except Exception as e:
            elapsed_ms = (time.monotonic() - t0) * 1000
            return ModelResponse(
                model_id=model_id, response_text="", patches=[],
                elapsed_ms=elapsed_ms, error=str(e)
            )

    @staticmethod
    def _normalize_patch_key(patch: PatchBlock) -> str:
        """Normalize a patch for deduplication comparison."""
        import re
        key = patch.search_content.strip()
        # Normalize whitespace but keep structure
        key = re.sub(r'\s+', ' ', key)
        return key[:200].lower()
