// Tools whose successful execution mutates a file at `input.path`.
// Mirrors backend: deerflow/sandbox/tools.py::write_file_tool, str_replace_tool.
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
  // The tool returns "OK" on success, "Error: ..." on failure.
  // If output is present and indicates failure, the file was not changed —
  // skip invalidation to avoid spurious refetches.
  if (typeof data.output === "string" && data.output.startsWith("Error")) {
    return null;
  }
  return trimmed;
}
