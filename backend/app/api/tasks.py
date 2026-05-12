from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.core import excel, scheduler
from app.core.state import session
from app.services.plan_service import persist_current_plan

router = APIRouter(tags=["tasks"])
log = logging.getLogger(__name__)
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _safe_error(status_code: int, code: str, detail: str | None = None) -> HTTPException:
    payload: dict[str, str] = {"error": code}
    if detail:
        payload["detail"] = detail
    return HTTPException(status_code, detail=payload)


@router.get("/tasks")
async def get_tasks():
    return {"plan": session.plan.model_dump(mode="json"), "revision": session.revision}


class TaskCreate(BaseModel):
    name: str
    description: str = ""
    assignee: str = ""
    duration_days: int = 1
    start_date: Optional[date] = None
    predecessor_ids: list[str] = []


class TaskPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    assignee: Optional[str] = None
    duration_days: Optional[int] = None
    start_date: Optional[date] = None
    predecessor_ids: Optional[list[str]] = None


@router.patch("/tasks/{task_id}")
async def patch_task(task_id: str, body: TaskPatch):
    """Manual task edit from the UI (drag bar, edit modal)."""
    async with session.lock:
        plan = session.plan.model_copy(deep=True)
        id_map = plan.task_by_id()
        if task_id not in id_map:
            raise _safe_error(404, "task_not_found", f"Task {task_id!r} not found")
        t = id_map[task_id]

        if body.name is not None:
            t.name = body.name.strip()
        if body.description is not None:
            t.description = body.description
        if body.assignee is not None:
            t.assignee = body.assignee.strip()
        if body.duration_days is not None:
            if body.duration_days < 1:
                raise _safe_error(400, "invalid_request", "duration_days must be >= 1")
            t.duration_days = body.duration_days
            t.end_date = t.start_date + timedelta(days=t.duration_days - 1)
        if body.predecessor_ids is not None:
            other_ids = [p for p in body.predecessor_ids if p != task_id]
            if len(other_ids) < len(body.predecessor_ids):
                raise _safe_error(400, "scheduler_invalid", "Task cannot depend on itself")
            try:
                scheduler.validate_references(plan, other_ids)
            except scheduler.SchedulerError as e:
                raise _safe_error(400, "scheduler_invalid", str(e)) from e
            t.predecessor_ids = list(dict.fromkeys(other_ids))
        if body.start_date is not None:
            t.start_date = body.start_date
            t.end_date = t.start_date + timedelta(days=t.duration_days - 1)

        try:
            scheduler.assert_acyclic(plan)
            scheduler.propagate_constraints(plan)
        except scheduler.SchedulerError as e:
            raise _safe_error(400, "scheduler_invalid", str(e)) from e

        session.set_plan(plan)
        log.info("Manual patch task_id=%s fields=%s", task_id, body.model_dump(exclude_none=True))

    await session.broadcast_plan()
    return {"plan": session.plan.model_dump(mode="json"), "revision": session.revision}


@router.post("/tasks")
async def add_task(body: TaskCreate):
    """Add a new task from the UI."""
    from app.config import get_settings

    async with session.lock:
        plan = session.plan.model_copy(deep=True)
        settings = get_settings()
        if len(plan.tasks) >= settings.max_tasks_total:
            raise _safe_error(
                400, "task_limit_reached",
                f"Maximum {settings.max_tasks_total} tasks allowed",
            )
        existing_ids = {t.id for t in plan.tasks}
        idx = len(plan.tasks) + 1
        while f"t{idx}" in existing_ids:
            idx += 1
        new_id = f"t{idx}"

        start = body.start_date or (plan.tasks[-1].end_date + timedelta(days=1) if plan.tasks else date.today())
        end = start + timedelta(days=max(1, body.duration_days) - 1)

        from app.core.models import Task as TaskModel
        new_task = TaskModel(
            id=new_id,
            name=body.name.strip(),
            description=body.description,
            assignee=body.assignee.strip(),
            duration_days=max(1, body.duration_days),
            predecessor_ids=body.predecessor_ids,
            start_date=start,
            end_date=end,
        )
        plan.tasks.append(new_task)

        if body.predecessor_ids:
            try:
                scheduler.validate_references(plan, body.predecessor_ids)
                scheduler.assert_acyclic(plan)
                scheduler.propagate_constraints(plan)
            except scheduler.SchedulerError as e:
                raise _safe_error(400, "scheduler_invalid", str(e)) from e

        session.set_plan(plan)
        log.info("Added task id=%s name=%r", new_id, body.name)

    await persist_current_plan("add_task")
    await session.broadcast_plan()
    return {"plan": session.plan.model_dump(mode="json"), "revision": session.revision}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a task from the UI."""
    async with session.lock:
        plan = session.plan.model_copy(deep=True)
        id_map = plan.task_by_id()
        if task_id not in id_map:
            raise _safe_error(404, "task_not_found", f"Task {task_id!r} not found")

        plan.tasks = [t for t in plan.tasks if t.id != task_id]
        for t in plan.tasks:
            if task_id in t.predecessor_ids:
                t.predecessor_ids = [p for p in t.predecessor_ids if p != task_id]

        try:
            scheduler.propagate_constraints(plan)
        except scheduler.SchedulerError as e:
            raise _safe_error(400, "scheduler_invalid", str(e)) from e

        session.set_plan(plan)
        log.info("Deleted task id=%s", task_id)

    await persist_current_plan("delete_task")
    await session.broadcast_plan()
    return {"plan": session.plan.model_dump(mode="json"), "revision": session.revision}


@router.post("/upload")
async def upload_excel(file: UploadFile = File(...)):
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    if not filename.endswith(".xlsx"):
        raise _safe_error(
            400,
            "unsupported_format",
            "Use .xlsx (legacy .xls not supported)",
        )
    if content_type and content_type not in {
        XLSX_MIME,
        "application/octet-stream",
        "application/vnd.ms-excel",
    }:
        raise _safe_error(
            400,
            "unsupported_format",
            "Upload a valid .xlsx file",
        )
    data = await file.read()
    try:
        plan = excel.parse_excel_bytes(data)
    except ValueError as e:
        raise _safe_error(400, "invalid_excel", str(e)) from e
    async with session.lock:
        session.set_plan(plan)
    await persist_current_plan("upload")
    await session.broadcast_plan()
    return {"plan": session.plan.model_dump(mode="json"), "revision": session.revision}


@router.post("/reset")
async def reset_demo():
    """Reset session to the seed plan (useful for tests and demo restarts)."""
    async with session.lock:
        session.reset_demo()
    await persist_current_plan("seed")
    await session.broadcast_plan()
    return {"plan": session.plan.model_dump(mode="json"), "revision": session.revision}


@router.get("/export")
async def export_excel():
    blob = excel.plan_to_excel_bytes(session.plan)
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="plan.xlsx"'},
    )
