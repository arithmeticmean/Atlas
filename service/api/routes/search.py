from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.dependencies import (
    ProjectMemberCtx,
    get_search_service,
    require_ready,
)
from service import SearchService

router = APIRouter(prefix="/projects/{project_id}/search", tags=["search"])

ServiceDep = Annotated[SearchService, Depends(get_search_service)]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=50)


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
        query=r.query, k=r.k, project_id=ctx.project.id
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
