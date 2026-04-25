import { getBackendBaseURL } from "../config";

export interface BoundSkill {
  name: string;
  version: string;
  bound_at: string;
}

export async function bindSkillToThread(
  threadId: string,
  skillName: string,
  version = "latest",
): Promise<BoundSkill[]> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/skills`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ skill_name: skillName, version }),
    },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  const data = (await res.json()) as { bound_skills: BoundSkill[] };
  return data.bound_skills;
}

export async function unbindSkillFromThread(
  threadId: string,
  skillName: string,
): Promise<BoundSkill[]> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/skills/${encodeURIComponent(skillName)}`,
    { method: "DELETE", credentials: "include" },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  const data = (await res.json()) as { bound_skills: BoundSkill[] };
  return data.bound_skills;
}

export async function fetchBoundSkills(threadId: string): Promise<BoundSkill[]> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/skills`,
    { credentials: "include" },
  );
  if (!res.ok) return [];
  const data = (await res.json()) as { bound_skills: BoundSkill[] };
  return data.bound_skills;
}
