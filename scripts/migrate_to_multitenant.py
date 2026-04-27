#!/usr/bin/env python3
"""One-shot migration to the multi-tenant storage layout (spec §10.2).

Typical usage::

    # dry-run (safe, writes nothing but the report JSON):
    python scripts/migrate_to_multitenant.py --dry-run

    # real migration to the default tenant + workspace:
    python scripts/migrate_to_multitenant.py --apply

    # migration targeting a non-default tenant:
    python scripts/migrate_to_multitenant.py --apply --tenant-slug acme

Behaviour contract
------------------

* ``--dry-run`` **never** mutates the filesystem.
* ``--apply`` acquires a PG advisory lock AND a file lock before moving
  anything. Concurrent invocations (same host or separate replicas) fail
  with a non-zero exit code.
* A JSON report is always written, even on failure, under
  ``$DEER_FLOW_HOME/_system/migration_report_{ts}.json``.
* Exit code ``0`` on success, ``1`` on pre-check failure, ``2`` on
  argument error, ``3`` on lock contention, ``4`` on partial / failed
  migration.

Rollback is exposed separately::

    python scripts/migrate_to_multitenant.py --rollback --report PATH

The CLI re-reads the plan's tenant/workspace from ``PATH`` so the caller
doesn't need to pass them twice.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure ``backend/`` is on ``sys.path`` so the ``app.*`` imports below
# work whether the script is invoked via ``uv run`` (which sets
# PYTHONPATH=backend) or directly via ``python scripts/...`` from the
# repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


logger = logging.getLogger("deerflow.migrate")

_EXIT_OK = 0
_EXIT_PRECHECK = 1
_EXIT_USAGE = 2
_EXIT_LOCK = 3
_EXIT_FAIL = 4


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="migrate_to_multitenant",
        description="Migrate legacy single-tenant on-disk state to the multi-tenant layout (spec §10.2).",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    mode.add_argument("--apply", action="store_true", help="execute the plan (writes)")
    mode.add_argument(
        "--rollback",
        action="store_true",
        help="reverse a previously-applied plan (requires --report)",
    )

    p.add_argument("--tenant-slug", default="default", help="target tenant slug (default: 'default')")
    p.add_argument("--workspace-slug", default="default", help="target workspace slug (default: 'default')")
    p.add_argument(
        "--report",
        type=Path,
        default=None,
        help="output report path (default: $DEER_FLOW_HOME/_system/migration_report_{ts}.json)",
    )
    p.add_argument(
        "--no-db",
        action="store_true",
        help="skip DB pre-check and advisory lock (use for air-gapped rehearsals)",
    )
    p.add_argument(
        "--legacy-home",
        type=Path,
        default=None,
        help="override the legacy $DEER_FLOW_HOME (default: the live value)",
    )
    p.add_argument(
        "--repo-root",
        type=Path,
        default=_REPO_ROOT,
        help="override the repo root used to resolve skills/custom, skills/user",
    )
    p.add_argument("--verbose", "-v", action="store_true")

    return p.parse_args(argv)


async def _resolve_tenant_workspace(engine, *, tenant_slug: str, workspace_slug: str) -> tuple[int, int]:
    """Look up the (tenant_id, workspace_id) for the given slugs.

    The caller is expected to pre-check that the identity schema exists
    (via ``precheck``). This function raises ``RuntimeError`` if either
    row is missing so the CLI can render a clear error.
    """

    from sqlalchemy import select  # local import — keep imports optional in --no-db
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.gateway.identity.models import Tenant, Workspace

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.slug == tenant_slug))).scalar_one_or_none()
        if tenant is None:
            raise RuntimeError(f"tenant with slug {tenant_slug!r} not found")
        workspace = (
            await session.execute(
                select(Workspace).where(
                    Workspace.tenant_id == tenant.id,
                    Workspace.slug == workspace_slug,
                )
            )
        ).scalar_one_or_none()
        if workspace is None:
            raise RuntimeError(f"workspace {workspace_slug!r} not found in tenant {tenant_slug!r}")
        return tenant.id, workspace.id


async def _precheck(
    *,
    legacy_home: Path,
    engine,
    skip_db: bool,
) -> list[str]:
    """Return a list of precondition failures; empty list = ready to run.

    Checks:

    * ``legacy_home`` exists and is writable.
    * ``{legacy_home}/_system`` is creatable (mkdir -p).
    * No stale ``migration_lock_path`` (lock file check is done in the
      lock context manager; here we only warn).
    * DB connectivity (when ``skip_db`` is False).
    * ``identity`` schema + ``tenants`` table exist (same condition).
    """

    from app.gateway.identity.storage.paths import migration_lock_path

    issues: list[str] = []

    if not legacy_home.exists():
        issues.append(f"DEER_FLOW_HOME {legacy_home!s} does not exist")
    elif not os.access(str(legacy_home), os.W_OK):
        issues.append(f"DEER_FLOW_HOME {legacy_home!s} is not writable")

    # _system dir must be creatable so we can drop reports + the lockfile.
    sys_dir = legacy_home / "_system"
    try:
        sys_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        issues.append(f"cannot create {sys_dir!s}: {exc}")

    # Stale lock → fail loudly so operators don't think "it's stuck".
    if migration_lock_path().exists():
        # Non-fatal here because the file_lock() ctx itself probes flock;
        # a stale file with no process holding it is safe to reuse.
        logger.warning("lock file %s exists — will try to take flock", migration_lock_path())

    if skip_db:
        return issues

    if engine is None:
        issues.append("DB engine not configured (set DEERFLOW_DATABASE_URL or use --no-db)")
        return issues

    try:
        from sqlalchemy import text

        async with engine.connect() as conn:
            # Probe the identity schema + a seed table.
            await conn.execute(text("SELECT 1"))
            await conn.execute(text("SELECT 1 FROM identity.tenants LIMIT 1"))
    except Exception as exc:  # noqa: BLE001
        issues.append(f"DB pre-check failed: {type(exc).__name__}: {exc}")

    return issues


def _print_plan(plan) -> None:
    """Render the plan in a human-friendly shape on stdout."""

    from app.gateway.identity.migration.planner import ItemKind

    by_kind: dict[ItemKind, list] = {k: [] for k in ItemKind}
    for item in plan.items:
        by_kind[item.kind].append(item)

    print()
    print(f"Migration plan: tenant_slug={plan.tenant_slug} (id={plan.tenant_id}), workspace_slug={plan.workspace_slug} (id={plan.workspace_id})")
    print(f"  total items:       {len(plan.items)}")
    print(f"  pending moves:     {len(plan.pending)}")
    print(f"  already migrated:  {len(plan.skipped)}")
    print()
    for kind, items in by_kind.items():
        if not items:
            continue
        print(f"[{kind.value}] ({len(items)} items)")
        for it in items[:50]:
            status = "SKIP" if it.already_migrated else "MOVE"
            print(f"  {status}  {it.source}  ->  {it.target}")
        if len(items) > 50:
            print(f"  ... +{len(items) - 50} more")
        print()


async def _cmd_run(args: argparse.Namespace) -> int:
    from app.gateway.identity.migration.executor import apply_plan
    from app.gateway.identity.migration.lock import (
        LockAcquireError,
        file_lock,
        pg_advisory_lock,
    )
    from app.gateway.identity.migration.planner import build_plan
    from app.gateway.identity.migration.report import now_ts
    from app.gateway.identity.storage.paths import (
        deerflow_home,
        migration_lock_path,
        migration_report_path,
    )

    legacy_home = args.legacy_home or deerflow_home()
    engine = _build_engine_or_none(args.no_db)

    # --- Pre-check ---
    issues = await _precheck(legacy_home=legacy_home, engine=engine, skip_db=args.no_db)
    if issues:
        print("Pre-check failed:", file=sys.stderr)
        for s in issues:
            print(f"  - {s}", file=sys.stderr)
        await _dispose(engine)
        return _EXIT_PRECHECK

    # --- Resolve tenant + workspace ---
    if args.no_db:
        if args.tenant_slug != "default" or args.workspace_slug != "default":
            print("--no-db requires tenant-slug=default and workspace-slug=default", file=sys.stderr)
            return _EXIT_USAGE
        tenant_id, workspace_id = 1, 1
    else:
        try:
            tenant_id, workspace_id = await _resolve_tenant_workspace(engine, tenant_slug=args.tenant_slug, workspace_slug=args.workspace_slug)
        except Exception as exc:  # noqa: BLE001
            print(f"Tenant/workspace resolution failed: {exc}", file=sys.stderr)
            await _dispose(engine)
            return _EXIT_PRECHECK

    # --- Build the plan ---
    plan = build_plan(
        legacy_home=legacy_home,
        repo_root=args.repo_root,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        tenant_slug=args.tenant_slug,
        workspace_slug=args.workspace_slug,
    )
    _print_plan(plan)

    report_path = args.report or migration_report_path(now_ts())

    # --- Locks + execution ---
    try:
        if args.apply:
            with file_lock(migration_lock_path()):
                async with pg_advisory_lock(engine):
                    report = await apply_plan(
                        plan,
                        report_path=report_path,
                        audit_writer=_make_audit_writer(args.no_db),
                        dry_run=False,
                    )
        else:  # dry-run
            report = await apply_plan(plan, report_path=report_path, dry_run=True)
    except LockAcquireError as exc:
        print(f"Migration already in progress: {exc}", file=sys.stderr)
        await _dispose(engine)
        return _EXIT_LOCK
    finally:
        await _dispose(engine)

    print(f"\nReport written to: {report_path}")
    print(f"  moved:   {sum(1 for i in report.items if i.status == 'moved')}")
    print(f"  skipped: {sum(1 for i in report.items if i.status == 'skipped')}")
    print(f"  failed:  {sum(1 for i in report.items if i.status == 'failed')}")

    if report.errors:
        return _EXIT_FAIL
    return _EXIT_OK


async def _cmd_rollback(args: argparse.Namespace) -> int:
    import json

    from app.gateway.identity.migration.lock import (
        LockAcquireError,
        file_lock,
        pg_advisory_lock,
    )
    from app.gateway.identity.migration.planner import (
        ItemKind,
        MigrationItem,
        MigrationPlan,
    )
    from app.gateway.identity.migration.report import now_ts
    from app.gateway.identity.migration.rollback import rollback_plan
    from app.gateway.identity.storage.paths import (
        deerflow_home,
        migration_lock_path,
        migration_report_path,
    )

    if args.report is None:
        print("--rollback requires --report PATH", file=sys.stderr)
        return _EXIT_USAGE

    try:
        prior = json.loads(args.report.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"Could not read report {args.report}: {exc}", file=sys.stderr)
        return _EXIT_USAGE

    items = tuple(
        MigrationItem(
            kind=ItemKind(raw["kind"]),
            source=Path(raw["source"]),
            target=Path(raw["target"]),
        )
        for raw in prior.get("items", [])
        if raw.get("status") == "moved"
    )
    plan = MigrationPlan(
        tenant_id=prior["tenant_id"],
        workspace_id=prior["workspace_id"],
        tenant_slug=prior.get("tenant_slug", "default"),
        workspace_slug=prior.get("workspace_slug", "default"),
        items=items,
    )
    if not items:
        print("No moved items to roll back.", file=sys.stderr)
        return _EXIT_OK

    engine = _build_engine_or_none(args.no_db)

    report_path = migration_report_path("rollback-" + now_ts())
    try:
        with file_lock(migration_lock_path()):
            async with pg_advisory_lock(engine):
                report = await rollback_plan(
                    plan,
                    report_path=report_path,
                    audit_writer=_make_audit_writer(args.no_db),
                )
    except LockAcquireError as exc:
        print(f"Rollback blocked: {exc}", file=sys.stderr)
        await _dispose(engine)
        return _EXIT_LOCK
    finally:
        await _dispose(engine)

    # Silence unused var warnings for deerflow_home import.
    _ = deerflow_home

    print(f"\nRollback report: {report_path}")
    if report.errors:
        return _EXIT_FAIL
    return _EXIT_OK


def _build_engine_or_none(skip_db: bool):
    if skip_db:
        return None
    try:
        from app.gateway.identity.db import create_engine_and_sessionmaker
        from app.gateway.identity.settings import get_identity_settings
    except Exception:  # noqa: BLE001
        logger.exception("identity bootstrap import failed")
        return None

    settings = get_identity_settings()
    if not settings.database_url:
        return None
    engine, _ = create_engine_and_sessionmaker(settings.database_url)
    return engine


def _make_audit_writer(skip_db: bool):
    """Return an awaitable writer or None.

    The migration runs outside the gateway lifespan, so we don't have a
    live ``AuditBatchWriter``. Instead we emit directly to the fallback
    JSONL log: events survive in one file operators can ship to the
    batch writer's backfill path on the next gateway boot.
    """

    if skip_db:
        return None

    from app.gateway.identity.audit.fallback import FallbackLog
    from app.gateway.identity.storage.paths import deerflow_home

    # FallbackLog wants the deerflow root; it appends _audit/fallback.jsonl
    # internally. Passing the full file path causes nested directories.
    log = FallbackLog(deerflow_home())

    async def _write(event, critical: bool) -> None:  # noqa: ARG001 — contract
        await log.write(event)

    return _write


async def _dispose(engine) -> None:
    if engine is not None:
        try:
            await engine.dispose()
        except Exception:  # noqa: BLE001
            logger.exception("engine dispose failed")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # --legacy-home is a test/rehearsal override: force the storage layer
    # to treat it as the live $DEER_FLOW_HOME so source AND target paths
    # agree on the same root. In production neither flag is passed and
    # the existing DEER_FLOW_HOME (or the fallback) drives both.
    if args.legacy_home is not None:
        os.environ["DEER_FLOW_HOME"] = str(args.legacy_home)
    if args.rollback:
        return asyncio.run(_cmd_rollback(args))
    return asyncio.run(_cmd_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
