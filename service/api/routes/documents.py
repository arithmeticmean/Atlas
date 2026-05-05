from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict

from api.dependencies import (
    ProjectMemberCtx,
    get_document_service,
    require_ready,
)
from service import DocumentService

# Documents live under a project; every route requires membership (the
# ProjectMemberCtx dependency 404s an unknown project and 403s a non-member).
router = APIRouter(
    prefix="/projects/{project_id}/documents", tags=["documents"]
)

ServiceDep = Annotated[DocumentService, Depends(get_document_service)]


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    source_path: str
    mime_type: str | None
    file_size_bytes: int | None
    content_hash: str | None
    status: str
    indexed_at: datetime | None


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentResponse,
    dependencies=[Depends(require_ready)],
)
async def upload_document(
    ctx: ProjectMemberCtx,
    service: ServiceDep,
    file: Annotated[UploadFile, File(...)],
) -> DocumentResponse:
    """Store an uploaded file and queue it for background ingestion.

    Returns ``202`` immediately with ``status="queued"``; poll
    ``GET .../documents/{id}`` to watch it become ``indexed``.
    """
    meta = await service.store(
        project_id=ctx.project.id,
        filename=file.filename or "untitled",
        mime_type=file.content_type,
        source=file.file,
    )
    return DocumentResponse.model_validate(meta)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    ctx: ProjectMemberCtx, service: ServiceDep
) -> list[DocumentResponse]:
    metas = await service.list(project_id=ctx.project.id)
    return [DocumentResponse.model_validate(m) for m in metas]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    ctx: ProjectMemberCtx,
    service: ServiceDep,
    document_id: str,
) -> DocumentResponse:
    meta = await service.get(document_id, project_id=ctx.project.id)
    if meta is None:
        raise HTTPException(status_code=404, detail="document not found")
    return DocumentResponse.model_validate(meta)


@router.post(
    "/{document_id}/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentResponse,
    dependencies=[Depends(require_ready)],
)
async def reingest_document(
    ctx: ProjectMemberCtx,
    service: ServiceDep,
    document_id: str,
) -> DocumentResponse:
    """Re-queue an existing document for ingestion (e.g. retry a failure)."""
    try:
        meta = await service.reingest(document_id, project_id=ctx.project.id)
    except LookupError:
        raise HTTPException(
            status_code=404, detail="document not found"
        ) from None
    return DocumentResponse.model_validate(meta)
