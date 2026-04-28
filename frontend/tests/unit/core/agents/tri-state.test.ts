import { describe, expect, it } from "vitest";

import {
  decodeTriState,
  encodeTriState,
  skillBaseName,
  toggleSkillSelection,
} from "@/core/agents/tri-state";

describe("decodeTriState", () => {
  it("treats null as 'use all'", () => {
    expect(decodeTriState(null)).toEqual({ useAll: true, selected: [] });
  });

  it("treats [] as 'all off'", () => {
    expect(decodeTriState([])).toEqual({ useAll: false, selected: [] });
  });

  it("treats a non-empty list as 'whitelist'", () => {
    expect(decodeTriState(["a", "b"])).toEqual({
      useAll: false,
      selected: ["a", "b"],
    });
  });

  it("preserves skills with @version pin in selected", () => {
    expect(decodeTriState(["my_skill@1.2.0", "plain"])).toEqual({
      useAll: false,
      selected: ["my_skill@1.2.0", "plain"],
    });
  });
});

describe("encodeTriState", () => {
  it("returns null when useAll", () => {
    expect(encodeTriState({ useAll: true, selected: [] })).toBeNull();
    expect(encodeTriState({ useAll: true, selected: ["ignored"] })).toBeNull();
  });

  it("returns [] when useAll is false and nothing selected", () => {
    expect(encodeTriState({ useAll: false, selected: [] })).toEqual([]);
  });

  it("returns the selected list verbatim otherwise", () => {
    expect(encodeTriState({ useAll: false, selected: ["a", "b"] })).toEqual([
      "a",
      "b",
    ]);
  });
});

describe("skillBaseName", () => {
  it("strips @version suffix", () => {
    expect(skillBaseName("my_skill@1.2.0")).toBe("my_skill");
    expect(skillBaseName("plain")).toBe("plain");
  });
});

describe("toggleSkillSelection", () => {
  it("adds bare name when not present", () => {
    expect(toggleSkillSelection(["a"], "b")).toEqual(["a", "b"]);
  });

  it("removes by base name (drops @version too)", () => {
    expect(toggleSkillSelection(["my_skill@1.2.0", "other"], "my_skill")).toEqual(
      ["other"],
    );
  });

  it("preserves @version pin when re-toggling within session", () => {
    // Off then on within the same session: the page tracks the previous value
    // and passes it back as initialPin.
    const offThenOn = toggleSkillSelection(
      ["other"],
      "my_skill",
      "my_skill@1.2.0",
    );
    expect(offThenOn).toEqual(["other", "my_skill@1.2.0"]);
  });

  it("falls back to bare name when no pin remembered", () => {
    expect(toggleSkillSelection(["other"], "my_skill")).toEqual([
      "other",
      "my_skill",
    ]);
  });
});
