import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownContent } from "@/features/chat/components/MarkdownContent";
import { ConversationView } from "@/features/chat/components/ConversationView";

describe("MarkdownContent", () => {
  it("renders shared GFM structures", () => {
    const { container } = render(
      <MarkdownContent
        content={[
          "# Heading",
          "- item",
          "> quote",
          "| A | B |\n| - | - |\n| 1 | 2 |",
          "`inline`",
          "```ts",
          "const value = 1",
          "```"
        ].join("\n\n")}
      />
    );

    expect(screen.getByRole("heading", { name: "Heading" })).toBeVisible();
    expect(screen.getByRole("list")).toBeVisible();
    expect(container.querySelector("blockquote")).toHaveTextContent("quote");
    expect(screen.getByRole("table")).toBeVisible();
    expect(screen.getByText("inline").tagName).toBe("CODE");
    expect(screen.getByText("const value = 1").closest("pre")).toBeInTheDocument();
  });

  it("does not create raw HTML or executable links", () => {
    const { container } = render(
      <MarkdownContent
        content={'<mark data-danger="yes">raw</mark> [bad](javascript:alert(1)) [safe](https://example.com)'}
      />
    );

    expect(container.querySelector("mark")).not.toBeInTheDocument();
    expect(container.querySelector('[data-danger="yes"]')).not.toBeInTheDocument();
    expect(screen.getByText("bad").closest("a")).toHaveAttribute("href", "");
    expect(screen.getByRole("link", { name: "safe" })).toHaveAttribute(
      "rel",
      "noopener noreferrer nofollow"
    );
  });

  it("is used for user, assistant, and reasoning content", () => {
    render(
      <ConversationView
        session={{
          id: "one",
          createdAt: "2026-08-08T10:00:00",
          updatedAt: "2026-08-08T10:00:00",
          messages: [
            {
              id: "user",
              role: "user",
              content: "**user markdown**",
              createdAt: "2026-08-08T10:00:00"
            },
            {
              id: "assistant",
              role: "assistant",
              content: "`assistant markdown`",
              createdAt: "2026-08-08T10:00:01"
            },
            {
              id: "reasoning",
              role: "assistant",
              content: "",
              reasoningContent: "# reasoning markdown",
              createdAt: "2026-08-08T10:00:02"
            }
          ]
        }}
      />
    );

    expect(screen.getByText("user markdown").tagName).toBe("STRONG");
    expect(screen.getByText("assistant markdown").tagName).toBe("CODE");
    expect(screen.getByRole("button", { name: "思考过程" })).toBeInTheDocument();
  });
});
