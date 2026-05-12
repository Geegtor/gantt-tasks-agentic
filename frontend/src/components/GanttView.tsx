import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Gantt, Task, ViewMode } from "gantt-task-react";
import "gantt-task-react/dist/index.css";
import type { ApiTask } from "../types";
import { updateTask } from "../api/client";
import { usePlanStore } from "../store/usePlanStore";
import { useI18n } from "../i18n/I18nContext";
import { useDragToPan } from "../hooks/useDragToPan";

function toGanttTasks(tasks: ApiTask[]): Task[] {
  return tasks.map((t) => ({
    id: t.id,
    name: t.name,
    start: new Date(t.start_date + "T00:00:00"),
    end: new Date(t.end_date + "T23:59:59"),
    type: "task" as const,
    progress: 0,
    dependencies: t.predecessor_ids?.length ? t.predecessor_ids : undefined,
  }));
}

interface Props {
  tasks: ApiTask[];
  onTaskClick: (task: ApiTask) => void;
  onEditTask: (task: ApiTask) => void;
}

export function GanttView({ tasks, onTaskClick, onEditTask }: Props) {
  const setPlan = usePlanStore((s) => s.setPlan);
  const chatLoading = usePlanStore((s) => s.chatLoading);
  const { t, lang } = useI18n();
  const drag = useDragToPan<HTMLDivElement>();

  const [containerHeight, setContainerHeight] = useState(0);

  useEffect(() => {
    const el = drag.containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerHeight(Math.floor(entry.contentRect.height));
      }
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, [drag.containerRef]);

  // Tracks the timestamp of the last completed bar drag/resize so we can
  // suppress the spurious onClick the library fires after every mouseup.
  const lastDragAt = useRef(0);

  // Stable refs so TaskListTable (passed as a component type) never changes
  // its function identity — if it did, React would unmount/remount the whole
  // task list on every render.
  const apiMapRef = useRef(new Map<string, ApiTask>());
  const onEditTaskRef = useRef(onEditTask);
  const tRef = useRef(t);

  const apiMap = useMemo(() => {
    const m = new Map<string, ApiTask>();
    tasks.forEach((t) => m.set(t.id, t));
    return m;
  }, [tasks]);

  // Keep refs in sync so stable TaskListTable always reads latest values.
  apiMapRef.current = apiMap;
  onEditTaskRef.current = onEditTask;
  tRef.current = t;

  const ganttTasks = useMemo(() => toGanttTasks(tasks), [tasks]);

  // Only recalculate when the task *set* (IDs) changes, not when dates change.
  // Dragging a bar updates dates, which must not scroll the viewport back to
  // the earliest task every time.
  const chartKey = useMemo(() => tasks.map((t) => t.id).join("|"), [tasks]);

  const viewDate = useMemo(() => {
    if (!tasks.length) return undefined;
    let min = tasks[0].start_date;
    for (const t of tasks) if (t.start_date < min) min = t.start_date;
    return new Date(`${min}T12:00:00`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartKey]); // intentional: stable across date-only changes

  // ── Custom task list: name-only column ───────────────────────
  const TaskListHeader = useCallback(
    ({
      headerHeight,
      rowWidth,
      fontFamily,
      fontSize,
    }: {
      headerHeight: number;
      rowWidth: string;
      fontFamily: string;
      fontSize: string;
    }) => (
      <div
        style={{ height: headerHeight, fontFamily, fontSize, width: rowWidth }}
        className="flex items-center px-3 border-b border-slate-200 text-slate-500 font-semibold text-xs uppercase tracking-wide bg-slate-50"
      >
        {t.gantt.listHeader}
      </div>
    ),
    [t.gantt.listHeader],
  );

  const TaskListTable = useCallback(
    ({
      rowHeight,
      rowWidth,
      fontFamily,
      fontSize,
      tasks,
      selectedTaskId,
      setSelectedTask,
    }: {
      rowHeight: number;
      rowWidth: string;
      fontFamily: string;
      fontSize: string;
      locale: string;
      tasks: Task[];
      selectedTaskId: string;
      setSelectedTask: (id: string) => void;
      onExpanderClick: (task: Task) => void;
    }) => {
      // Local state is fine here — the Gantt library mounts this as a real
      // React component, and the stable useCallback ref keeps identity fixed.
      const [hoveredId, setHoveredId] = useState<string | null>(null);
      const [tipPos, setTipPos] = useState({ x: 0, y: 0 });

      return (
        <div style={{ fontFamily, fontSize }}>
          {tasks.map((task) => {
            const api = apiMapRef.current.get(task.id);
            const tl = tRef.current.gantt.tooltip;
            return (
              <div
                key={task.id}
                style={{ height: rowHeight, width: rowWidth }}
                className={`relative flex items-center px-3 cursor-pointer border-b border-slate-100 text-sm truncate transition-colors ${
                  task.id === selectedTaskId
                    ? "bg-blue-50 text-blue-700 font-medium"
                    : "text-slate-700 hover:bg-slate-50"
                }`}
                onClick={() => {
                  setSelectedTask(task.id);
                  if (api) onEditTaskRef.current(api);
                }}
                onMouseEnter={(e) => {
                  setHoveredId(task.id);
                  const r = e.currentTarget.getBoundingClientRect();
                  setTipPos({ x: r.right + 10, y: r.top });
                }}
                onMouseLeave={() => setHoveredId(null)}
              >
                <span className="truncate">{task.name}</span>

                {hoveredId === task.id && api && (
                  <div
                    style={{
                      position: "fixed",
                      left: tipPos.x,
                      top: tipPos.y,
                      zIndex: 9999,
                      pointerEvents: "none",
                    }}
                    className="gantt-tooltip-portal bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-lg rounded-lg p-3 text-xs text-slate-700 dark:text-slate-200 min-w-[220px] max-w-[300px]"
                  >
                    <p className="font-semibold text-sm text-slate-900 dark:text-slate-100 mb-2 truncate">
                      {api.name}
                    </p>
                    <table className="w-full border-collapse">
                      <tbody>
                        {(
                          [
                            [tl.assignee, api.assignee || "—"],
                            [tl.duration, tl.days(api.duration_days)],
                            [tl.start, api.start_date],
                            [tl.end, api.end_date],
                            [
                              tl.predecessors,
                              api.predecessor_ids.length
                                ? api.predecessor_ids.join(", ")
                                : tl.none,
                            ],
                            [tl.description, api.description || "—"],
                          ] as [string, string][]
                        ).map(([label, value]) => (
                          <tr
                            key={label}
                            className="border-t border-slate-100 dark:border-slate-700 first:border-t-0"
                          >
                            <td className="py-0.5 pr-3 text-slate-400 dark:text-slate-500 font-medium whitespace-nowrap">
                              {label}
                            </td>
                            <td className="py-0.5 break-words">{value}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      );
    },
    // Intentionally empty — refs keep values fresh without changing identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // ── Hover tooltip ─────────────────────────────────────────────
  const TooltipContent = useCallback(
    ({ task, fontSize, fontFamily }: { task: Task; fontSize: string; fontFamily: string }) => {
      const api = apiMap.get(task.id);
      if (!api) return null;
      const tl = t.gantt.tooltip;
      const rows: [string, string][] = [
        [tl.assignee, api.assignee || "—"],
        [tl.duration, tl.days(api.duration_days)],
        [tl.start, api.start_date],
        [tl.end, api.end_date],
        [tl.predecessors, api.predecessor_ids.length ? api.predecessor_ids.join(", ") : tl.none],
        [tl.description, api.description || "—"],
      ];
      return (
        <div
          style={{ pointerEvents: "none", fontFamily, fontSize }}
          className="gantt-tooltip-portal bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-lg rounded-lg p-3 text-xs text-slate-700 dark:text-slate-200 min-w-[220px] max-w-[300px]"
        >
          <p className="font-semibold text-sm text-slate-900 dark:text-slate-100 mb-2 truncate">{api.name}</p>
          <table className="w-full border-collapse">
            <tbody>
              {rows.map(([label, value]) => (
                <tr key={label} className="border-t border-slate-100 dark:border-slate-700 first:border-t-0">
                  <td className="py-0.5 pr-3 text-slate-400 dark:text-slate-500 font-medium whitespace-nowrap">
                    {label}
                  </td>
                  <td className="py-0.5 text-slate-700 dark:text-slate-200 break-words">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    },
    [apiMap, t.gantt.tooltip],
  );

  // ── Bar drag / resize → reschedule ───────────────────────────
  const onDateChange = useCallback(
    async (task: Task): Promise<boolean> => {
      if (usePlanStore.getState().chatLoading) return false;
      // Mark that a drag just finished so the next onClick is suppressed.
      lastDragAt.current = Date.now();

      // Use local date components to avoid UTC-offset issues when the
      // task dates were constructed as "YYYY-MM-DDT00:00:00" local time.
      const pad = (n: number) => String(n).padStart(2, "0");
      const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
      const start = fmt(task.start);
      const end = fmt(task.end);
      // Compute duration from the new start/end so resizes are persisted.
      const duration_days = Math.max(
        1,
        Math.round((task.end.getTime() - task.start.getTime()) / 86_400_000),
      );

      // Optimistic update: immediately reflect the change in the Zustand store
      // so the chart doesn't snap back to the old position while the PATCH is
      // in flight. We read state imperatively to avoid a closure over stale values.
      const snap = usePlanStore.getState();
      if (snap.plan) {
        setPlan(
          {
            ...snap.plan,
            tasks: snap.plan.tasks.map((t) =>
              t.id === task.id ? { ...t, start_date: start, end_date: end, duration_days } : t,
            ),
          },
          snap.planRevision,
        );
      }

      try {
        const res = await updateTask(task.id, { start_date: start, duration_days });
        setPlan(res.plan, typeof res.revision === "number" ? res.revision : undefined);
        return true;
      } catch (e) {
        // Revert optimistic update on failure.
        if (snap.plan) setPlan(snap.plan, snap.planRevision);
        console.error("Date update failed:", e);
        return false;
      }
    },
    [setPlan],
  );

  if (!ganttTasks.length) {
    return (
      <div className="h-full flex items-center justify-center text-slate-400 dark:text-slate-500 text-sm">
        {t.gantt.noTasks}
      </div>
    );
  }

  return (
    <div
      ref={drag.containerRef}
      onMouseDown={drag.onMouseDown}
      className={`gantt-chart-container h-full overflow-auto rounded-lg border border-slate-200 dark:border-slate-700 bg-white transition-colors duration-200 cursor-grab active:cursor-grabbing ${chatLoading ? "opacity-50 pointer-events-none" : ""}`}
    >
      <Gantt
        key={chartKey}
        tasks={ganttTasks}
        viewDate={viewDate}
        viewMode={ViewMode.Day}
        listCellWidth="180px"
        columnWidth={52}
        ganttHeight={containerHeight > 100 ? containerHeight - 70 : undefined}
        locale={lang}
        TaskListHeader={TaskListHeader}
        TaskListTable={TaskListTable}
        TooltipContent={TooltipContent}
        onDateChange={onDateChange}
        onClick={(task) => {
          // Suppress the spurious click the library fires after every bar drag / resize.
          if (Date.now() - lastDragAt.current < 300) return;
          const orig = apiMap.get(task.id);
          if (orig) onTaskClick(orig);
        }}
        onDoubleClick={(task) => {
          const orig = apiMap.get(task.id);
          if (orig) onEditTask(orig);
        }}
      />
    </div>
  );
}
