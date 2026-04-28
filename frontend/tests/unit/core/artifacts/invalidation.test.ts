import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "vitest";

import {
  extractInvalidatedPathsFromNewMessages,
  extractToolEndEventsFromNewMessages,
  extractWriteFilePath,
} from "@/core/artifacts/invalidation";

describe("extractWriteFilePath", () => {
  test("returns path for write_file tool result", () => {
    const result = extractWriteFilePath("write_file", {
      input: {
        description: "draft post",
        path: "/mnt/user-data/outputs/post.md",
        content: "hello",
      },
      output: "OK",
    });
    expect(result).toBe("/mnt/user-data/outputs/post.md");
  });

  test("returns path for str_replace tool result", () => {
    const result = extractWriteFilePath("str_replace", {
      input: {
        description: "fix typo",
        path: "/mnt/user-data/outputs/post.md",
        old_str: "teh",
        new_str: "the",
      },
      output: "OK",
    });
    expect(result).toBe("/mnt/user-data/outputs/post.md");
  });

  test("returns null for unrelated tool names", () => {
    expect(
      extractWriteFilePath("read_file", {
        input: { path: "/mnt/user-data/outputs/post.md" },
      }),
    ).toBeNull();
    expect(
      extractWriteFilePath("bash", {
        input: { command: "ls" },
      }),
    ).toBeNull();
    expect(
      extractWriteFilePath("present_files", {
        input: { paths: ["/mnt/user-data/outputs/post.md"] },
      }),
    ).toBeNull();
  });

  test("returns null when path is missing or wrong type", () => {
    expect(extractWriteFilePath("write_file", {})).toBeNull();
    expect(
      extractWriteFilePath("write_file", { input: {} }),
    ).toBeNull();
    expect(
      extractWriteFilePath("write_file", { input: { path: 123 } }),
    ).toBeNull();
    expect(
      extractWriteFilePath("write_file", null),
    ).toBeNull();
    expect(
      extractWriteFilePath("write_file", undefined),
    ).toBeNull();
  });

  test("returns null when tool failed (non-OK result)", () => {
    // If write_file errored, the file did not change — don't invalidate.
    const result = extractWriteFilePath("write_file", {
      input: {
        path: "/mnt/user-data/outputs/post.md",
        content: "hello",
      },
      output: "Error: Permission denied writing to file: /mnt/user-data/outputs/post.md",
    });
    expect(result).toBeNull();
  });

  test("trims whitespace from extracted path", () => {
    const result = extractWriteFilePath("write_file", {
      input: { path: "  /mnt/user-data/outputs/post.md  " },
      output: "OK",
    });
    expect(result).toBe("/mnt/user-data/outputs/post.md");
  });

  test("returns null when path is empty after trimming", () => {
    expect(
      extractWriteFilePath("write_file", {
        input: { path: "   " },
        output: "OK",
      }),
    ).toBeNull();
  });
});

function aiMsg(
  id: string,
  toolCalls: Array<{ id: string; name: string; args: Record<string, unknown> }>,
): Message {
  return {
    type: "ai",
    id,
    content: "",
    tool_calls: toolCalls,
  } as Message;
}

function toolMsg(
  id: string,
  toolCallId: string,
  name: string,
  content: string,
): Message {
  return {
    type: "tool",
    id,
    tool_call_id: toolCallId,
    name,
    content,
  } as Message;
}

