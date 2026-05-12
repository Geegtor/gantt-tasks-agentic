import { KeyboardEvent, useEffect, useRef, useState } from "react";
import { sendChat, undoChat } from "../api/client";
import { usePlanStore } from "../store/usePlanStore";
import { useI18n } from "../i18n/I18nContext";

function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatErrorContent(raw: string): string {
  try {
    const parsed = JSON.parse(raw);
    const detail = parsed?.detail;
    if (detail && typeof detail === "object" && detail.error) {
      const code = detail.error as string;
      const msg = detail.detail as string | undefined;
      return msg ? `${msg}` : code.replace(/_/g, " ");
    }
    if (typeof detail === "string") return detail;
    return raw;
  } catch {
    if (raw.startsWith("{")) {
      const m = raw.match(/"detail"\s*:\s*"([^"]+)"/);
      if (m) return m[1];
      const m2 = raw.match(/"error"\s*:\s*"([^"]+)".*?"detail"\s*:\s*"([^"]+)"/);
      if (m2) return m2[2];
    }
    return raw;
  }
}

export function ChatPanel() {
  const [input, setInput] = useState("");
  const [canUndo, setCanUndo] = useState(false);
  const addMessage = usePlanStore((s) => s.addMessage);
  const setPlan = usePlanStore((s) => s.setPlan);
  const setChatLoading = usePlanStore((s) => s.setChatLoading);
  const chatLoading = usePlanStore((s) => s.chatLoading);
  const messages = usePlanStore((s) => s.messages);
  const wsConnected = usePlanStore((s) => s.wsConnected);
  const { t } = useI18n();

  const messagesEndRef = useRef<HTMLDivElement>(null);
  /** Chains user text across clarify follow-ups; cleared when a command applies. */
  const pendingContextRef = useRef<string | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSubmit() {
    const text = input.trim();
    if (!text || chatLoading) return;
    addMessage({ role: "user", content: text });
    setInput("");
    setChatLoading(true);
    const payload = pendingContextRef.current
      ? `[Context from previous message(s): ${pendingContextRef.current}]\n${text}`
      : text;
    try {
      const res = await sendChat(payload);
      if (res.clarify) {
        pendingContextRef.current = pendingContextRef.current
          ? `${pendingContextRef.current}\n${text}`
          : text;
      } else {
        pendingContextRef.current = null;
      }
      let extra = "";
      if (res.clarify) extra += `\n\n${res.clarify}`;
      let metaText = "";
      if (res.meta?.provenance === "replay") {
        metaText += "[cached] Reused a prior successful edit (semantic replay).";
      }
      if (res.meta) {
        const m = res.meta;
        if (m.applied === 0 || m.plan_changed === false) {
          metaText +=
            (metaText ? "\n" : "") +
            `applied=${m.applied ?? "?"}` +
            (m.ops?.length ? ` ops=${m.ops.join(",")}` : "") +
            (m.reason ? ` reason=${m.reason}` : "") +
            (m.plan_changed === false ? ` ${t.chat.noChange}` : "") +
            (m.provenance ? ` provenance=${m.provenance}` : "");
        }
      }
      addMessage({ role: "assistant", content: res.summary + extra, meta: metaText || undefined });
      setPlan(res.plan, typeof res.revision === "number" ? res.revision : undefined);
      if (res.meta && res.meta.applied && res.meta.applied > 0) {
        setCanUndo(true);
      }
    } catch (err) {
      addMessage({
        role: "error",
        content: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setChatLoading(false);
    }
  }

  async function handleUndo() {
    if (chatLoading) return;
    setChatLoading(true);
    try {
      const res = await undoChat();
      setPlan(res.plan, typeof res.revision === "number" ? res.revision : undefined);
      addMessage({ role: "assistant", content: t.chat.undoOk });
      setCanUndo(false);
    } catch {
      addMessage({ role: "error", content: t.chat.undoFail });
      setCanUndo(false);
    } finally {
      setChatLoading(false);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit();
    }
  }

  const canSend = input.trim().length > 0 && !chatLoading;

  return (
    <div className="flex flex-col h-full overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 transition-colors duration-200">
      {/* Header */}
      <div className="shrink-0 px-3 py-2 border-b border-slate-100 dark:border-slate-700 text-sm font-medium text-slate-700 dark:text-slate-200 flex justify-between items-center">
        <span>{t.chat.title}</span>
        <span className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void handleUndo()}
            disabled={!canUndo || chatLoading}
            title={t.chat.undo}
            className="w-6 h-6 flex items-center justify-center rounded text-slate-500 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-600 disabled:opacity-30 disabled:pointer-events-none transition"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5">
              <path d="M3 7v6h6" /><path d="M3 13a9 9 0 0 1 3-7.5A9 9 0 0 1 21 12a9 9 0 0 1-9 9 9 9 0 0 1-6.7-3" />
            </svg>
          </button>
          <span className={`text-xs flex items-center gap-1 ${wsConnected ? "text-emerald-500" : "text-amber-500"}`}>
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${wsConnected ? "bg-emerald-500" : "bg-amber-400"}`} />
            {wsConnected ? t.chat.live : t.chat.connecting}
          </span>
        </span>
      </div>

      {/* Messages — scrolls independently */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 text-sm min-h-0">
        {messages.length === 0 && (
          <p className="text-slate-400 dark:text-slate-500 text-xs text-center pt-4">
            {t.chat.hint}
            <br />
            <span className="text-slate-300 dark:text-slate-600">{t.chat.hintExample}</span>
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={
                m.role === "user"
                  ? "bg-blue-600 dark:bg-blue-700 text-white rounded-2xl rounded-br-sm px-3 py-2 max-w-[85%] text-sm"
                  : m.role === "error"
                    ? "bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 text-red-700 dark:text-red-300 rounded-2xl rounded-bl-sm px-3 py-2 max-w-[85%] text-sm"
                    : "bg-slate-100 dark:bg-slate-700 text-slate-800 dark:text-slate-100 rounded-2xl rounded-bl-sm px-3 py-2 max-w-[85%] text-sm"
              }
            >
              <span className="whitespace-pre-wrap">
                {m.role === "error" ? formatErrorContent(m.content) : m.content}
              </span>
              <span className={`flex items-center gap-1 text-[10px] mt-1 ${m.role === "user" ? "text-blue-200" : m.role === "error" ? "text-red-400 dark:text-red-500" : "text-slate-400 dark:text-slate-500"}`}>
                {formatTime(m.timestamp)}
                {m.meta && (
                  <span
                    title={m.meta}
                    className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full text-[9px] bg-slate-300 dark:bg-slate-500 text-slate-600 dark:text-slate-200 cursor-help"
                  >?</span>
                )}
              </span>
            </div>
          </div>
        ))}
        {chatLoading && (
          <div className="flex justify-start">
            <div className="bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-300 rounded-2xl rounded-bl-sm px-3 py-2 text-sm">
              <span className="inline-flex gap-1">
                <span className="animate-bounce [animation-delay:0ms]">•</span>
                <span className="animate-bounce [animation-delay:150ms]">•</span>
                <span className="animate-bounce [animation-delay:300ms]">•</span>
              </span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="shrink-0 p-2 border-t border-slate-100 dark:border-slate-700">
        <div className="relative">
          <textarea
            className="w-full border border-slate-200 dark:border-slate-600 rounded-xl px-3 py-2 pr-11 text-sm resize-none h-[72px] focus:outline-none focus:ring-2 focus:ring-slate-300 dark:focus:ring-slate-500 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 disabled:opacity-50 transition"
            placeholder={t.chat.placeholder}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={chatLoading}
          />
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={!canSend}
            aria-label="Send message"
            className="absolute bottom-2.5 right-2.5 w-7 h-7 flex items-center justify-center rounded-lg bg-blue-600 dark:bg-blue-500 text-white disabled:opacity-30 hover:bg-blue-700 dark:hover:bg-blue-400 active:scale-95 transition-all"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="w-4 h-4"
            >
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
