import { useEffect, useState } from "react";
import { updateTask, addTask, deleteTask } from "../api/client";
import { usePlanStore } from "../store/usePlanStore";
import type { ApiTask } from "../types";
import { useI18n } from "../i18n/I18nContext";

function useToast() {
  return usePlanStore((s) => s.addToast);
}

interface Props {
  task: ApiTask | null;
  /** When true, the modal opens in "create new task" mode. */
  isNew?: boolean;
  allTasks: ApiTask[];
  onClose: () => void;
}

export function TaskEditModal({ task, isNew, allTasks, onClose }: Props) {
  const setPlan = usePlanStore((s) => s.setPlan);
  const chatLoading = usePlanStore((s) => s.chatLoading);
  const addToast = useToast();
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [assignee, setAssignee] = useState("");
  const [description, setDescription] = useState("");
  const [durationDays, setDurationDays] = useState(1);
  const [startDate, setStartDate] = useState("");
  const [predecessorIds, setPredecessorIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (isNew) {
      setName("");
      setAssignee("");
      setDescription("");
      setDurationDays(1);
      setStartDate("");
      setPredecessorIds([]);
      return;
    }
    if (!task) return;
    setName(task.name);
    setAssignee(task.assignee);
    setDescription(task.description);
    setDurationDays(task.duration_days);
    setStartDate(task.start_date);
    setPredecessorIds(task.predecessor_ids ?? []);
  }, [task, isNew]);

  if (!task && !isNew) return null;

  const otherTasks = isNew ? allTasks : allTasks.filter((t) => t.id !== task!.id);

  async function handleSave() {
    setSaving(true);
    try {
      if (isNew) {
        const res = await addTask({
          name: name.trim(),
          assignee: assignee.trim(),
          description,
          duration_days: durationDays,
          ...(startDate ? { start_date: startDate } : {}),
          predecessor_ids: predecessorIds,
        });
        setPlan(res.plan, typeof res.revision === "number" ? res.revision : undefined);
      } else {
        const res = await updateTask(task!.id, {
          name: name.trim(),
          assignee: assignee.trim(),
          description,
          duration_days: durationDays,
          start_date: startDate,
          predecessor_ids: predecessorIds,
        });
        setPlan(res.plan, typeof res.revision === "number" ? res.revision : undefined);
      }
      onClose();
    } catch (e) {
      onClose();
      addToast(parseError(e), "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!task) return;
    setDeleting(true);
    try {
      const res = await deleteTask(task.id);
      setPlan(res.plan, typeof res.revision === "number" ? res.revision : undefined);
      onClose();
    } catch (e) {
      onClose();
      addToast(parseError(e), "error");
    } finally {
      setDeleting(false);
    }
  }

  function togglePredecessor(id: string) {
    setPredecessorIds((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id],
    );
  }

  const title = isNew ? t.modal.titleAdd : t.modal.title;
  const saveBtnText = isNew
    ? saving ? t.modal.adding : t.modal.add
    : saving ? t.modal.saving : t.modal.save;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 dark:border-slate-700">
          <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">{title}</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 dark:text-slate-500 dark:hover:text-slate-300 transition-colors text-xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-3 max-h-[70vh] overflow-y-auto">
          <Field label={t.modal.name}>
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} autoFocus={isNew} />
          </Field>
          <Field label={t.modal.assignee}>
            <input className={inputCls} value={assignee} onChange={(e) => setAssignee(e.target.value)} />
          </Field>
          <Field label={t.modal.description}>
            <textarea className={`${inputCls} resize-none min-h-[60px]`} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t.modal.startDate}>
              <input type="date" className={inputCls} value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </Field>
            <Field label={t.modal.duration}>
              <input type="number" min={1} max={365} className={inputCls} value={durationDays} onChange={(e) => setDurationDays(Math.max(1, parseInt(e.target.value) || 1))} />
            </Field>
          </div>
          {otherTasks.length > 0 && (
            <Field label={t.modal.predecessors}>
              <div className="border border-slate-200 dark:border-slate-600 rounded-lg divide-y divide-slate-100 dark:divide-slate-700 max-h-36 overflow-y-auto">
                {otherTasks.map((t2) => (
                  <label key={t2.id} className="flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-700/50">
                    <input type="checkbox" checked={predecessorIds.includes(t2.id)} onChange={() => togglePredecessor(t2.id)} className="rounded border-slate-300 dark:border-slate-600 text-slate-900" />
                    <span className="text-slate-700 dark:text-slate-200 truncate">{t2.name}</span>
                    <span className="ml-auto text-xs text-slate-400 dark:text-slate-500">{t2.id}</span>
                  </label>
                ))}
              </div>
            </Field>
          )}

          {chatLoading && (
            <p className="text-sm text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-lg px-3 py-2">
              {t.modal.aiEditing}
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center px-5 py-4 border-t border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
          {!isNew && (
            <button
              onClick={() => void handleDelete()}
              disabled={deleting || chatLoading}
              className="px-3 py-2 text-sm rounded-lg border border-red-200 dark:border-red-700 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-40 transition"
            >
              {deleting ? t.modal.deleting : t.modal.delete}
            </button>
          )}
          <div className="flex-1" />
          <div className="flex gap-2">
            <button onClick={onClose} className="px-4 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition">
              {t.modal.cancel}
            </button>
            <button onClick={() => void handleSave()} disabled={saving || !name.trim() || chatLoading} className="px-4 py-2 text-sm rounded-lg bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 hover:bg-slate-700 dark:hover:bg-white disabled:opacity-40 transition">
              {saveBtnText}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function parseError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e);
  try {
    const parsed = JSON.parse(raw);
    const detail = parsed?.detail;
    if (detail && typeof detail === "object" && detail.detail) return detail.detail;
    if (typeof detail === "string") return detail;
  } catch { /* use raw */ }
  return raw;
}

const inputCls =
  "w-full border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-1.5 text-sm bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-300 dark:focus:ring-slate-500 transition";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wide">
        {label}
      </label>
      {children}
    </div>
  );
}
