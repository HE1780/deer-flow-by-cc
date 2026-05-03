from typing import Annotated, Any, NotRequired, TypedDict

from langchain.agents import AgentState
from langchain_core.messages import AnyMessage


class SandboxState(TypedDict):
    sandbox_id: NotRequired[str | None]


class ThreadDataState(TypedDict):
    workspace_path: NotRequired[str | None]
    uploads_path: NotRequired[str | None]
    outputs_path: NotRequired[str | None]


class ViewedImageData(TypedDict):
    base64: str
    mime_type: str


def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """Reducer for artifacts list - merges and deduplicates artifacts."""
    if existing is None:
        return new or []
    if new is None:
        return existing
    # Use dict.fromkeys to deduplicate while preserving order
    return list(dict.fromkeys(existing + new))


def merge_viewed_images(existing: dict[str, ViewedImageData] | None, new: dict[str, ViewedImageData] | None) -> dict[str, ViewedImageData]:
    """Reducer for viewed_images dict - merges image dictionaries.

    Special case: If new is an empty dict {}, it clears the existing images.
    This allows middlewares to clear the viewed_images state after processing.
    """
    if existing is None:
        return new or {}
    if new is None:
        return existing
    # Special case: empty dict means clear all viewed images
    if len(new) == 0:
        return {}
    # Merge dictionaries, new values override existing ones for same keys
    return {**existing, **new}


def merge_archived_messages(
    existing: list[AnyMessage] | None,
    new: list[AnyMessage] | None,
) -> list[AnyMessage]:
    """Reducer for archived messages - appends while deduplicating by message id."""
    if existing is None:
        existing = []
    if not new:
        return existing

    merged = list(existing)
    seen_ids = {
        message.id
        for message in merged
        if getattr(message, "id", None) is not None
    }

    for message in new:
        message_id = getattr(message, "id", None)
        if message_id is not None and message_id in seen_ids:
            continue
        merged.append(message)
        if message_id is not None:
            seen_ids.add(message_id)
    return merged


class ThreadState(AgentState):
    sandbox: NotRequired[SandboxState | None]
    thread_data: NotRequired[ThreadDataState | None]
    title: NotRequired[str | None]
    artifacts: Annotated[list[str], merge_artifacts]
    archived_messages: Annotated[list[AnyMessage], merge_archived_messages]
    todos: NotRequired[list | None]
    uploaded_files: NotRequired[list[dict] | None]
    viewed_images: Annotated[dict[str, ViewedImageData], merge_viewed_images]  # image_path -> {base64, mime_type}
    # Identity carried from the Gateway via HMAC-signed headers (M5). Opaque
    # (``Any``) so the harness stays decoupled from the Gateway ``Identity``
    # dataclass; consumers use ``extract_tenant_ids`` + attribute lookups.
    identity: NotRequired[Any]
