import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { MessageInput } from "@/features/chat/components/MessageInput";
import type { DraftAttachment } from "@/features/chat/model/chat.types";

const readyAttachment: DraftAttachment = {
  fileId: "att_one",
  fileName: "notes.txt",
  mimeType: "text/plain",
  extension: "txt",
  size: 5,
  type: "text",
  status: "ready"
};

function createProps(overrides: Partial<ComponentProps<typeof MessageInput>> = {}) {
  return {
    value: "",
    disabled: false,
    attachments: [],
    isUploadingAttachments: false,
    onChange: vi.fn(),
    onAddFiles: vi.fn(),
    onRemoveAttachment: vi.fn(),
    onSend: vi.fn(),
    ...overrides
  };
}

describe("MessageInput", () => {
  it("renders attachments and removes an item", async () => {
    const user = userEvent.setup();
    const props = createProps({ attachments: [readyAttachment] });
    render(<MessageInput {...props} />);
    const chip = screen.getByText("notes.txt").closest("div");

    expect(screen.getByText("notes.txt")).toBeVisible();
    expect(chip).toHaveClass("rounded-[20px]");
    expect(chip).not.toHaveClass("border");
    await user.click(screen.getByRole("button", { name: "移除附件 notes.txt" }));

    expect(props.onRemoveAttachment).toHaveBeenCalledWith("att_one");
  });

  it("renders draft attachments outside the textarea surface", () => {
    const props = createProps({ attachments: [readyAttachment] });
    render(<MessageInput {...props} />);

    const chip = screen.getByText("notes.txt");
    const textareaSurface = screen.getByLabelText("消息内容").parentElement;

    expect(textareaSurface).not.toContainElement(chip);
  });

  it("passes selected files from the add-file input", () => {
    const props = createProps();
    const { container } = render(<MessageInput {...props} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });

    fireEvent.change(input, { target: { files: [file] } });

    expect(props.onAddFiles).toHaveBeenCalledWith([file]);
  });

  it("disables send while an attachment is uploading", () => {
    render(
      <MessageInput
        {...createProps({
          value: "hello",
          attachments: [{ ...readyAttachment, fileId: "uploading-one", status: "uploading" }],
          isUploadingAttachments: true
        })}
      />
    );

    expect(screen.getByRole("button", { name: "发送消息" })).toBeDisabled();
    expect(screen.getByText("上传中")).toBeVisible();
  });

  it("allows sending with only a ready attachment", async () => {
    const user = userEvent.setup();
    const props = createProps({ attachments: [readyAttachment] });
    render(<MessageInput {...props} />);

    await user.click(screen.getByRole("button", { name: "发送消息" }));

    expect(props.onSend).toHaveBeenCalledTimes(1);
  });

  it("keeps Enter-to-send behavior", () => {
    const props = createProps({ value: "hello" });
    render(<MessageInput {...props} />);

    fireEvent.keyDown(screen.getByLabelText("消息内容"), { key: "Enter" });

    expect(props.onSend).toHaveBeenCalledTimes(1);
  });

  it("keeps textarea height at the 64px minimum when content is short", () => {
    const props = createProps();
    const { rerender } = render(<MessageInput {...props} />);
    const textarea = screen.getByLabelText("消息内容");

    Object.defineProperty(textarea, "scrollHeight", {
      configurable: true,
      value: 32
    });

    rerender(<MessageInput {...props} value="hello" />);

    expect(textarea).toHaveStyle({ height: "64px", overflowY: "hidden" });
  });

  it("caps textarea height at 180px and enables internal scrolling", () => {
    const props = createProps();
    const { rerender } = render(<MessageInput {...props} />);
    const textarea = screen.getByLabelText("消息内容");

    Object.defineProperty(textarea, "scrollHeight", {
      configurable: true,
      value: 240
    });

    rerender(<MessageInput {...props} value={"hello\n".repeat(20)} />);

    expect(textarea).toHaveStyle({ height: "180px", overflowY: "auto" });
  });
});
