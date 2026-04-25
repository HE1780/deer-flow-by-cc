"""POST /api/skills/publish — skill publish endpoint (Task 5.2a).

Auth: API token with ``skill:publish`` scope (enforced via ``requires()``).

The endpoint accepts a manifest YAML and a SKILL.md, validates both,
writes the files to the appropriate path under ``$DEER_FLOW_HOME/skills/…``,
inserts a row in ``identity.skill_registry``, and emits a ``skill.published``
audit event.

Scope → storage path mapping (mirrors spec §7.2 / §7.4):
  private → tenants/{tid}/users/{uid}/skills/{name}/v{version}/
  org     → tenants/{tid}/org-skills/{name}/v{version}/
  public  → skills/public/{name}/v{version}/

Status:
  private → 'active'           (owner only, no review needed)
  org     → 'pending_review'   (tenant admin must approve)
  public  → 'pending_review'   (platform admin must approve)
"""

from __future__ import annotations

import asyncio
import logging
import re
import textwrap
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import text

from app.gateway.identity.audit.events import AuditEvent
from app.gateway.identity.auth.identity import Identity
from app.gateway.identity.auth.runtime import get_runtime
from app.gateway.identity.rbac.decorator import requires
from app.gateway.identity.storage.path_guard import assert_within_tenant_root
from app.gateway.identity.storage.paths import deerflow_home

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
# Simple semver: MAJOR.MINOR.PATCH with optional pre-release / build metadata.
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+([-.][A-Za-z0-9.+\-]*)?$")
_VALID_SCOPES = frozenset({"public", "org", "private"})


def _validate_manifest(raw: str) -> dict:
    """Parse and validate the manifest YAML; raise HTTPException on failure."""
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"manifest YAML parse error: {exc}")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="manifest must be a YAML mapping")

    errors: list[str] = []

    name = data.get("name", "")
    if not isinstance(name, str) or not name:
        errors.append("name: required non-empty string")
    elif not _NAME_RE.match(name):
        errors.append("name: must match [a-z0-9-], max 64 chars")

    version = data.get("version", "")
    if not isinstance(version, str) or not version:
        errors.append("version: required non-empty string")
    elif not _SEMVER_RE.match(str(version)):
        errors.append(f"version: must be valid semver (e.g. 1.0.0), got {version!r}")

    scope = data.get("scope", "")
    if scope not in _VALID_SCOPES:
        errors.append(f"scope: must be one of {sorted(_VALID_SCOPES)}, got {scope!r}")

    description = data.get("description", "")
    if not isinstance(description, str) or not description.strip():
        errors.append("description: required non-empty string")

    author = data.get("author", "")
    if not isinstance(author, str) or not author.strip():
        errors.append("author: required non-empty string")

    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    return data


def _validate_skill_md(skill_md: str) -> dict:
    """Parse SKILL.md frontmatter; raise HTTPException if name/description missing."""
    stripped = skill_md.strip()
    if not stripped.startswith("---"):
        raise HTTPException(status_code=400, detail="SKILL.md: missing YAML frontmatter (must start with ---)")

    # Extract the first --- ... --- block.
    rest = stripped[3:]
    end = rest.find("---")
    if end == -1:
        raise HTTPException(status_code=400, detail="SKILL.md: frontmatter block not closed with ---")

    fm_raw = rest[:end].strip()
    try:
        fm = yaml.safe_load(fm_raw)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"SKILL.md frontmatter YAML parse error: {exc}")

    if not isinstance(fm, dict):
        raise HTTPException(status_code=400, detail="SKILL.md frontmatter must be a YAML mapping")

    errors: list[str] = []
    if not isinstance(fm.get("name", ""), str) or not fm.get("name", "").strip():
        errors.append("SKILL.md frontmatter: 'name' is required")
    if not isinstance(fm.get("description", ""), str) or not fm.get("description", "").strip():
        errors.append("SKILL.md frontmatter: 'description' is required")
    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    return fm


# ---------------------------------------------------------------------------
# Storage path resolution
# ---------------------------------------------------------------------------


def _skill_storage_path(scope: str, name: str, version: str, *, tenant_id: int | None, user_id: int) -> Path:
    """Return the absolute host-side directory for this skill version."""
    home = deerflow_home()
    v_tag = f"v{version}"
    if scope == "private":
        if tenant_id is None:
            raise HTTPException(status_code=400, detail="private skills require an active tenant")
        return home / "tenants" / str(tenant_id) / "users" / str(user_id) / "skills" / name / v_tag
    if scope == "org":
        if tenant_id is None:
            raise HTTPException(status_code=400, detail="org skills require an active tenant")
        return home / "tenants" / str(tenant_id) / "org-skills" / name / v_tag
    # public
    return home / "skills" / "public" / name / v_tag


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class PublishSkillRequest(BaseModel):
    manifest: str
    skill_md: str


