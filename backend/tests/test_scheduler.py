"""Unit tests for app.core.scheduler (pure graph functions)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.models import ProjectPlan, Task
from app.core import scheduler


BASE = date(2026, 1, 5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task(tid: str, duration: int, preds: list[str],
          start_offset: int = 0) -> Task:
    s = BASE + timedelta(days=start_offset)
    return Task(
        id=tid, name=tid, assignee="X",
        duration_days=duration, predecessor_ids=preds,
        start_date=s, end_date=s + timedelta(days=duration - 1),
    )


# ---------------------------------------------------------------------------
# validate_references
# ---------------------------------------------------------------------------

class TestValidateReferences:
    def test_all_known_ids_pass(self, simple_plan):
        scheduler.validate_references(simple_plan, ["t1", "t2"])

    def test_unknown_id_raises(self, simple_plan):
        with pytest.raises(scheduler.SchedulerError, match="Unknown task id"):
            scheduler.validate_references(simple_plan, ["t1", "t_ghost"])

    def test_empty_list_passes(self, simple_plan):
        scheduler.validate_references(simple_plan, [])


# ---------------------------------------------------------------------------
# assert_acyclic
# ---------------------------------------------------------------------------

class TestAssertAcyclic:
    def test_linear_chain_is_acyclic(self, simple_plan):
        scheduler.assert_acyclic(simple_plan)

    def test_direct_self_loop_raises(self):
        t1 = _task("t1", 2, ["t1"])
        plan = ProjectPlan(tasks=[t1], project_start=BASE)
        with pytest.raises(scheduler.SchedulerError, match="Circular"):
            scheduler.assert_acyclic(plan)

    def test_two_task_cycle_raises(self):
        t1 = _task("t1", 2, ["t2"])
        t2 = _task("t2", 2, ["t1"])
        plan = ProjectPlan(tasks=[t1, t2], project_start=BASE)
        with pytest.raises(scheduler.SchedulerError, match="Circular"):
            scheduler.assert_acyclic(plan)

    def test_longer_cycle_raises(self):
        t1 = _task("t1", 1, ["t3"])
        t2 = _task("t2", 1, ["t1"])
        t3 = _task("t3", 1, ["t2"])
        plan = ProjectPlan(tasks=[t1, t2, t3], project_start=BASE)
        with pytest.raises(scheduler.SchedulerError, match="Circular"):
            scheduler.assert_acyclic(plan)

    def test_diamond_is_acyclic(self, parallel_plan):
        scheduler.assert_acyclic(parallel_plan)


# ---------------------------------------------------------------------------
# topological_order
# ---------------------------------------------------------------------------

class TestTopologicalOrder:
    def test_linear_order(self, simple_plan):
        order = scheduler.topological_order(simple_plan)
        assert order.index("t1") < order.index("t2")
        assert order.index("t2") < order.index("t3")

    def test_parallel_predecessors_before_merge(self, parallel_plan):
        order = scheduler.topological_order(parallel_plan)
        assert order.index("t1") < order.index("t2")
        assert order.index("t1") < order.index("t3")
        assert order.index("t2") < order.index("t4")
        assert order.index("t3") < order.index("t4")


# ---------------------------------------------------------------------------
# full_recompute
# ---------------------------------------------------------------------------

class TestFullRecompute:
    def test_linear_chain_dates(self):
        """t1(3d) → t2(4d) → t3(2d)  starting from BASE."""
        t1 = _task("t1", 3, [])
        t2 = _task("t2", 4, ["t1"])
        t3 = _task("t3", 2, ["t2"])
        plan = ProjectPlan(tasks=[t1, t2, t3], project_start=BASE)
        scheduler.full_recompute(plan)

        assert plan.tasks[0].start_date == BASE
        assert plan.tasks[0].end_date == BASE + timedelta(days=2)
        assert plan.tasks[1].start_date == BASE + timedelta(days=3)
        assert plan.tasks[1].end_date == BASE + timedelta(days=6)
        assert plan.tasks[2].start_date == BASE + timedelta(days=7)
        assert plan.tasks[2].end_date == BASE + timedelta(days=8)

    def test_parallel_merge_waits_for_longer_branch(self):
        """t1(2) → t2(3) and t1 → t3(5); t4 waits for t3."""
        t1 = _task("t1", 2, [])
        t2 = _task("t2", 3, ["t1"])
        t3 = _task("t3", 5, ["t1"])
        t4 = _task("t4", 2, ["t2", "t3"])
        plan = ProjectPlan(tasks=[t1, t2, t3, t4], project_start=BASE)
        scheduler.full_recompute(plan)

        id_map = plan.task_by_id()
        # t3 ends at BASE+1+5=BASE+6 (end_date = start+duration-1 = BASE+2+4 = BASE+6)
        t3_end = id_map["t3"].end_date
        assert id_map["t4"].start_date == t3_end + timedelta(days=1)

    def test_no_predecessors_always_starts_at_project_start(self):
        t1 = _task("t1", 2, [])
        t2 = _task("t2", 3, [])  # also no predecessors
        plan = ProjectPlan(tasks=[t1, t2], project_start=BASE)
        scheduler.full_recompute(plan)
        assert plan.tasks[0].start_date == BASE
        assert plan.tasks[1].start_date == BASE

    def test_empty_plan_is_noop(self):
        plan = ProjectPlan(tasks=[], project_start=BASE)
        scheduler.full_recompute(plan)  # should not raise

    def test_infers_project_start_when_none(self):
        t1 = _task("t1", 3, [], start_offset=5)
        plan = ProjectPlan(tasks=[t1], project_start=None)
        scheduler.full_recompute(plan)
        assert plan.project_start == BASE + timedelta(days=5)


# ---------------------------------------------------------------------------
# propagate_constraints
# ---------------------------------------------------------------------------

class TestPropagateConstraints:
    def test_no_violation_leaves_dates_unchanged(self, simple_plan):
        before = {t.id: (t.start_date, t.end_date) for t in simple_plan.tasks}
        scheduler.propagate_constraints(simple_plan)
        after = {t.id: (t.start_date, t.end_date) for t in simple_plan.tasks}
        assert before == after

    def test_pushes_task_forward_when_pred_end_violated(self):
        """Move t1 forward so t2 would start before t1 ends."""
        t1 = _task("t1", 5, [], start_offset=0)    # ends BASE+4
        t2 = _task("t2", 3, ["t1"], start_offset=2)  # starts BASE+2 — violation
        plan = ProjectPlan(tasks=[t1, t2], project_start=BASE)
        scheduler.propagate_constraints(plan)
        id_map = plan.task_by_id()
        assert id_map["t2"].start_date == id_map["t1"].end_date + timedelta(days=1)

    def test_independent_task_not_shifted(self):
        """A task with no predecessors must never be moved by propagate."""
        t1 = _task("t1", 3, [], start_offset=10)  # deliberately later
        t2 = _task("t2", 2, [], start_offset=0)   # independent
        plan = ProjectPlan(tasks=[t1, t2], project_start=BASE)
        scheduler.propagate_constraints(plan)
        id_map = plan.task_by_id()
        assert id_map["t2"].start_date == BASE  # unchanged

    def test_cascade_propagation(self):
        """t1 → t2 → t3: pushing t1 forward should cascade to t3."""
        t1 = _task("t1", 3, [], start_offset=0)  # BASE … BASE+2
        t2 = _task("t2", 3, ["t1"], start_offset=1)  # violation: starts BASE+1
        t3 = _task("t3", 2, ["t2"], start_offset=2)  # will also be pushed
        plan = ProjectPlan(tasks=[t1, t2, t3], project_start=BASE)
        scheduler.propagate_constraints(plan)
        id_map = plan.task_by_id()
        t2_start = id_map["t2"].start_date
        assert t2_start == BASE + timedelta(days=3)
        assert id_map["t3"].start_date == id_map["t2"].end_date + timedelta(days=1)
