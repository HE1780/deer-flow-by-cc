from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML

from app.gateway.config_writer import edit_config
from app.gateway.identity.auth.dependencies import get_current_identity
from app.gateway.identity.settings import get_identity_settings
from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig

_yaml_ro = YAML(typ="safe")


def _read_raw_models() -> list[dict[str, Any]]:
    """Return the raw `models:` list straight from disk (no env interpolation).

    Used by the admin detail endpoint so the editor can round-trip `$VAR`
    placeholders without ever resolving them to real secrets.
    """
    path = AppConfig.resolve_config_path()
    with path.open("r", encoding="utf-8") as f:
        data = _yaml_ro.load(f) or {}
    raw = data.get("models") or []
    return [dict(m) for m in raw if isinstance(m, dict)]

router = APIRouter(prefix="/api", tags=["models"])


def _require_admin(request: Request) -> None:
    """Require platform_admin when identity is on; allow all when off."""
    if not get_identity_settings().enabled:
        return
    ident = get_current_identity(request)
    if not ident.is_authenticated:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    if not ident.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "platform_admin required")


class ModelResponse(BaseModel):
    """Response model for model information."""

    name: str = Field(..., description="Unique identifier for the model")
    model: str = Field(..., description="Actual provider model identifier")
    display_name: str | None = Field(None, description="Human-readable name")
    description: str | None = Field(None, description="Model description")
    supports_thinking: bool = Field(default=False, description="Whether model supports thinking mode")
    supports_reasoning_effort: bool = Field(default=False, description="Whether model supports reasoning effort")


class TokenUsageResponse(BaseModel):
    """Token usage display configuration."""

    enabled: bool = Field(default=False, description="Whether token usage display is enabled")


class ModelsListResponse(BaseModel):
    """Response model for listing all models."""

    models: list[ModelResponse]
    token_usage: TokenUsageResponse


class ModelMutationPayload(BaseModel):
    """Payload accepted by POST and PUT.

    Mirrors the writable subset of `ModelConfig`. Unknown extra fields are
    preserved verbatim and written into the YAML model entry.
    """

    name: str = Field(..., min_length=1, description="Unique model identifier")
    model: str = Field(..., min_length=1, description="Provider's model id (e.g. gpt-4o)")
    use: str = Field(..., min_length=1, description="Class path (e.g. langchain_openai:ChatOpenAI)")
    display_name: str | None = None
    description: str | None = None
    base_url: str | None = None
    api_base: str | None = None
    api_key: str | None = Field(default=None, description="API key or $ENV_VAR placeholder")
    supports_thinking: bool = False
    supports_vision: bool = False
    supports_reasoning_effort: bool = False
    use_responses_api: bool | None = None
    output_version: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    request_timeout: float | None = None
    timeout: float | None = None
    max_retries: int | None = None

    model_config = ConfigDict(extra="allow")


def _payload_to_yaml_dict(payload: ModelMutationPayload) -> dict[str, Any]:
    """Drop None values so they don't pollute the YAML with empty keys."""
    raw = payload.model_dump(exclude_none=True)
    return raw


@router.get(
    "/models",
    response_model=ModelsListResponse,
    summary="List All Models",
)
async def list_models() -> ModelsListResponse:
    """List all configured models (sensitive fields stripped)."""
    config = get_app_config()
    models = [
        ModelResponse(
            name=m.name,
            model=m.model,
            display_name=m.display_name,
            description=m.description,
            supports_thinking=m.supports_thinking,
            supports_reasoning_effort=m.supports_reasoning_effort,
        )
        for m in config.models
    ]
    return ModelsListResponse(
        models=models,
        token_usage=TokenUsageResponse(enabled=config.token_usage.enabled),
    )


@router.get(
    "/models/{model_name}",
    response_model=ModelResponse,
    summary="Get Model Details",
)
async def get_model(model_name: str) -> ModelResponse:
    config = get_app_config()
    m = config.get_model_config(model_name)
    if m is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")
    return ModelResponse(
        name=m.name,
        model=m.model,
        display_name=m.display_name,
        description=m.description,
        supports_thinking=m.supports_thinking,
        supports_reasoning_effort=m.supports_reasoning_effort,
    )


@router.get(
    "/admin/models/{model_name}/raw",
    summary="Get Raw Model Config (admin)",
    description="Return the raw YAML entry for a model — including unresolved $ENV placeholders. Admin only.",
)
async def get_model_raw(model_name: str, _: None = Depends(_require_admin)) -> dict[str, Any]:
    raw = _read_raw_models()
    entry = next((m for m in raw if m.get("name") == model_name), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")
    return entry


@router.post(
    "/models",
    response_model=ModelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Model",
)
async def create_model(payload: ModelMutationPayload, _: None = Depends(_require_admin)) -> ModelResponse:
    new_entry = _payload_to_yaml_dict(payload)

    def mutate(data: dict[str, Any]) -> None:
        models = data.get("models")
        if models is None:
            data["models"] = []
            models = data["models"]
        for m in models:
            if isinstance(m, dict) and m.get("name") == payload.name:
                raise HTTPException(status.HTTP_409_CONFLICT, f"Model '{payload.name}' already exists")
        models.append(new_entry)

    await edit_config(mutate)
    return ModelResponse(
        name=payload.name,
        model=payload.model,
        display_name=payload.display_name,
        description=payload.description,
        supports_thinking=payload.supports_thinking,
        supports_reasoning_effort=payload.supports_reasoning_effort,
    )


@router.put(
    "/models/{model_name}",
    response_model=ModelResponse,
    summary="Update Model",
)
async def update_model(
    model_name: str,
    payload: ModelMutationPayload,
    _: None = Depends(_require_admin),
) -> ModelResponse:
    if payload.name != model_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "payload.name must match path parameter")

    new_entry = _payload_to_yaml_dict(payload)

    # Nested keys the form does not edit; preserve them on the existing entry
    # if the YAML had them set.
    PRESERVE_KEYS = frozenset({
        "when_thinking_enabled",
        "when_thinking_disabled",
        "thinking",
        "extra_body",
    })

    def mutate(data: dict[str, Any]) -> None:
        models = data.get("models") or []
        idx = next((i for i, m in enumerate(models) if isinstance(m, dict) and m.get("name") == model_name), None)
        if idx is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Model '{model_name}' not found")
        existing = models[idx]
        preserved = {k: existing[k] for k in existing.keys() if k in PRESERVE_KEYS}
        existing.clear()
        for key, value in new_entry.items():
            existing[key] = value
        for key, value in preserved.items():
            if key not in existing:
                existing[key] = value

    await edit_config(mutate)
    return ModelResponse(
        name=payload.name,
        model=payload.model,
        display_name=payload.display_name,
        description=payload.description,
        supports_thinking=payload.supports_thinking,
        supports_reasoning_effort=payload.supports_reasoning_effort,
    )


@router.delete(
    "/models/{model_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Model",
)
async def delete_model(model_name: str, _: None = Depends(_require_admin)) -> None:
    def mutate(data: dict[str, Any]) -> None:
        models = data.get("models") or []
        idx = next((i for i, m in enumerate(models) if isinstance(m, dict) and m.get("name") == model_name), None)
        if idx is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Model '{model_name}' not found")
        del models[idx]

    await edit_config(mutate)
