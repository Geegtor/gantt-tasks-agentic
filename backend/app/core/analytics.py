"""Lightweight plan analytics for read-only queries."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

import networkx as nx

from app.core.models import ProjectPlan


def critical_path(plan: ProjectPlan) -> list[str]:
    """Return task ids on the longest-duration path (critical path)."""
    if not plan.tasks:
        return []
    g = nx.DiGraph()
    id_map = {t.id: t for t in plan.tasks}
    for t in plan.tasks:
        g.add_node(t.id, weight=t.duration_days)
        for p in t.predecessor_ids:
            if p in id_map:
                g.add_edge(p, t.id)
    if not nx.is_directed_acyclic_graph(g):
        return []
    try:
        return nx.dag_longest_path(g, weight="weight")
    except nx.NetworkXError:
        return []


def parallel_groups(plan: ProjectPlan) -> list[list[str]]:
    """Return groups of tasks that run in parallel (overlapping date ranges, no dependency)."""
    if not plan.tasks:
        return []
    dep_pairs: set[tuple[str, str]] = set()
    for t in plan.tasks:
        for p in t.predecessor_ids:
            dep_pairs.add((p, t.id))
            dep_pairs.add((t.id, p))

    groups: list[list[str]] = []
    tasks = sorted(plan.tasks, key=lambda t: t.start_date)
    for i, a in enumerate(tasks):
        group = [a.id]
        for b in tasks[i + 1 :]:
            if b.start_date > a.end_date:
                break
            if (a.id, b.id) not in dep_pairs:
                group.append(b.id)
        if len(group) > 1:
            groups.append(group)
    return groups


def overloaded_assignees(plan: ProjectPlan) -> dict[str, int]:
    """Return assignees with overlapping task date ranges (count of overlapping pairs)."""
    by_assignee: dict[str, list[tuple[date, date, str]]] = defaultdict(list)
    for t in plan.tasks:
        if t.assignee:
            by_assignee[t.assignee].append((t.start_date, t.end_date, t.id))

    result: dict[str, int] = {}
    for assignee, ranges in by_assignee.items():
        ranges.sort()
        overlaps = 0
        for i in range(len(ranges)):
            for j in range(i + 1, len(ranges)):
                if ranges[j][0] <= ranges[i][1]:
                    overlaps += 1
                else:
                    break
        if overlaps > 0:
            result[assignee] = overlaps
    return result


def analytics_summary(plan: ProjectPlan) -> str:
    """One-line summary for injection into LLM prompt context."""
    cp = critical_path(plan)
    pg = parallel_groups(plan)
    ol = overloaded_assignees(plan)
    id_map = {t.id: t.name for t in plan.tasks}

    parts = []
    if cp:
        names = [id_map.get(tid, tid) for tid in cp]
        parts.append(f"Critical path ({len(cp)} tasks): {' → '.join(names)}")
    if pg:
        parts.append(f"Parallel groups: {len(pg)}")
    if ol:
        items = [f"{a} ({n} overlaps)" for a, n in ol.items()]
        parts.append(f"Overloaded assignees: {', '.join(items)}")
    return "; ".join(parts) if parts else "No analytics data available."
