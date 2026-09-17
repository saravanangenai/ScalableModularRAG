from fastapi import APIRouter, Depends

from apps.api.config import Settings as ApiSettings
from apps.api.deps.rate_limit import enforce_rate_limit
from apps.api.deps.rbac import WorkspaceAccess, require_workspace_role
from apps.api.schemas.search import SearchRequest, SearchResponse, SearchResultOut
from packages.retrieval.search import search

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["search"])

_api_settings = ApiSettings()


@router.post("/search", response_model=SearchResponse)
async def search_workspace(
    body: SearchRequest,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> SearchResponse:
    """Dense+sparse+RRF+rerank hybrid search (specs/040-hybrid-retrieval-reranking, built on
    specs/030-workspace-rbac-filtering's route/auth), scoped to access.workspace_id —
    resolved and authorized by require_workspace_role, never taken from the request body.
    Rate-limited per caller (specs/070-api-hardening) since every call triggers a real paid
    OpenAI embedding call plus a Qdrant query."""
    enforce_rate_limit("search", access, _api_settings.rate_limit_search_per_minute)
    results = search(workspace_id=access.workspace_id, query=body.query, k=body.k)
    return SearchResponse(results=[SearchResultOut.model_validate(r) for r in results])
