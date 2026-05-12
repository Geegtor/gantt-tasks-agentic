"""Unit tests for app.core.engine (apply_command / apply_batch)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.core import scheduler
from app.core.models import ProjectPlan, Task
from app.core.commands import (
    AddTask,
    Answer,
    Clarify,
    DeleteTask,
    MoveTask,
    ReassignTask,
    RenameTask,
    ResizeTask,
    SetDependency,
    SwapTasks,
)
from app.core.engine import apply_batch, apply_command


# ===========================================================================
# MoveTask
# ===========================================================================

class TestMoveTask:
    def test_shift_forward(self, simple_plan):
        cmd = MoveTask(task_id="t2", delta_days=3)
        new_plan = apply_command(simple_plan, cmd)
        t2 = new_plan.task_by_id()["t2"]
        orig = simple_plan.task_by_id()["t2"]
        assert t2.start_date == orig.start_date + timedelta(days=3)
        assert t2.end_date == orig.end_date + timedelta(days=3)

    def test_shift_backward(self, simple_plan):
        """Moving t2 backward may violate t1→t2 constraint; propagate pushes it back."""
        cmd = MoveTask(task_id="t1", delta_days=-2)
        new_plan = apply_command(simple_plan, cmd)
        t1 = new_plan.task_by_id()["t1"]
        orig = simple_plan.task_by_id()["t1"]
        assert t1.start_date == orig.start_date + timedelta(days=-2)

    def test_propagates_to_successor(self, simple_plan):
        """Moving t1 forward must push t2 and t3 via propagate_constraints."""
        cmd = MoveTask(task_id="t1", delta_days=5)
        new_plan = apply_command(simple_plan, cmd)
        id_map = new_plan.task_by_id()
        assert id_map["t2"].start_date >= id_map["t1"].end_date + timedelta(days=1)
        assert id_map["t3"].start_date >= id_map["t2"].end_date + timedelta(days=1)

    def test_unknown_task_raises(self, simple_plan):
        with pytest.raises(scheduler.SchedulerError, match="Unknown task id"):
            apply_command(simple_plan, MoveTask(task_id="t_ghost", delta_days=1))

    def test_plan_is_immutable(self, simple_plan):
        orig_start = simple_plan.task_by_id()["t1"].start_date
        apply_command(simple_plan, MoveTask(task_id="t1", delta_days=2))
        assert simple_plan.task_by_id()["t1"].start_date == orig_start


# ===========================================================================
# ResizeTask
# ===========================================================================


class TestResizeTask:
    def test_extend_duration(self, simple_plan):
        orig = simple_plan.task_by_id()["t2"]
        cmd = ResizeTask(task_id="t2", delta_days=3)
        new_plan = apply_command(simple_plan, cmd)
        t2 = new_plan.task_by_id()["t2"]
        assert t2.duration_days == orig.duration_days + 3
        assert t2.start_date == orig.start_date
        assert t2.end_date == orig.end_date + timedelta(days=3)

    def test_shorten_duration_clamped_to_one(self, simple_plan):
        orig = simple_plan.task_by_id()["t2"]
        big_negative = -(orig.duration_days + 5)
        cmd = ResizeTask(task_id="t2", delta_days=big_negative)
        new_plan = apply_command(simple_plan, cmd)
        t2 = new_plan.task_by_id()["t2"]
        assert t2.duration_days == 1

    def test_unknown_task_raises(self, simple_plan):
        with pytest.raises(scheduler.SchedulerError, match="Unknown task id"):
            apply_command(simple_plan, ResizeTask(task_id="t_ghost", delta_days=1))


# ===========================================================================
# SwapTasks
# ===========================================================================

class TestSwapTasks:
    def test_swaps_start_dates(self, simple_plan):
        t1_orig = simple_plan.task_by_id()["t1"]
        t3_orig = simple_plan.task_by_id()["t3"]
        cmd = SwapTasks(task_a_id="t1", task_b_id="t3")
        new_plan = apply_command(simple_plan, cmd)
        t1_new = new_plan.task_by_id()["t1"]
        t3_new = new_plan.task_by_id()["t3"]
        assert t1_new.start_date == t3_orig.start_date
        assert t3_new.start_date == t1_orig.start_date

    def test_durations_preserved_after_swap(self, simple_plan):
        orig_dur_t1 = simple_plan.task_by_id()["t1"].duration_days
        orig_dur_t3 = simple_plan.task_by_id()["t3"].duration_days
        cmd = SwapTasks(task_a_id="t1", task_b_id="t3")
        new_plan = apply_command(simple_plan, cmd)
        assert new_plan.task_by_id()["t1"].duration_days == orig_dur_t1
        assert new_plan.task_by_id()["t3"].duration_days == orig_dur_t3

    def test_end_date_recomputed_from_own_duration(self, simple_plan):
        cmd = SwapTasks(task_a_id="t1", task_b_id="t3")
        new_plan = apply_command(simple_plan, cmd)
        id_map = new_plan.task_by_id()
        for tid in ("t1", "t3"):
            t = id_map[tid]
            assert t.end_date == t.start_date + timedelta(days=t.duration_days - 1)

    def test_no_propagation_after_swap(self, simple_plan):
        """Swap must NOT call propagate_constraints so that the swap sticks."""
        # t1→t2: after swapping t1 and t3, t1 will be at t3's original position
        # (after t2 in the chain) — a deliberate "violation" that must remain.
        cmd = SwapTasks(task_a_id="t1", task_b_id="t3")
        new_plan = apply_command(simple_plan, cmd)
        orig_t3_start = simple_plan.task_by_id()["t3"].start_date
        assert new_plan.task_by_id()["t1"].start_date == orig_t3_start

    def test_unknown_task_raises(self, simple_plan):
        with pytest.raises(scheduler.SchedulerError):
            apply_command(simple_plan, SwapTasks(task_a_id="t1", task_b_id="t_ghost"))


# ===========================================================================
# SwapTasks with swap_dependencies=True
# ===========================================================================

class TestSwapTasksFull:
    """Tests for swap_tasks with swap_dependencies=True (full graph swap)."""

    def test_swaps_predecessor_ids(self, simple_plan):
        """t1(preds=[]) and t3(preds=[t2]) -> after: t1.preds=[t2], t3.preds=[]."""
        cmd = SwapTasks(task_a_id="t1", task_b_id="t3", swap_dependencies=True)
        new_plan = apply_command(simple_plan, cmd)
        id_map = new_plan.task_by_id()
        assert id_map["t1"].predecessor_ids == ["t2"]
        assert id_map["t3"].predecessor_ids == []

    def test_updates_reverse_references(self, simple_plan):
        """t2 originally depends on t1. After full swap t1<->t3, t2 should depend on t3."""
        cmd = SwapTasks(task_a_id="t1", task_b_id="t3", swap_dependencies=True)
        new_plan = apply_command(simple_plan, cmd)
        id_map = new_plan.task_by_id()
        assert "t3" in id_map["t2"].predecessor_ids
        assert "t1" not in id_map["t2"].predecessor_ids

    def test_no_cycle_after_full_swap(self, simple_plan):
        """Full swap of t1 and t3 must not create a cycle."""
        cmd = SwapTasks(task_a_id="t1", task_b_id="t3", swap_dependencies=True)
        new_plan = apply_command(simple_plan, cmd)
        scheduler.assert_acyclic(new_plan)

    def test_cross_reference_removed(self, simple_plan):
        """If A depends on B (direct edge), swap must remove that cross-ref."""
        # t2 depends on t1. Swap t1 and t2 with full deps.
        # After swap: t1 gets t2's preds (which was [t1]), t2 gets t1's (which was []).
        # Cross-ref filter removes t1 from t1's preds and t2 from t2's preds.
        cmd = SwapTasks(task_a_id="t1", task_b_id="t2", swap_dependencies=True)
        new_plan = apply_command(simple_plan, cmd)
        id_map = new_plan.task_by_id()
        # t1 got t2's original preds [t1] but self-ref removed → []
        assert id_map["t1"].predecessor_ids == []
        # t2 got t1's original preds [] → []
        assert id_map["t2"].predecessor_ids == []
        # t3 originally depended on t2 → now depends on t1 (reverse ref update)
        assert "t1" in id_map["t3"].predecessor_ids
        scheduler.assert_acyclic(new_plan)

    def test_dates_recomputed_from_graph(self, simple_plan):
        """Full swap recomputes dates from the new dependency graph (not raw calendar swap)."""
        cmd = SwapTasks(task_a_id="t1", task_b_id="t3", swap_dependencies=True)
        new_plan = apply_command(simple_plan, cmd)
        id_map = new_plan.task_by_id()
        # After full swap: t3 is root, t2→t3, t1→t2. Dates follow topo order.
        for t in new_plan.tasks:
            assert t.end_date == t.start_date + timedelta(days=t.duration_days - 1)

    def test_full_recompute_called(self, simple_plan):
        """After full swap, dates are recomputed from dependency graph."""
        cmd = SwapTasks(task_a_id="t1", task_b_id="t3", swap_dependencies=True)
        new_plan = apply_command(simple_plan, cmd)
        id_map = new_plan.task_by_id()
        # t3 is now root (no preds), t2 depends on t3, t1 depends on t2
        # So: t3.start = project_start, t2 after t3, t1 after t2
        assert id_map["t3"].start_date <= id_map["t2"].start_date
        assert id_map["t2"].start_date <= id_map["t1"].start_date

    def test_seed_plan_swap_discovery_qa(self):
        """Reproduce the exact failing scenario from the bug report: swap t1 and t6 with deps."""
        from app.core.seed import seed_plan
        plan = seed_plan()
        cmd = SwapTasks(task_a_id="t1", task_b_id="t6", swap_dependencies=True)
        new_plan = apply_command(plan, cmd)
        id_map = new_plan.task_by_id()
        # t6 (was QA, now first) should have no predecessors
        assert id_map["t6"].predecessor_ids == []
        # t1 (was Discovery, now last) should depend on Integration (t5)
        assert "t5" in id_map["t1"].predecessor_ids
        # t2 (Design) originally depended on t1, now should depend on t6
        assert "t6" in id_map["t2"].predecessor_ids
        assert "t1" not in id_map["t2"].predecessor_ids
        # No cycles
        scheduler.assert_acyclic(new_plan)


# ===========================================================================
# AddTask
# ===========================================================================

class TestAddTask:
    def test_task_appended_to_plan(self, simple_plan):
        cmd = AddTask(name="Deploy", assignee="Eve", duration_days=2)
        new_plan = apply_command(simple_plan, cmd)
        assert len(new_plan.tasks) == len(simple_plan.tasks) + 1
        names = [t.name for t in new_plan.tasks]
        assert "Deploy" in names

    def test_sequential_id_assigned(self, simple_plan):
        """New task must get t4 (max existing = t3)."""
        cmd = AddTask(name="Deploy", assignee="Eve", duration_days=2)
        new_plan = apply_command(simple_plan, cmd)
        new_task = next(t for t in new_plan.tasks if t.name == "Deploy")
        assert new_task.id == "t4"

    def test_second_add_increments_id(self, simple_plan):
        """Two sequential adds should yield t4, then t5."""
        plan1 = apply_command(simple_plan, AddTask(name="Deploy", assignee="Eve", duration_days=2))
        plan2 = apply_command(plan1, AddTask(name="Monitor", assignee="Frank", duration_days=1))
        ids = [t.id for t in plan2.tasks]
        assert "t4" in ids
        assert "t5" in ids

    def test_full_recompute_sets_correct_dates(self, simple_plan):
        """No-predecessor task starts at project_start after full_recompute."""
        cmd = AddTask(name="Deploy", assignee="Eve", duration_days=2)
        new_plan = apply_command(simple_plan, cmd)
        new_task = new_plan.task_by_id()["t4"]
        assert new_task.start_date == new_plan.project_start

    def test_add_with_predecessor_dates_are_sequenced(self, simple_plan):
        """Task added after t3 must start the day after t3 ends."""
        cmd = AddTask(name="Deploy", assignee="Eve", duration_days=2, predecessor_ids=["t3"])
        new_plan = apply_command(simple_plan, cmd)
        t3 = new_plan.task_by_id()["t3"]
        deploy = new_plan.task_by_id()["t4"]
        assert deploy.start_date == t3.end_date + timedelta(days=1)

    def test_add_with_invalid_predecessor_raises(self, simple_plan):
        with pytest.raises(scheduler.SchedulerError, match="Unknown task id"):
            apply_command(simple_plan, AddTask(name="X", assignee="Y", duration_days=1,
                                               predecessor_ids=["t_ghost"]))

    def test_duration_clamped_to_one(self):
        """AddTask validator must clamp 0 or None to 1."""
        cmd = AddTask(name="X", assignee="Y", duration_days=0)
        assert cmd.duration_days == 1

    def test_original_plan_unchanged(self, simple_plan):
        orig_count = len(simple_plan.tasks)
        apply_command(simple_plan, AddTask(name="Deploy", assignee="Eve", duration_days=1))
        assert len(simple_plan.tasks) == orig_count

    # --- THE KEY BUG SCENARIO: reference a freshly-created task's ID --------

    def test_can_set_dependency_on_freshly_added_task(self, simple_plan):
        """
        Regression: after add_task the new task receives a predictable sequential
        ID (t4) so a subsequent set_dependency command can reference it without
        hallucinating a UUID.
        """
        plan_after_add = apply_command(
            simple_plan,
            AddTask(name="Deploy", assignee="Eve", duration_days=2),
        )
        new_task = next(t for t in plan_after_add.tasks if t.name == "Deploy")
        # This would have failed before the fix if the ID was a UUID
        final_plan = apply_command(
            plan_after_add,
            SetDependency(task_id=new_task.id, predecessor_ids=["t3"]),
        )
        assert new_task.id in final_plan.task_by_id()
        assert "t3" in final_plan.task_by_id()[new_task.id].predecessor_ids

    def test_freshly_added_task_can_be_moved(self, simple_plan):
        plan_after_add = apply_command(
            simple_plan,
            AddTask(name="Deploy", assignee="Eve", duration_days=2),
        )
        new_task = next(t for t in plan_after_add.tasks if t.name == "Deploy")
        orig_start = new_task.start_date
        moved_plan = apply_command(
            plan_after_add,
            MoveTask(task_id=new_task.id, delta_days=3),
        )
        assert moved_plan.task_by_id()[new_task.id].start_date == orig_start + timedelta(days=3)

    def test_freshly_added_task_can_be_reassigned(self, simple_plan):
        plan_after_add = apply_command(
            simple_plan,
            AddTask(name="Deploy", assignee="Eve", duration_days=2),
        )
        new_task = next(t for t in plan_after_add.tasks if t.name == "Deploy")
        final = apply_command(
            plan_after_add,
            ReassignTask(task_id=new_task.id, new_assignee="Zara"),
        )
        assert final.task_by_id()[new_task.id].assignee == "Zara"


# ===========================================================================
# DeleteTask
# ===========================================================================

class TestDeleteTask:
    def test_task_removed_from_plan(self, simple_plan):
        new_plan = apply_command(simple_plan, DeleteTask(task_id="t2"))
        assert "t2" not in new_plan.task_by_id()
        assert len(new_plan.tasks) == 2

    def test_predecessor_ref_cleaned_up(self, simple_plan):
        """Deleting t2 must remove t2 from t3's predecessor_ids."""
        new_plan = apply_command(simple_plan, DeleteTask(task_id="t2"))
        assert "t2" not in new_plan.task_by_id()["t3"].predecessor_ids

    def test_full_recompute_runs_after_delete(self, simple_plan):
        """After deleting the middle task, t3 should re-anchor to project_start."""
        new_plan = apply_command(simple_plan, DeleteTask(task_id="t2"))
        t3 = new_plan.task_by_id()["t3"]
        # t3 no longer has predecessors, so it starts at project_start
        assert t3.start_date == new_plan.project_start

    def test_unknown_task_raises(self, simple_plan):
        with pytest.raises(scheduler.SchedulerError):
            apply_command(simple_plan, DeleteTask(task_id="t_ghost"))


