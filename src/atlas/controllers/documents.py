"""A project's documents.

Uploads take one file per request: the client sends several in parallel and
gets progress for each. Downloads are always attachments, so an uploaded HTML
file can never run as a page on Atlas's own origin.
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from atlas.controllers._common import (
    CurrentCaller,
    Page,
    PageQuery,
    ResponseModel,
    Services,
    page_request,
    problems,
    require_ready,
    to_page,
)
from atlas.models.document import DocumentStatus
from atlas.repository.base import Paged

router = APIRouter(prefix="/projects/{project_id}", tags=["documents"])

_DOWNLOAD_BLOCK = 64 * 1024


class DocumentResponse(ResponseModel):
    # No storage key: where a file sits never leaves the server.
    id: str
    project_id: str
    title: str
    mime_type: str | None
    size_bytes: int | None = Field(validation_alias="file_size_bytes")
    content_hash: str | None
    status: DocumentStatus
    tags: list[str]
    created_at: datetime | None
    updated_at: datetime | None
    indexed_at: datetime | None


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    tags: list[str] | None = Field(
        default=None, description="replaces the document's tags"
    )


class DocumentListQuery(PageQuery):
    q: str | None = Field(default=None, description="matches the title")
    status: DocumentStatus | None = None
    tag: str | None = None


class ChunkResponse(BaseModel):
    index: int
    text: str
    page: int


class TagCount(BaseModel):
    name: str
    count: int


@router.post(
    "/documents",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_ready)],
    responses={
        200: {
            "model": DocumentResponse,
            "description": "identical bytes already in this project",
        },
        **problems(401, 404, 413, 415, 503),
    },
)
async def upload_document(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    response: Response,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=500)] = None,
    tags: Annotated[list[str] | None, Form()] = None,
) -> DocumentResponse:
    """``202`` and ``status="queued"`` for a new document; ``200`` with the
    existing one when the same bytes were uploaded before."""
    document, created = await services.documents.upload(
        caller,
        project_id,
        filename=file.filename or "untitled",
        mime_type=file.content_type,
        content=file.file,
        title=title,
        tags=tags or (),
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return DocumentResponse.model_validate(document)


@router.get("/documents", responses=problems(401, 404))
async def list_documents(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    query: Annotated[DocumentListQuery, Query()],
) -> Page[DocumentResponse]:
    documents = await services.documents.list_documents(
        caller,
        project_id,
        page_request(query),
        q=query.q,
        status=query.status,
        tag=query.tag,
    )
    return to_page(DocumentResponse, documents)


@router.get("/documents/{document_id}", responses=problems(401, 404))
async def get_document(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    document_id: str,
) -> DocumentResponse:
    document = await services.documents.get(caller, project_id, document_id)
    return DocumentResponse.model_validate(document)


@router.patch("/documents/{document_id}", responses=problems(401, 404, 422))
async def update_document(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    document_id: str,
    body: DocumentUpdate,
) -> DocumentResponse:
    document = await services.documents.update(
        caller, project_id, document_id, title=body.title, tags=body.tags
    )
    return DocumentResponse.model_validate(document)


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problems(401, 404),
)
async def delete_document(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    document_id: str,
) -> None:
    await services.documents.delete(caller, project_id, document_id)


@router.get(
    "/documents/{document_id}/content",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"application/octet-stream": {}},
            "description": "the original file, as an attachment",
        },
        **problems(401, 404),
    },
)
async def download_document(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    document_id: str,
) -> StreamingResponse:
    document, reader = await services.documents.open_content(
        caller, project_id, document_id
    )

    async def body() -> AsyncGenerator[bytes, None]:
        async with reader as content:
            while block := await asyncio.to_thread(
                content.read, _DOWNLOAD_BLOCK
            ):
                yield block

    return StreamingResponse(
        body(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(document.title)}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/documents/{document_id}/chunks", responses=problems(401, 404))
async def list_chunks(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    document_id: str,
    query: Annotated[PageQuery, Query()],
) -> Page[ChunkResponse]:
    chunks = await services.documents.list_chunks(
        caller, project_id, document_id
    )
    responses = [
        ChunkResponse(
            index=chunk.metadata["chunk_index"],
            text=chunk.page_content,
            page=chunk.metadata["page"],
        )
        for chunk in chunks
    ]
    return to_page(ChunkResponse, Paged.slice(responses, page_request(query)))


@router.post(
    "/documents/{document_id}/reindex",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_ready)],
    responses=problems(401, 404, 503),
)
async def reindex_document(
    services: Services,
    caller: CurrentCaller,
    project_id: str,
    document_id: str,
) -> DocumentResponse:
    document = await services.documents.reindex(
        caller, project_id, document_id
    )
    return DocumentResponse.model_validate(document)


@router.get("/tags", responses=problems(401, 404))
async def list_tags(
    services: Services, caller: CurrentCaller, project_id: str
) -> list[TagCount]:
    tags = await services.documents.list_tags(caller, project_id)
    return [TagCount(name=name, count=count) for name, count in tags]
