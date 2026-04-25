// frontend/src/app/(admin)/admin/tokens/page.tsx
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
import { PermBadge } from "@/core/identity/components/PermBadge";
import { RequirePermission } from "@/core/identity/components/RequirePermission";
import {
  useCreateTenantToken,
  useHasPermission,
  useIdentity,
  useRevokeTenantToken,
  useTenantTokens,
} from "@/core/identity/hooks";
import { type CreateTokenResult } from "@/core/identity/types";

const PAGE_SIZE = 50;

export default function TokensPage() {
  return (
    <RequirePermission perm="token:read">
      <Inner />
    </RequirePermission>
  );
}

function Inner() {
  const { identity } = useIdentity();
  const { t } = useI18n();
  const tid = identity?.active_tenant_id ?? undefined;
  const [offset, setOffset] = useState(0);
  const [includeRevoked, setIncludeRevoked] = useState(false);
  const { data, isLoading } = useTenantTokens(tid, {
    include_revoked: includeRevoked,
    offset,
    limit: PAGE_SIZE,
  });

  const canCreate = useHasPermission("token:create");
  const canRevoke = useHasPermission("token:revoke");
  const [createOpen, setCreateOpen] = useState(false);
  const [createdToken, setCreatedToken] = useState<CreateTokenResult | null>(
    null,
  );

  return (
    <section className="p-6" data-testid="tokens-page">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t.admin.pages.tokensTitle}</h1>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={includeRevoked}
              onChange={(e) => setIncludeRevoked(e.target.checked)}
            />
            {t.admin.tokens.showRevoked}
          </label>
          {canCreate && (
            <Button
              size="sm"
              onClick={() => setCreateOpen(true)}
              data-testid="tokens-new-btn"
            >
              <PlusIcon className="size-4" /> {t.admin.actions.newToken}
            </Button>
          )}
        </div>
      </header>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t.admin.table.colName}</TableHead>
            <TableHead>{t.admin.table.colPrefix}</TableHead>
            <TableHead>{t.admin.table.colScopes}</TableHead>
            <TableHead>{t.admin.table.colLastUsed}</TableHead>
            <TableHead>{t.admin.table.colStatus}</TableHead>
            {canRevoke && <TableHead aria-label="actions" />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading && (
            <TableRow>
              <TableCell colSpan={6} className="text-muted-foreground">
                {t.admin.table.loading}
              </TableCell>
            </TableRow>
          )}
          {data?.items.map((tok) => (
            <TableRow key={tok.id} data-testid={`token-row-${tok.id}`}>
              <TableCell>{tok.name}</TableCell>
              <TableCell className="font-mono text-xs">{tok.prefix}</TableCell>
              <TableCell className="flex flex-wrap gap-1">
                {tok.scopes.map((s) => (
                  <PermBadge key={s} perm={s} />
                ))}
              </TableCell>
              <TableCell>{tok.last_used_at?.slice(0, 10) ?? "—"}</TableCell>
              <TableCell>
                {tok.revoked_at
                  ? `${t.admin.table.statusRevoked} ${tok.revoked_at.slice(0, 10)}`
                  : tok.expires_at
                    ? `expires ${tok.expires_at.slice(0, 10)}`
                    : t.admin.table.statusActive}
              </TableCell>
              {canRevoke && (
                <TableCell>
                  {!tok.revoked_at && tid && (
                    <RevokeButton tenantId={tid} tokenId={tok.id} />
                  )}
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <footer className="mt-4 flex gap-2 text-sm">
        <button
          type="button"
          className="rounded-md border px-3 py-1 disabled:opacity-50"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
        >
          {t.admin.table.prev}
        </button>
        <button
          type="button"
          className="rounded-md border px-3 py-1 disabled:opacity-50"
          disabled={!data || offset + PAGE_SIZE >= data.total}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          {t.admin.table.next}
        </button>
      </footer>

      {createOpen && tid && identity && (
        <CreateTokenDialog
          tenantId={tid}
          callerUserId={identity.user_id}
          onClose={() => setCreateOpen(false)}
          onCreated={(t) => {
            setCreatedToken(t);
            setCreateOpen(false);
          }}
        />
      )}
      {createdToken && (
        <PlaintextDialog
          token={createdToken}
          onClose={() => setCreatedToken(null)}
        />
      )}
    </section>
  );
}

function CreateTokenDialog({
  tenantId,
  callerUserId,
  onClose,
  onCreated,
}: {
  tenantId: number;
  callerUserId: number;
  onClose: () => void;
  onCreated: (tok: CreateTokenResult) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [scopesText, setScopesText] = useState("skill:invoke");
  const create = useCreateTenantToken(tenantId);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="token-create-dialog">
        <DialogHeader>
          <DialogTitle>{t.admin.tokens.createTitle}</DialogTitle>
          <DialogDescription>{t.admin.tokens.createDesc}</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim()) return;
            create.mutate(
              {
                name: name.trim(),
                scopes: scopesText
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
                user_id: callerUserId,
              },
              { onSuccess: onCreated },
            );
          }}
        >
          <label className="grid gap-1 text-sm">
            <span>{t.admin.tokens.nameLabel}</span>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="ci-bot, ingest-job, …"
              required
              data-testid="token-name-input"
            />
          </label>
          <label className="grid gap-1 text-sm">
            <span>{t.admin.tokens.scopesLabel}</span>
            <Input
              value={scopesText}
              onChange={(e) => setScopesText(e.target.value)}
              placeholder="skill:invoke, thread:read"
              data-testid="token-scopes-input"
            />
          </label>
          {create.isError && (
            <p className="text-sm text-red-600" role="alert">
              Failed to create token. Check your permissions and try again.
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
              data-testid="token-submit-btn"
            >
              {create.isPending ? "Creating…" : t.admin.actions.newToken}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function PlaintextDialog({
  token,
  onClose,
}: {
  token: CreateTokenResult;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="token-plaintext-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyIcon className="size-5" /> {t.admin.tokens.createdTitle}
          </DialogTitle>
          <DialogDescription>
            {t.admin.tokens.createdDesc}{" "}
            <span className="font-mono">{token.prefix}</span>
          </DialogDescription>
        </DialogHeader>
        <CopyableSecret
          value={token.plaintext}
          valueTestId="token-plaintext-value"
          copyTestId="token-copy-btn"
        />
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" data-testid="token-plaintext-close-btn">
              {t.admin.actions.done}
            </Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RevokeButton({ tenantId, tokenId }: { tenantId: number; tokenId: number }) {
  const { t } = useI18n();
  const revoke = useRevokeTenantToken(tenantId);
  return (
    <InlineConfirm
      label={t.admin.actions.revoke}
      onConfirm={() => revoke.mutate(tokenId)}
      pending={revoke.isPending}
      triggerTestId={`token-revoke-${tokenId}`}
      confirmTestId={`token-revoke-confirm-${tokenId}`}
    />
  );
}
