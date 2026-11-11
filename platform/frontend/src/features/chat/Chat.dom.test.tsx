// This file is part of Prometheus
// https://inl.gov/super-intelligence/prometheus/
//
// Copyright 2026 Battelle Energy Alliance, LLC
// All rights reserved, see NOTICE.txt for full restrictions
// https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
//
// Licensed under the MIT License, please see LICENSE for details
// https://github.com/idaholab/prometheus_core/blob/main/LICENSE
//
// SPDX-License-Identifier: MIT

/* Drops on the chat composer, through a live <Chat> with the chat store and the API
 * client mocked. Each describe block covers one test-plan entry and shares the render
 * helper, the store state and the fake uploadFile below. */
import { createRef } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { ConfigResponse, UploadDescriptor } from "@/lib/api/types";
import type { ChatState } from "./store/chat";
import { Chat } from "./Chat.tsx";

type ComposerState = Pick<ChatState, "items" | "awaiting" | "config" | "resumingConversationId">;

const mocks = vi.hoisted(() => ({
  state: {} as ComposerState,
  uploadFile: vi.fn<(file: File) => Promise<UploadDescriptor>>(),
}));

vi.mock("./store/chat", () => ({
  useChatState: () => mocks.state,
  chatStore: { sendTurn: vi.fn(), stop: vi.fn(), submitFollowup: vi.fn(), decidePlan: vi.fn() },
}));
vi.mock("@/lib/api/client", () => {
  class StubApiError extends Error {
    constructor(
      public status: number,
      message: string,
    ) {
      super(message);
      this.name = "ApiError";
    }
  }
  return { ApiError: StubApiError, api: { uploadFile: mocks.uploadFile } };
});

// jsdom has no ResizeObserver; Chat observes the message list once it has messages.
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

beforeEach(() => {
  mocks.uploadFile.mockReset();
});

