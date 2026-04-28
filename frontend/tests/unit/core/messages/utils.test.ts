import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, it } from "vitest";

import { groupMessages } from "@/core/messages/utils";

function human(id: string, content: string, name?: string): Message {
  return {
    id,
    type: "human",
    content,
    ...(name ? { name } : {}),
  } as Message;
}

function ai(id: string, content: string): Message {
  return {
    id,
    type: "ai",
    content,
    tool_calls: [],
  } as Message;
}

describe("groupMessages — system reminder filtering", () => {
  it("filters out human messages named 'todo_reminder'", () => {
    const messages: Message[] = [
      human("u1", "hi"),
      ai("a1", "hello"),
      human("r1", "<system_reminder>...</system_reminder>", "todo_reminder"),
      ai("a2", "ok"),
    ];

    const groups = groupMessages(messages, (g) => g);

    // todo_reminder must NOT appear as a human group
    expect(groups.filter((g) => g.type === "human").length).toBe(1);
    expect(
      groups.some((g) =>
        g.messages.some((m) => m.name === "todo_reminder"),
      ),
    ).toBe(false);
  });

  it("filters out human messages named 'todo_completion_reminder'", () => {
    // Regression: prior code only filtered todo_reminder, leaving
    // todo_completion_reminder visible as fake user messages.
    const messages: Message[] = [
      human("u1", "hi"),
      ai("a1", "hello"),
      human(
        "r1",
        "<system_reminder>You have incomplete todo items...</system_reminder>",
        "todo_completion_reminder",
      ),
      ai("a2", "still working"),
    ];

    const groups = groupMessages(messages, (g) => g);

    expect(groups.filter((g) => g.type === "human").length).toBe(1);
    expect(
      groups.some((g) =>
        g.messages.some((m) => m.name === "todo_completion_reminder"),
      ),
    ).toBe(false);
  });

  it("keeps regular human messages without name unchanged", () => {
    const messages: Message[] = [
      human("u1", "real user question"),
    ];
    const groups = groupMessages(messages, (g) => g);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.type).toBe("human");
  });
});
