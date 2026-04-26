import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { enableSkill } from "./api";
import {
  bindSkillToThread,
  fetchBoundSkills,
  unbindSkillFromThread,
  type BoundSkill,
} from "./thread-api";

import { loadSkills } from ".";

export function useSkills() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["skills"],
    queryFn: () => loadSkills(),
  });
  return { skills: data ?? [], isLoading, error };
}

export function useEnableSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      skillName,
      enabled,
    }: {
      skillName: string;
      enabled: boolean;
    }) => {
      await enableSkill(skillName, enabled);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}

export function useBoundSkills(threadId: string) {
  const { data, isLoading } = useQuery({
    queryKey: ["threads", threadId, "skills"],
    queryFn: () => fetchBoundSkills(threadId),
    enabled: !!threadId,
  });
  return { boundSkills: data ?? [], isLoading };
}

export function useBindSkill(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      skillName,
      version,
    }: {
      skillName: string;
      version?: string;
    }) => bindSkillToThread(threadId, skillName, version),
    onSuccess: (data) => {
      queryClient.setQueryData<BoundSkill[]>(
        ["threads", threadId, "skills"],
        data,
      );
    },
  });
}

export function useUnbindSkill(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (skillName: string) =>
      unbindSkillFromThread(threadId, skillName),
    onSuccess: (data) => {
      queryClient.setQueryData<BoundSkill[]>(
        ["threads", threadId, "skills"],
        data,
      );
    },
  });
}