class PublishSkillResponse(BaseModel):
    skill_id: int
    status: str


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/publish",
    response_model=PublishSkillResponse,
    summary="Publish Skill",
    description=textwrap.dedent("""\
        Publish a skill to the registry.

        Requires an API token with the ``skill:publish`` scope.
        The caller must supply both the manifest YAML and the SKILL.md content.
        Files are written to the appropriate path under ``$DEER_FLOW_HOME``.
        A row is inserted in ``identity.skill_registry``.
        An audit event ``skill.published`` is emitted.
    """),
)
async def publish_skill(
    body: PublishSkillRequest,
    request: Request,
    identity: Identity = Depends(requires("skill:publish", "platform")),
) -> PublishSkillResponse:
    # --- 1. Validate manifest & SKILL.md ---
    manifest = _validate_manifest(body.manifest)
    _validate_skill_md(body.skill_md)

    name: str = manifest["name"]
    version: str = str(manifest["version"])
    scope: str = manifest["scope"]
    description: str = manifest["description"]

    tenant_id = identity.tenant_id
    user_id = identity.user_id

    # --- 2. Resolve storage path ---
    skill_dir = _skill_storage_path(scope, name, version, tenant_id=tenant_id, user_id=user_id)

    # --- 2.5. Path traversal guard ---
    if tenant_id is not None:
        assert_within_tenant_root(skill_dir, tenant_id)

    # --- 3. DB: check for duplicate (name, version) ---
    rt = get_runtime()
    async with rt.session_maker() as db:
        # Duplicate check: for private, per (name, version, owner_id);
        # for org/public, per (name, version, tenant_id).
        if scope == "private":
            dup_q = text(
                "SELECT id FROM identity.skill_registry "
                "WHERE name = :name AND version = :version AND owner_id = :owner_id "
                "LIMIT 1"
            )
            dup_row = (await db.execute(dup_q, {"name": name, "version": version, "owner_id": user_id})).fetchone()
        else:
            dup_q = text(
                "SELECT id FROM identity.skill_registry "
                "WHERE name = :name AND version = :version AND tenant_id = :tid "
                "LIMIT 1"
            )
            dup_row = (await db.execute(dup_q, {"name": name, "version": version, "tid": tenant_id})).fetchone()

        if dup_row is not None:
            raise HTTPException(status_code=409, detail=f"skill {name!r} version {version!r} already exists")

        # --- 4. Write files to disk ---
        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "manifest.yaml").write_text(body.manifest, encoding="utf-8")
            (skill_dir / "SKILL.md").write_text(body.skill_md, encoding="utf-8")
        except OSError as exc:
            logger.error("failed to write skill files to %s: %s", skill_dir, exc)
            raise HTTPException(status_code=500, detail=f"failed to write skill files: {exc}")

        # --- 5. Insert skill_registry row ---
        reg_status = "active" if scope == "private" else "pending_review"
        insert_q = text(
            """
            INSERT INTO identity.skill_registry
                (name, version, scope, tenant_id, owner_id, status, storage_path, created_by)
            VALUES
                (:name, :version, :scope, :tenant_id, :owner_id, :status, :storage_path, :created_by)
            RETURNING id
            """
        )
        result = await db.execute(
            insert_q,
            {
                "name": name,
                "version": version,
                "scope": scope,
                "tenant_id": tenant_id,
                "owner_id": user_id if scope == "private" else None,
                "status": reg_status,
                "storage_path": str(skill_dir),
                "created_by": user_id,
            },
        )
        skill_id = result.fetchone()[0]
        await db.commit()

    # --- 6. Emit audit event ---
    writer = getattr(getattr(request.app, "state", None), "audit_writer", None)
    if writer is not None:
        try:
            ev = AuditEvent(
                action="skill.published",
                result="success",
                tenant_id=tenant_id,
                user_id=user_id,
                resource_type="skill",
                resource_id=str(skill_id),
                ip=identity.ip,
                metadata={
                    "name": name,
                    "version": version,
                    "scope": scope,
                    "description": description,
                    "storage_path": str(skill_dir),
                },
            )
            asyncio.create_task(writer.enqueue(ev, critical=False))
        except Exception:
            logger.debug("audit enqueue from skill.published failed", exc_info=True)

    logger.info("skill published: name=%s version=%s scope=%s skill_id=%d user_id=%d", name, version, scope, skill_id, user_id)
    return PublishSkillResponse(skill_id=skill_id, status=reg_status)
