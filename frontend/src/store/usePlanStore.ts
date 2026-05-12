import { create } from "zustand";
import type { ProjectPlan } from "../types";

export interface ChatMessage {
  role: "user" | "assistant" | "error";
  content: string;
  timestamp: number;
}

interface PlanState {
  plan: ProjectPlan | null;
  /** Server monotonic revision; drop WebSocket payloads with lower revision (stale). */
  planRevision: number;
  messages: ChatMessage[];
  wsConnected: boolean;
  chatLoading: boolean;
  /** Pass `revision` from API/WS when available so we can ignore stale socket replays. */
  setPlan: (plan: ProjectPlan, revision?: number) => void;
  setWsConnected: (v: boolean) => void;
  addMessage: (m: Omit<ChatMessage, "timestamp"> & { timestamp?: number }) => void;
  setChatLoading: (v: boolean) => void;
}

export const usePlanStore = create<PlanState>((set) => ({
  plan: null,
  planRevision: -1,
  messages: [],
  wsConnected: false,
  chatLoading: false,
  setPlan: (plan, revision) =>
    set((s) => {
      const nextRev =
        typeof revision === "number"
          ? revision
          : s.planRevision < 0
            ? 0
            : s.planRevision + 1;
      return { plan, planRevision: nextRev };
    }),
  setWsConnected: (wsConnected) => set({ wsConnected }),
  addMessage: (m) => set((s) => ({ messages: [...s.messages, { ...m, timestamp: m.timestamp ?? Date.now() }] })),
  setChatLoading: (chatLoading) => set({ chatLoading }),
}));
