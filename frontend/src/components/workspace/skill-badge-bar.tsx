"use client";

import { SparklesIcon, XIcon } from "lucide-react";

import { useUnbindSkill } from "@/core/skills/hooks";
import type { BoundSkill } from "@/core/skills/thread-api";

interface SkillBadgeBarProps {
  threadId: string;
  boundSkills: BoundSkill[];
  // Optional override for the X click. Used while the thread is still
  // pending (no real thread_id yet) so we just clear local state instead of
  // calling the unbind API on a non-existent thread.
  onUnbind?: (skillName: string) => void;
}

export function SkillBadgeBar({
  threadId,
  boundSkills,
  onUnbind,
}: SkillBadgeBarProps) {
  const { mutate: unbind } = useUnbindSkill(threadId);
  const handleUnbind = onUnbind ?? unbind;

  if (boundSkills.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center justify-center gap-1.5 px-3 pb-2">
      {boundSkills.map((skill) => (
        <span
          key={skill.name}
          className="bg-primary/10 text-primary flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium"
        >
          <SparklesIcon className="h-3 w-3" />
          /{skill.name}
          <button
            onClick={() => handleUnbind(skill.name)}
            className="hover:text-primary/60 ml-0.5 transition-colors"
            aria-label={`解绑 ${skill.name}`}
          >
            <XIcon className="h-3 w-3" />
          </button>
        </span>
      ))}
    </div>
  );
}
