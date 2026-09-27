from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from service.api.dependencies import (
    ProjectMemberCtx,
    get_search_service,
    require_ready,
)
from service.core.search import SearchService
from service.storage.store import SearchMode

router = APIRouter(prefix="/projects/{project_id}/search", tags=["search"])

ServiceDep = Annotated[SearchService, Depends(get_search_service)]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=50)
    # Both default to the instance configuration. Overriding is what makes the
    # difference between the legs visible: the same query in "vector" and "fts"
    # shows what each contributes to the fused result.
    mode: SearchMode | None = None
    rerank: bool | None = None


class SearchHitResponse(BaseModel):
    document_id: str | None
    chunk_index: int | None
    text: str
    score: float


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHitResponse]


@router.post("", dependencies=[Depends(require_ready)])
async def search(
    ctx: ProjectMemberCtx, service: ServiceDep, r: SearchRequest
) -> SearchResponse:
    """Return the chunks most similar to ``query`` within this project.

    Gated on readiness: while a reindex is in progress the index is being
    rebuilt, so queries would see partial results -- returns 503 instead.
    """
    hits = await service.search(
        query=r.query,
        k=r.k,
        project_id=ctx.project.id,
        mode=r.mode,
        rerank=r.rerank,
    )
    return SearchResponse(
        query=r.query,
        hits=[
            SearchHitResponse(
                document_id=hit.document_id,
                chunk_index=hit.chunk_index,
                text=hit.text,
                score=hit.score,
            )
            for hit in hits
        ],
    )