function renderChat(state: Partial<ComposerState> = {}) {
  mocks.state = { items: [], awaiting: false, config: null, resumingConversationId: null, ...state };
  return render(<Chat scrollContainerRef={createRef<HTMLDivElement>()} />);
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const descriptorFor = (file: File): UploadDescriptor => ({
  upload_id: `u-${file.name}`,
  name: file.name,
  mime_type: file.type,
  size_bytes: file.size,
});

// The pointer is over the textarea; the events bubble to the composer box.
const composer = () => screen.getByRole("textbox", { name: "Message" });

/** Drags files from the desktop onto the composer and drops them there. */
function dropFiles(files: File[]) {
  const dataTransfer = { types: ["Files"], files, dropEffect: "none" };
  fireEvent.dragEnter(composer(), { dataTransfer });
  fireEvent.dragOver(composer(), { dataTransfer });
  fireEvent.drop(composer(), { dataTransfer });
}

const chipOf = (name: string) =>
  screen.getByRole("button", { name: `Remove ${name}` }).closest("[title]") as HTMLElement;
const chipSpinner = (name: string) => within(chipOf(name)).queryByRole("img", { name: "Uploading" });

describe("composer_drop_attaches_files", () => {
  test("a dropped file shows an uploading chip that turns ready when uploadFile resolves", async () => {
    const upload = deferred<UploadDescriptor>();
    mocks.uploadFile.mockReturnValue(upload.promise);
    const file = new File(["hello"], "a.txt", { type: "text/plain" });
    renderChat();

    dropFiles([file]);

    expect(mocks.uploadFile).toHaveBeenCalledExactlyOnceWith(file);
    expect(screen.getByText("a.txt")).toBeInTheDocument();
    expect(chipSpinner("a.txt")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();

    await act(async () => upload.resolve(descriptorFor(file)));

    expect(screen.getByText("a.txt")).toBeInTheDocument();
    expect(chipSpinner("a.txt")).toBeNull();
    expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled();
  });

  test("a drop of two files uploads each and shows two chips; Remove a.txt removes only its chip", async () => {
    const user = userEvent.setup();
    mocks.uploadFile.mockImplementation(() => deferred<UploadDescriptor>().promise);
    const a = new File(["hello"], "a.txt", { type: "text/plain" });
    const b = new File(["x,y\n1,2\n"], "b.csv", { type: "text/csv" });
    renderChat();

    dropFiles([a, b]);

    expect(mocks.uploadFile).toHaveBeenCalledTimes(2);
    expect(mocks.uploadFile).toHaveBeenNthCalledWith(1, a);
    expect(mocks.uploadFile).toHaveBeenNthCalledWith(2, b);
    expect(screen.getAllByRole("button", { name: /^Remove / })).toHaveLength(2);
    expect(screen.getByText("a.txt")).toBeInTheDocument();
    expect(screen.getByText("b.csv")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove a.txt" }));

    expect(screen.queryByText("a.txt")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove a.txt" })).not.toBeInTheDocument();
    expect(screen.getByText("b.csv")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Remove / })).toHaveLength(1);
  });

  test("a file picked with the paperclip attaches through the same path as a drop", async () => {
    // user-event does not read accept="*/*" as a wildcard, so it would drop every file.
    const user = userEvent.setup({ applyAccept: false });
    const upload = deferred<UploadDescriptor>();
    mocks.uploadFile.mockReturnValue(upload.promise);
    const file = new File(["hello"], "picked.txt", { type: "text/plain" });
    const { container } = renderChat();
    // The input is hidden; the "Attach files" button opens its picker.
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();

    await user.upload(input!, file);

    expect(mocks.uploadFile).toHaveBeenCalledExactlyOnceWith(file);
    expect(chipSpinner("picked.txt")).not.toBeNull();
    expect(input!.value).toBe("");

    await act(async () => upload.resolve(descriptorFor(file)));

    expect(chipSpinner("picked.txt")).toBeNull();
    expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled();
  });
});

describe("composer_drop_size_limit", () => {
  const config: ConfigResponse = {
    profiles: [],
    chat_intro: "",
    chat_suggestion_title: "",
    workflow_suggestions: [],
    auto_approve_steps: false,
    max_upload_bytes: 10,
  };

  test("a dropped file above max_upload_bytes shows the limit error chip and is not uploaded; a smaller file in the same drop uploads", async () => {
    const upload = deferred<UploadDescriptor>();
    mocks.uploadFile.mockReturnValue(upload.promise);
    const big = new File(["x".repeat(11)], "big.bin", { type: "application/octet-stream" });
    const small = new File(["hello"], "small.txt", { type: "text/plain" });
    renderChat({ config });

    dropFiles([big, small]);

    expect(mocks.uploadFile).toHaveBeenCalledExactlyOnceWith(small);
    expect(chipOf("big.bin")).toHaveAttribute("title", "File exceeds the upload limit");
    expect(chipSpinner("big.bin")).toBeNull();
    expect(chipSpinner("small.txt")).not.toBeNull();

    await act(async () => upload.resolve(descriptorFor(small)));

    expect(chipSpinner("small.txt")).toBeNull();
    expect(chipOf("small.txt")).not.toHaveAttribute("title", "File exceeds the upload limit");
    expect(chipOf("big.bin")).toHaveAttribute("title", "File exceeds the upload limit");
    expect(mocks.uploadFile).toHaveBeenCalledTimes(1);
  });

  test("a dropped file of exactly max_upload_bytes uploads and shows no limit error", async () => {
    const upload = deferred<UploadDescriptor>();
    mocks.uploadFile.mockReturnValue(upload.promise);
    const atLimit = new File(["x".repeat(10)], "limit.bin", { type: "application/octet-stream" });
    renderChat({ config });

    dropFiles([atLimit]);

    expect(mocks.uploadFile).toHaveBeenCalledExactlyOnceWith(atLimit);
    expect(chipSpinner("limit.bin")).not.toBeNull();
    expect(chipOf("limit.bin")).not.toHaveAttribute("title", "File exceeds the upload limit");

    await act(async () => upload.resolve(descriptorFor(atLimit)));

    expect(chipSpinner("limit.bin")).toBeNull();
    expect(chipOf("limit.bin")).not.toHaveAttribute("title", "File exceeds the upload limit");
  });
});

describe("composer_drop_ignored_when_disabled", () => {
  test.each<[string, Partial<ComposerState>]>([
    ["a turn is sending", { awaiting: true }],
    ["a conversation is resuming", { resumingConversationId: "c-1" }],
  ])(
    "while %s a file drag shows no drop target and a drop attaches nothing but is still defaultPrevented",
    (_when, state) => {
      mocks.uploadFile.mockImplementation(() => deferred<UploadDescriptor>().promise);
      const file = new File(["hello"], "a.txt", { type: "text/plain" });
      // Starts at "copy", so only the disabled composer's dragOver can turn it to "none".
      const dataTransfer = { types: ["Files"], files: [file], dropEffect: "copy" };
      renderChat(state);

      fireEvent.dragEnter(composer(), { dataTransfer });
      fireEvent.dragOver(composer(), { dataTransfer });

      expect(screen.queryByText("Drop files to attach")).not.toBeInTheDocument();
      expect(dataTransfer.dropEffect).toBe("none");

      // fireEvent returns false when a handler called preventDefault().
      const notPrevented = fireEvent.drop(composer(), { dataTransfer });

      expect(notPrevented).toBe(false);
      expect(mocks.uploadFile).not.toHaveBeenCalled();
      expect(screen.queryByText("a.txt")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^Remove / })).not.toBeInTheDocument();
    },
  );
});

