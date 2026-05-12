"""Shared fixtures for the Gantt backend test-suite."""
from __future__ import annotations

import os
from datetime import date, timedelta

# Default: no Postgres for unit tests. Set PYTEST_USE_DB=1 to use DATABASE_URL from the environment.
if os.getenv("PYTEST_USE_DB") != "1":
    os.environ["DATABASE_URL"] = ""

import pytest
from fastapi.testclient import TestClient

from app.core.models import ProjectPlan, Task
from app.core.seed import seed_plan
from app.core.state import session
from app.main import app

# ---------------------------------------------------------------------------
# Deterministic base date so every test is date-independent.
# ---------------------------------------------------------------------------
BASE = date(2026, 1, 5)  # Monday


@pytest.fixture()
def base_date() -> date:
    return BASE


@pytest.fixture()
def simple_plan() -> ProjectPlan:
    """Minimal linear plan: t1 → t2 → t3 (3 tasks, clean IDs)."""
    t1 = Task(
        id="t1",
        name="Discovery",
        assignee="Alice",
        duration_days=3,
        predecessor_ids=[],
        start_date=BASE,
        end_date=BASE + timedelta(days=2),
    )
    t2 = Task(
        id="t2",
        name="Design",
        assignee="Bob",
        duration_days=4,
        predecessor_ids=["t1"],
        start_date=BASE + timedelta(days=3),
        end_date=BASE + timedelta(days=6),
    )
    t3 = Task(
        id="t3",
        name="QA",
        assignee="Carol",
        duration_days=2,
        predecessor_ids=["t2"],
        start_date=BASE + timedelta(days=7),
        end_date=BASE + timedelta(days=8),
    )
    return ProjectPlan(tasks=[t1, t2, t3], project_start=BASE)


@pytest.fixture()
def parallel_plan() -> ProjectPlan:
    """Diamond plan:  t1 → {t2, t3} → t4."""
    t1 = Task(
        id="t1",
        name="Start",
        assignee="Alice",
        duration_days=2,
        predecessor_ids=[],
        start_date=BASE,
        end_date=BASE + timedelta(days=1),
    )
    t2 = Task(
        id="t2",
        name="Branch A",
        assignee="Bob",
        duration_days=3,
        predecessor_ids=["t1"],
        start_date=BASE + timedelta(days=2),
        end_date=BASE + timedelta(days=4),
    )
    t3 = Task(
        id="t3",
        name="Branch B",
        assignee="Carol",
        duration_days=5,
        predecessor_ids=["t1"],
        start_date=BASE + timedelta(days=2),
        end_date=BASE + timedelta(days=6),
    )
    t4 = Task(
        id="t4",
        name="Merge",
        assignee="Dan",
        duration_days=2,
        predecessor_ids=["t2", "t3"],
        start_date=BASE + timedelta(days=7),
        end_date=BASE + timedelta(days=8),
    )
    return ProjectPlan(tasks=[t1, t2, t3, t4], project_start=BASE)


@pytest.fixture()
def api_client() -> TestClient:
    """FastAPI TestClient with session reset before each test (lifespan runs)."""
    session.reset_demo()
    with TestClient(app) as client:
        yield client
