from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class Task(BaseModel):
    id: str
    name: str
    description: str = ""
    assignee: str
    duration_days: int = Field(ge=1)
    predecessor_ids: list[str] = Field(default_factory=list)
    start_date: date
    end_date: date


class ProjectPlan(BaseModel):
    tasks: list[Task] = Field(default_factory=list)
    project_start: date | None = None

    def task_by_id(self) -> dict[str, Task]:
        return {t.id: t for t in self.tasks}

    def task_by_name(self) -> dict[str, Task]:
        out: dict[str, Task] = {}
        for t in self.tasks:
            key = t.name.strip().lower()
            if key not in out:
                out[key] = t
        return out
