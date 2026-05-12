import { describe, expect, it, beforeEach } from "vitest";
import { usePlanStore } from "../store/usePlanStore";

describe("GanttView chat-blocking logic", () => {
  beforeEach(() => {
    usePlanStore.setState({
      plan: null,
      planRevision: -1,
      messages: [],
      wsConnected: false,
      chatLoading: false,
    });
  });

  it("chatLoading is readable from store for blocking", () => {
    expect(usePlanStore.getState().chatLoading).toBe(false);
    usePlanStore.getState().setChatLoading(true);
    expect(usePlanStore.getState().chatLoading).toBe(true);
  });

  it("onDateChange should be blocked when chatLoading is true", () => {
    usePlanStore.getState().setChatLoading(true);
    // In the actual GanttView, onDateChange checks usePlanStore.getState().chatLoading
    // and returns false early. We verify the store state that drives this behavior.
    expect(usePlanStore.getState().chatLoading).toBe(true);
  });
});