# ===========================================================================
# SetDependency
# ===========================================================================

class TestSetDependency:
    def test_sets_new_predecessor(self, simple_plan):
        """Make t3 depend directly on t1 instead of t2."""
        new_plan = apply_command(simple_plan, SetDependency(task_id="t3", predecessor_ids=["t1"]))
        assert new_plan.task_by_id()["t3"].predecessor_ids == ["t1"]

    def test_empty_list_makes_task_independent(self, simple_plan):
        new_plan = apply_command(simple_plan, SetDependency(task_id="t3", predecessor_ids=[]))
        assert new_plan.task_by_id()["t3"].predecessor_ids == []
        assert new_plan.task_by_id()["t3"].start_date == new_plan.project_start

    def test_self_dependency_raises(self, simple_plan):
        with pytest.raises(scheduler.SchedulerError, match="depend on itself"):
            apply_command(simple_plan, SetDependency(task_id="t1", predecessor_ids=["t1"]))

    def test_cycle_raises(self, simple_plan):
        """t1 → t2 → t3; making t1 depend on t3 creates a cycle."""
        with pytest.raises(scheduler.SchedulerError, match="Circular"):
            apply_command(simple_plan, SetDependency(task_id="t1", predecessor_ids=["t3"]))

    def test_duplicate_predecessor_ids_deduped(self, simple_plan):
        new_plan = apply_command(
            simple_plan, SetDependency(task_id="t3", predecessor_ids=["t1", "t1"])
        )
        assert new_plan.task_by_id()["t3"].predecessor_ids == ["t1"]

    def test_full_recompute_runs_after_set_dependency(self, simple_plan):
        """Changing t3's predecessor to t1 (shorter chain) should shift t3 earlier."""
        orig_start = simple_plan.task_by_id()["t3"].start_date
        new_plan = apply_command(simple_plan, SetDependency(task_id="t3", predecessor_ids=["t1"]))
        assert new_plan.task_by_id()["t3"].start_date < orig_start

    def test_unknown_task_id_raises(self, simple_plan):
        with pytest.raises(scheduler.SchedulerError):
            apply_command(simple_plan, SetDependency(task_id="t_ghost", predecessor_ids=[]))


