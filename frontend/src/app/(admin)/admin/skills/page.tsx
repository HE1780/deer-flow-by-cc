// frontend/src/app/(admin)/admin/skills/page.tsx
"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircleIcon,
  PackagePlusIcon,
  SearchIcon,
  SparklesIcon,
  ToggleLeftIcon,
  ToggleRightIcon,
  XCircleIcon,
} from "lucide-react";
import { useRef, useState } from "react";


import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getBackendBaseURL } from "@/core/config";
import { identityFetch } from "@/core/identity/fetcher";
import { useEnableSkill, useSkills } from "@/core/skills/hooks";
import type { Skill } from "@/core/skills/type";

// ── API helpers ──────────────────────────────────────────────────────────────

interface PendingSkill {
  id: number;
  name: string;
  version: string;
  scope: string;
  status: string;
  created_at: string | null;
  created_by: number;
  storage_path: string;
}

async function fetchPendingSkills(): Promise<PendingSkill[]> {
  const data = await identityFetch<{ skills: PendingSkill[] }>(
    `${getBackendBaseURL()}/api/admin/skills/pending`,
  );
  return data.skills;
}

async function approveSkill(id: number): Promise<void> {
  await identityFetch<unknown>(
    `${getBackendBaseURL()}/api/admin/skills/${id}/approve`,
    { method: "POST", body: "{}" },
  );
}

async function rejectSkill(id: number, reason: string): Promise<void> {
  await identityFetch<unknown>(
    `${getBackendBaseURL()}/api/admin/skills/${id}/reject`,
    { method: "POST", body: JSON.stringify({ reason }) },
  );
}

interface ReviewedSkill {
  id: number;
  name: string;
  version: string;
  scope: string;
  status: string;
  rejection_reason: string | null;
  created_at: string | null;
  created_by: number;
  reviewed_at: string | null;
  storage_path: string;
}

async function fetchReviewedSkills(): Promise<ReviewedSkill[]> {
  const data = await identityFetch<{ skills: ReviewedSkill[] }>(
    `${getBackendBaseURL()}/api/admin/skills/reviewed`,
  );
  return data.skills;
}

async function installSkillFile(file: File): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  // FormData upload: use raw fetch with credentials (identityFetch sets
  // content-type to application/json when body is present, which would
  // break multipart; use fetch directly here with credentials only).
  const res = await fetch(`${getBackendBaseURL()}/api/skills/install`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Install failed (${res.status})`);
  }
}

// ── Sub-components ───────────────────────────────────────────────────────────

function SkillBadge({ category }: { category: string }) {
  const colour =
    category === "public"
      ? "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
      : "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300";
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${colour}`}>
      {category}
    </span>
  );
}

