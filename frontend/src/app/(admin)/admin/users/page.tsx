// frontend/src/app/(admin)/admin/users/page.tsx
"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { PlusIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";

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
import { PermBadge } from "@/core/identity/components/PermBadge";
import { RequirePermission } from "@/core/identity/components/RequirePermission";
import {
  useCreateUser,
  useHasPermission,
  useIdentity,
  useUsers,
} from "@/core/identity/hooks";
import {
  type CreateUserFields,
  createUserSchema,
} from "@/core/identity/schemas";

const PAGE_SIZE = 20;

export default function UsersPage() {
  return (
    <RequirePermission perm="membership:read">
      <Inner />
    </RequirePermission>
  );
}

function Inner() {
  const { identity } = useIdentity();
  const { t } = useI18n();
  const tid = identity?.active_tenant_id ?? undefined;
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const { data, isLoading, isError } = useUsers(tid, {
    q,
    offset,
    limit: PAGE_SIZE,
  });
  const canInvite = useHasPermission("membership:invite");
  const [createOpen, setCreateOpen] = useState(false);

  return (
    <section className="p-6" data-testid="users-page">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t.admin.pages.usersTitle}</h1>
        <div className="flex items-center gap-3">
          <Input
            aria-label="Filter by email"
            placeholder="Filter by email…"
            className="w-64"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
          />
          {canInvite && (
            <Button
              size="sm"
              onClick={() => setCreateOpen(true)}
              data-testid="users-new-btn"
            >
              <PlusIcon className="size-4" /> {t.admin.actions.newUser}
            </Button>
          )}
        </div>
      </header>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t.admin.table.colEmail}</TableHead>
            <TableHead>{t.admin.table.colName}</TableHead>
            <TableHead>{t.admin.table.colRoles}</TableHead>
            <TableHead>{t.admin.table.colStatus}</TableHead>
            <TableHead>{t.admin.table.colLastLogin}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading && (
            <TableRow>
              <TableCell colSpan={5} className="text-muted-foreground">
                {t.admin.table.loading}
              </TableCell>
            </TableRow>
          )}
          {isError && (
            <TableRow>
              <TableCell colSpan={5} className="text-destructive">
                Failed to load users.
              </TableCell>
            </TableRow>
          )}
          {data?.items.map((u) => (
            <TableRow key={u.id}>
              <TableCell>
                <Link href={`/admin/users/${u.id}`} className="underline">
                  {u.email}
                </Link>
              </TableCell>
              <TableCell>{u.display_name ?? "—"}</TableCell>
              <TableCell className="flex flex-wrap gap-1">
                {u.roles.map((r) => (
                  <PermBadge key={r} perm={r} />
                ))}
              </TableCell>
              <TableCell>
                {u.status === 1
                  ? t.admin.table.statusActive
                  : t.admin.table.statusDisabled}
              </TableCell>
              <TableCell>{u.last_login_at?.slice(0, 10) ?? "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <footer className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
        <span>{data?.total ?? 0} total</span>
        <div className="flex gap-2">
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
        </div>
      </footer>

      {createOpen && tid && (
        <CreateUserDialog
          tenantId={tid}
          onClose={() => setCreateOpen(false)}
        />
      )}
    </section>
  );
}

function CreateUserDialog({
  tenantId,
  onClose,
}: {
  tenantId: number;
  onClose: () => void;
}) {
  // Dialog form for tenant user onboarding, with optional local-password bootstrap.
  const { t } = useI18n();
  const create = useCreateUser(tenantId);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError,
  } = useForm<CreateUserFields>({ resolver: zodResolver(createUserSchema) });

  const onSubmit = async (data: CreateUserFields) => {
    try {
      const initialPassword = data.initial_password?.trim();
      await create.mutateAsync({
        email: data.email,
        display_name: data.display_name?.trim() ?? undefined,
        initial_password:
          initialPassword && initialPassword.length > 0
            ? initialPassword
            : undefined,
      });
      onClose();
    } catch {
      setError("root", {
        message:
          "Could not create user. The email may already be a member of this tenant.",
      });
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid="users-create-dialog">
        <DialogHeader>
          <DialogTitle>{t.admin.actions.newUser}</DialogTitle>
          <DialogDescription>
            Adds the user to this tenant. They sign in via OIDC the first time
            and inherit the tenant&apos;s default workspace role.
          </DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={handleSubmit(onSubmit)}>
          <div className="grid gap-1 text-sm">
            <label htmlFor="users-create-email">{t.admin.forms.emailLabel}</label>
            <Input
              id="users-create-email"
              type="email"
              {...register("email")}
              data-testid="users-create-email"
            />
            {errors.email && (
              <p className="text-xs text-destructive">{errors.email.message}</p>
            )}
          </div>
          <div className="grid gap-1 text-sm">
            <label htmlFor="users-create-display-name">
              Display name (optional)
            </label>
            <Input
              id="users-create-display-name"
              {...register("display_name")}
              data-testid="users-create-display-name"
            />
          </div>
          <div className="grid gap-1 text-sm">
            <label htmlFor="users-create-initial-password">
              Initial password (optional)
            </label>
            <Input
              id="users-create-initial-password"
              type="password"
              autoComplete="new-password"
              placeholder="At least 8 characters"
              {...register("initial_password")}
              data-testid="users-create-initial-password"
            />
            {errors.initial_password && (
              <p className="text-xs text-destructive">
                {errors.initial_password.message}
              </p>
            )}
          </div>
          {errors.root && (
            <p className="text-sm text-red-600" role="alert">
              {errors.root.message}
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
              disabled={isSubmitting}
              data-testid="users-create-submit"
            >
              {isSubmitting ? "Creating…" : t.admin.actions.newUser}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
