"""Request-scoped wiring (the composition root for the web layer).

Builds a ``DocumentService`` backed by the SQL metadata store and the on-disk
blob store, inside a single session whose transaction commits when the request
finishes successfully (``get_session`` handles commit/rollback).
"""

from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
)
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.embeddings import Embeddings

from service.config import settings
from service.core.answer import AnswerService
from service.core.auth import (
    AuthService,
    InvalidToken,
    PermissionDenied,
    Principal,
    TokenCodec,
)
from service.core.connector_manager import ConnectorManager
from service.core.connectors import ConnectorService
from service.core.document import DocumentService
from service.core.embedding_index import EmbeddingIndex
from service.core.ingestion import IngestionService
from service.core.llm import build_chat_model
from service.core.projects import ProjectService, UnknownProject
from service.core.search import SearchService
from service.core.worker import IngestionWorker, OnProgress
from service.ingest import IngestionPipeline, build_embeddings
from service.models import Project
from service.storage.blob.disk import DiskDocumentStore
from service.storage.lance import LanceChunkIndex
from service.storage.sql import get_session
from service.storage.sql.connector import SqlConnectorStore
from service.storage.sql.document_meta import SqlDocumentMetaStore
from service.storage.sql.jobs import SqlJobQueue
from service.storage.sql.project import SqlProjectStore
from service.storage.sql.user import SqlUserStore
from service.storage.store import (
    ConnectorStore,
    DocumentMetaStore,
    JobQueue,
    ProjectStore,
    UserStore,
)


# The signing key and TTLs are process-wide, so build the codec once and share
# it across requests; only the per-request DB session is rebuilt each time.
# Built on first use, not at import: the secret comes from the instance
# directory, which may not exist yet when this module is first imported (see
# cli.init).
@lru_cache
def _codec() -> TokenCodec:
    return TokenCodec(
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        access_ttl=timedelta(minutes=settings.access_token_ttl_minutes),
        refresh_ttl=timedelta(minutes=settings.refresh_token_ttl_minutes),
        invite_ttl=timedelta(minutes=settings.invite_token_ttl_minutes),
    )


# authN/authZ are stateless (token-only), so one shared, store-less service
# serves every request. The account flows get their own store-backed service
# per request (see get_auth_service).
@lru_cache
def _auth() -> AuthService:
    return AuthService(token_codec=_codec())

# auto_error=False so a missing/blank header yields None and we can raise our
# own 401 (with a WWW-Authenticate header) rather than FastAPI's default 403.
_bearer = HTTPBearer(auto_error=False)


async def get_auth_service() -> AsyncIterator[AuthService]:
    async with get_session() as session:
        yield AuthService(
            token_codec=_codec(),
            user_store=SqlUserStore(session),
        )


async def get_signup_services() -> (
    AsyncIterator[tuple[AuthService, ProjectService]]
):
    """Auth + project services on **one** session for the signup flow.

    Creating the account and (for a project invite) joining the project must
    share a single transaction: it makes onboarding atomic, and -- crucially on
    SQLite, which allows a single writer -- avoids the two-open-write-sessions
    deadlock that separate per-service sessions would cause in one request.
    """
    async with get_session() as session:
        yield (
            AuthService(
                token_codec=_codec(),
                user_store=SqlUserStore(session),
            ),
            ProjectService(store=SqlProjectStore(session)),
        )


