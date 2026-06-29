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

    expect(screen.getByText("notes.txt")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "移除附件 notes.txt" }));

    expect(props.onRemoveAttachment).toHaveBeenCalledWith("att_one");
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
});
