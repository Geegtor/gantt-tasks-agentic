import { useRef } from "react";
import { exportUrl, uploadExcel } from "../api/client";
import { usePlanStore } from "../store/usePlanStore";
import { useI18n } from "../i18n/I18nContext";

export function ExcelControls() {
  const inputRef = useRef<HTMLInputElement>(null);
  const setPlan = usePlanStore((s) => s.setPlan);
  const addMessage = usePlanStore((s) => s.addMessage);
  const { t } = useI18n();

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    try {
      const { plan, revision } = await uploadExcel(f);
      setPlan(plan, typeof revision === "number" ? revision : undefined);
      addMessage({ role: "assistant", content: `Loaded Excel: ${f.name} (${plan.tasks.length} tasks).` });
    } catch (err) {
      addMessage({
        role: "error",
        content: err instanceof Error ? err.message : String(err),
      });
    }
  }

  return (
    <div className="flex flex-wrap gap-2 items-center">
      <input ref={inputRef} type="file" accept=".xlsx,.xls" className="hidden" onChange={onFile} />
      <button
        type="button"
        className="px-3 py-1.5 text-sm bg-slate-100 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 text-slate-700 dark:text-slate-200 rounded hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
        onClick={() => inputRef.current?.click()}
      >
        {t.uploadExcel}
      </button>
      <a
        href={exportUrl()}
        className="px-3 py-1.5 text-sm bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 rounded hover:bg-slate-700 dark:hover:bg-white transition-colors"
        download
      >
        {t.exportExcel}
      </a>
    </div>
  );
}
