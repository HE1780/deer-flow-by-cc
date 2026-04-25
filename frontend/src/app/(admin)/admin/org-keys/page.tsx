// frontend/src/app/(admin)/admin/org-keys/page.tsx
"use client";

import { KeyIcon, PlusIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useI18n } from "@/core/i18n/hooks";
import { CopyableSecret } from "@/core/identity/components/CopyableSecret";
import { InlineConfirm } from "@/core/identity/components/InlineConfirm";
import { RequirePermission } from "@/core/identity/components/RequirePermission";
import {
  useCreateOrgKey,
  useHasPermission,
  useOrgKeys,
  useRevokeOrgKey,
} from "@/core/identity/hooks";
import { type OrgKeyCreateResult } from "@/core/identity/types";

export default function OrgKeysPage() {
  return (
    <RequirePermission perm="membership:read">
      <Inner />
    </RequirePermission>
  );
}

function Inner() {
  const { t } = useI18n();
  const { data, isLoading } = useOrgKeys();
  const canManage = useHasPermission("membership:read");
  const [createOpen, setCreateOpen] = useState(false);
  const [createdKey, setCreatedKey] = useState<OrgKeyCreateResult | null>(null);

  return (
    <section className="p-6" data-testid="org-keys-page">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Org Key 管理</h1>
        {canManage && (
          <Button
            size="sm"
            onClick={() => setCreateOpen(true)}
            data-testid="org-keys-new-btn"
          >
            <PlusIcon className="size-4" /> 创建新 Key
          </Button>
        )}
      </header>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>名称</TableHead>
            <TableHead>{t.admin.table.colPrefix}</TableHead>
            <TableHead>创建时间</TableHead>
            <TableHead>有效期</TableHead>
            <TableHead>下次自动轮换</TableHead>
            <TableHead>{t.admin.table.colLastUsed}</TableHead>
            <TableHead>状态</TableHead>
            {canManage && <TableHead aria-label="actions" />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading && (
            <TableRow>
              <TableCell colSpan={8} className="text-muted-foreground">
                {t.admin.table.loading}
              </TableCell>
            </TableRow>
          )}
          {data?.keys.map((key) => (
            <TableRow key={key.id} data-testid={`org-key-row-${key.id}`}>
              <TableCell>{key.name}</TableCell>
              <TableCell className="font-mono text-xs">{key.prefix}</TableCell>
              <TableCell>{key.created_at?.slice(0, 10) ?? "—"}</TableCell>
              <TableCell>
                {key.no_expiry
                  ? "永久（系统自动轮换）"
                  : (key.expires_at?.slice(0, 10) ?? "—")}
              </TableCell>
              <TableCell>
                {key.auto_rotate_at ? key.auto_rotate_at.slice(0, 10) : "—"}
              </TableCell>
              <TableCell>{key.last_used_at?.slice(0, 10) ?? "—"}</TableCell>
              <TableCell>
                {key.revoked_at
                  ? `${t.admin.table.statusRevoked} ${key.revoked_at.slice(0, 10)}`
                  : t.admin.table.statusActive}
              </TableCell>
              {canManage && (
                <TableCell>
                  {!key.revoked_at && (
                    <RevokeButton keyId={key.id} />
                  )}
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {createOpen && (
        <CreateOrgKeyDialog
          onClose={() => setCreateOpen(false)}
          onCreated={(k) => {
            setCreatedKey(k);
            setCreateOpen(false);
          }}
        />
      )}
      {createdKey && (
        <PlaintextDialog
          keyResult={createdKey}
          onClose={() => setCreatedKey(null)}
        />
      )}
    </section>
  );
}

function CreateOrgKeyDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (k: OrgKeyCreateResult) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [noExpiry, setNoExpiry] = useState(true);
  const [expiresInDays, setExpiresInDays] = useState(90);
  const create = useCreateOrgKey();

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="org-key-create-dialog">
        <DialogHeader>
          <DialogTitle>创建 Org Key</DialogTitle>
          <DialogDescription>
            明文仅显示一次，请立即复制——我们不会以可恢复的形式存储它。
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim()) return;
            create.mutate(
              {
                name: name.trim(),
                no_expiry: noExpiry,
                expires_in_days: noExpiry ? undefined : expiresInDays,
                allowed_skills: [],
              },
              { onSuccess: onCreated },
            );
          }}
        >
          <label className="grid gap-1 text-sm">
            <span>名称</span>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例：production-ingest"
              required
              data-testid="org-key-name-input"
            />
          </label>

          <fieldset className="grid gap-2 text-sm">
            <legend className="mb-1 font-medium">有效期</legend>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="expiry"
                checked={noExpiry}
                onChange={() => setNoExpiry(true)}
              />
              永久（系统每年自动轮换）
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="expiry"
                checked={!noExpiry}
                onChange={() => setNoExpiry(false)}
              />
              固定有效期
            </label>
            {!noExpiry && (
              <div className="ml-6 flex items-center gap-2">
                <Input
                  type="number"
                  min={30}
                  max={730}
                  value={expiresInDays}
                  onChange={(e) => setExpiresInDays(Number(e.target.value))}
                  className="w-24"
                  data-testid="org-key-days-input"
                />
                <span>天 (30–730)</span>
              </div>
            )}
          </fieldset>

          {create.isError && (
            <p className="text-sm text-red-600" role="alert">
              创建失败，请检查权限后重试。
            </p>
          )}
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {t.admin.actions.cancel}
              </Button>
            </DialogClose>
            <Button
              type="submit"
              disabled={create.isPending || !name.trim()}
              data-testid="org-key-submit-btn"
            >
              {create.isPending ? "创建中…" : "创建"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function PlaintextDialog({
  keyResult,
  onClose,
}: {
  keyResult: OrgKeyCreateResult;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="org-key-plaintext-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyIcon className="size-5" /> Org Key 已创建
          </DialogTitle>
          <DialogDescription>
            请立即复制此值——关闭对话框后仅保留前缀{" "}
            <span className="font-mono">{keyResult.prefix}</span>。
          </DialogDescription>
        </DialogHeader>
        <CopyableSecret
          value={keyResult.plaintext}
          valueTestId="org-key-plaintext-value"
          copyTestId="org-key-copy-btn"
        />
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" data-testid="org-key-plaintext-close-btn">
              {t.admin.actions.done}
            </Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RevokeButton({ keyId }: { keyId: number }) {
  const { t } = useI18n();
  const revoke = useRevokeOrgKey();
  return (
    <InlineConfirm
      label={t.admin.actions.revoke}
      onConfirm={() => revoke.mutate(keyId)}
      pending={revoke.isPending}
      triggerTestId={`org-key-revoke-${keyId}`}
      confirmTestId={`org-key-revoke-confirm-${keyId}`}
    />
  );
}