# ===========================================================================
# ReassignTask
# ===========================================================================

class TestReassignTask:
    def test_updates_assignee(self, simple_plan):
        new_plan = apply_command(simple_plan, ReassignTask(task_id="t1", new_assignee="Zara"))
        assert new_plan.task_by_id()["t1"].assignee == "Zara"

    def test_dates_unchanged(self, simple_plan):
        orig = simple_plan.task_by_id()["t1"]
        new_plan = apply_command(simple_plan, ReassignTask(task_id="t1", new_assignee="Zara"))
        t1 = new_plan.task_by_id()["t1"]
        assert t1.start_date == orig.start_date
        assert t1.end_date == orig.end_date

    def test_unknown_task_raises(self, simple_plan):
        with pytest.raises(scheduler.SchedulerError):
            apply_command(simple_plan, ReassignTask(task_id="t_ghost", new_assignee="X"))


# ===========================================================================
# Clarify
# ===========================================================================

class TestClarify:
    def test_clarify_returns_deep_copy_unchanged(self, simple_plan):
        orig_json = simple_plan.model_dump(mode="json")
        new_plan = apply_command(simple_plan, Clarify(question="What do you mean?"))
        assert new_plan.model_dump(mode="json") == orig_json


# ===========================================================================
# apply_batch
# ===========================================================================

