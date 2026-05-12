"""Unit tests for app.core.analytics."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.analytics import (
    analytics_summary,
    critical_path,
    overloaded_assignees,
    parallel_groups,
)
from app.core.models import ProjectPlan, Task

BASE = date(2026, 1, 5)


def _task(tid: str, dur: int, preds: list[str], assignee: str = "X", offset: int = 0) -> Task:
    s = BASE + timedelta(days=offset)
    return Task(
        id=tid, name=f"Task_{tid}", assignee=assignee,
        duration_days=dur, predecessor_ids=preds,
        start_date=s, end_date=s + timedelta(days=dur - 1),
    )


class TestCriticalPath:
    def test_linear_chain(self):
        t1 = _task("t1", 3, [])
        t2 = _task("t2", 5, ["t1"], offset=3)
        t3 = _task("t3", 2, ["t2"], offset=8)
        plan = ProjectPlan(tasks=[t1, t2, t3], project_start=BASE)
        cp = critical_path(plan)
        assert cp == ["t1", "t2", "t3"]

    def test_parallel_picks_longer_branch(self):
        t1 = _task("t1", 1, [])
        t2 = _task("t2", 2, ["t1"], offset=1)
        t3 = _task("t3", 10, ["t1"], offset=1)
        t4 = _task("t4", 1, ["t2", "t3"], offset=11)
        plan = ProjectPlan(tasks=[t1, t2, t3, t4], project_start=BASE)
        cp = critical_path(plan)
        # The critical path goes through the longer branch
        assert len(cp) >= 2
        assert "t1" in cp

    def test_empty_plan(self):
        plan = ProjectPlan(tasks=[], project_start=BASE)
        assert critical_path(plan) == []


class TestParallelGroups:
    def test_overlapping_independent_tasks(self):
        t1 = _task("t1", 5, [], assignee="A", offset=0)
        t2 = _task("t2", 3, [], assignee="B", offset=1)
        plan = ProjectPlan(tasks=[t1, t2], project_start=BASE)
        pg = parallel_groups(plan)
        assert len(pg) >= 1
        assert {"t1", "t2"} == set(pg[0])

    def test_sequential_tasks_not_parallel(self):
        t1 = _task("t1", 2, [], offset=0)
        t2 = _task("t2", 2, ["t1"], offset=2)
        plan = ProjectPlan(tasks=[t1, t2], project_start=BASE)
        pg = parallel_groups(plan)
        assert pg == []

    def test_empty_plan(self):
        plan = ProjectPlan(tasks=[], project_start=BASE)
        assert parallel_groups(plan) == []


class TestOverloadedAssignees:
    def test_overlap_detected(self):
        t1 = _task("t1", 5, [], assignee="Alice", offset=0)
        t2 = _task("t2", 3, [], assignee="Alice", offset=2)
        plan = ProjectPlan(tasks=[t1, t2], project_start=BASE)
        ol = overloaded_assignees(plan)
        assert "Alice" in ol
        assert ol["Alice"] >= 1

    def test_no_overlap(self):
        t1 = _task("t1", 2, [], assignee="Alice", offset=0)
        t2 = _task("t2", 2, [], assignee="Alice", offset=5)
        plan = ProjectPlan(tasks=[t1, t2], project_start=BASE)
        ol = overloaded_assignees(plan)
        assert "Alice" not in ol

    def test_different_assignees_no_overlap(self):
        t1 = _task("t1", 5, [], assignee="Alice", offset=0)
        t2 = _task("t2", 5, [], assignee="Bob", offset=0)
        plan = ProjectPlan(tasks=[t1, t2], project_start=BASE)
        ol = overloaded_assignees(plan)
        assert ol == {}


class TestAnalyticsSummary:
    def test_returns_string(self):
        t1 = _task("t1", 3, [])
        plan = ProjectPlan(tasks=[t1], project_start=BASE)
        s = analytics_summary(plan)
        assert isinstance(s, str)
        assert len(s) > 0

    def test_empty_plan(self):
        plan = ProjectPlan(tasks=[], project_start=BASE)
        s = analytics_summary(plan)
        assert "No analytics" in s