def get_current_principal(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ],
) -> Principal:
    """Authenticate the request from its ``Authorization: Bearer`` token.

    Depend on this in any route that requires a logged-in caller. It never
    touches the database -- the access token is self-contained -- so it is
    cheap enough to attach broadly.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return _auth().authenticate(credentials.credentials)
    except InvalidToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_role(role: str) -> Callable[[Principal], Principal]:
    """Build a dependency that authorizes the caller against ``role``.

    Usage in a route::

        @router.get("/admin", dependencies=[Depends(require_role("admin"))])

    or, to also read the identity::

        principal: Annotated[Principal, Depends(require_role("admin"))]
    """

    def dependency(principal: CurrentPrincipal) -> Principal:
        try:
            _auth().authorize(principal, require_role=role)
        except PermissionDenied as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
            ) from exc
        return principal

    return dependency


async def get_document_service() -> AsyncIterator[DocumentService]:
    async with get_session() as session:
        yield DocumentService(
            meta_store=SqlDocumentMetaStore(session),
            document_store=DiskDocumentStore(settings.blob_path),
            jobs=SqlJobQueue(session),
        )


@asynccontextmanager
async def _meta_store_uow() -> AsyncGenerator[DocumentMetaStore]:
    """One committed unit of work over the metadata store."""
    async with get_session() as session:
        yield SqlDocumentMetaStore(session)


@asynccontextmanager
async def _job_queue_uow() -> AsyncGenerator[JobQueue]:
    """One committed unit of work over the job queue."""
    async with get_session() as session:
        yield SqlJobQueue(session)


@asynccontextmanager
async def _reindex_uow() -> (
    AsyncGenerator[tuple[DocumentMetaStore, JobQueue]]
):
    """Metadata store and job queue on one session, so re-enqueueing every
    document on reindex is a single atomic unit of work."""
    async with get_session() as session:
        yield SqlDocumentMetaStore(session), SqlJobQueue(session)


async def _wipe_vector_table() -> None:
    """Drop the chunk index for a re-embed (the lock file beside it stays).

    Routed through the index rather than a separate lancedb connection: two
    clients mutating one dataset can leave its manifest referencing data files
    the drop deleted, after which every write fails with a missing-file error.
    """
    await get_chunk_index().drop()


def build_embedding_index() -> EmbeddingIndex:
    """Construct the embedding-index lifecycle manager (used in lifespan)."""
    return EmbeddingIndex(
        vector_path=settings.vector_path,
        provider=settings.embedding_provider,
        model=settings.embedding_model,
        embeddings=build_embeddings(),
        reindex_uow=_reindex_uow,
        jobs_uow=_job_queue_uow,
        wipe_table=_wipe_vector_table,
    )


def build_ingestion_worker(
    on_progress: OnProgress | None = None,
) -> IngestionWorker:
    """Construct the background worker (started in the app lifespan)."""
    return IngestionWorker(
        jobs=_job_queue_uow,
        ingestion=get_ingestion_service(),
        poll_interval=settings.ingest_poll_interval_seconds,
        max_attempts=settings.ingest_max_attempts,
        on_progress=on_progress,
    )


def require_ready(request: Request) -> None:
    """Gate write/search routes until the instance is ready (not reindexing).

    Returns 503 while the embedding index is initializing or reindexing.
    """
    index: EmbeddingIndex | None = getattr(
        request.app.state, "embedding_index", None
    )
    if index is None or not index.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="instance not ready (embedding index initializing)",
        )


@lru_cache
def get_chunk_index() -> LanceChunkIndex:
    """The process-wide chunk index.

    Cached deliberately: the adapter holds the LanceDB connection and table
    handle and serialises writes behind a lock, so one per request would both
    reconnect constantly and reopen the create-vs-add race the lock exists to
    close.
    """
    return LanceChunkIndex(
        uri=settings.vector_path,
        table_name=settings.vector_table,
    )


@lru_cache
def get_embeddings() -> Embeddings:
    """One embedding client per process; provider clients are reusable."""
    return build_embeddings()


def get_ingestion_service() -> IngestionService:
    return IngestionService(
        meta_store=_meta_store_uow,
        pipeline=IngestionPipeline(
            index=get_chunk_index(),
            embeddings=get_embeddings(),
        ),
    )


def get_search_service() -> SearchService:
    """Retrieval for ``GET/POST /search``: fast by default.

    Reranking is off unless the instance opts in, because a raw lookup should
    not cost a model call.
    """
    return SearchService(
        index=get_chunk_index(),
        embeddings=get_embeddings(),
        chat_model=build_chat_model() if settings.rerank_search else None,
        mode=settings.search_mode,
        rerank=settings.rerank_search,
        rerank_candidates=settings.rerank_candidates,
    )


def get_answer_service() -> AnswerService:
    """Retrieval + generation, reranked by default.

    The request already pays for a model call, and the order of the passages
    decides what the answer gets built from.
    """
    chat_model = build_chat_model()
    return AnswerService(
        search=SearchService(
            index=get_chunk_index(),
            embeddings=get_embeddings(),
            chat_model=chat_model,
            mode=settings.search_mode,
            rerank=settings.rerank_answers,
            rerank_candidates=settings.rerank_candidates,
        ),
        chat_model=chat_model,
    )


@asynccontextmanager
async def _document_service_uow() -> AsyncGenerator[DocumentService]:
    """One committed unit of work over the full document intake (blob + meta
    + queue). Connectors store each fetched item in its own UoW."""
    async with get_session() as session:
        yield DocumentService(
            meta_store=SqlDocumentMetaStore(session),
            document_store=DiskDocumentStore(settings.blob_path),
            jobs=SqlJobQueue(session),
        )


def get_connector_service() -> ConnectorService:
    return ConnectorService(documents_uow=_document_service_uow)


async def get_project_service() -> AsyncIterator[ProjectService]:
    async with get_session() as session:
        yield ProjectService(store=SqlProjectStore(session))


@asynccontextmanager
async def _connector_store_uow() -> AsyncGenerator[ConnectorStore]:
    """One committed unit of work over the connector store."""
    async with get_session() as session:
        yield SqlConnectorStore(session)


def get_connector_manager() -> ConnectorManager:
    return ConnectorManager(
        store_uow=_connector_store_uow,
        importer=ConnectorService(documents_uow=_document_service_uow),
    )


async def get_directory_stores() -> (
    AsyncIterator[tuple[UserStore, ProjectStore]]
):
    """User and project stores on one session, for the user directory.

    The directory reads accounts and the memberships that decide who may see
    them; one session keeps that a single consistent read.
    """
    async with get_session() as session:
        yield SqlUserStore(session), SqlProjectStore(session)


async def get_user_store() -> AsyncIterator[UserStore]:
    async with get_session() as session:
        yield SqlUserStore(session)


async def get_membership_services() -> (
    AsyncIterator[tuple[ProjectService, UserStore]]
):
    """Project + user services on **one** session for the member routes.

    ``add_member`` writes a membership *and* reads the user by email; sharing a
    session keeps that a single transaction and avoids concurrent read/write
    sessions racing for SQLite's single writer lock in one request."""
    async with get_session() as session:
        yield (
            ProjectService(store=SqlProjectStore(session)),
            SqlUserStore(session),
        )


