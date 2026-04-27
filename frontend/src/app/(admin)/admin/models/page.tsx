// frontend/src/app/(admin)/admin/models/page.tsx
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";

import { getBackendBaseURL } from "@/core/config";
import { identityFetch } from "@/core/identity/fetcher";

interface ModelRow {
  name: string;
  model: string;
  display_name: string | null;
  description: string | null;
  supports_thinking: boolean;
  supports_reasoning_effort: boolean;
}

interface ModelMutation {
  name: string;
  model: string;
  use: string;
  display_name?: string | null;
  description?: string | null;
  base_url?: string | null;
  api_base?: string | null;
  api_key?: string | null;
  supports_thinking?: boolean;
  supports_vision?: boolean;
  supports_reasoning_effort?: boolean;
  use_responses_api?: boolean | null;
  temperature?: number | null;
  max_tokens?: number | null;
  request_timeout?: number | null;
  max_retries?: number | null;
}

const PROVIDER_PRESETS = [
  { label: "OpenAI compatible (ChatOpenAI)", value: "langchain_openai:ChatOpenAI" },
  { label: "Anthropic", value: "langchain_anthropic:ChatAnthropic" },
  { label: "DeepSeek (patched)", value: "deerflow.models.patched_deepseek:PatchedChatDeepSeek" },
  { label: "vLLM (Qwen reasoning)", value: "deerflow.models.vllm_provider:VllmChatModel" },
  { label: "Google Gemini", value: "langchain_google_genai:ChatGoogleGenerativeAI" },
];

async function listModels(): Promise<ModelRow[]> {
  const data = await identityFetch<{ models: ModelRow[] }>(
    `${getBackendBaseURL()}/api/models`,
  );
  return data.models;
}

