// frontend/src/app/(admin)/admin/audit/page.tsx
"use client";

import { DownloadIcon } from "lucide-react";
import { useMemo, useState } from "react";

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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useI18n } from "@/core/i18n/hooks";
import { RequirePermission } from "@/core/identity/components/RequirePermission";
import { useAudit, useIdentity } from "@/core/identity/hooks";
import type { AuditFilters, AuditRow } from "@/core/identity/types";

export default function AuditPage() {
  return (
    <RequirePermission
      perm="audit:read"
      fallback={
        <section className="p-6" data-testid="audit-denied">
          <h2 className="text-lg font-semibold">Permission required</h2>
          <p className="text-sm text-muted-foreground">
            You need <code>audit:read</code> to view audit logs.
          </p>
        </section>
      }
    >
      <Inner />
    </RequirePermission>
  );
}

function Inner() {
  const { identity } = useIdentity();
  const { t } = useI18n();
  const tid = identity?.active_tenant_id ?? undefined;
  const [filters, setFilters] = useState<AuditFilters>({ limit: 50 });
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([
    undefined,
  ]);
  const [selected, setSelected] = useState<AuditRow | null>(null);

  const currentCursor = cursorStack[cursorStack.length - 1];

  const { data, isLoading } = useAudit(tid, {
    ...filters,
    cursor: currentCursor,
  });

  const exportHref = useMemo(() => {
    if (!tid) return null;
    const qs = new URLSearchParams();
    if (filters.action) qs.set("action", filters.action);
    if (filters.user_id) qs.set("user_id", String(filters.user_id));
    if (filters.resource_type) qs.set("resource_type", filters.resource_type);
    if (filters.result) qs.set("result", filters.result);
    if (filters.date_from) qs.set("date_from", filters.date_from);
    if (filters.date_to) qs.set("date_to", filters.date_to);
    const q = qs.toString();
    return `/api/tenants/${tid}/audit/export${q ? `?${q}` : ""}`;
  }, [tid, filters]);

  const onChangeFilter = (next: Partial<AuditFilters>) => {
    setCursorStack([undefined]);
    setFilters((prev) => ({ ...prev, ...next }));
  };

  return (
    <section className="p-6" data-testid="audit-page">
      <header className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{t.admin.pages.auditTitle}</h1>
        <Input
          aria-label="Filter action"
          placeholder={t.admin.audit.filterAction}
          className="w-64"
          value={filters.action ?? ""}
          data-testid="audit-action-filter"
          onChange={(e) =>
            onChangeFilter({ action: e.target.value || undefined })
          }
        />
        <Input
          aria-label="Filter user id"
          placeholder={t.admin.audit.filterUserId}
          className="w-28"
          type="number"
          min={1}
          value={filters.user_id ?? ""}
          onChange={(e) =>
            onChangeFilter({
              user_id: e.target.value ? Number(e.target.value) : undefined,
            })
          }
        />
        <Input
          aria-label="Filter resource type"
          placeholder={t.admin.audit.filterResource}
          className="w-40"
          value={filters.resource_type ?? ""}
          onChange={(e) =>
            onChangeFilter({ resource_type: e.target.value || undefined })
          }
        />
        <Select
          value={filters.result ?? "all"}
          onValueChange={(v) =>
            onChangeFilter({
              result: v === "all" ? undefined : (v as "success" | "failure"),
            })
          }
        >
          <SelectTrigger className="w-40" data-testid="audit-result-filter">
            <SelectValue placeholder={t.admin.audit.filterResult} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t.admin.audit.resultAll}</SelectItem>
            <SelectItem value="success">{t.admin.audit.resultSuccess}</SelectItem>
            <SelectItem value="failure">{t.admin.audit.resultFailure}</SelectItem>
          </SelectContent>
        </Select>
        <Input
          aria-label="From date"
          type="date"
          className="w-40"
          value={filters.date_from ?? ""}
          onChange={(e) =>
            onChangeFilter({ date_from: e.target.value || undefined })
          }
        />
        <Input
          aria-label="To date"
          type="date"
          className="w-40"
          value={filters.date_to ?? ""}
          onChange={(e) =>
            onChangeFilter({ date_to: e.target.value || undefined })
          }
        />
        {exportHref && (
          <a
            href={exportHref}
            download
            className="ml-auto inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm hover:bg-accent"
            data-testid="audit-export-link"
          >
            <DownloadIcon className="size-4" /> {t.admin.actions.exportCsv}
          </a>
        )}
      </header>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time (UTC)</TableHead>
            <TableHead>Actor</TableHead>
            <TableHead>Action</TableHead>
            <TableHead>Resource</TableHead>
            <TableHead>Result</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading && (
            <TableRow>
              <TableCell colSpan={5} className="text-muted-foreground">
                Loading…
              </TableCell>
            </TableRow>
          )}
          {data?.items.map((e) => (
            <TableRow
              key={e.id}
              role="button"
              tabIndex={0}
              className="cursor-pointer hover:bg-accent/40"
              data-testid={`audit-row-${e.id}`}
              onClick={() => setSelected(e)}
              onKeyDown={(ev) => {
                if (ev.key === "Enter" || ev.key === " ") {
                  ev.preventDefault();
                  setSelected(e);
                }
              }}
            >
              <TableCell className="font-mono text-xs">
                {e.created_at?.replace("T", " ").slice(0, 19) ?? "—"}
              </TableCell>
              <TableCell>{e.user_id ?? "—"}</TableCell>
              <TableCell className="font-mono text-xs">{e.action}</TableCell>
              <TableCell>
                {e.resource_type
                  ? `${e.resource_type}:${e.resource_id ?? ""}`
                  : "—"}
              </TableCell>
              <TableCell
                className={e.result === "failure" ? "text-destructive" : ""}
              >
                {e.result}
              </TableCell>
            </TableRow>
          ))}
          {data?.items.length === 0 && !isLoading && (
            <TableRow>
              <TableCell colSpan={5} className="text-muted-foreground">
                {t.admin.audit.noEvents}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <footer className="mt-4 flex gap-2 text-sm">
        <button
          type="button"
          className="rounded-md border px-3 py-1 disabled:opacity-50"
          disabled={cursorStack.length <= 1}
          onClick={() => setCursorStack(cursorStack.slice(0, -1))}
        >
          Prev
        </button>
        <button
          type="button"
          className="rounded-md border px-3 py-1 disabled:opacity-50"
          disabled={!data?.next_cursor}
          onClick={() => {
            if (data?.next_cursor)
              setCursorStack([...cursorStack, data.next_cursor]);
          }}
        >
          Next
        </button>
      </footer>

      {selected && (
        <AuditDetailDialog
          row={selected}
          onClose={() => setSelected(null)}
        />
      )}
    </section>
  );
}