class TestSetDepGroupAtomic:
    """Regression: bulk re-wiring of dependency chains must not fail on transient cycles."""

    def test_reverse_linear_chain(self, simple_plan):
        """
        Original: t1 → t2 → t3.
        After reversal: t3 → t2 → t1.
        cmd[1] sets t1.predecessors=[t2]; at this point t2 still points to t1 → transient cycle.
        The atomic group must absorb all three updates before checking acyclicity.
        """
        cmds = [
            SetDependency(task_id="t1", predecessor_ids=["t2"]),
            SetDependency(task_id="t2", predecessor_ids=["t3"]),
            SetDependency(task_id="t3", predecessor_ids=[]),
        ]
        new_plan = apply_batch(simple_plan, cmds)
        id_map = new_plan.task_by_id()
        assert id_map["t1"].predecessor_ids == ["t2"]
        assert id_map["t2"].predecessor_ids == ["t3"]
        assert id_map["t3"].predecessor_ids == []

    def test_reversed_chain_dates_correct(self, simple_plan):
        """After reversal t3 is the root; t2 starts after t3; t1 starts after t2."""
        cmds = [
            SetDependency(task_id="t1", predecessor_ids=["t2"]),
            SetDependency(task_id="t2", predecessor_ids=["t3"]),
            SetDependency(task_id="t3", predecessor_ids=[]),
        ]
        new_plan = apply_batch(simple_plan, cmds)
        id_map = new_plan.task_by_id()
        assert id_map["t3"].start_date == new_plan.project_start
        assert id_map["t2"].start_date == id_map["t3"].end_date + timedelta(days=1)
        assert id_map["t1"].start_date == id_map["t2"].end_date + timedelta(days=1)

    def test_genuine_cycle_still_raises(self, simple_plan):
        """A true cycle in the final state must still be rejected."""
        cmds = [
            SetDependency(task_id="t1", predecessor_ids=["t2"]),
            SetDependency(task_id="t2", predecessor_ids=["t3"]),
            # t3 → t1 closes the cycle; this should fail even with atomic grouping
            SetDependency(task_id="t3", predecessor_ids=["t1"]),
        ]
        with pytest.raises(scheduler.SchedulerError, match="Circular"):
            apply_batch(simple_plan, cmds)

    def test_self_loop_inside_group_raises_immediately(self, simple_plan):
        cmds = [
            SetDependency(task_id="t1", predecessor_ids=["t2"]),
            SetDependency(task_id="t2", predecessor_ids=["t2"]),  # self-loop
        ]
        with pytest.raises(scheduler.SchedulerError, match="depend on itself"):
            apply_batch(simple_plan, cmds)

    def test_set_dep_group_separated_by_other_command(self, simple_plan):
        """Two set_dependency groups separated by a reassign must each be atomic."""
        cmds = [
            # Group 1: detach t3
            SetDependency(task_id="t3", predecessor_ids=[]),
            # Break: non-SetDep command
            ReassignTask(task_id="t1", new_assignee="Zara"),
            # Group 2: re-attach t3 after t1
            SetDependency(task_id="t3", predecessor_ids=["t1"]),
        ]
        new_plan = apply_batch(simple_plan, cmds)
        id_map = new_plan.task_by_id()
        assert id_map["t1"].assignee == "Zara"
        assert id_map["t3"].predecessor_ids == ["t1"]

    def test_sixteen_task_chain_reversal(self):
        """Exact reproduction of the log scenario: 16-task chain reversed in one batch."""
        from datetime import date
        base = date(2026, 1, 5)
        tasks = []
        for n in range(1, 17):
            preds = [] if n == 1 else [f"t{n - 1}"]
            s = base + timedelta(days=(n - 1))
            tasks.append(
                Task(
                    id=f"t{n}", name=f"Task {n}", assignee="X",
                    duration_days=1, predecessor_ids=preds,
                    start_date=s, end_date=s,
                )
            )
        plan = ProjectPlan(tasks=tasks, project_start=base)

        # Mirror the LLM output from the log
        cmds = [SetDependency(task_id=f"t{n}", predecessor_ids=[f"t{n + 1}"])
                for n in range(1, 16)]
        cmds.append(SetDependency(task_id="t16", predecessor_ids=[]))

        new_plan = apply_batch(plan, cmds)
        id_map = new_plan.task_by_id()
        assert id_map["t16"].predecessor_ids == []
        assert id_map["t1"].predecessor_ids == ["t2"]
        # t16 is now the root
        assert id_map["t16"].start_date == new_plan.project_start


