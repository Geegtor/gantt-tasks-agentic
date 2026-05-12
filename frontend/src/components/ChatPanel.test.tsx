import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ChatPanel } from "./ChatPanel";
import { I18nProvider } from "../i18n/I18nContext";
import { usePlanStore } from "../store/usePlanStore";
import { sendChat } from "../api/client";

vi.mock("../api/client", () => ({
  sendChat: vi.fn(),
}));

describe("ChatPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    usePlanStore.setState({
      plan: null,
      planRevision: -1,
      messages: [],
      wsConnected: false,
      chatLoading: false,
    });
  });

  it("renders and sends a chat message", async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      summary: "Done",
      plan: { tasks: [], project_start: "2026-01-01" },
      revision: 1,
    });

    render(
      <I18nProvider>
        <ChatPanel />
      </I18nProvider>,
    );

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Move QA by 2 days" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => expect(sendChat).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText("Done")).toBeInTheDocument());
  });

  it("chains clarify context into the next request", async () => {
    vi.mocked(sendChat)
      .mockResolvedValueOnce({
        summary: "Need clarification",
        clarify: "Which QA task do you mean?",
        plan: { tasks: [], project_start: "2026-01-01" },
        revision: 1,
      })
      .mockResolvedValueOnce({
        summary: "Applied",
        plan: { tasks: [], project_start: "2026-01-01" },
        revision: 2,
      });

    render(
      <I18nProvider>
        <ChatPanel />
      </I18nProvider>,
    );

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Move QA task" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));
    await waitFor(() => expect(sendChat).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "The final QA task" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));
    await waitFor(() => expect(sendChat).toHaveBeenCalledTimes(2));

    const secondCallPayload = vi.mocked(sendChat).mock.calls[1][0];
    expect(secondCallPayload).toContain("[Context from previous message(s): Move QA task]");
    expect(secondCallPayload).toContain("The final QA task");
  });

  it("disables send button when chatLoading is true", () => {
    usePlanStore.setState({ chatLoading: true });

    render(
      <I18nProvider>
        <ChatPanel />
      </I18nProvider>,
    );

    const sendBtn = screen.getByRole("button", { name: /send message/i });
    expect(sendBtn).toBeDisabled();
  });
});
