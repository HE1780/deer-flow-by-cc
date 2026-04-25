import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  bindSkillToThread,
  fetchBoundSkills,
  unbindSkillFromThread,
} from "@/core/skills/thread-api";

const BACKEND = "http://localhost:8000";

vi.mock("@/core/config", () => ({ getBackendBaseURL: () => BACKEND }));

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

beforeEach(() => mockFetch.mockReset());

describe("bindSkillToThread", () => {
  it("POSTs to /api/threads/{id}/skills and returns bound_skills", async () => {
    const bound = [
      { name: "data-analyst", version: "1.0.0", bound_at: "2026-04-25T00:00:00Z" },
    ];
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ bound_skills: bound }),
    });

    const result = await bindSkillToThread("thread-1", "data-analyst", "1.0.0");

    expect(mockFetch).toHaveBeenCalledWith(
      `${BACKEND}/api/threads/thread-1/skills`,
      expect.objectContaining({ method: "POST" }),
    );
    expect(result).toEqual(bound);
  });

  it("throws on HTTP error", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({ detail: "thread not found" }),
    });
    await expect(
      bindSkillToThread("no-thread", "skill", "latest"),
    ).rejects.toThrow("thread not found");
  });
});

describe("unbindSkillFromThread", () => {
  it("DELETEs to /api/threads/{id}/skills/{name}", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ bound_skills: [] }),
    });

    const result = await unbindSkillFromThread("thread-1", "data-analyst");
    expect(mockFetch).toHaveBeenCalledWith(
      `${BACKEND}/api/threads/thread-1/skills/data-analyst`,
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(result).toEqual([]);
  });
});

describe("fetchBoundSkills", () => {
  it("returns empty array on non-ok response", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({}),
    });
    const result = await fetchBoundSkills("missing-thread");
    expect(result).toEqual([]);
  });

  it("returns skills list on success", async () => {
    const bound = [
      { name: "sql-expert", version: "2.0.0", bound_at: "2026-04-25T00:00:00Z" },
    ];
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ bound_skills: bound }),
    });
    const result = await fetchBoundSkills("thread-1");
    expect(result).toEqual(bound);
  });
});