function ScopeBadge({ scope }: { scope: string }) {
  const colour =
    scope === "public"
      ? "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
      : scope === "org"
        ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
        : "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300";
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${colour}`}>
      {scope}
    </span>
  );
}

function SkillRow({
  skill,
  onToggle,
}: {
  skill: Skill;
  onToggle: (name: string, enabled: boolean) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded-lg border bg-card p-4 transition-shadow hover:shadow-sm">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-md bg-muted p-1.5">
          <SparklesIcon className="size-4 text-muted-foreground" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium">{skill.name}</span>
            <SkillBadge category={skill.category} />
            {skill.license && (
              <span className="text-xs text-muted-foreground">
                {skill.license}
              </span>
            )}
          </div>
          <p
            className={`mt-1 text-sm text-muted-foreground ${expanded ? "" : "line-clamp-2"}`}
          >
            {skill.description}
          </p>
          {skill.description.length > 120 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="mt-1 text-xs text-primary hover:underline"
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          )}
        </div>
        <button
          onClick={() => onToggle(skill.name, !skill.enabled)}
          className="shrink-0"
          title={skill.enabled ? "Disable skill" : "Enable skill"}
        >
          {skill.enabled ? (
            <ToggleRightIcon className="size-6 text-primary" />
          ) : (
            <ToggleLeftIcon className="size-6 text-muted-foreground" />
          )}
        </button>
      </div>
    </div>
  );
}

function PendingSkillRow({
  skill,
  onApprove,
  onReject,
}: {
  skill: PendingSkill;
  onApprove: (id: number) => Promise<void>;
  onReject: (id: number) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleApprove() {
    setBusy(true);
    setError(null);
    try {
      await onApprove(skill.id);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border bg-card p-4 transition-shadow hover:shadow-sm">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-md bg-muted p-1.5">
          <SparklesIcon className="size-4 text-muted-foreground" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium">{skill.name}</span>
            <span className="text-xs text-muted-foreground">v{skill.version}</span>
            <ScopeBadge scope={skill.scope} />
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            提交者: {skill.created_by} · {skill.created_at ? new Date(skill.created_at).toLocaleString("zh-CN") : "—"}
          </p>
          {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            onClick={handleApprove}
            disabled={busy}
            className="inline-flex items-center gap-1 rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            <CheckCircleIcon className="size-4" />
            审批
          </button>
          <button
            onClick={() => onReject(skill.id)}
            disabled={busy}
            className="inline-flex items-center gap-1 rounded-md border border-destructive px-3 py-1.5 text-sm font-medium text-destructive hover:bg-destructive/10 disabled:opacity-50"
          >
            <XCircleIcon className="size-4" />
            拒绝
          </button>
        </div>
      </div>
    </div>
  );
}

function ArchivedSkillRow({ skill }: { skill: ReviewedSkill }) {
  const statusColour =
    skill.status === "rejected"
      ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300"
      : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400";
  return (
    <div className="rounded-lg border bg-card p-4 transition-shadow hover:shadow-sm">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-md bg-muted p-1.5">
          <SparklesIcon className="size-4 text-muted-foreground" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium">{skill.name}</span>
            <span className="text-xs text-muted-foreground">v{skill.version}</span>
            <ScopeBadge scope={skill.scope} />
            <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${statusColour}`}>
              {skill.status}
            </span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            提交者: {skill.created_by} · {skill.created_at ? new Date(skill.created_at).toLocaleString("zh-CN") : "—"}
          </p>
          {skill.rejection_reason && (
            <p className="mt-1 text-xs text-destructive">
              拒绝原因：{skill.rejection_reason}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function RejectDialog({
  skillId,
  onConfirm,
  onCancel,
}: {
  skillId: number;
  onConfirm: (id: number, reason: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    setBusy(true);
    setError(null);
    try {
      await onConfirm(skillId, reason);
    } catch (err) {
      setError(String(err));
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-xl border bg-card p-6 shadow-lg space-y-4">
        <h2 className="text-lg font-semibold">拒绝 Skill #{skillId}</h2>
        <p className="text-sm text-muted-foreground">请输入拒绝原因（可选）：</p>
        <textarea
          className="w-full rounded-md border bg-background p-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          rows={3}
          placeholder="拒绝原因…"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md border px-4 py-2 text-sm hover:bg-muted"
          >
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={busy}
            className="rounded-md bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
          >
            {busy ? "处理中…" : "确认拒绝"}
          </button>
        </div>
      </div>
    </div>
  );
}

function InstallButton({ onInstalled }: { onInstalled: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setInstalling(true);
    setError(null);
    try {
      await installSkillFile(file);
      onInstalled();
    } catch (err) {
      setError(String(err));
    } finally {
      setInstalling(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <input
        ref={fileRef}
        type="file"
        accept=".skill,.zip"
        className="hidden"
        onChange={handleFile}
      />
      <button
        onClick={() => fileRef.current?.click()}
        disabled={installing}
        className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {installing ? (
          <>
            <PackagePlusIcon className="size-4 animate-pulse" />
            Installing…
          </>
        ) : (
          <>
            <PackagePlusIcon className="size-4" />
            Install .skill
          </>
        )}
      </button>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function SkillsHubPage() {
  const { skills, isLoading: skillsLoading, error: skillsError } = useSkills();
  const { mutate: enableSkill } = useEnableSkill();
  const queryClient = useQueryClient();

  // Pending skills query
  const {
    data: pendingSkills = [],
    isLoading: pendingLoading,
    error: pendingError,
    refetch: refetchPending,
  } = useQuery({
    queryKey: ["admin", "skills", "pending"],
    queryFn: fetchPendingSkills,
  });

  // Reviewed (rejected/archived) skills query
  const {
    data: reviewedSkills = [],
    isLoading: reviewedLoading,
    error: reviewedError,
  } = useQuery({
    queryKey: ["admin", "skills", "reviewed"],
    queryFn: fetchReviewedSkills,
  });

  // State for active-tab filters
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<"all" | "public" | "custom">("all");

  // Reject dialog state
  const [rejectingId, setRejectingId] = useState<number | null>(null);

  // Categorise active skills from /api/skills (status=active, legacy skills)
  const activeSkills = skills.filter((s) => {
    const matchQuery =
      !query ||
      s.name.toLowerCase().includes(query.toLowerCase()) ||
      s.description.toLowerCase().includes(query.toLowerCase());
    const matchCat = category === "all" || s.category === category;
    return matchQuery && matchCat;
  });

  const counts = {
    all: skills.length,
    public: skills.filter((s) => s.category === "public").length,
    custom: skills.filter((s) => s.category === "custom").length,
    enabled: skills.filter((s) => s.enabled).length,
  };

  async function handleApprove(id: number) {
    await approveSkill(id);
    await refetchPending();
    void queryClient.invalidateQueries({ queryKey: ["skills"] });
  }

  async function handleRejectConfirm(id: number, reason: string) {
    await rejectSkill(id, reason);
    setRejectingId(null);
    await refetchPending();
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Skills Hub</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {counts.enabled} of {counts.all} skills enabled ·{" "}
            {counts.public} public · {counts.custom} custom
          </p>
        </div>
        <InstallButton onInstalled={() => void queryClient.invalidateQueries({ queryKey: ["skills"] })} />
      </div>

      {/* Tab system */}
      <Tabs defaultValue="pending">
        <TabsList>
          <TabsTrigger value="pending">
            待审批
            {pendingSkills.length > 0 && (
              <span className="ml-1.5 rounded-full bg-destructive px-1.5 py-0.5 text-xs font-bold text-destructive-foreground">
                {pendingSkills.length}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="active">已发布</TabsTrigger>
          <TabsTrigger value="archived">已拒绝/归档</TabsTrigger>
        </TabsList>

        {/* Tab 1: Pending review */}
        <TabsContent value="pending">
          <div className="mt-4 space-y-3">
            {pendingLoading && (
              <p className="text-sm text-muted-foreground">加载中…</p>
            )}
            {pendingError && (
              <p className="text-sm text-destructive">
                加载失败: {pendingError.message}
              </p>
            )}
            {!pendingLoading && !pendingError && pendingSkills.length === 0 && (
              <div className="rounded-lg border border-dashed p-10 text-center text-muted-foreground">
                暂无待审批 Skill
              </div>
            )}
            {pendingSkills.map((skill) => (
              <PendingSkillRow
                key={skill.id}
                skill={skill}
                onApprove={handleApprove}
                onReject={(id) => setRejectingId(id)}
              />
            ))}
          </div>
        </TabsContent>

        {/* Tab 2: Active/published skills */}
        <TabsContent value="active">
          <div className="mt-4 space-y-4">
            {/* Filters */}
            <div className="flex flex-wrap items-center gap-3">
              <div className="relative flex-1 min-w-48">
                <SearchIcon className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <input
                  type="search"
                  placeholder="Search skills…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="w-full rounded-md border bg-background py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <div className="flex rounded-md border">
                {(["all", "public", "custom"] as const).map((cat) => (
                  <button
                    key={cat}
                    onClick={() => setCategory(cat)}
                    className={`px-3 py-1.5 text-sm first:rounded-l-md last:rounded-r-md ${
                      category === cat
                        ? "bg-primary text-primary-foreground"
                        : "hover:bg-muted"
                    }`}
                  >
                    {cat.charAt(0).toUpperCase() + cat.slice(1)}
                    <span className="ml-1 text-xs opacity-70">
                      ({counts[cat]})
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {skillsLoading && (
              <p className="text-sm text-muted-foreground">Loading skills…</p>
            )}
            {skillsError && (
              <p className="text-sm text-destructive">
                Failed to load skills: {skillsError.message}
              </p>
            )}
            {!skillsLoading && !skillsError && activeSkills.length === 0 && (
              <div className="rounded-lg border border-dashed p-10 text-center text-muted-foreground">
                {query
                  ? `No skills match "${query}"`
                  : category !== "all"
                    ? `No ${category} skills yet`
                    : "No skills installed"}
              </div>
            )}
            <div className="space-y-3">
              {activeSkills.map((skill) => (
                <SkillRow
                  key={skill.name}
                  skill={skill}
                  onToggle={(name, enabled) => enableSkill({ skillName: name, enabled })}
                />
              ))}
            </div>
          </div>
        </TabsContent>

        {/* Tab 3: Rejected / archived */}
        <TabsContent value="archived">
          <div className="mt-4 space-y-3">
            {reviewedLoading && (
              <p className="text-sm text-muted-foreground">加载中…</p>
            )}
            {reviewedError && (
              <p className="text-sm text-destructive">
                加载失败: {reviewedError.message}
              </p>
            )}
            {!reviewedLoading && !reviewedError && reviewedSkills.length === 0 && (
              <div className="rounded-lg border border-dashed p-10 text-center text-muted-foreground">
                暂无已拒绝或归档的 Skill
              </div>
            )}
            {reviewedSkills.map((skill) => (
              <ArchivedSkillRow key={skill.id} skill={skill} />
            ))}
          </div>
        </TabsContent>
      </Tabs>

      {/* Reject dialog overlay */}
      {rejectingId !== null && (
        <RejectDialog
          skillId={rejectingId}
          onConfirm={handleRejectConfirm}
          onCancel={() => setRejectingId(null)}
        />
      )}
    </div>
  );
}
