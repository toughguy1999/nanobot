import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "@/features/chat/components/Sidebar";
import { SIDEBAR_COLLAPSED_STORAGE_KEY } from "@/features/chat/hooks/useSidebarPreference";
import type { Session } from "@/features/chat/model/chat.types";

const sessions: Session[] = [
  {
    id: "pinned-session",
    sessionTitle: "置顶会话标题",
    createdAt: "2026-06-24T00:00:00.000Z",
    updatedAt: "2026-06-25T00:00:00.000Z",
    pinned: true,
    messages: []
  },
  {
    id: "regular-session",
    sessionTitle: "普通会话标题",
    createdAt: "2026-06-23T00:00:00.000Z",
    updatedAt: "2026-06-24T00:00:00.000Z",
    pinned: false,
    messages: []
  }
];

function createProps() {
  return {
    sessions,
    activeSessionId: "regular-session",
    onCreateSession: vi.fn(),
    onDeleteSession: vi.fn(),
    onPinSession: vi.fn(),
    onSelectSession: vi.fn(),
    onUnpinSession: vi.fn()
  };
}

function renderSidebar() {
  const props = createProps();
  return {
    props,
    ...render(<Sidebar {...props} />)
  };
}

describe("Sidebar", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders expanded by default", () => {
    renderSidebar();

    expect(screen.getByRole("complementary")).toHaveClass("w-72");
    expect(screen.getByText("Nanobot")).toBeVisible();
    expect(screen.getByRole("button", { name: "收起侧边栏" })).toBeVisible();
    expect(screen.getByRole("button", { name: "新建会话" })).toBeVisible();
    expect(screen.getByText("置顶会话标题")).toBeVisible();
    expect(screen.getByText("普通会话标题")).toBeVisible();
  });

  it("creates a session once", async () => {
    const user = userEvent.setup();
    const { props } = renderSidebar();

    await user.click(screen.getByRole("button", { name: "新建会话" }));

    expect(props.onCreateSession).toHaveBeenCalledTimes(1);
  });

  it("collapses and unmounts expanded content", async () => {
    const user = userEvent.setup();
    renderSidebar();

    await user.click(screen.getByRole("button", { name: "收起侧边栏" }));

    expect(screen.getByRole("complementary")).toHaveClass("w-14");
    expect(screen.queryByText("Nanobot")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "新建会话" })).not.toBeInTheDocument();
    expect(screen.queryByText("置顶会话标题")).not.toBeInTheDocument();
    expect(screen.queryByText("普通会话标题")).not.toBeInTheDocument();
    expect(screen.queryByText("置顶")).not.toBeInTheDocument();
    expect(screen.queryByText("会话")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "展开侧边栏" })).toBeVisible();
  });

  it("switches the collapsed entry icon on hover and focus", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, "true");
    renderSidebar();

    const expandButton = screen.getByRole("button", { name: "展开侧边栏" });
    expect(expandButton).toHaveTextContent("🐈");

    await user.hover(expandButton);
    expect(screen.getByTestId("sidebar-expand-icon")).toBeInTheDocument();
    await user.unhover(expandButton);
    expect(expandButton).toHaveTextContent("🐈");

    fireEvent.focus(expandButton);
    expect(screen.getByTestId("sidebar-expand-icon")).toBeInTheDocument();
    fireEvent.blur(expandButton);
    expect(expandButton).toHaveTextContent("🐈");
  });

  it("expands after clicking the collapsed entry", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, "true");
    renderSidebar();

    await user.click(screen.getByRole("button", { name: "展开侧边栏" }));

    expect(screen.getByRole("complementary")).toHaveClass("w-72");
    expect(screen.getByText("Nanobot")).toBeVisible();
    expect(screen.getByRole("button", { name: "新建会话" })).toBeVisible();
    expect(screen.getByText("普通会话标题")).toBeVisible();
  });

  it.each(["{Enter}", " "])("expands from the keyboard with %s", async (key) => {
    const user = userEvent.setup();
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, "true");
    renderSidebar();

    await user.tab();
    expect(screen.getByRole("button", { name: "展开侧边栏" })).toHaveFocus();
    await user.keyboard(key);

    expect(screen.getByRole("complementary")).toHaveClass("w-72");
  });

  it("closes an open session menu when collapsed", async () => {
    const user = userEvent.setup();
    renderSidebar();

    await user.click(screen.getAllByRole("button", { name: "会话菜单" })[1]);
    expect(screen.getByRole("button", { name: "置顶" })).toBeVisible();
    expect(screen.getByRole("button", { name: "删除" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "收起侧边栏" }));

    expect(screen.queryByRole("button", { name: "置顶" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "删除" })).not.toBeInTheDocument();
  });

  it("does not invoke session actions while toggling the sidebar", async () => {
    const user = userEvent.setup();
    const { props } = renderSidebar();

    await user.click(screen.getByRole("button", { name: "收起侧边栏" }));
    await user.click(screen.getByRole("button", { name: "展开侧边栏" }));

    expect(props.onSelectSession).not.toHaveBeenCalled();
    expect(props.onPinSession).not.toHaveBeenCalled();
    expect(props.onUnpinSession).not.toHaveBeenCalled();
    expect(props.onDeleteSession).not.toHaveBeenCalled();
  });

  it("restores a stored collapsed preference without an initial transition", () => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, "true");

    renderSidebar();

    expect(screen.getByRole("complementary")).toHaveClass(
      "w-14",
      "transition-[width]",
      "duration-200",
      "ease-in-out"
    );
  });
});
