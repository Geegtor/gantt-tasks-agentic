from __future__ import annotations

from datetime import date, timedelta

from app.core.models import ProjectPlan, Task


def seed_plan() -> ProjectPlan:
    """Deterministic demo plan (IDs stable for LLM + tests)."""
    base = date.today()
    tasks = [
        Task(
            id="t1",
            name="Discovery",
            description="Gather requirements",
            assignee="Alice",
            duration_days=3,
            predecessor_ids=[],
            start_date=base,
            end_date=base + timedelta(days=2),
        ),
        Task(
            id="t2",
            name="Design",
            description="UX and architecture",
            assignee="Bob",
            duration_days=4,
            predecessor_ids=["t1"],
            start_date=base + timedelta(days=3),
            end_date=base + timedelta(days=6),
        ),
        Task(
            id="t3",
            name="Backend API",
            description="FastAPI services",
            assignee="Carol",
            duration_days=5,
            predecessor_ids=["t2"],
            start_date=base + timedelta(days=7),
            end_date=base + timedelta(days=11),
        ),
        Task(
            id="t4",
            name="Frontend",
            description="React Gantt UI",
            assignee="Dan",
            duration_days=5,
            predecessor_ids=["t2"],
            start_date=base + timedelta(days=7),
            end_date=base + timedelta(days=11),
        ),
        Task(
            id="t5",
            name="Integration",
            description="Wire API + UI",
            assignee="Eve",
            duration_days=3,
            predecessor_ids=["t3", "t4"],
            start_date=base + timedelta(days=12),
            end_date=base + timedelta(days=14),
        ),
        Task(
            id="t6",
            name="QA",
            description="Test pass",
            assignee="Frank",
            duration_days=2,
            predecessor_ids=["t5"],
            start_date=base + timedelta(days=15),
            end_date=base + timedelta(days=16),
        ),
    ]
    return ProjectPlan(tasks=tasks, project_start=base)