class TestApplyBatch:
    def test_batch_applies_multiple_commands(self, simple_plan):
        cmds = [
            MoveTask(task_id="t1", delta_days=2),
            ReassignTask(task_id="t2", new_assignee="Zara"),
        ]
        new_plan = apply_batch(simple_plan, cmds)
        assert new_plan.task_by_id()["t2"].assignee == "Zara"

    def test_clarify_in_batch_skipped(self, simple_plan):
        cmds = [
            Clarify(question="Which task?"),
            ReassignTask(task_id="t1", new_assignee="Zara"),
        ]
        new_plan = apply_batch(simple_plan, cmds)
        assert new_plan.task_by_id()["t1"].assignee == "Zara"

    def test_batch_is_sequential(self, simple_plan):
        """Second command should see the result of the first."""
        cmds = [
            AddTask(name="Deploy", assignee="Eve", duration_days=2),
            # t4 is the predictable ID after the fix
            SetDependency(task_id="t4", predecessor_ids=["t3"]),
        ]
        new_plan = apply_batch(simple_plan, cmds)
        assert "t3" in new_plan.task_by_id()["t4"].predecessor_ids

    def test_batch_stops_on_error(self, simple_plan):
        """An invalid command in the middle must raise before mutating state."""
        cmds = [
            ReassignTask(task_id="t1", new_assignee="Zara"),
            MoveTask(task_id="t_ghost", delta_days=1),  # will raise
        ]
        with pytest.raises(scheduler.SchedulerError):
            apply_batch(simple_plan, cmds)


