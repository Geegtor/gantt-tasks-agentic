"""Convert CommandBatch <-> template JSON using task names (task_ref) for safe replay across plans."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core import scheduler
from app.core.commands import (
    AddTask,
    Clarify,
    Command,
    CommandBatch,
    DeleteTask,
    MoveTask,
    ReassignTask,
    ResizeTask,
    SetDependency,
    SwapTasks,
)
from app.core.models import ProjectPlan

log = logging.getLogger(__name__)


def _name_by_id(plan: ProjectPlan) -> dict[str, str]:
    return {t.id: t.name for t in plan.tasks}


def _id_by_lower_name(plan: ProjectPlan) -> dict[str, str]:
    return {t.name.strip().lower(): t.id for t in plan.tasks}


def _norm_label(s: str) -> str:
    """Same normalization rules as chat user text (lowercase, collapsed spaces)."""
    t = (s or "").strip().lower()
    return re.sub(r"\s+", " ", t)


def collect_template_task_refs(template: dict[str, Any]) -> list[str]:
    """Task / predecessor names that must appear in the user message for safe replay."""
    refs: list[str] = []
    for d in template.get("commands") or []:
        op = d.get("op")
        if op in ("move_task", "resize_task", "delete_task", "reassign_task"):
            refs.append(str(d.get("task_ref") or ""))
        elif op == "swap_tasks":
            refs.append(str(d.get("task_a_ref") or ""))
            refs.append(str(d.get("task_b_ref") or ""))
        elif op == "set_dependency":
            refs.append(str(d.get("task_ref") or ""))
            for x in d.get("predecessor_names") or []:
                refs.append(str(x))
        elif op == "add_task":
            refs.append(str(d.get("name") or ""))
            for x in d.get("predecessor_names") or []:
                refs.append(str(x))
    return [r for r in refs if r.strip()]


def template_grounded_in_user_message(template: dict[str, Any], user_message_norm: str) -> bool:
    """True if every template task name is a substring of the normalized user message.

    Prevents similarity-replay from applying the wrong task (e.g. Frontend vs Backend API)
    when the bag-of-tokens embedding scores two different slot fillings alike.
    """
    u = user_message_norm or ""
    for ref in collect_template_task_refs(template):
        key = _norm_label(ref)
        if not key:
            continue
        if key not in u:
            return False
    return True


def command_batch_to_template(plan: ProjectPlan, batch: CommandBatch) -> dict[str, Any]:
    """Serialize commands with task_ref / predecessor_names instead of ids."""
    names = _name_by_id(plan)
    out_cmds: list[dict[str, Any]] = []
    for c in batch.commands:
        if isinstance(c, Clarify):
            out_cmds.append({"op": "clarify", "question": c.question})
        elif isinstance(c, MoveTask):
            out_cmds.append(
                {"op": "move_task", "task_ref": names.get(c.task_id, c.task_id), "delta_days": c.delta_days}
            )
        elif isinstance(c, ResizeTask):
            out_cmds.append(
                {"op": "resize_task", "task_ref": names.get(c.task_id, c.task_id), "delta_days": c.delta_days}
            )
        elif isinstance(c, SwapTasks):
            out_cmds.append(
                {
                    "op": "swap_tasks",
                    "task_a_ref": names.get(c.task_a_id, c.task_a_id),
                    "task_b_ref": names.get(c.task_b_id, c.task_b_id),
                }
            )
        elif isinstance(c, AddTask):
            pred_names = [names.get(p, p) for p in c.predecessor_ids]
            out_cmds.append(
                {
                    "op": "add_task",
                    "name": c.name,
                    "description": c.description,
                    "assignee": c.assignee,
                    "duration_days": c.duration_days,
                    "predecessor_names": pred_names,
                }
            )
        elif isinstance(c, DeleteTask):
            out_cmds.append({"op": "delete_task", "task_ref": names.get(c.task_id, c.task_id)})
        elif isinstance(c, SetDependency):
            pred_names = [names.get(p, p) for p in c.predecessor_ids]
            out_cmds.append(
                {
                    "op": "set_dependency",
                    "task_ref": names.get(c.task_id, c.task_id),
                    "predecessor_names": pred_names,
                }
            )
        elif isinstance(c, ReassignTask):
            out_cmds.append(
                {
                    "op": "reassign_task",
                    "task_ref": names.get(c.task_id, c.task_id),
                    "new_assignee": c.new_assignee,
                }
            )
        else:
            out_cmds.append({"op": "unknown", "raw": str(c)})
    return {"commands": out_cmds, "summary": batch.summary}


def template_to_command_batch(plan: ProjectPlan, template: dict[str, Any]) -> CommandBatch:
    """Resolve task_ref / predecessor_names to ids; raises SchedulerError if name missing."""
    by_name = _id_by_lower_name(plan)
    cmds: list[Command] = []

    def rid(ref: str) -> str:
        key = ref.strip().lower()
        tid = by_name.get(key)
        if not tid:
            raise scheduler.SchedulerError(f"Unknown task name in template: {ref!r}")
        return tid

    def rids(refs: list[str]) -> list[str]:
        return [rid(r) for r in refs]

    for d in template.get("commands") or []:
        op = d.get("op")
        if op == "clarify":
            cmds.append(Clarify(question=str(d.get("question", ""))))
        elif op == "move_task":
            cmds.append(MoveTask(task_id=rid(str(d["task_ref"])), delta_days=int(d["delta_days"])))
        elif op == "resize_task":
            cmds.append(ResizeTask(task_id=rid(str(d["task_ref"])), delta_days=int(d["delta_days"])))
        elif op == "swap_tasks":
            cmds.append(
                SwapTasks(task_a_id=rid(str(d["task_a_ref"])), task_b_id=rid(str(d["task_b_ref"])))
            )
        elif op == "add_task":
            preds = d.get("predecessor_names") or []
            cmds.append(
                AddTask(
                    name=str(d["name"]),
                    description=str(d.get("description") or ""),
                    assignee=str(d.get("assignee") or ""),
                    duration_days=int(d.get("duration_days") or 1),
                    predecessor_ids=rids([str(x) for x in preds]),
                )
            )
        elif op == "delete_task":
            cmds.append(DeleteTask(task_id=rid(str(d["task_ref"]))))
        elif op == "set_dependency":
            preds = d.get("predecessor_names") or []
            cmds.append(
                SetDependency(task_id=rid(str(d["task_ref"])), predecessor_ids=rids([str(x) for x in preds]))
            )
        elif op == "reassign_task":
            cmds.append(
                ReassignTask(task_id=rid(str(d["task_ref"])), new_assignee=str(d["new_assignee"]))
            )
        elif op == "unknown":
            log.warning("Skipping unknown template op: %s", d)
        else:
            raise scheduler.SchedulerError(f"Unsupported template op: {op!r}")

    summary = str(template.get("summary") or "")
    return CommandBatch(commands=cmds, summary=summary)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def template_json_dumps(t: dict[str, Any]) -> str:
    return json.dumps(t, ensure_ascii=False, separators=(",", ":"))


def template_json_loads(s: str) -> dict[str, Any]:
    return json.loads(s)
