"""M3 stub routes used by the horizontal-access matrix test.

These endpoints exist purely to prove that ``@requires(...)`` enforces
authorization correctly before M4/M7 lands the real handlers. Each
returns an empty JSON body with the expected status code.

**Do not use these routes in production callers** — the paths may move
to feature-owned routers in later milestones.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.gateway.identity.rbac.decorator import requires

router = APIRouter()


@router.get(
    "/api/tenants/{tid}/workspaces/{wid}/threads",
    dependencies=[Depends(requires("thread:read", "workspace"))],
)
async def list_threads_stub(tid: int, wid: int):
    return {"tid": tid, "wid": wid, "threads": []}


@router.post(
    "/api/tenants/{tid}/workspaces/{wid}/threads",
    status_code=201,
    dependencies=[Depends(requires("thread:write", "workspace"))],
)
async def create_thread_stub(tid: int, wid: int):
    return {"tid": tid, "wid": wid, "thread_id": 1}


@router.delete(
    "/api/tenants/{tid}/workspaces/{wid}/skills/{skid}",
    dependencies=[Depends(requires("skill:manage", "workspace"))],
)
async def delete_skill_stub(tid: int, wid: int, skid: int):
    return {"tid": tid, "wid": wid, "skid": skid, "deleted": True}


# NOTE: ``POST /api/tenants/{tid}/workspaces`` and ``POST /api/admin/tenants``
# stubs were removed when M7A A3 landed real handlers in ``admin_writes.py``.
# Routes are matched in registration order, so the stubs were shadowing the
# real handlers and silently making "create" calls a no-op.