# ===========================================================================
# RenameTask
# ===========================================================================

class TestRenameTask:
    def test_renames_task_name(self, simple_plan):
        cmd = RenameTask(task_id="t1", new_name="Research")
        new_plan = apply_command(simple_plan, cmd)
        assert new_plan.task_by_id()["t1"].name == "Research"

    def test_strips_whitespace(self, simple_plan):
        cmd = RenameTask(task_id="t1", new_name="  Research  ")
        new_plan = apply_command(simple_plan, cmd)
        assert new_plan.task_by_id()["t1"].name == "Research"

    def test_updates_description_if_provided(self, simple_plan):
        cmd = RenameTask(task_id="t1", new_name="Research", new_description="Updated desc")
        new_plan = apply_command(simple_plan, cmd)
        assert new_plan.task_by_id()["t1"].description == "Updated desc"

    def test_preserves_description_if_none(self, simple_plan):
        orig_desc = simple_plan.task_by_id()["t1"].description
        cmd = RenameTask(task_id="t1", new_name="Research")
        new_plan = apply_command(simple_plan, cmd)
        assert new_plan.task_by_id()["t1"].description == orig_desc

    def test_dates_unchanged(self, simple_plan):
        orig = simple_plan.task_by_id()["t1"]
        cmd = RenameTask(task_id="t1", new_name="Research")
        new_plan = apply_command(simple_plan, cmd)
        t1 = new_plan.task_by_id()["t1"]
        assert t1.start_date == orig.start_date
        assert t1.end_date == orig.end_date

    def test_assignee_unchanged(self, simple_plan):
        orig_assignee = simple_plan.task_by_id()["t1"].assignee
        cmd = RenameTask(task_id="t1", new_name="Research")
        new_plan = apply_command(simple_plan, cmd)
        assert new_plan.task_by_id()["t1"].assignee == orig_assignee

    def test_unknown_task_raises(self, simple_plan):
        with pytest.raises(scheduler.SchedulerError, match="Unknown task id"):
            apply_command(simple_plan, RenameTask(task_id="t_ghost", new_name="X"))