describe("composer_drag_state", () => {
  const dropTarget = () => screen.queryByText("Drop files to attach");
  // The composer box holds the drag handlers; the textarea sits inside it.
  const composerBox = () => screen.getByRole("group", { name: "Message composer" });
  const fileDrag = () => ({ types: ["Files"], files: [] as File[], dropEffect: "none" });

  /** Dispatches a drop on window, outside the composer; jsdom has no DragEvent. */
  function dropOnWindow(types: string[]) {
    const event = new Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: { types, files: [] } });
    act(() => {
      window.dispatchEvent(event);
    });
    return event;
  }

  test("a file dragEnter shows the drop target; a dragEnter on the textarea then a dragLeave from the box keeps it; the final dragLeave hides it", () => {
    const dataTransfer = fileDrag();
    renderChat();

    fireEvent.dragEnter(composerBox(), { dataTransfer });

    expect(dropTarget()).toBeInTheDocument();

    fireEvent.dragEnter(composer(), { dataTransfer });
    fireEvent.dragLeave(composerBox(), { dataTransfer });

    expect(dropTarget()).toBeInTheDocument();

    fireEvent.dragLeave(composer(), { dataTransfer });

    expect(dropTarget()).not.toBeInTheDocument();
  });

  test("a dragend on window after a file dragEnter hides the drop target", () => {
    renderChat();

    fireEvent.dragEnter(composer(), { dataTransfer: fileDrag() });

    expect(dropTarget()).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new Event("dragend"));
    });

    expect(dropTarget()).not.toBeInTheDocument();
  });

  test("a drop of files on the composer hides the drop target", () => {
    mocks.uploadFile.mockImplementation(() => deferred<UploadDescriptor>().promise);
    const dataTransfer = { ...fileDrag(), files: [new File(["hello"], "a.txt", { type: "text/plain" })] };
    renderChat();

    fireEvent.dragEnter(composer(), { dataTransfer });
    fireEvent.dragOver(composer(), { dataTransfer });

    expect(dropTarget()).toBeInTheDocument();

    fireEvent.drop(composer(), { dataTransfer });

    expect(dropTarget()).not.toBeInTheDocument();
  });

  test("a drag of text or a link shows no drop target, and its leave and drop attach nothing", () => {
    const dataTransfer = { types: ["text/plain", "text/uri-list"], files: [] as File[], dropEffect: "none" };
    renderChat();

    fireEvent.dragEnter(composer(), { dataTransfer });
    fireEvent.dragOver(composer(), { dataTransfer });

    expect(dropTarget()).not.toBeInTheDocument();

    fireEvent.dragLeave(composer(), { dataTransfer });
    // fireEvent returns true when no handler called preventDefault(), so the text drops as usual.
    const notPrevented = fireEvent.drop(composer(), { dataTransfer });

    expect(notPrevented).toBe(true);
    expect(dropTarget()).not.toBeInTheDocument();
    expect(mocks.uploadFile).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /^Remove / })).not.toBeInTheDocument();
  });

  test("a file drop on window outside the composer is defaultPrevented; a text drop is not", () => {
    renderChat();

    expect(dropOnWindow(["Files"]).defaultPrevented).toBe(true);
    expect(dropOnWindow(["text/plain", "text/uri-list"]).defaultPrevented).toBe(false);
  });
});
