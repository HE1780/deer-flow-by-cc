import logging
import mimetypes
import re
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.gateway.identity.request_scope import extract_scope
from app.gateway.identity.storage.path_guard import PathEscapeError, assert_within_tenant_root
from app.gateway.path_utils import resolve_thread_virtual_path
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["artifacts"])


def _extract_scope(request: Request | None) -> tuple[int | None, int | None]:
    """Backward-compat alias retained for in-file callers; delegates to the
    shared :func:`app.gateway.identity.request_scope.extract_scope`."""
    return extract_scope(request)


ACTIVE_CONTENT_MIME_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
}


def _build_content_disposition(disposition_type: str, filename: str) -> str:
    """Build an RFC 5987 encoded Content-Disposition header value."""
    return f"{disposition_type}; filename*=UTF-8''{quote(filename)}"


def _build_attachment_headers(filename: str, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Content-Disposition": _build_content_disposition("attachment", filename)}
    if extra_headers:
        headers.update(extra_headers)
    return headers


_TENANT_DIR_RE = re.compile(r"^\d+$")


def _legacy_tenant_fallback(thread_id: str, virtual_path: str) -> Path | None:
    """Locate ``thread_id`` under the tenant-stratified tree when the legacy
    flat path doesn't exist.

    Anonymous callers (no identity in ``request.state``) hit the legacy resolver
    which looks under ``$DEER_FLOW_HOME/threads/{thread_id}``. After M4 most new
    threads only live under ``tenants/{tid}/workspaces/{wid}/threads/{thread_id}``
    with no legacy symlink, so the legacy lookup 404s.

    This walker scans ``tenants/*/workspaces/*/threads/{thread_id}`` once and
    re-resolves through the tenant-aware path helper if exactly one candidate
    is found. Multiple matches (collision across tenants) are rejected — the
    caller has no way to disambiguate without a verified identity.

    Returns ``None`` when no candidate exists or the candidate is ambiguous;
    the caller should treat that as a 404. ``ValueError`` from the resolver
    (invalid virtual path) is re-raised so the 400/403 surfaces unchanged.
    """
    base_dir = get_paths().base_dir
    tenants_root = base_dir / "tenants"
    if not tenants_root.is_dir():
        return None

    candidates: list[tuple[int, int]] = []
    for tenant_dir in tenants_root.iterdir():
        if not tenant_dir.is_dir() or not _TENANT_DIR_RE.match(tenant_dir.name):
            continue
        workspaces_root = tenant_dir / "workspaces"
        if not workspaces_root.is_dir():
            continue
        for workspace_dir in workspaces_root.iterdir():
            if not workspace_dir.is_dir() or not _TENANT_DIR_RE.match(workspace_dir.name):
                continue
            if (workspace_dir / "threads" / thread_id).is_dir():
                candidates.append((int(tenant_dir.name), int(workspace_dir.name)))

    if len(candidates) != 1:
        if len(candidates) > 1:
            logger.warning(
                "artifact.fallback.ambiguous thread=%s candidates=%s",
                thread_id,
                candidates,
            )
        return None

    tid, wid = candidates[0]
    return resolve_thread_virtual_path(thread_id, virtual_path, tenant_id=tid, workspace_id=wid)


def is_text_file_by_content(path: Path, sample_size: int = 8192) -> bool:
    """Check if file is text by examining content for null bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
            # Text files shouldn't contain null bytes
            return b"\x00" not in chunk
    except Exception:
        return False


def _extract_file_from_skill_archive(zip_path: Path, internal_path: str) -> bytes | None:
    """Extract a file from a .skill ZIP archive.

    Args:
        zip_path: Path to the .skill file (ZIP archive).
        internal_path: Path to the file inside the archive (e.g., "SKILL.md").

    Returns:
        The file content as bytes, or None if not found.
    """
    if not zipfile.is_zipfile(zip_path):
        return None

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            # List all files in the archive
            namelist = zip_ref.namelist()

            # Try direct path first
            if internal_path in namelist:
                return zip_ref.read(internal_path)

            # Try with any top-level directory prefix (e.g., "skill-name/SKILL.md")
            for name in namelist:
                if name.endswith("/" + internal_path) or name == internal_path:
                    return zip_ref.read(name)

            # Not found
            return None
    except (zipfile.BadZipFile, KeyError):
        return None


@router.get(
    "/threads/{thread_id}/artifacts/{path:path}",
    summary="Get Artifact File",
    description="Retrieve an artifact file generated by the AI agent. Text and binary files can be viewed inline, while active web content is always downloaded.",
)
async def get_artifact(thread_id: str, path: str, request: Request, download: bool = False) -> Response:
    """Get an artifact file by its path.

    The endpoint automatically detects file types and returns appropriate content types.
    Use the `download` query parameter to force file download for non-active content.

    Args:
        thread_id: The thread ID.
        path: The artifact path with virtual prefix (e.g., mnt/user-data/outputs/file.txt).
        request: FastAPI request object (automatically injected).

    Returns:
        The file content as a FileResponse with appropriate content type:
        - Active content (HTML/XHTML/SVG): Served as download attachment
        - Text files: Plain text with proper MIME type
        - Binary files: Inline display with download option

    Raises:
        HTTPException:
            - 400 if path is invalid or not a file
            - 403 if access denied (path traversal detected)
            - 404 if file not found

    Query Parameters:
        download (bool): If true, forces attachment download for file types that are
            otherwise returned inline or as plain text. Active HTML/XHTML/SVG content
            is always downloaded regardless of this flag.

    Example:
        - Get text file inline: `/api/threads/abc123/artifacts/mnt/user-data/outputs/notes.txt`
        - Download file: `/api/threads/abc123/artifacts/mnt/user-data/outputs/data.csv?download=true`
        - Active web content such as `.html`, `.xhtml`, and `.svg` artifacts is always downloaded
    """
    tid, wid = _extract_scope(request)

    def _resolve(virtual_path: str) -> Path:
        if tid is not None and wid is not None:
            # Intercept the resolver's 403 (``"Access denied: path traversal
            # detected"``) and rewrite the body to a generic ``"Access denied"``
            # so the client can't probe for path-shape hints. 400s pass through
            # unchanged — they describe bad input, not policy decisions.
            try:
                actual = resolve_thread_virtual_path(thread_id, virtual_path, tenant_id=tid, workspace_id=wid)
            except HTTPException as exc:
                if exc.status_code == 403:
                    logger.warning(
                        "authz.path.denied thread=%s tenant=%s reason=%s",
                        thread_id,
                        tid,
                        exc.detail,
                    )
                    raise HTTPException(status_code=403, detail="Access denied") from None
                raise
            try:
                assert_within_tenant_root(actual, tid)
            except PathEscapeError as exc:
                logger.warning(
                    "authz.path.denied thread=%s tenant=%s reason=%s",
                    thread_id,
                    tid,
                    exc,
                )
                raise HTTPException(status_code=403, detail="Access denied") from None
            return actual
        # Legacy / anonymous branch: try the flat path first, then fall back
        # to a tenant-tree scan so artifacts created post-M4 (which no longer
        # leave a legacy symlink) remain reachable when the request can't be
        # authenticated. Tenant-scoped callers bypass this entirely above.
        legacy = resolve_thread_virtual_path(thread_id, virtual_path)
        if legacy.exists():
            return legacy
        fallback = _legacy_tenant_fallback(thread_id, virtual_path)
        if fallback is not None:
            return fallback
        return legacy

    # Check if this is a request for a file inside a .skill archive (e.g., xxx.skill/SKILL.md)
    if ".skill/" in path:
        # Split the path at ".skill/" to get the ZIP file path and internal path
        skill_marker = ".skill/"
        marker_pos = path.find(skill_marker)
        skill_file_path = path[: marker_pos + len(".skill")]  # e.g., "mnt/user-data/outputs/my-skill.skill"
        internal_path = path[marker_pos + len(skill_marker) :]  # e.g., "SKILL.md"

        actual_skill_path = _resolve(skill_file_path)

        if not actual_skill_path.exists():
            raise HTTPException(status_code=404, detail=f"Skill file not found: {skill_file_path}")

        if not actual_skill_path.is_file():
            raise HTTPException(status_code=400, detail=f"Path is not a file: {skill_file_path}")

        # Extract the file from the .skill archive
        content = _extract_file_from_skill_archive(actual_skill_path, internal_path)
        if content is None:
            raise HTTPException(status_code=404, detail=f"File '{internal_path}' not found in skill archive")

        # Determine MIME type based on the internal file
        mime_type, _ = mimetypes.guess_type(internal_path)
        # Add cache headers to avoid repeated ZIP extraction (cache for 5 minutes)
        cache_headers = {"Cache-Control": "private, max-age=300"}
        download_name = Path(internal_path).name or actual_skill_path.stem
        if download or mime_type in ACTIVE_CONTENT_MIME_TYPES:
            return Response(content=content, media_type=mime_type or "application/octet-stream", headers=_build_attachment_headers(download_name, cache_headers))

        if mime_type and mime_type.startswith("text/"):
            return PlainTextResponse(content=content.decode("utf-8"), media_type=mime_type, headers=cache_headers)

        # Default to plain text for unknown types that look like text
        try:
            return PlainTextResponse(content=content.decode("utf-8"), media_type="text/plain", headers=cache_headers)
        except UnicodeDecodeError:
            return Response(content=content, media_type=mime_type or "application/octet-stream", headers=cache_headers)

    actual_path = _resolve(path)

    logger.info(f"Resolving artifact path: thread_id={thread_id}, requested_path={path}, actual_path={actual_path}")

    if not actual_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {path}")

    if not actual_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {path}")

    mime_type, _ = mimetypes.guess_type(actual_path)

    if download:
        return FileResponse(path=actual_path, filename=actual_path.name, media_type=mime_type, headers=_build_attachment_headers(actual_path.name))

    # Always force download for active content types to prevent script execution
    # in the application origin when users open generated artifacts.
    if mime_type in ACTIVE_CONTENT_MIME_TYPES:
        return FileResponse(path=actual_path, filename=actual_path.name, media_type=mime_type, headers=_build_attachment_headers(actual_path.name))

    if mime_type and mime_type.startswith("text/"):
        return PlainTextResponse(content=actual_path.read_text(encoding="utf-8"), media_type=mime_type)

    if is_text_file_by_content(actual_path):
        return PlainTextResponse(content=actual_path.read_text(encoding="utf-8"), media_type=mime_type)

    return Response(content=actual_path.read_bytes(), media_type=mime_type, headers={"Content-Disposition": _build_content_disposition("inline", actual_path.name)})
