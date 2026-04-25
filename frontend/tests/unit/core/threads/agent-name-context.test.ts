import { describe, it, expect } from "vitest";

// Validate that AgentThreadContext includes agent_name as an optional field
import type { AgentThreadContext } from "@/core/threads/types";

describe("AgentThreadContext", () => {
  it("includes agent_name as optional string field", () => {
    const ctx: AgentThreadContext = {
      thread_id: "test-thread",
      model_name: undefined,
      thinking_enabled: false,
      is_plan_mode: false,
      subagent_enabled: false,
      agent_name: "my-agent",
    };
    expect(ctx.agent_name).toBe("my-agent");
  });

  it("allows agent_name to be undefined", () => {
    const ctx: AgentThreadContext = {
      thread_id: "test-thread",
      model_name: undefined,
      thinking_enabled: false,
      is_plan_mode: false,
      subagent_enabled: false,
    };
    expect(ctx.agent_name).toBeUndefined();
  });
});
