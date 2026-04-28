import type { Message } from "@langchain/langgraph-sdk";

const FILE_MUTATING_TOOLS = new Set(["write_file", "str_replace"]);

export function extractWriteFilePath(
  toolName: string,
  toolData: unknown,
): string | null {
  if (!FILE_MUTATING_TOOLS.has(toolName)) {
    return null;
  }
  if (typeof toolData !== "object" || toolData === null) {
    return null;
  }
  const data = toolData as { input?: unknown; output?: unknown };
  if (typeof data.input !== "object" || data.input === null) {
    return null;
  }
  const input = data.input as { path?: unknown };
  if (typeof input.path !== "string") {
    return null;
  }
  const trimmed = input.path.trim();
  if (!trimmed) {
    return null;
  }
  if (typeof data.output === "string" && data.output.startsWith("Error")) {
    return null;
  }
  return trimmed;
}

function getToolMessageText(message: Message): string {
  if (message.type !== "tool") {
    return "";
  }
  const content = (message as { content?: unknown }).content;
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") return part;
        if (
          part &&
          typeof part === "object" &&
          "text" in part &&
          typeof (part as { text: unknown }).text === "string"
        ) {
          return (part as { text: string }).text;
        }
        return "";
      })
      .join("");
  }
  return "";
}

function findToolCallArgsById(
  messages: Message[],
  toolCallId: string,
  toolName: string,
): Record<string, unknown> | null {
  for (const message of messages) {
    if (message.type !== "ai") continue;
    const toolCalls = (message as { tool_calls?: Array<{
      id?: string;
      name?: string;
      args?: Record<string, unknown>;
    }> }).tool_calls;
    if (!toolCalls) continue;
    for (const call of toolCalls) {
      if (call.id !== toolCallId) continue;
      if (call.name !== toolName) continue;
      return call.args ?? {};
    }
  }
  return null;
}

export function extractInvalidatedPathsFromNewMessages(
  before: Message[],
  after: Message[],
): string[] {
  if (after.length <= before.length) {
    return [];
  }
  const newMessages = after.slice(before.length);
  const paths: string[] = [];
  const seen = new Set<string>();

  for (const message of newMessages) {
    if (message.type !== "tool") continue;
    const tm = message as {
      tool_call_id?: string;
      name?: string;
    };
    if (!tm.tool_call_id || !tm.name) continue;
    if (!FILE_MUTATING_TOOLS.has(tm.name)) continue;

    const text = getToolMessageText(message);
    if (text.startsWith("Error")) continue;

    const args = findToolCallArgsById(after, tm.tool_call_id, tm.name);
    if (!args) continue;
    const rawPath = args.path;
    if (typeof rawPath !== "string") continue;
    const path = rawPath.trim();
    if (!path) continue;
    if (seen.has(path)) continue;
    seen.add(path);
    paths.push(path);
  }

  return paths;
}

export type ToolEndEvent = {
  name: string;
  data: { input: Record<string, unknown>; output: string };
};

export function extractToolEndEventsFromNewMessages(
  before: Message[],
  after: Message[],
): ToolEndEvent[] {
  if (after.length <= before.length) {
    return [];
  }
  const newMessages = after.slice(before.length);
  const events: ToolEndEvent[] = [];

  for (const message of newMessages) {
    if (message.type !== "tool") continue;
    const tm = message as { tool_call_id?: string; name?: string };
    if (!tm.name) continue;

    const output = getToolMessageText(message);
    const input = tm.tool_call_id
      ? findToolCallArgsById(after, tm.tool_call_id, tm.name) ?? {}
      : {};

    events.push({ name: tm.name, data: { input, output } });
  }

  return events;
}
