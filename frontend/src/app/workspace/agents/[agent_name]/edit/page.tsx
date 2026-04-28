"use client";

import { ArrowLeftIcon } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useAgent, useToolGroups, useUpdateAgent } from "@/core/agents";
import {
  decodeTriState,
  encodeTriState,
  skillBaseName,
  toggleSkillSelection,
  type TriState,
} from "@/core/agents/tri-state";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { useSkills } from "@/core/skills/hooks";

export default function EditAgentPage() {
  const { t } = useI18n();
  const router = useRouter();
  const params = useParams<{ agent_name: string }>();
  const agentName = params?.agent_name ?? "";

  const { agent, isLoading: agentLoading, error: agentError } = useAgent(agentName);
  const { models } = useModels();
  const { toolGroups, error: toolGroupsError } = useToolGroups();
  const { skills, error: skillsError } = useSkills();
  const updateAgent = useUpdateAgent();

  const [description, setDescription] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [orgKeyEnv, setOrgKeyEnv] = useState("");
  const [soul, setSoul] = useState("");
  const [toolGroupsState, setToolGroupsState] = useState<TriState>({
    useAll: true,
    selected: [],
  });
  const [skillsState, setSkillsState] = useState<TriState>({
    useAll: true,
    selected: [],
  });
  const [skillPins, setSkillPins] = useState<Record<string, string>>({});
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (!agent || hydrated) return;
    setDescription(agent.description ?? "");
    setModel(agent.model);
    setOrgKeyEnv(agent.org_key_env ?? "");
    setSoul(agent.soul ?? "");
    setToolGroupsState(decodeTriState(agent.tool_groups));

    const decodedSkills = decodeTriState(agent.skills);
    setSkillsState(decodedSkills);
    const pins: Record<string, string> = {};
    for (const v of decodedSkills.selected) {
      if (v.includes("@")) pins[skillBaseName(v)] = v;
    }
    setSkillPins(pins);
    setHydrated(true);
  }, [agent, hydrated]);

  const advancedOpen = useMemo(
    () =>
      !toolGroupsState.useAll ||
      !skillsState.useAll ||
      orgKeyEnv.trim().length > 0,
    [toolGroupsState.useAll, skillsState.useAll, orgKeyEnv],
  );
  const [advancedExpanded, setAdvancedExpanded] = useState(false);
  useEffect(() => {
    if (advancedOpen) setAdvancedExpanded(true);
  }, [advancedOpen]);

  if (agentLoading) {
    return (
      <div className="mx-auto w-full max-w-2xl space-y-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (agentError || !agent) {
    return (
      <div className="mx-auto w-full max-w-2xl space-y-4 p-6">
        <Alert variant="destructive">
          <AlertDescription>{t.agents.editLoadFailed}</AlertDescription>
        </Alert>
        <Button variant="outline" onClick={() => router.push("/workspace/agents")}>
          {t.agents.editLoadFailedBack}
        </Button>
      </div>
    );
  }

  function handleToolGroupToggle(name: string) {
    setToolGroupsState((s) => ({
      useAll: s.useAll,
      selected: s.selected.includes(name)
        ? s.selected.filter((g) => g !== name)
        : [...s.selected, name],
    }));
  }

  function handleSkillToggle(baseName: string) {
    setSkillsState((s) => ({
      useAll: s.useAll,
      selected: toggleSkillSelection(s.selected, baseName, skillPins[baseName]),
    }));
  }

  async function handleSave() {
    try {
      await updateAgent.mutateAsync({
        name: agentName,
        request: {
          description,
          model,
          tool_groups: encodeTriState(toolGroupsState),
          skills: encodeTriState(skillsState),
          org_key_env: orgKeyEnv.trim() === "" ? null : orgKeyEnv.trim(),
          soul,
        },
      });
      toast.success(t.agents.editSaveSuccess);
      router.push("/workspace/agents");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.agents.editSaveFailed);
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6 p-6">
      <header className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => router.push("/workspace/agents")}
          >
            <ArrowLeftIcon className="h-4 w-4" />
          </Button>
          <h1 className="truncate text-lg font-semibold">{agentName}</h1>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button
            variant="outline"
            onClick={() => router.push("/workspace/agents")}
            disabled={updateAgent.isPending}
          >
            {t.common.cancel}
          </Button>
          <Button onClick={() => void handleSave()} disabled={updateAgent.isPending}>
            {updateAgent.isPending ? t.common.loading : t.common.save}
          </Button>
        </div>
      </header>

      <section className="space-y-4 rounded-lg border p-4">
        <h2 className="text-sm font-semibold">{t.agents.editBasicSection}</h2>

        <div className="space-y-2">
          <label htmlFor="description" className="text-sm font-medium">
            {t.agents.editFieldDescription}
          </label>
          <Textarea
            id="description"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t.agents.editFieldDescriptionPlaceholder}
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="model" className="text-sm font-medium">
            {t.agents.editFieldModel}
          </label>
          <Select
            value={model ?? "__default__"}
            onValueChange={(v) => setModel(v === "__default__" ? null : v)}
          >
            <SelectTrigger id="model">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__default__">
                {t.agents.editFieldModelDefault}
              </SelectItem>
              {models.map((m) => (
                <SelectItem key={m.name} value={m.name}>
                  {m.display_name ?? m.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <label htmlFor="soul" className="text-sm font-medium">
            {t.agents.editFieldSoul}
          </label>
          <Textarea
            id="soul"
            rows={12}
            className="font-mono text-xs"
            value={soul}
            onChange={(e) => setSoul(e.target.value)}
            placeholder={t.agents.editFieldSoulPlaceholder}
          />
        </div>
      </section>

      <section className="space-y-4 rounded-lg border p-4">
        <button
          type="button"
          className="flex w-full items-center justify-between text-sm font-semibold"
          onClick={() => setAdvancedExpanded((e) => !e)}
        >
          <span>{t.agents.editAdvancedSection}</span>
          <span className="text-muted-foreground text-xs">
            {advancedExpanded ? "−" : "+"}
          </span>
        </button>

        {advancedExpanded ? (
          <div className="space-y-6">
            <div className="space-y-3">
              <span className="text-sm font-medium">
                {t.agents.editFieldToolGroups}
              </span>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  checked={toolGroupsState.useAll}
                  onChange={(e) =>
                    setToolGroupsState((s) => ({
                      ...s,
                      useAll: e.target.checked,
                    }))
                  }
                />
                {t.agents.editUseAllToolGroups}
              </label>
              {!toolGroupsState.useAll ? (
                toolGroupsError ? (
                  <p className="text-destructive text-xs">
                    {t.agents.editToolGroupsLoadFailed}
                  </p>
                ) : (
                  <div className="ml-6 grid grid-cols-2 gap-2">
                    {toolGroups.map((g) => (
                      <label
                        key={g.name}
                        className="flex items-center gap-2 text-sm"
                      >
                        <input
                          type="checkbox"
                          className="h-4 w-4"
                          checked={toolGroupsState.selected.includes(g.name)}
                          onChange={() => handleToolGroupToggle(g.name)}
                        />
                        {g.name}
                      </label>
                    ))}
                  </div>
                )
              ) : null}
            </div>

            <div className="space-y-3">
              <span className="text-sm font-medium">
                {t.agents.editFieldSkills}
              </span>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  checked={skillsState.useAll}
                  onChange={(e) =>
                    setSkillsState((s) => ({
                      ...s,
                      useAll: e.target.checked,
                    }))
                  }
                />
                {t.agents.editUseAllSkills}
              </label>
              {!skillsState.useAll ? (
                skillsError ? (
                  <p className="text-destructive text-xs">
                    {t.agents.editSkillsLoadFailed}
                  </p>
                ) : (
                  <div className="ml-6 grid grid-cols-2 gap-2">
                    {skills.map((s) => {
                      const checked = skillsState.selected.some(
                        (v) => skillBaseName(v) === s.name,
                      );
                      const pin = skillsState.selected.find(
                        (v) =>
                          skillBaseName(v) === s.name && v.includes("@"),
                      );
                      const version = pin ? pin.split("@", 2)[1] : null;
                      return (
                        <label
                          key={s.name}
                          className="flex items-center gap-2 text-sm"
                        >
                          <input
                            type="checkbox"
                            className="h-4 w-4"
                            checked={checked}
                            onChange={() => handleSkillToggle(s.name)}
                          />
                          <span className="truncate">{s.name}</span>
                          {version ? (
                            <span className="text-muted-foreground text-xs">
                              (
                              {t.agents.editVersionPinned.replace(
                                "{version}",
                                version,
                              )}
                              )
                            </span>
                          ) : null}
                        </label>
                      );
                    })}
                  </div>
                )
              ) : null}
            </div>

            <div className="space-y-2">
              <label htmlFor="org-key-env" className="text-sm font-medium">
                {t.agents.editFieldOrgKeyEnv}
              </label>
              <Input
                id="org-key-env"
                value={orgKeyEnv}
                onChange={(e) => setOrgKeyEnv(e.target.value)}
                placeholder={t.agents.editFieldOrgKeyEnvPlaceholder}
              />
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
