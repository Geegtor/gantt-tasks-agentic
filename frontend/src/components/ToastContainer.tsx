import { usePlanStore } from "../store/usePlanStore";

export function ToastContainer() {
  const toasts = usePlanStore((s) => s.toasts);
  const removeToast = usePlanStore((s) => s.removeToast);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 max-w-sm">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`flex items-start gap-2 px-4 py-3 rounded-xl shadow-lg text-sm animate-in slide-in-from-bottom-2 ${
            t.type === "error"
              ? "bg-red-600 text-white"
              : "bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-900"
          }`}
        >
          <span className="flex-1 break-words">{t.message}</span>
          <button
            onClick={() => removeToast(t.id)}
            className="shrink-0 opacity-70 hover:opacity-100 text-lg leading-none"
          >
            &times;
          </button>
        </div>
      ))}
    </div>
  );
}
