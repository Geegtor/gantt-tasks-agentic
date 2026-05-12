from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re
import time
from typing import Any

from fastapi import HTTPException
import httpx
from pydantic import ValidationError

from app.ai.embeddings import HASH_EMBEDDING_DIM, maybe_embed
from app.ai.injection import detect_injection
from app.ai.llm import get_llm
from app.ai.prompt import build_few_shot_suffix
from app.config import get_settings
from app.core.command_template import (
    command_batch_to_template,
    template_grounded_in_user_message,
    template_to_command_batch,
)
from app.core.commands import Answer, Clarify, CommandBatch, DeleteTask
from app.core.engine import apply_batch
from app.core import scheduler
from app.core.plan_signature import plan_topology_signature
from app.core.scheduler import CycleError, UnknownReferenceError
from app.core.state import session
from app.repositories import chat_repo, exemplar_repo
from app.repositories.exemplar_repo import ExemplarHit
from app.services.plan_service import persist_current_plan

log = logging.getLogger(__name__)


def _task_fingerprint(t: Any) -> tuple:
    return (
        str(t.start_date),
        str(t.end_date),
        t.assignee,
        t.name,
        t.duration_days,
        tuple(sorted(t.predecessor_ids)),
    )


def _op_name(cmd: Any) -> str:
    return getattr(cmd, "op", type(cmd).__name__)