describe("extractInvalidatedPathsFromNewMessages", () => {
  test("returns path for newly arrived successful write_file ToolMessage", () => {
    const before: Message[] = [
      aiMsg("ai-1", [
        {
          id: "call-1",
          name: "write_file",
          args: { path: "/mnt/user-data/outputs/post.md", content: "x" },
        },
      ]),
    ];
    const after: Message[] = [
      ...before,
      toolMsg("tool-1", "call-1", "write_file", "OK"),
    ];

    expect(
      extractInvalidatedPathsFromNewMessages(before, after),
    ).toEqual(["/mnt/user-data/outputs/post.md"]);
  });

  test("returns path for newly arrived str_replace ToolMessage", () => {
    const before: Message[] = [
      aiMsg("ai-1", [
        {
          id: "call-1",
          name: "str_replace",
          args: {
            path: "/mnt/user-data/outputs/post.md",
            old_str: "a",
            new_str: "b",
          },
        },
      ]),
    ];
    const after: Message[] = [
      ...before,
      toolMsg("tool-1", "call-1", "str_replace", "OK"),
    ];

    expect(
      extractInvalidatedPathsFromNewMessages(before, after),
    ).toEqual(["/mnt/user-data/outputs/post.md"]);
  });

  test("returns empty array when only old messages are present", () => {
    const messages: Message[] = [
      aiMsg("ai-1", [
        {
          id: "call-1",
          name: "write_file",
          args: { path: "/mnt/user-data/outputs/post.md" },
        },
      ]),
      toolMsg("tool-1", "call-1", "write_file", "OK"),
    ];

    expect(
      extractInvalidatedPathsFromNewMessages(messages, messages),
    ).toEqual([]);
  });

  test("ignores ToolMessage when paired tool_call is unrelated", () => {
    const before: Message[] = [
      aiMsg("ai-1", [{ id: "call-1", name: "read_file", args: { path: "/x" } }]),
    ];
    const after: Message[] = [
      ...before,
      toolMsg("tool-1", "call-1", "read_file", "OK"),
    ];

    expect(
      extractInvalidatedPathsFromNewMessages(before, after),
    ).toEqual([]);
  });

  test("ignores failed tool call (Error result)", () => {
    const before: Message[] = [
      aiMsg("ai-1", [
        {
          id: "call-1",
          name: "write_file",
          args: { path: "/mnt/user-data/outputs/post.md" },
        },
      ]),
    ];
    const after: Message[] = [
      ...before,
      toolMsg(
        "tool-1",
        "call-1",
        "write_file",
        "Error: Permission denied writing to file",
      ),
    ];

    expect(
      extractInvalidatedPathsFromNewMessages(before, after),
    ).toEqual([]);
  });

  test("returns paths from multiple new ToolMessages", () => {
    const before: Message[] = [
      aiMsg("ai-1", [
        {
          id: "call-1",
          name: "write_file",
          args: { path: "/mnt/user-data/outputs/a.md" },
        },
        {
          id: "call-2",
          name: "write_file",
          args: { path: "/mnt/user-data/outputs/b.md" },
        },
      ]),
    ];
    const after: Message[] = [
      ...before,
      toolMsg("tool-1", "call-1", "write_file", "OK"),
      toolMsg("tool-2", "call-2", "write_file", "OK"),
    ];

    expect(
      extractInvalidatedPathsFromNewMessages(before, after),
    ).toEqual([
      "/mnt/user-data/outputs/a.md",
      "/mnt/user-data/outputs/b.md",
    ]);
  });

  test("dedupes when same path appears in multiple new ToolMessages", () => {
    const before: Message[] = [
      aiMsg("ai-1", [
        {
          id: "call-1",
          name: "write_file",
          args: { path: "/mnt/user-data/outputs/post.md" },
        },
        {
          id: "call-2",
          name: "str_replace",
          args: { path: "/mnt/user-data/outputs/post.md" },
        },
      ]),
    ];
    const after: Message[] = [
      ...before,
      toolMsg("tool-1", "call-1", "write_file", "OK"),
      toolMsg("tool-2", "call-2", "str_replace", "OK"),
    ];

    expect(
      extractInvalidatedPathsFromNewMessages(before, after),
    ).toEqual(["/mnt/user-data/outputs/post.md"]);
  });

  test("only considers messages newly appended after the previous render", () => {
    const old: Message[] = [
      aiMsg("ai-0", [
        {
          id: "call-0",
          name: "write_file",
          args: { path: "/mnt/user-data/outputs/old.md" },
        },
      ]),
      toolMsg("tool-0", "call-0", "write_file", "OK"),
    ];
    const before: Message[] = [...old];
    const after: Message[] = [
      ...old,
      aiMsg("ai-1", [
        {
          id: "call-1",
          name: "write_file",
          args: { path: "/mnt/user-data/outputs/new.md" },
        },
      ]),
      toolMsg("tool-1", "call-1", "write_file", "OK"),
    ];

    expect(
      extractInvalidatedPathsFromNewMessages(before, after),
    ).toEqual(["/mnt/user-data/outputs/new.md"]);
  });

  test("handles ToolMessage whose paired AIMessage is in earlier history", () => {
    // The tool_call may have been emitted in a prior render and the
    // ToolMessage only arrives in the next snapshot.
    const before: Message[] = [
      aiMsg("ai-1", [
        {
          id: "call-1",
          name: "write_file",
          args: { path: "/mnt/user-data/outputs/post.md" },
        },
      ]),
    ];
    const after: Message[] = [
      ...before,
      toolMsg("tool-1", "call-1", "write_file", "OK"),
    ];

    expect(
      extractInvalidatedPathsFromNewMessages(before, after),
    ).toEqual(["/mnt/user-data/outputs/post.md"]);
  });

  test("ignores new ToolMessage whose tool_call_id has no matching AIMessage", () => {
    const before: Message[] = [];
    const after: Message[] = [
      toolMsg("tool-1", "call-orphan", "write_file", "OK"),
    ];

    expect(
      extractInvalidatedPathsFromNewMessages(before, after),
    ).toEqual([]);
  });
});

describe("extractToolEndEventsFromNewMessages", () => {
  test("emits one event per newly arrived ToolMessage with paired input", () => {
    const before: Message[] = [
      aiMsg("ai-1", [
        {
          id: "call-1",
          name: "setup_agent",
          args: { name: "researcher" },
        },
      ]),
    ];
    const after: Message[] = [
      ...before,
      toolMsg("tool-1", "call-1", "setup_agent", "OK"),
    ];

    const events = extractToolEndEventsFromNewMessages(before, after);
    expect(events).toEqual([
      {
        name: "setup_agent",
        data: {
          input: { name: "researcher" },
          output: "OK",
        },
      },
    ]);
  });

  test("returns empty when no new ToolMessage arrived", () => {
    const messages: Message[] = [
      aiMsg("ai-1", [
        { id: "call-1", name: "write_file", args: { path: "/x" } },
      ]),
      toolMsg("tool-1", "call-1", "write_file", "OK"),
    ];
    expect(
      extractToolEndEventsFromNewMessages(messages, messages),
    ).toEqual([]);
  });

  test("emits even when paired AIMessage args is missing (input becomes {})", () => {
    const before: Message[] = [];
    const after: Message[] = [
      toolMsg("tool-1", "call-orphan", "some_tool", "OK"),
    ];
    expect(
      extractToolEndEventsFromNewMessages(before, after),
    ).toEqual([
      { name: "some_tool", data: { input: {}, output: "OK" } },
    ]);
  });

  test("preserves Error output strings in event payload", () => {
    const before: Message[] = [
      aiMsg("ai-1", [
        { id: "call-1", name: "write_file", args: { path: "/x" } },
      ]),
    ];
    const after: Message[] = [
      ...before,
      toolMsg("tool-1", "call-1", "write_file", "Error: nope"),
    ];

    expect(
      extractToolEndEventsFromNewMessages(before, after),
    ).toEqual([
      {
        name: "write_file",
        data: { input: { path: "/x" }, output: "Error: nope" },
      },
    ]);
  });
});
