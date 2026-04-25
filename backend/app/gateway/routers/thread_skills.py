"""POST/DELETE/GET /api/threads/{tid}/skills — bind/unbind skills to a thread."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.gateway.deps import get_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/threads", tags=["thread-skills"])

THREADS_NS: tuple[str, ...] = ("threads",)


class BindSkillRequest(BaseModel):
    skill_name: str
    version: str = "latest"


async def _get_bound_skills(store, thread_id: str) -> list[dict]:
    if store is None:
        return []
    item = await store.aget(THREADS_NS, thread_id)
    if item is None:
        return []
    return item.value.get("values", {}).get("bound_skills", [])


async def _set_bound_skills(store, thread_id: str, skills: list[dict]) -> None:
    if store is None:
        raise HTTPException(status_code=503, detail="store not available")
    item = await store.aget(THREADS_NS, thread_id)
    if item is None:
        raise HTTPException(status_code=404, detail="thread not found")
    val = item.value.copy()
    val.setdefault("values", {})["bound_skills"] = skills
    await store.aput(THREADS_NS, thread_id, val)


@router.post("/{thread_id}/skills")
async def bind_skill(thread_id: str, body: BindSkillRequest, request: Request) -> dict:
    """Bind a skill to the thread. Idempotent — duplicate binds are ignored."""
    store = get_store(request)
    skills = await _get_bound_skills(store, thread_id)
    already = any(s["name"] == body.skill_name and s["version"] == body.version for s in skills)
    if not already:
        skills = [
            *skills,
            {
                "name": body.skill_name,
                "version": body.version,
                "bound_at": datetime.now(timezone.utc).isoformat(),
            },
        ]
        await _set_bound_skills(store, thread_id, skills)
    return {"bound_skills": skills}


@router.delete("/{thread_id}/skills/{skill_name}")
async def unbind_skill(thread_id: str, skill_name: str, request: Request) -> dict:
    """Unbind a skill from the thread."""
    store = get_store(request)
    skills = await _get_bound_skills(store, thread_id)
    updated = [s for s in skills if s["name"] != skill_name]
    if len(updated) != len(skills):
        await _set_bound_skills(store, thread_id, updated)
    return {"bound_skills": updated}


@router.get("/{thread_id}/skills")
async def list_bound_skills(thread_id: str, request: Request) -> dict:
    """Return the skills currently bound to this thread."""
    store = get_store(request)
    skills = await _get_bound_skills(store, thread_id)
    return {"bound_skills": skills}