async function createModel(payload: ModelMutation): Promise<void> {
  await identityFetch<unknown>(`${getBackendBaseURL()}/api/models`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

async function updateModel(name: string, payload: ModelMutation): Promise<void> {
  await identityFetch<unknown>(
    `${getBackendBaseURL()}/api/models/${encodeURIComponent(name)}`,
    { method: "PUT", body: JSON.stringify(payload) },
  );
}

async function fetchRawModel(name: string): Promise<ModelMutation> {
  const raw = await identityFetch<Record<string, unknown>>(
    `${getBackendBaseURL()}/api/admin/models/${encodeURIComponent(name)}/raw`,
  );
  // Coerce to the form shape; unknown extra keys are dropped from the form
  // but preserved in YAML on PUT (the backend keeps `when_thinking_enabled`
  // etc. via PRESERVE_KEYS).
  const str = (v: unknown): string =>
    typeof v === "string" ? v : "";
  const num = (v: unknown): number | undefined =>
    typeof v === "number" ? v : undefined;
  const bool = (v: unknown): boolean => v === true;
  return {
    name: str(raw.name) || name,
    model: str(raw.model),
    use: str(raw.use) || PROVIDER_PRESETS[0]!.value,
    display_name: str(raw.display_name),
    description: str(raw.description),
    base_url: str(raw.base_url) || str(raw.api_base),
    api_key: str(raw.api_key),
    supports_thinking: bool(raw.supports_thinking),
    supports_vision: bool(raw.supports_vision),
    supports_reasoning_effort: bool(raw.supports_reasoning_effort),
    temperature: num(raw.temperature),
    max_tokens: num(raw.max_tokens),
    request_timeout: num(raw.request_timeout) ?? num(raw.timeout),
    max_retries: num(raw.max_retries),
  };
}

async function deleteModel(name: string): Promise<void> {
  // 204 has no body — bypass identityFetch so it doesn't try to parse JSON.
  const res = await fetch(
    `${getBackendBaseURL()}/api/models/${encodeURIComponent(name)}`,
    { method: "DELETE", credentials: "include" },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Delete failed (${res.status})`);
  }
}

function emptyForm(): ModelMutation {
  return {
    name: "",
    model: "",
    use: PROVIDER_PRESETS[0]!.value,
    display_name: "",
    base_url: "",
    api_key: "",
    supports_thinking: false,
    supports_vision: false,
    supports_reasoning_effort: false,
  };
}

function ModelDialog({
  initial,
  onClose,
  onSubmit,
  title,
  lockName,
}: {
  initial: ModelMutation;
  onClose: () => void;
  onSubmit: (payload: ModelMutation) => Promise<void>;
  title: string;
  lockName?: boolean;
}) {
  const [form, setForm] = useState<ModelMutation>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function update<K extends keyof ModelMutation>(key: K, value: ModelMutation[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit() {
    if (!form.name.trim() || !form.model.trim() || !form.use.trim()) {
      setError("名称、模型 ID、Provider 都是必填");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const blankToUndef = (v: string | null | undefined) => {
        const t = v?.trim();
        return t === "" || t === undefined ? undefined : t;
      };
      const payload: ModelMutation = {
        name: form.name.trim(),
        model: form.model.trim(),
        use: form.use.trim(),
        display_name: blankToUndef(form.display_name),
        description: blankToUndef(form.description),
        base_url: blankToUndef(form.base_url),
        api_key: blankToUndef(form.api_key),
        supports_thinking: !!form.supports_thinking,
        supports_vision: !!form.supports_vision,
        supports_reasoning_effort: !!form.supports_reasoning_effort,
        temperature: form.temperature ?? undefined,
        max_tokens: form.max_tokens ?? undefined,
        request_timeout: form.request_timeout ?? undefined,
        max_retries: form.max_retries ?? undefined,
      };
      await onSubmit(payload);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl border bg-card p-6 shadow-lg space-y-4">
        <h2 className="text-lg font-semibold">{title}</h2>

        <div className="grid grid-cols-2 gap-3">
          <Field label="名称（唯一标识） *">
            <input
              className="input"
              value={form.name}
              disabled={lockName}
              onChange={(e) => update("name", e.target.value)}
              placeholder="gpt-4o"
            />
          </Field>
          <Field label="显示名">
            <input
              className="input"
              value={form.display_name ?? ""}
              onChange={(e) => update("display_name", e.target.value)}
              placeholder="GPT-4o"
            />
          </Field>
          <Field label="Provider *">
            <select
              className="input"
              value={form.use}
              onChange={(e) => update("use", e.target.value)}
            >
              {PROVIDER_PRESETS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="模型 ID *">
            <input
              className="input"
              value={form.model}
              onChange={(e) => update("model", e.target.value)}
              placeholder="gpt-4o"
            />
          </Field>
          <Field label="Base URL" colSpan={2}>
            <input
              className="input"
              value={form.base_url ?? ""}
              onChange={(e) => update("base_url", e.target.value)}
              placeholder="https://api.openai.com/v1"
            />
          </Field>
          <Field label="API Key（支持 $ENV_VAR 占位）" colSpan={2}>
            <input
              className="input"
              value={form.api_key ?? ""}
              onChange={(e) => update("api_key", e.target.value)}
              placeholder="$OPENAI_API_KEY"
            />
          </Field>
        </div>

        <div className="flex flex-wrap gap-x-4 gap-y-2">
          <Toggle
            label="支持 thinking"
            checked={!!form.supports_thinking}
            onChange={(v) => update("supports_thinking", v)}
          />
          <Toggle
            label="支持 vision"
            checked={!!form.supports_vision}
            onChange={(v) => update("supports_vision", v)}
          />
          <Toggle
            label="支持 reasoning_effort"
            checked={!!form.supports_reasoning_effort}
            onChange={(v) => update("supports_reasoning_effort", v)}
          />
        </div>

        <details className="rounded-md border bg-muted/30 p-3">
          <summary className="cursor-pointer text-sm font-medium">
            高级参数
          </summary>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <Field label="temperature">
              <input
                type="number"
                step="0.1"
                className="input"
                value={form.temperature ?? ""}
                onChange={(e) =>
                  update(
                    "temperature",
                    e.target.value === "" ? undefined : Number(e.target.value),
                  )
                }
              />
            </Field>
            <Field label="max_tokens">
              <input
                type="number"
                className="input"
                value={form.max_tokens ?? ""}
                onChange={(e) =>
                  update(
                    "max_tokens",
                    e.target.value === "" ? undefined : Number(e.target.value),
                  )
                }
              />
            </Field>
            <Field label="request_timeout (秒)">
              <input
                type="number"
                step="1"
                className="input"
                value={form.request_timeout ?? ""}
                onChange={(e) =>
                  update(
                    "request_timeout",
                    e.target.value === "" ? undefined : Number(e.target.value),
                  )
                }
              />
            </Field>
            <Field label="max_retries">
              <input
                type="number"
                className="input"
                value={form.max_retries ?? ""}
                onChange={(e) =>
                  update(
                    "max_retries",
                    e.target.value === "" ? undefined : Number(e.target.value),
                  )
                }
              />
            </Field>
          </div>
        </details>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onClose}
            className="rounded-md border px-4 py-2 text-sm hover:bg-muted"
          >
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={busy}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {busy ? "保存中…" : "保存"}
          </button>
        </div>

        <style jsx>{`
          :global(.input) {
            width: 100%;
            border-radius: 0.375rem;
            border: 1px solid hsl(var(--border));
            background: hsl(var(--background));
            padding: 0.5rem 0.75rem;
            font-size: 0.875rem;
          }
          :global(.input:focus) {
            outline: none;
            box-shadow: 0 0 0 2px hsl(var(--ring));
          }
        `}</style>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
  colSpan,
}: {
  label: string;
  children: React.ReactNode;
  colSpan?: number;
}) {
  return (
    <label className={`flex flex-col gap-1 ${colSpan === 2 ? "col-span-2" : ""}`}>
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  );
}

export default function ModelsAdminPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin", "models"],
    queryFn: listModels,
  });

  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<ModelMutation | null>(null);
  const [editingLoadError, setEditingLoadError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: createModel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "models"] }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ name, payload }: { name: string; payload: ModelMutation }) =>
      updateModel(name, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "models"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteModel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "models"] }),
  });

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">模型管理</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            在此处设置模型的配置。改动会写入项目根目录的 config.yaml 并即时生效。
          </p>
        </div>
        <button
          onClick={() => setAdding(true)}
          className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          <PlusIcon className="size-4" />
          添加模型
        </button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
      {error && (
        <p className="text-sm text-destructive">
          加载失败：{error instanceof Error ? error.message : String(error)}
        </p>
      )}

      {editingLoadError && (
        <p className="text-sm text-destructive">
          加载模型详情失败：{editingLoadError}
        </p>
      )}

      {!isLoading && !error && (data?.length ?? 0) === 0 && (
        <div className="rounded-lg border border-dashed p-10 text-center text-muted-foreground">
          暂无配置模型，点击右上角「添加模型」开始
        </div>
      )}

      <div className="space-y-3">
        {data?.map((m) => (
          <div
            key={m.name}
            className="flex items-center justify-between rounded-lg border bg-card p-4"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium">{m.display_name ?? m.name}</span>
                <span className="text-xs text-muted-foreground">{m.name}</span>
                {m.supports_thinking && (
                  <Badge label="thinking" tone="violet" />
                )}
                {m.supports_reasoning_effort && (
                  <Badge label="reasoning" tone="amber" />
                )}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                provider model: <code>{m.model}</code>
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <button
                onClick={async () => {
                  setEditingLoadError(null);
                  try {
                    const full = await fetchRawModel(m.name);
                    setEditing(full);
                  } catch (err) {
                    setEditingLoadError(
                      err instanceof Error ? err.message : String(err),
                    );
                  }
                }}
                className="inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm hover:bg-muted"
              >
                <PencilIcon className="size-3.5" />
                编辑
              </button>
              <button
                onClick={() => setConfirmDelete(m.name)}
                className="inline-flex items-center gap-1 rounded-md border border-destructive px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10"
              >
                <Trash2Icon className="size-3.5" />
                删除
              </button>
            </div>
          </div>
        ))}
      </div>

      {adding && (
        <ModelDialog
          initial={emptyForm()}
          title="添加模型"
          onClose={() => setAdding(false)}
          onSubmit={(payload) => createMutation.mutateAsync(payload)}
        />
      )}

      {editing && (
        <ModelDialog
          initial={editing}
          title={`编辑模型：${editing.name}`}
          lockName
          onClose={() => setEditing(null)}
          onSubmit={(payload) =>
            updateMutation.mutateAsync({ name: editing.name, payload })
          }
        />
      )}

      {confirmDelete && (
        <ConfirmDialog
          title="删除模型"
          message={`确定要删除模型「${confirmDelete}」吗？此操作会从 config.yaml 中移除该条目。`}
          onCancel={() => setConfirmDelete(null)}
          onConfirm={async () => {
            await deleteMutation.mutateAsync(confirmDelete);
            setConfirmDelete(null);
          }}
        />
      )}
    </div>
  );
}

function Badge({ label, tone }: { label: string; tone: "violet" | "amber" }) {
  const cls =
    tone === "violet"
      ? "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300"
      : "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300";
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

function ConfirmDialog({
  title,
  message,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-xl border bg-card p-6 shadow-lg space-y-4">
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="text-sm text-muted-foreground">{message}</p>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md border px-4 py-2 text-sm hover:bg-muted"
          >
            取消
          </button>
          <button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await onConfirm();
              } catch (err) {
                setError(err instanceof Error ? err.message : String(err));
                setBusy(false);
              }
            }}
            className="rounded-md bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
          >
            {busy ? "处理中…" : "确认"}
          </button>
        </div>
      </div>
    </div>
  );
}
