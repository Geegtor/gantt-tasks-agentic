"""Deterministic topology signature for RAG / replay (task ids, preds, durations)."""
from __future__ import annotations

import hashlib
import json

from app.core.models import ProjectPlan


def plan_topology_signature(plan: ProjectPlan) -> str:
    """Hash stable across dates/assignee names; same graph + durations => same signature."""
    rows: list[list[object]] = []
    for t in sorted(plan.tasks, key=lambda x: x.id):
        rows.append(
            [
                t.id,
                t.duration_days,
                sorted(t.predecessor_ids),
                t.name.strip().lower(),
            ]
        )
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
