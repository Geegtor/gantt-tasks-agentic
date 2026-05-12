import { useEffect, useState } from "react";
import { fetchPlan, getWsUrl } from "./api/client";
import type { ApiTask, ProjectPlan } from "./types";
import { ChatPanel } from "./components/ChatPanel";
import { ExcelControls } from "./components/ExcelControls";
import { GanttView } from "./components/GanttView";
import { TaskEditModal } from "./components/TaskEditModal";
import { usePlanStore } from "./store/usePlanStore";
import { useTheme } from "./hooks/useTheme";
import { useI18n } from "./i18n/I18nContext";

export function shouldApplyIncomingRevision(
  incomingRevision: number | undefined,
  currentRevision: number,
): boolean {
  if (typeof incomingRevision !== "number") return true;
  if (currentRevision < 0) return true;
  return incomingRevision >= currentRevision;
}

function usePlanWebSocket() {
  const setPlan = usePlanStore((s) => s.setPlan);
  const setWsConnected = usePlanStore((s) => s.setWsConnected);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout>;

    function connect() {
      if (closed) return;
      const url = getWsUrl();
      ws = new WebSocket(url);
      ws.onopen = () => {
        attempt = 0;
        setWsConnected(true);
      };
      ws.onclose = () => {
        setWsConnected(false);
        attempt += 1;
        const delay = Math.min(30000, 1000 * 2 ** attempt);
        timer = setTimeout(connect, delay);
      };
      ws.onerror = () => {
        ws?.close();
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data as string) as {
            type?: string;
            revision?: number;
            plan?: ProjectPlan;
          };
          if (data.type !== "plan_updated" || !data.plan) return;
          const incoming = data.revision;
          const current = usePlanStore.getState().planRevision;
          if (!shouldApplyIncomingRevision(incoming, current)) return;
          setPlan(data.plan, typeof incoming === "number" ? incoming : undefined);
        } catch {
          /* ignore */
        }
      };
    }

    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, [setPlan, setWsConnected]);
}

function ThemeToggle({ isDark, onToggle }: { isDark: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      aria-label="Toggle dark mode"
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className="flex items-center justify-center w-8 h-8 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-600 transition-colors duration-200"
    >
      {isDark ? (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
          <circle cx="12" cy="12" r="5" />
          <line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
          <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
          <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
          <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
        </svg>
      ) : (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      )}
    </button>
  );
}

export default function App() {
  const plan = usePlanStore((s) => s.plan);
  const setPlan = usePlanStore((s) => s.setPlan);
  const [editingTask, setEditingTask] = useState<ApiTask | null>(null);
  const [addingNew, setAddingNew] = useState(false);
  const { isDark, toggle: toggleTheme } = useTheme();
  const { lang, t, toggleLang } = useI18n();

  usePlanWebSocket();

  useEffect(() => {
    let cancelled = false;
    fetchPlan()
      .then(({ plan, revision }) => {
        if (!cancelled) setPlan(plan, revision);
      })
      .catch((e) => {
        if (!cancelled) {
          usePlanStore.getState().addMessage({
            role: "error",
            content: `Failed to load plan: ${e instanceof Error ? e.message : String(e)}`,
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [setPlan]);

  const tasks = plan?.tasks ?? [];

  return (
    // Root fills exactly the viewport; no page scroll — both panels scroll internally
    <div className="h-screen flex flex-col bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-slate-100 overflow-hidden transition-colors duration-200">
      {/* ── Header ─────────────────────────────────────────────── */}
      <header className="shrink-0 border-b border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-2.5 flex flex-wrap gap-3 items-center justify-between transition-colors duration-200">
        <h1 className="text-lg font-semibold tracking-tight">{t.appName}</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setAddingNew(true)}
            title={t.modal.titleAdd}
            className="px-3 py-1.5 text-sm bg-slate-100 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 text-slate-700 dark:text-slate-200 rounded hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
          >
            {t.modal.titleAdd}
          </button>
          <ExcelControls />
          <button
            onClick={toggleLang}
            title={lang === "en" ? "Переключить на русский" : "Switch to English"}
            className="flex items-center justify-center h-8 px-2.5 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-600 transition-colors duration-200 text-xs font-semibold tracking-wide"
          >
            {lang === "en" ? "RU" : "EN"}
          </button>
          <ThemeToggle isDark={isDark} onToggle={toggleTheme} />
        </div>
      </header>

      {/* ── Main: side-by-side on lg, stacked on mobile ────────── */}
      <main className="flex-1 flex flex-col lg:flex-row gap-3 p-3 overflow-hidden min-h-0">
        {/* Gantt — scrolls inside its wrapper */}
        <section className="flex-1 min-w-0 min-h-0 overflow-hidden rounded-lg">
          <GanttView tasks={tasks} onTaskClick={setEditingTask} onEditTask={setEditingTask} />
        </section>

        {/* Chat — fixed width on lg, full width on mobile, always contained */}
        <aside className="w-full lg:w-[360px] shrink-0 min-h-0 flex flex-col overflow-hidden">
          <ChatPanel />
        </aside>
      </main>

      <TaskEditModal task={editingTask} allTasks={tasks} onClose={() => setEditingTask(null)} />
      {addingNew && (
        <TaskEditModal task={null} isNew allTasks={tasks} onClose={() => setAddingNew(false)} />
      )}
    </div>
  );
}
