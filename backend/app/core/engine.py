from __future__ import annotations

import re
from datetime import timedelta

from app.core.commands import (
    AddTask,
    Answer,
    Clarify,
    Command,
    DeleteTask,
    MoveTask,
    ReassignTask,
    RenameTask,
    ResizeTask,
    SetDependency,
    SwapTasks,
)
from app.core.models import ProjectPlan, Task
from app.core import scheduler


def apply_command(plan: ProjectPlan, cmd: Command) -> ProjectPlan:
    """Return a new plan with command applied (immutable-ish: deep copy tasks)."""
    if isinstance(cmd, Clarify):
        return plan.model_copy(deep=True)

    if isinstance(cmd, Answer):
        return plan.model_copy(deep=True)

    new_tasks = [t.model_copy(deep=True) for t in plan.tasks]
    new_plan = ProjectPlan(tasks=new_tasks, project_start=plan.project_start)

    if isinstance(cmd, MoveTask):
        scheduler.validate_references(new_plan, [cmd.task_id])
        t = new_plan.task_by_id()[cmd.task_id]
        t.start_date += timedelta(days=cmd.delta_days)
        t.end_date += timedelta(days=cmd.delta_days)
        scheduler.propagate_constraints(new_plan)
        return new_plan

    if isinstance(cmd, ResizeTask):
        scheduler.validate_references(new_plan, [cmd.task_id])
        t = new_plan.task_by_id()[cmd.task_id]
        new_duration = max(1, t.duration_days + cmd.delta_days)
        t.duration_days = new_duration
        t.end_date = t.start_date + timedelta(days=new_duration - 1)
        scheduler.propagate_constraints(new_plan)
        return new_plan

    if isinstance(cmd, SwapTasks):
        scheduler.validate_references(new_plan, [cmd.task_a_id, cmd.task_b_id])
        a = new_plan.task_by_id()[cmd.task_a_id]
        b = new_plan.task_by_id()[cmd.task_b_id]

        a.start_date, b.start_date = b.start_date, a.start_date
        a.end_date = a.start_date + timedelta(days=a.duration_days - 1)
        b.end_date = b.start_date + timedelta(days=b.duration_days - 1)

        if cmd.swap_dependencies:
            aid, bid = cmd.task_a_id, cmd.task_b_id
            # 1) Swap their own predecessor lists
            a.predecessor_ids, b.predecessor_ids = b.predecessor_ids, a.predecessor_ids
            # 2) Remove cross-references (A depending on B or vice versa → cycle)
            a.predecessor_ids = [p for p in a.predecessor_ids if p not in (aid, bid)]
            b.predecessor_ids = [p for p in b.predecessor_ids if p not in (aid, bid)]
            # 3) Update all other tasks: references TO A become B, and vice versa
            for t in new_plan.tasks:
                if t.id in (aid, bid):
                    continue
                t.predecessor_ids = [
                    bid if p == aid else aid if p == bid else p
                    for p in t.predecessor_ids
                ]
            scheduler.assert_acyclic(new_plan)
            scheduler.full_recompute(new_plan)
        else:
            scheduler.assert_acyclic(new_plan)

        return new_plan

    if isinstance(cmd, AddTask):
        scheduler.validate_references(new_plan, cmd.predecessor_ids)
        # Sequential IDs (t7, t8, …) instead of UUIDs so the LLM can
        # predict and reference freshly-created tasks in follow-up turns.
        existing_nums = [
            int(t.id[1:])
            for t in new_plan.tasks
            if t.id.startswith("t") and t.id[1:].isdigit()
        ]
        nid = f"t{max(existing_nums, default=0) + 1}"
        from app.config import get_settings
        _settings = get_settings()
        if len(new_plan.tasks) >= _settings.max_tasks_total:
            raise scheduler.SchedulerError(
                f"Task limit reached ({_settings.max_tasks_total}). Delete some tasks first."
            )
        from datetime import date

        dates = [t.start_date for t in new_plan.tasks]
        placeholder_start = new_plan.project_start or (min(dates) if dates else date.today())
        new_plan.tasks.append(
            Task(
                id=nid,
                name=cmd.name,
                description=cmd.description,
                assignee=cmd.assignee,
                duration_days=cmd.duration_days,
                predecessor_ids=list(cmd.predecessor_ids),
                start_date=placeholder_start,
                end_date=placeholder_start + timedelta(days=max(0, cmd.duration_days - 1)),
            )
        )
        scheduler.full_recompute(new_plan)
        return new_plan

    if isinstance(cmd, DeleteTask):
        scheduler.validate_references(new_plan, [cmd.task_id])
        new_plan.tasks = [t for t in new_plan.tasks if t.id != cmd.task_id]
        for t in new_plan.tasks:
            t.predecessor_ids = [p for p in t.predecessor_ids if p != cmd.task_id]
        if new_plan.tasks:
            scheduler.full_recompute(new_plan)
        return new_plan

    if isinstance(cmd, SetDependency):
        scheduler.validate_references(new_plan, [cmd.task_id, *cmd.predecessor_ids])
        t = new_plan.task_by_id()[cmd.task_id]
        if cmd.task_id in cmd.predecessor_ids:
            raise scheduler.CycleError("Task cannot depend on itself")
        t.predecessor_ids = list(dict.fromkeys(cmd.predecessor_ids))  # dedupe, stable
        scheduler.assert_acyclic(new_plan)
        scheduler.full_recompute(new_plan)
        return new_plan

    if isinstance(cmd, RenameTask):
        scheduler.validate_references(new_plan, [cmd.task_id])
        t = new_plan.task_by_id()[cmd.task_id]
        t.name = cmd.new_name.strip()
        if cmd.new_description is not None:
            t.description = cmd.new_description
        return new_plan

    if isinstance(cmd, ReassignTask):
        scheduler.validate_references(new_plan, [cmd.task_id])
        t = new_plan.task_by_id()[cmd.task_id]
        t.assignee = cmd.new_assignee
        return new_plan

    raise TypeError(f"Unsupported command: {type(cmd)}")


