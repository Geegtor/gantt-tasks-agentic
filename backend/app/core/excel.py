from __future__ import annotations

import io
import re
from datetime import date

import pandas as pd

from app.core.models import ProjectPlan, Task
from app.core import scheduler

COL_MAP = {
    "задача": "name",
    "описание": "description",
    "исполнитель": "assignee",
    "длительность": "duration_days",
    "предшественники": "predecessors_raw",
}

REQUIRED_RU = list(COL_MAP.keys())


def _norm_col(c: str) -> str:
    return str(c).strip().lower()


def parse_excel_bytes(data: bytes) -> ProjectPlan:
    df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
    df.columns = [_norm_col(c) for c in df.columns]
    missing = [c for c in REQUIRED_RU if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}. Required: {REQUIRED_RU}")

    df = df.rename(columns=COL_MAP)

    tmp_tasks: list[Task] = []
    row_pred_raws: list[str | None] = []

    for i, row in df.iterrows():
        name = str(row["name"]).strip()
        if not name or name.lower() == "nan":
            continue
        # Sequential t-prefixed IDs (consistent with add_task in engine.py)
        tid = f"t{len(tmp_tasks) + 1}"
        desc = "" if pd.isna(row.get("description")) else str(row["description"])
        assignee = "" if pd.isna(row.get("assignee")) else str(row["assignee"])
        dur = row["duration_days"]
        if pd.isna(dur):
            raise ValueError(f"Row {int(i)+2}: duration empty for {name!r}")
        duration_days = int(float(dur))
        if duration_days < 1:
            raise ValueError(f"Row {int(i)+2}: duration must be >= 1")

        pr = row.get("predecessors_raw")
        pred_raw_str: str | None = None if pr is None or (isinstance(pr, float) and pd.isna(pr)) else str(pr)

        tmp_tasks.append(
            Task(
                id=tid,
                name=name,
                description=desc,
                assignee=assignee or "Unassigned",
                duration_days=duration_days,
                predecessor_ids=[],
                start_date=date.today(),
                end_date=date.today(),
            )
        )
        row_pred_raws.append(pred_raw_str)

    from app.config import get_settings
    _max = get_settings().max_tasks_total
    if len(tmp_tasks) > _max:
        raise ValueError(f"Excel contains {len(tmp_tasks)} tasks; maximum allowed is {_max}")

    id_by_name = {t.name.strip().lower(): t.id for t in tmp_tasks}

    for t, pred_raw_str in zip(tmp_tasks, row_pred_raws, strict=True):
        if not pred_raw_str or not str(pred_raw_str).strip():
            continue
        s = str(pred_raw_str).strip()
        preds: list[str] = []
        for part in re.split(r"[,;]\s*|\s+/\s+", s):
            pname = part.strip()
            if not pname:
                continue
            pid = id_by_name.get(pname.strip().lower())
            if not pid:
                raise ValueError(f"Unknown predecessor name {pname!r} for task {t.name!r}")
            preds.append(pid)
        t.predecessor_ids = list(dict.fromkeys(preds))

    plan = ProjectPlan(tasks=tmp_tasks, project_start=date.today())
    if plan.tasks:
        scheduler.assert_acyclic(plan)
        scheduler.full_recompute(plan)
    return plan


def plan_to_excel_bytes(plan: ProjectPlan) -> bytes:
    rows = []
    id_to_name = {t.id: t.name for t in plan.tasks}
    for t in plan.tasks:
        preds = ", ".join(id_to_name.get(p, p) for p in t.predecessor_ids)
        rows.append(
            {
                "задача": t.name,
                "описание": t.description,
                "исполнитель": t.assignee,
                "длительность": t.duration_days,
                "предшественники": preds,
            }
        )
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    buf.seek(0)
    return buf.read()
