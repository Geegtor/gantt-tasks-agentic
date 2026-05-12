import type { ProjectPlan } from "../types";

const API = import.meta.env.VITE_API_URL?.replace(/\/$/, "") || "";
const WS = import.meta.env.VITE_WS_URL || "";

export function getApiBase(): string {
  return API;
}

export function getWsUrl(): string {
  if (WS) return WS;
  if (typeof window !== "undefined") {
    const u = new URL(API || window.location.origin);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.pathname = "/ws";
    u.search = "";
    u.hash = "";
    return u.toString();
  }
  return "ws://localhost:8000/ws";
}

export async function fetchPlan(): Promise<{ plan: ProjectPlan; revision: number }> {
  const r = await fetch(`${API}/tasks`, { cache: "no-store" });
  if (!r.ok) throw new Error(await r.text());
  const j = (await r.json()) as { plan: ProjectPlan; revision?: number };
  return { plan: j.plan, revision: typeof j.revision === "number" ? j.revision : 0 };
}

export interface ChatMeta {
  applied?: number;
  reason?: string;
  ops?: string[];
  plan_changed?: boolean;
  /** llm | replay | repair */
  provenance?: string;
}

export async function sendChat(message: string): Promise<{
  summary: string;
  plan: ProjectPlan;
  revision?: number;
  clarify?: string;
  meta?: ChatMeta;
}> {
  const r = await fetch(`${API}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    cache: "no-store",
  });
  const text = await r.text();
  if (!r.ok) throw new Error(text);
  return JSON.parse(text) as {
    summary: string;
    plan: ProjectPlan;
    revision?: number;
    clarify?: string;
    meta?: ChatMeta;
  };
}

export async function uploadExcel(file: File): Promise<{ plan: ProjectPlan; revision?: number }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${API}/upload`, { method: "POST", body: fd, cache: "no-store" });
  if (!r.ok) throw new Error(await r.text());
  const j = (await r.json()) as { plan: ProjectPlan; revision?: number };
  return { plan: j.plan, revision: j.revision };
}

export async function updateTask(
  taskId: string,
  patch: {
    name?: string;
    description?: string;
    assignee?: string;
    duration_days?: number;
    start_date?: string;
    predecessor_ids?: string[];
  },
): Promise<{ plan: ProjectPlan; revision?: number }> {
  const r = await fetch(`${API}/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ plan: ProjectPlan; revision?: number }>;
}

export async function addTask(data: {
  name: string;
  description?: string;
  assignee?: string;
  duration_days?: number;
  start_date?: string;
  predecessor_ids?: string[];
}): Promise<{ plan: ProjectPlan; revision?: number }> {
  const r = await fetch(`${API}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ plan: ProjectPlan; revision?: number }>;
}

export async function deleteTask(taskId: string): Promise<{ plan: ProjectPlan; revision?: number }> {
  const r = await fetch(`${API}/tasks/${taskId}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ plan: ProjectPlan; revision?: number }>;
}

export function exportUrl(): string {
  return `${API}/export`;
}
