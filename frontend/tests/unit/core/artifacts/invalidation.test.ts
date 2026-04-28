import { describe, expect, test } from "vitest";

import { extractWriteFilePath } from "@/core/artifacts/invalidation";

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