function AuditDetailDialog({
  row,
  onClose,
}: {
  row: AuditRow;
  onClose: () => void;
}) {
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        className="max-w-2xl"
        data-testid="audit-detail-dialog"
      >
        <DialogHeader>
          <DialogTitle className="font-mono text-base">
            {row.action}
          </DialogTitle>
          <DialogDescription>
            Event {row.id} ·{" "}
            {row.created_at?.replace("T", " ").slice(0, 19) ?? "unknown time"}
          </DialogDescription>
        </DialogHeader>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
          <Detail label="Result" value={row.result} />
          <Detail label="User id" value={row.user_id ?? "—"} />
          <Detail label="Tenant id" value={row.tenant_id ?? "—"} />
          <Detail label="Workspace id" value={row.workspace_id ?? "—"} />
          <Detail label="Thread id" value={row.thread_id ?? "—"} />
          <Detail label="Resource type" value={row.resource_type ?? "—"} />
          <Detail label="Resource id" value={row.resource_id ?? "—"} />
          <Detail label="IP" value={row.ip ?? "—"} />
          <Detail label="User agent" value={row.user_agent ?? "—"} />
          <Detail label="Duration" value={row.duration_ms != null ? `${row.duration_ms} ms` : "—"} />
          <Detail label="Error code" value={row.error_code ?? "—"} />
        </dl>
        <div>
          <p className="mb-1 text-sm font-medium">Metadata</p>
          <pre
            className="max-h-64 overflow-auto rounded-md border bg-muted/40 p-3 text-xs"
            data-testid="audit-detail-metadata"
          >
            {JSON.stringify(row.metadata, null, 2)}
          </pre>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button">Close</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono text-xs break-all">{value}</dd>
    </>
  );
}
