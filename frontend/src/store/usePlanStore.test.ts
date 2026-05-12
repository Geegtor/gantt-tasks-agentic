import { describe, expect, it, beforeEach } from "vitest";
import { usePlanStore } from "./usePlanStore";

const samplePlan = {
  project_start: "2026-01-01",
  tasks: [],
};

describe("usePlanStore", () => {
  beforeEach(() => {
    usePlanStore.setState({
      plan: null,
      planRevision: -1,
      messages: [],
      wsConnected: false,
      chatLoading: false,
    });
  });

  it("increments revision when revision is not provided", () => {
    usePlanStore.getState().setPlan(samplePlan);
    expect(usePlanStore.getState().planRevision).toBe(0);
    usePlanStore.getState().setPlan(samplePlan);
    expect(usePlanStore.getState().planRevision).toBe(1);
  });

  it("uses explicit revision when provided", () => {
    usePlanStore.getState().setPlan(samplePlan, 7);
    expect(usePlanStore.getState().planRevision).toBe(7);
  });

  it("appends chat messages", () => {
    usePlanStore.getState().addMessage({ role: "user", content: "hello" });
    usePlanStore.getState().addMessage({ role: "assistant", content: "world" });
    expect(usePlanStore.getState().messages).toHaveLength(2);
  });
});