# ===========================================================================
# Answer (read-only no-op)
# ===========================================================================

class TestAnswer:
    def test_answer_returns_deep_copy_unchanged(self, simple_plan):
        orig_json = simple_plan.model_dump(mode="json")
        new_plan = apply_command(simple_plan, Answer(text="There are 3 tasks."))
        assert new_plan.model_dump(mode="json") == orig_json


# ===========================================================================
# CycleClassification — error subclass checks
# ===========================================================================

class TestCycleClassification:
    def test_cycle_raises_cycle_error(self, simple_plan):
        """Creating a cycle should raise CycleError specifically."""
        with pytest.raises(scheduler.CycleError, match="Circular"):
            apply_command(simple_plan, SetDependency(task_id="t1", predecessor_ids=["t3"]))

    def test_self_dep_raises_cycle_error(self, simple_plan):
        with pytest.raises(scheduler.CycleError, match="depend on itself"):
            apply_command(simple_plan, SetDependency(task_id="t1", predecessor_ids=["t1"]))

    def test_unknown_ref_raises_unknown_reference_error(self, simple_plan):
        with pytest.raises(scheduler.UnknownReferenceError, match="Unknown task id"):
            apply_command(simple_plan, MoveTask(task_id="t_ghost", delta_days=1))

    def test_cycle_is_scheduler_error(self, simple_plan):
        """CycleError is a subclass of SchedulerError for backward compat."""
        with pytest.raises(scheduler.SchedulerError):
            apply_command(simple_plan, SetDependency(task_id="t1", predecessor_ids=["t3"]))

    def test_unknown_ref_is_scheduler_error(self, simple_plan):
        with pytest.raises(scheduler.SchedulerError):
            apply_command(simple_plan, MoveTask(task_id="t_ghost", delta_days=1))


# ===========================================================================
# MaxTasksLimit
# ===========================================================================

class TestMaxTasksLimit:
    def test_add_task_respects_limit(self, simple_plan, monkeypatch):
        """Adding a task beyond the limit should raise SchedulerError."""
        from app.config import get_settings
        get_settings.cache_clear()
        settings = get_settings()
        monkeypatch.setattr(settings, "max_tasks_total", 3)
        try:
            with pytest.raises(scheduler.SchedulerError, match="Task limit reached"):
                apply_command(simple_plan, AddTask(name="Extra", assignee="X", duration_days=1))
        finally:
            get_settings.cache_clear()

    def test_add_task_within_limit_succeeds(self, simple_plan, monkeypatch):
        from app.config import get_settings
        get_settings.cache_clear()
        settings = get_settings()
        monkeypatch.setattr(settings, "max_tasks_total", 10)
        try:
            new_plan = apply_command(simple_plan, AddTask(name="Extra", assignee="X", duration_days=1))
            assert len(new_plan.tasks) == 4
        finally:
            get_settings.cache_clear()