def _apply_set_dep_group(plan: ProjectPlan, cmds: list[SetDependency]) -> ProjectPlan:
    """Apply a group of SetDependency commands atomically.

    Updating a whole dependency chain in one batch creates transient cycles in
    intermediate states (e.g. reversing t1→t2→t3 requires setting t1→[t2]
    before t2→[t3] is cleared, which looks like a cycle to a per-command
    check).  We therefore validate references and self-loops per command but
    defer the single acyclicity check and full_recompute until all predecessor
    lists have been updated.
    """
    new_tasks = [t.model_copy(deep=True) for t in plan.tasks]
    new_plan = ProjectPlan(tasks=new_tasks, project_start=plan.project_start)
    id_map = new_plan.task_by_id()

    for cmd in cmds:
        scheduler.validate_references(new_plan, [cmd.task_id, *cmd.predecessor_ids])
        if cmd.task_id in cmd.predecessor_ids:
            raise scheduler.CycleError("Task cannot depend on itself")
        id_map[cmd.task_id].predecessor_ids = list(dict.fromkeys(cmd.predecessor_ids))

    scheduler.assert_acyclic(new_plan)
    scheduler.full_recompute(new_plan)
    return new_plan


def apply_batch(plan: ProjectPlan, commands: list[Command]) -> ProjectPlan:
    cur = plan
    i = 0
    while i < len(commands):
        c = commands[i]
        if isinstance(c, Clarify):
            i += 1
            continue

        # Collect runs of consecutive SetDependency commands so they are applied
        # atomically (see _apply_set_dep_group for the rationale).
        if isinstance(c, SetDependency):
            run: list[SetDependency] = []
            while i < len(commands) and isinstance(commands[i], SetDependency):
                run.append(commands[i])  # type: ignore[arg-type]
                i += 1
            cur = _apply_set_dep_group(cur, run)
        else:
            cur = apply_command(cur, c)
            i += 1

    return cur


def plan_for_prompt(plan: ProjectPlan, max_tasks: int) -> str:
    tasks = plan.tasks[:max_tasks]
    lines = []
    for t in tasks:
        lines.append(
            {
                "id": t.id,
                "name": t.name,
                "assignee": t.assignee,
                "duration_days": t.duration_days,
                "predecessor_ids": t.predecessor_ids,
                "start_date": str(t.start_date),
                "end_date": str(t.end_date),
            }
        )
    import json

    return json.dumps({"tasks": lines}, ensure_ascii=False, indent=2)


# --- Mock LLM pattern matching -------------------------------------------------

_SWAP_RE = re.compile(
    r"(?:swap|поменяй\s+местами|обменяй)\s+(?:tasks?\s+)?['\"]?([^'\"]+?)['\"]?\s+(?:and|и|with)\s+['\"]?([^'\"]+?)['\"]?",
    re.I,
)
_MOVE_RE = re.compile(
    r"(?:move|перенеси|сдвинь).{0,80}?['\"]?([^'\"]+?)['\"]?.{0,40}?(\d+)\s*(?:days?|дн)",
    re.I,
)
_EXTEND_RE = re.compile(
    r"(?:extend|увелич|увеличь|добавь).{0,80}?['\"]?([^'\"]+?)['\"]?.{0,40}?(\d+)\s*(?:days?|дн)",
    re.I,
)


def mock_command_batch(user_message: str, plan: ProjectPlan) -> tuple[list[Command], str]:
    """Cheap deterministic path for demos without API keys."""
    msg = user_message.strip()
    by_name = plan.task_by_name()

    m = _SWAP_RE.search(msg)
    if m:
        a, b = m.group(1).strip().lower(), m.group(2).strip().lower()
        ta = by_name.get(a) or by_name.get(a.split()[0] if a else "")
        tb = by_name.get(b) or by_name.get(b.split()[0] if b else "")
        if ta and tb:
            return [
                SwapTasks(task_a_id=ta.id, task_b_id=tb.id),
            ], f"Swapped schedule positions for {ta.name!r} and {tb.name!r}."

    m2 = _MOVE_RE.search(msg)
    if m2:
        name = m2.group(1).strip().lower()
        days = int(m2.group(2))
        if "later" in msg.lower() or "позже" in msg.lower() or "назад" not in msg.lower():
            delta = days
        elif "earlier" in msg.lower() or "раньше" in msg.lower():
            delta = -days
        else:
            delta = days
        t = by_name.get(name)
        if t:
            return [MoveTask(task_id=t.id, delta_days=delta)], f"Moved {t.name!r} by {delta} day(s)."

    m3 = _EXTEND_RE.search(msg)
    if m3:
        name = m3.group(1).strip().lower()
        days = int(m3.group(2))
        t = by_name.get(name)
        if t:
            return [ResizeTask(task_id=t.id, delta_days=days)], f"Extended {t.name!r} by {days} day(s)."

    return (
        [Clarify(question="Try: 'Swap Design and Backend API' or 'Move QA 2 days later'.")],
        "I need a clearer instruction (mock mode).",
    )
