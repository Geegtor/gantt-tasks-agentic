from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

import networkx as nx

from app.core.models import ProjectPlan, Task


class SchedulerError(Exception):
    pass


class CycleError(SchedulerError):
    pass


class UnknownReferenceError(SchedulerError):
    pass


class PropagationError(SchedulerError):
    pass


def _graph(plan: ProjectPlan) -> nx.DiGraph:
    g = nx.DiGraph()
    for t in plan.tasks:
        g.add_node(t.id)
    for t in plan.tasks:
        for p in t.predecessor_ids:
            if p not in g:
                raise UnknownReferenceError(f"Unknown predecessor id {p!r} for task {t.id}")
            g.add_edge(p, t.id)
    return g


def assert_acyclic(plan: ProjectPlan) -> None:
    g = _graph(plan)
    if not nx.is_directed_acyclic_graph(g):
        cycles = list(nx.simple_cycles(g))
        cyc = cycles[0] if cycles else []
        raise CycleError(f"Circular dependencies: {' -> '.join(cyc)}")


def topological_order(plan: ProjectPlan) -> list[str]:
    assert_acyclic(plan)
    g = _graph(plan)
    return list(nx.topological_sort(g))


def full_recompute(plan: ProjectPlan) -> None:
    """Set dates from durations, predecessors, and project_start only."""
    if not plan.tasks:
        return
    assert_acyclic(plan)
    order = topological_order(plan)
    id_map = {t.id: t for t in plan.tasks}
    project_start = plan.project_start
    if project_start is None:
        project_start = min(t.start_date for t in plan.tasks)
        plan.project_start = project_start
    for tid in order:
        t = id_map[tid]
        if not t.predecessor_ids:
            t.start_date = project_start
        else:
            pred_end = max(id_map[p].end_date for p in t.predecessor_ids)
            t.start_date = pred_end + timedelta(days=1)
        t.end_date = t.start_date + timedelta(days=t.duration_days - 1)


def propagate_constraints(plan: ProjectPlan) -> None:
    """Push tasks forward to satisfy predecessor end dates (fixed-point)."""
    if not plan.tasks:
        return
    assert_acyclic(plan)
    order = topological_order(plan)
    id_map = {t.id: t for t in plan.tasks}
    for _ in range(max(1, len(plan.tasks) * 3)):
        changed = False
        for tid in order:
            t = id_map[tid]
            if not t.predecessor_ids:
                continue
            need_start = max(id_map[p].end_date for p in t.predecessor_ids) + timedelta(days=1)
            if t.start_date < need_start:
                delta = (need_start - t.start_date).days
                t.start_date += timedelta(days=delta)
                t.end_date += timedelta(days=delta)
                changed = True
        if not changed:
            return
    raise PropagationError("Could not stabilize schedule (propagation loop)")


def validate_references(plan: ProjectPlan, task_ids: Iterable[str]) -> None:
    id_set = {t.id for t in plan.tasks}
    for tid in task_ids:
        if tid not in id_set:
            raise UnknownReferenceError(f"Unknown task id: {tid!r}")
