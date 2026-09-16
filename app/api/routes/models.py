"""OpenAI-style model listing theo allowlist project."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import require_runtime_policy
from app.domain.auth import ProjectPolicy

router = APIRouter(tags=["Models"])


@router.get("/models")
async def list_allowed_models(
    policy: ProjectPolicy = Depends(require_runtime_policy),
) -> dict[str, object]:
    return {
        "object": "list",
        "data": [
            {"id": model, "object": "model", "owned_by": policy.project_name}
            for model in policy.allowed_models
        ],
    }