# --- project membership gate ------------------------------------------------


@dataclass(slots=True)
class ProjectContext:
    """What a project-scoped route learns after the membership check passes:
    the project, the caller, and the caller's effective role on it."""

    project: Project
    principal: Principal
    role: str


def _project_gate(
    *, moderate: bool
) -> Callable[..., Awaitable[ProjectContext]]:
    """Build a dependency that resolves ``{project_id}`` and authorizes the
    caller against it. ``moderate=True`` requires owner/admin; otherwise any
    member (owner/admin/member) passes.

    404 if the project doesn't exist, 403 if the caller is authenticated but
    may not act on it.
    """

    async def gate(
        project_id: str, principal: CurrentPrincipal
    ) -> ProjectContext:
        # Use a short-lived, read-only session that closes before the route
        # handler runs. Holding this open (as a yielded service would) keeps a
        # read lock that blocks the handler's own write session on SQLite --
        # the default backend and a single writer -- so we scope it tightly.
        async with get_session() as session:
            service = ProjectService(store=SqlProjectStore(session))
            try:
                project = await service.get(project_id)
            except UnknownProject as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="project not found",
                ) from exc
            try:
                role = (
                    await service.require_moderate(principal, project_id)
                    if moderate
                    else await service.require_access(principal, project_id)
                )
            except PermissionDenied as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
                ) from exc
        return ProjectContext(project=project, principal=principal, role=role)

    return gate


# Any member (read/search/upload); and moderators only (manage connectors,
# members, delete). Attach one to every project-scoped route.
ProjectMemberCtx = Annotated[
    ProjectContext, Depends(_project_gate(moderate=False))
]
ProjectModeratorCtx = Annotated[
    ProjectContext, Depends(_project_gate(moderate=True))
]