def normalize_user_message(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _safe_error(status_code: int, code: str, detail: str | None = None) -> HTTPException:
    payload: dict[str, str] = {"error": code}
    if detail:
        payload["detail"] = detail
    return HTTPException(status_code, detail=payload)


@dataclass
class ChatSnapshot:
    plan_before: Any
    plan: Any
    history: list[dict[str, str]]
    revision: int
    signature: str
    normalized_message: str


@dataclass
class ComputeOutcome:
    kind: str
    batch: CommandBatch
    summary: str
    clarify: str | None
    non_clarify: list[Any]
    plan_after: Any
    changed: bool
    meta_reason: str
    provenance: str
    query_emb: list[float] | None


async def _snapshot_for_chat(user_message: str) -> ChatSnapshot:
    settings = get_settings()
    norm = normalize_user_message(user_message)
    async with session.lock:
        if session.chat_turns() >= settings.max_chat_turns_per_session:
            raise _safe_error(
                429,
                "chat_turn_limit_reached",
                f"Chat turn limit ({settings.max_chat_turns_per_session}) reached for this session.",
            )
        plan_before = session.plan.model_copy(deep=True)
        plan = session.plan.model_copy(deep=True)
        history = session.get_history()
        revision = session.revision
    return ChatSnapshot(
        plan_before=plan_before,
        plan=plan,
        history=history,
        revision=revision,
        signature=plan_topology_signature(plan),
        normalized_message=norm,
    )


async def _compute_outcome(
    user_message: str, snapshot: ChatSnapshot, settings: Any, llm: Any
) -> ComputeOutcome:
    provenance = "llm"
    plan = snapshot.plan

    injection_warning = detect_injection(user_message)
    if injection_warning:
        log.warning("prompt_injection_guard_triggered user=%r", user_message[:200])
        warning_batch = CommandBatch(
            commands=[Clarify(question=injection_warning)],
            summary=injection_warning,
        )
        return ComputeOutcome(
            kind="clarify",
            batch=warning_batch,
            summary=injection_warning,
            clarify=injection_warning,
            non_clarify=[],
            plan_after=plan,
            changed=False,
            meta_reason="injection_blocked",
            provenance="guard",
            query_emb=None,
        )

    embed_text = f"{snapshot.normalized_message} | {snapshot.signature}"
    query_emb = await maybe_embed(embed_text)
    hits: list[ExemplarHit] = []
    if query_emb is not None:
        hits = await exemplar_repo.search_exemplars(
            query_embedding=query_emb,
            plan_signature=snapshot.signature,
            limit=settings.exemplar_search_limit,
        )

    top_sim = hits[0].similarity if hits else 0.0
    emb_dim = len(query_emb) if query_emb else 0
    replay_sim_thr = (
        settings.replay_similarity_threshold_hash
        if emb_dim == HASH_EMBEDDING_DIM
        else settings.replay_similarity_threshold
    )
    log.info(
        "Exemplar retrieval | plan_sig=%s… | candidates=%d | top_similarity=%.4f | replay_threshold=%.2f | embedding_dims=%d",
        snapshot.signature[:16],
        len(hits),
        top_sim,
        replay_sim_thr,
        emb_dim,
    )

    batch: CommandBatch | None = None
    few_shot = build_few_shot_suffix(
        [{"user_message_norm": h.user_message_norm, "command_template": h.command_template} for h in hits[:3]]
    )

    _exact_hit = next(
        (
            h
            for h in hits
            if h.user_message_norm == snapshot.normalized_message and h.plan_signature == snapshot.signature
        ),
        None,
    )
    _sim_hit = (
        hits[0]
        if (
            query_emb is not None
            and hits
            and hits[0].similarity >= replay_sim_thr
            and hits[0].plan_signature == snapshot.signature
        )
        else None
    )
    _replay_hit = _exact_hit or _sim_hit
    if _replay_hit is _sim_hit and _sim_hit is not None:
        if not template_grounded_in_user_message(_sim_hit.command_template, snapshot.normalized_message):
            log.info(
                "Replay skipped: exemplar id=%s sim=%.4f not grounded in user text",
                _sim_hit.id,
                _sim_hit.similarity,
            )
            _replay_hit = None
    if _replay_hit:
        try:
            batch = template_to_command_batch(plan, _replay_hit.command_template)
            provenance = "replay"
            log.info(
                "Chat replay from exemplar id=%s sim=%.4f exact=%s",
                _replay_hit.id,
                _replay_hit.similarity,
                _replay_hit is _exact_hit,
            )
        except scheduler.SchedulerError as e:
            log.warning("Replay template resolve failed: %s — falling back to LLM", e)
            batch = None

    if batch is None:
        try:
            batch = await llm.generate_command_batch(
                user_message, plan, history=snapshot.history, extra_system_suffix=few_shot
            )
        except (asyncio.TimeoutError, httpx.TimeoutException):
            log.warning("LLM request timed out")
            raise _safe_error(504, "llm_timeout", "LLM did not respond in time.") from None
        except Exception:
            log.exception("LLM generate_command_batch failed")
            raise _safe_error(502, "llm_unavailable") from None

    cmds = list(batch.commands)
    log.info(
        "Chat | user=%r | commands=%d | summary=%r | provenance=%s",
        user_message[:160],
        len(cmds),
        (batch.summary or "")[:200],
        provenance,
    )
    if cmds:
        for i, c in enumerate(cmds, 1):
            log.info("  cmd[%d] %s", i, c.model_dump())

    if not cmds:
        return ComputeOutcome(
            kind="empty",
            batch=batch,
            summary=batch.summary or "Model returned no commands; nothing changed.",
            clarify=None,
            non_clarify=[],
            plan_after=plan,
            changed=False,
            meta_reason="empty_commands",
            provenance=provenance,
            query_emb=query_emb,
        )

    non_clarify = [c for c in cmds if not isinstance(c, (Clarify, Answer))]

    # --- Batch size guard ---
    if len(non_clarify) > settings.max_commands_per_batch:
        log.warning("Batch too large: %d commands (max %d)", len(non_clarify), settings.max_commands_per_batch)
        guard_batch = CommandBatch(
            commands=[Clarify(question=f"Too many operations ({len(non_clarify)} > {settings.max_commands_per_batch}). Please split into smaller requests.")],
            summary=f"Batch too large ({len(non_clarify)} commands).",
        )
        return ComputeOutcome(
            kind="clarify", batch=guard_batch,
            summary=guard_batch.summary, clarify=guard_batch.commands[0].question,
            non_clarify=[], plan_after=plan, changed=False,
            meta_reason="batch_too_large", provenance=provenance, query_emb=query_emb,
        )

    # --- Mass-delete guard ---
    # Triggers only when the number of deletes exceeds MAX_DELETES_PER_BATCH
    # (default 200, configurable via env).  The user can bypass with the
    # confirmation phrase "YES_DELETE_BULK" anywhere in the message.
    delete_cmds = [c for c in non_clarify if isinstance(c, DeleteTask)]
    total_tasks = len(plan.tasks)
    bulk_confirm = "yes_delete_bulk" in snapshot.normalized_message
    if not bulk_confirm and len(delete_cmds) > settings.max_deletes_per_batch:
        log.warning("prompt_injection_guard_triggered mass_delete=%d tasks=%d", len(delete_cmds), total_tasks)
        warn = (
            f"This would delete {len(delete_cmds)} of {total_tasks} tasks "
            f"(limit is {settings.max_deletes_per_batch} per request). "
            "To confirm, repeat your request with the phrase YES_DELETE_BULK."
        )
        guard_batch = CommandBatch(commands=[Clarify(question=warn)], summary=warn)
        return ComputeOutcome(
            kind="clarify", batch=guard_batch,
            summary=warn, clarify=warn,
            non_clarify=[], plan_after=plan, changed=False,
            meta_reason="mass_delete_blocked", provenance=provenance, query_emb=query_emb,
        )

    if not non_clarify:
        c0 = cmds[0]
        if isinstance(c0, Clarify):
            return ComputeOutcome(
                kind="clarify",
                batch=batch,
                summary=batch.summary or c0.question,
                clarify=c0.question,
                non_clarify=[],
                plan_after=plan,
                changed=False,
                meta_reason="clarify_only",
                provenance=provenance,
                query_emb=query_emb,
            )

    # --- Answer-only (read-only query) ---
    answer_cmds = [c for c in cmds if isinstance(c, Answer)]
    if not non_clarify and answer_cmds:
        return ComputeOutcome(
            kind="answer",
            batch=batch,
            summary=answer_cmds[0].text,
            clarify=None,
            non_clarify=[],
            plan_after=plan,
            changed=False,
            meta_reason="answer",
            provenance=provenance,
            query_emb=query_emb,
        )

    cur = plan
    meta_provenance = provenance
    try:
        cur = apply_batch(plan, non_clarify)
    except scheduler.CycleError as e:
        log.warning("Cycle error (no repair): %s", e)
        raise _safe_error(400, "scheduler_invalid", str(e))
    except scheduler.SchedulerError as e:
        if not isinstance(e, UnknownReferenceError):
            raise _safe_error(400, "scheduler_invalid", str(e))
        log.warning("First apply failed: %s — repair retry", e)
        repair_msg = (
            f"{user_message}\n\n"
            f"The following command batch failed when applied to the schedule:\n"
            f"{batch.model_dump_json()}\n\n"
            f"Scheduler error: {e}\n"
            "Return a corrected CommandBatch JSON object only (commands + summary)."
        )
        try:
            batch = await llm.generate_command_batch(
                repair_msg, plan, history=snapshot.history, extra_system_suffix=""
            )
        except (asyncio.TimeoutError, httpx.TimeoutException):
            log.warning("LLM repair request timed out")
            raise _safe_error(504, "llm_timeout", "LLM did not respond in time.") from None
        except Exception:
            log.exception("LLM repair failed")
            raise _safe_error(502, "llm_unavailable") from None

        non_clarify = [c for c in batch.commands if not isinstance(c, Clarify)]
        if not non_clarify:
            raise _safe_error(400, "scheduler_invalid", str(e)) from e
        try:
            cur = apply_batch(plan, non_clarify)
        except (scheduler.SchedulerError, ValidationError) as e2:
            log.warning("Repair apply failed: %s", e2)
            raise _safe_error(400, "scheduler_invalid", str(e2)) from e2
        meta_provenance = "repair"
    except ValidationError as e:
        log.warning("Command produced invalid model data: %s", e)
        raise _safe_error(400, "invalid_command_data")
    except Exception:
        log.exception("Unexpected error applying command")
        raise _safe_error(500, "internal")

    before_fp = {t.id: _task_fingerprint(t) for t in snapshot.plan_before.tasks}
    after_fp = {t.id: _task_fingerprint(t) for t in cur.tasks}
    changed = before_fp != after_fp or len(snapshot.plan_before.tasks) != len(cur.tasks)
    return ComputeOutcome(
        kind="applied",
        batch=batch,
        summary=batch.summary,
        clarify=None,
        non_clarify=non_clarify,
        plan_after=cur,
        changed=changed,
        meta_reason="ok",
        provenance=meta_provenance,
        query_emb=query_emb,
    )


async def _commit_outcome(snapshot: ChatSnapshot, outcome: ComputeOutcome, user_message: str) -> tuple[bool, int]:
    async with session.lock:
        if session.revision != snapshot.revision:
            return False, session.revision
        if outcome.kind == "clarify":
            session.incr_chat_turn()
            if outcome.clarify:
                session.add_history_turn(user=user_message, assistant=outcome.clarify)
        elif outcome.kind == "applied":
            session.incr_chat_turn()
            session.set_plan(outcome.plan_after)
            session.add_history_turn(user=user_message, assistant=outcome.summary or "")
        return True, session.revision


async def run_chat(user_message: str) -> dict[str, Any]:
    settings = get_settings()
    llm = get_llm()
    t0 = time.perf_counter()
    provider = (settings.llm_provider or "").strip().lower()
    last_outcome: ComputeOutcome | None = None
    last_snapshot: ChatSnapshot | None = None

    for attempt in range(2):
        snapshot = await _snapshot_for_chat(user_message)
        outcome = await _compute_outcome(user_message, snapshot, settings, llm)
        committed, rev_after = await _commit_outcome(snapshot, outcome, user_message)
        if not committed:
            log.info(
                "occ_conflict_retry attempt=%d expected_rev=%d actual_rev=%d",
                attempt + 1,
                snapshot.revision,
                rev_after,
            )
            last_outcome = outcome
            last_snapshot = snapshot
            continue

        latency_ms = int((time.perf_counter() - t0) * 1000)
        chat_turn_id = await chat_repo.save_chat_turn(
            user_message=user_message,
            summary=outcome.summary,
            command_batch=outcome.batch.model_dump(mode="json"),
            applied=len(outcome.non_clarify),
            plan_changed=outcome.changed,
            reason=outcome.meta_reason,
            provider=provider,
            llm_latency_ms=latency_ms,
            plan_revision_before=snapshot.revision,
            plan_revision_after=session.revision,
            provenance=outcome.provenance,
        )

        if outcome.kind == "applied":
            await persist_current_plan("chat")
            log.info(
                "Applied %d command(s) | plan_changed=%s | rev=%s | provenance=%s",
                len(outcome.non_clarify),
                outcome.changed,
                session.revision,
                outcome.provenance,
            )
            if (
                chat_turn_id is not None
                and outcome.provenance in ("llm", "repair")
                and len(outcome.non_clarify) > 0
            ):
                tmpl = command_batch_to_template(outcome.plan_after, outcome.batch)
                await exemplar_repo.insert_exemplar(
                    chat_turn_id=chat_turn_id,
                    user_message_norm=snapshot.normalized_message,
                    plan_signature=snapshot.signature,
                    command_template=tmpl,
                    embedding=outcome.query_emb,
                )
            await session.broadcast_plan()
            return {
                "summary": outcome.summary,
                "plan": session.plan.model_dump(mode="json"),
                "revision": session.revision,
                "meta": {
                    "applied": len(outcome.non_clarify),
                    "ops": [_op_name(c) for c in outcome.non_clarify],
                    "plan_changed": outcome.changed,
                    "provenance": outcome.provenance,
                },
            }

        if outcome.kind == "clarify":
            return {
                "summary": outcome.summary,
                "clarify": outcome.clarify,
                "plan": session.plan.model_dump(mode="json"),
                "revision": session.revision,
                "meta": {"applied": 0, "reason": "clarify_only", "provenance": outcome.provenance},
            }

        if outcome.kind == "answer":
            return {
                "summary": outcome.summary,
                "plan": session.plan.model_dump(mode="json"),
                "revision": session.revision,
                "meta": {"applied": 0, "reason": "answer", "provenance": outcome.provenance},
            }

        return {
            "summary": outcome.summary,
            "plan": session.plan.model_dump(mode="json"),
            "revision": session.revision,
            "meta": {"applied": 0, "reason": "empty_commands", "provenance": outcome.provenance},
        }

    log.warning("occ_conflict_giveup after retry")
    if last_outcome is not None and last_snapshot is not None:
        await chat_repo.save_chat_turn(
            user_message=user_message,
            summary="Plan changed concurrently. Please retry.",
            command_batch=last_outcome.batch.model_dump(mode="json"),
            applied=0,
            plan_changed=False,
            reason="occ_conflict",
            provider=provider,
            llm_latency_ms=int((time.perf_counter() - t0) * 1000),
            plan_revision_before=last_snapshot.revision,
            plan_revision_after=session.revision,
            provenance=last_outcome.provenance,
        )
    raise _safe_error(409, "occ_conflict", "Plan changed concurrently. Please retry.")
