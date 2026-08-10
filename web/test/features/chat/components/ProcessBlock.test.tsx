import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AssistantMessage } from "@/features/chat/components/AssistantMessage";
import { ProcessBlock } from "@/features/chat/components/ProcessBlock";

describe("ProcessBlock", () => {
  it("starts collapsed, shows reasoning before ordered tools, and resets on remount", async () => {
    const user = userEvent.setup();
    const props = {
      reasoningContent: "**reasoning first**",
      toolCalls: [
        { id: "call-1", name: "first", arguments: '{"nested":{"value":1}}' },
        { id: "call-2", name: "second", arguments: "not-json" }
      ]
    };
    const view = render(<ProcessBlock {...props} />);
    const toggle = screen.getByRole("button", { name: "思考过程" });

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("reasoning first")).not.toBeInTheDocument();

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const reasoning = screen.getByText("reasoning first");
    const first = screen.getByText("first");
    const second = screen.getByText("second");
    expect(reasoning.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText(/"nested": \{/)).toBeInTheDocument();
    expect(screen.getByText("not-json")).toBeInTheDocument();

    view.unmount();
    render(<ProcessBlock {...props} />);
    expect(screen.getByRole("button", { name: "思考过程" })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
  });

  it("supports tool-only, reasoning-only, and final reasoning plus answer", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <AssistantMessage
        message={{
          id: "stage",
          role: "assistant",
          content: "hidden stage content",
          toolCalls: [{ id: "call", name: "search", arguments: "{}" }],
          createdAt: "2026-08-08T10:00:00"
        }}
      />
    );
    expect(screen.getByRole("button", { name: "思考过程" })).toBeInTheDocument();
    expect(screen.queryByText("hidden stage content")).not.toBeInTheDocument();

    rerender(
      <AssistantMessage
        message={{
          id: "reasoning",
          role: "assistant",
          content: "",
          reasoningContent: "only reasoning",
          createdAt: "2026-08-08T10:00:01"
        }}
      />
    );
    await user.click(screen.getByRole("button", { name: "思考过程" }));
    expect(screen.getByText("only reasoning")).toBeVisible();

    rerender(
      <AssistantMessage
        message={{
          id: "final",
          role: "assistant",
          content: "**final answer**",
          reasoningContent: "final reasoning",
          createdAt: "2026-08-08T10:00:02"
        }}
      />
    );
    expect(screen.getByText("final answer")).toBeVisible();
  });

  it("keeps multiple stage expansion state independent", async () => {
    const user = userEvent.setup();
    render(
      <>
        <ProcessBlock reasoningContent="first reasoning" />
        <ProcessBlock reasoningContent="second reasoning" />
      </>
    );
    const toggles = screen.getAllByRole("button", { name: "思考过程" });

    await user.click(toggles[0]);

    expect(toggles[0]).toHaveAttribute("aria-expanded", "true");
    expect(toggles[1]).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("first reasoning")).toBeVisible();
    expect(screen.queryByText("second reasoning")).not.toBeInTheDocument();
  });
});
