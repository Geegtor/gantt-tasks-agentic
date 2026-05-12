"""MCP server exposing schedule mutations (mount at /mcp in main app)."""

from __future__ import annotations

import json

try:
    from mcp.server.mcpserver import MCPServer as _MCPFactory
except ImportError:  # pragma: no cover - older sdk
    from mcp.server.fastmcp import FastMCP as _MCPFactory  # type: ignore

from app.core.commands import (
    AddTask,
    DeleteTask,
    MoveTask,
    ReassignTask,
    RenameTask,
    SetDependency,
    SwapTasks,
)
from app.core.engine import apply_command
from app.core import scheduler
from app.core.state import session
from app.services.plan_service import persist_current_plan

mcp = _MCPFactory("gantt-ai-planner")


def _ok() -> str:
    return json.dumps({"ok": True})


def _err(error_code: str, message: str) -> str:
    return json.dumps({"ok": False, "error_code": error_code, "message": message})


@mcp.tool()
async def get_plan() -> str:
    """Return the current project plan as JSON."""
    async with session.lock:
        return session.plan.model_dump_json()


@mcp.tool()
async def move_task(task_id: str, delta_days: int) -> str:
    """Shift task start/end by delta_days (integer; negative allowed)."""
    async with session.lock:
        try:
            new_plan = apply_command(session.plan, MoveTask(task_id=task_id, delta_days=delta_days))
        except scheduler.SchedulerError as e:
            return _err("scheduler_invalid", str(e))
        session.set_plan(new_plan)
    await persist_current_plan("mcp")
    await session.broadcast_plan()
    return _ok()


@mcp.tool()
async def swap_tasks(task_a_id: str, task_b_id: str, swap_dependencies: bool = False) -> str:
    """Swap timeline positions of two tasks. Set swap_dependencies=True to also
    swap their predecessor relationships and update all reverse references."""
    async with session.lock:
        try:
            new_plan = apply_command(
                session.plan,
                SwapTasks(task_a_id=task_a_id, task_b_id=task_b_id, swap_dependencies=swap_dependencies),
            )
        except scheduler.SchedulerError as e:
            return _err("scheduler_invalid", str(e))
        session.set_plan(new_plan)
    await persist_current_plan("mcp")
    await session.broadcast_plan()
    return _ok()


@mcp.tool()
async def add_task(
    name: str,
    assignee: str,
    duration_days: int,
    description: str = "",
    predecessor_ids: list[str] | None = None,
) -> str:
    """Add a task. predecessor_ids are existing task ids."""
    preds = predecessor_ids or []
    async with session.lock:
        try:
            new_plan = apply_command(
                session.plan,
                AddTask(
                    name=name,
                    description=description,
                    assignee=assignee,
                    duration_days=duration_days,
                    predecessor_ids=preds,
                ),
            )
        except scheduler.SchedulerError as e:
            return _err("scheduler_invalid", str(e))
        session.set_plan(new_plan)
    await persist_current_plan("mcp")
    await session.broadcast_plan()
    return _ok()


@mcp.tool()
async def delete_task(task_id: str) -> str:
    """Remove a task and clean predecessor links."""
    async with session.lock:
        try:
            new_plan = apply_command(session.plan, DeleteTask(task_id=task_id))
        except scheduler.SchedulerError as e:
            return _err("scheduler_invalid", str(e))
        session.set_plan(new_plan)
    await persist_current_plan("mcp")
    await session.broadcast_plan()
    return _ok()


@mcp.tool()
async def set_dependency(task_id: str, predecessor_ids: list[str]) -> str:
    """Replace all predecessors of task_id."""
    async with session.lock:
        try:
            new_plan = apply_command(
                session.plan,
                SetDependency(task_id=task_id, predecessor_ids=predecessor_ids),
            )
        except scheduler.SchedulerError as e:
            return _err("scheduler_invalid", str(e))
        session.set_plan(new_plan)
    await persist_current_plan("mcp")
    await session.broadcast_plan()
    return _ok()


@mcp.tool()
async def rename_task(task_id: str, new_name: str, new_description: str | None = None) -> str:
    """Rename a task (change its title). Does not affect dates or dependencies."""
    async with session.lock:
        try:
            new_plan = apply_command(
                session.plan,
                RenameTask(task_id=task_id, new_name=new_name, new_description=new_description),
            )
        except scheduler.SchedulerError as e:
            return _err("scheduler_invalid", str(e))
        session.set_plan(new_plan)
    await persist_current_plan("mcp")
    await session.broadcast_plan()
    return _ok()


@mcp.tool()
async def reassign_task(task_id: str, new_assignee: str) -> str:
    """Change assignee for a task."""
    async with session.lock:
        try:
            new_plan = apply_command(
                session.plan,
                ReassignTask(task_id=task_id, new_assignee=new_assignee),
            )
        except scheduler.SchedulerError as e:
            return _err("scheduler_invalid", str(e))
        session.set_plan(new_plan)
    await persist_current_plan("mcp")
    await session.broadcast_plan()
    return _ok()


def streamable_http_asgi():  # type: ignore[no-untyped-def]
    fn = getattr(mcp, "streamable_http_app", None)
    if callable(fn):
        try:
            return fn(json_response=True)
        except TypeError:
            return fn()
    fn = getattr(mcp, "sse_app", None)
    if callable(fn):
        try:
            return fn()
        except TypeError:
            return fn()
    raise RuntimeError("MCP SDK: no streamable_http_app or sse_app on server instance")
