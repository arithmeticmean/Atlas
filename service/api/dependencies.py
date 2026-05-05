"""Request-scoped wiring (the composition root for the web layer).

Builds a ``DocumentService`` backed by the SQL metadata store and the on-disk
blob store, inside a single session whose transaction commits when the request
finishes successfully (``get_session`` handles commit/rollback).
"""

import asyncio
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
)
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import settings
from ingest import IngestionPipeline, build_embeddings
from models import Project
from service import (
    AnswerService,
    AuthService,
    ConnectorManager,
    ConnectorService,
    DocumentService,
    EmbeddingIndex,
    IngestionService,
    InvalidToken,
    PermissionDenied,
    Principal,
    ProjectService,
    SearchService,
    TokenCodec,
    UnknownProject,
    build_chat_model,
    ensure_owner,
)
from service.worker import IngestionWorker, OnProgress
from storage.blob.disk import DiskDocumentStore
from storage.sql import get_session
from storage.sql.connector import SqlConnectorStore
from storage.sql.document_meta import SqlDocumentMetaStore
from storage.sql.jobs import SqlJobQueue
from storage.sql.project import SqlProjectStore
from storage.sql.user import SqlUserStore
from storage.store import (
    ConnectorStore,
    DocumentMetaStore,
    JobQueue,
    UserStore,
)
from storage.vector.lancedb import LanceDB

# The signing key and TTLs are process-wide, so build the codec once and share
# it across requests; only the per-request DB session is rebuilt each time.
_token_codec = TokenCodec(
    secret=settings.jwt_secret,
    algorithm=settings.jwt_algorithm,
    access_ttl=timedelta(minutes=settings.access_token_ttl_minutes),
    refresh_ttl=timedelta(minutes=settings.refresh_token_ttl_minutes),
    invite_ttl=timedelta(minutes=settings.invite_token_ttl_minutes),
)

# authN/authZ are stateless (token-only), so one shared, store-less service
# serves every request. The account flows get their own store-backed service
# per request (see get_auth_service).
_stateless_auth = AuthService(token_codec=_token_codec)

# auto_error=False so a missing/blank header yields None and we can raise our
# own 401 (with a WWW-Authenticate header) rather than FastAPI's default 403.
_bearer = HTTPBearer(auto_error=False)


async def get_auth_service() -> AsyncIterator[AuthService]:
    async with get_session() as session:
        yield AuthService(
            token_codec=_token_codec,
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
                token_codec=_token_codec,
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
        return _stateless_auth.authenticate(credentials.credentials)
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
            _stateless_auth.authorize(principal, require_role=role)
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
    """Drop the vector table (leaving the lock file beside it intact)."""

    def _drop() -> None:
        import lancedb  # type: ignore[import-untyped]

        db = lancedb.connect(settings.vector_path)
        if settings.vector_table in db.table_names():
            db.drop_table(settings.vector_table)

    await asyncio.to_thread(_drop)


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


def _build_vector_store() -> LanceDB:
    # mode="append" is essential: langchain's LanceDB defaults to "overwrite",
    # which would replace the whole table on every add.
    return LanceDB(
        uri=settings.vector_path,
        embedding=build_embeddings(),
        table_name=settings.vector_table,
        mode="append",
    )


def get_ingestion_service() -> IngestionService:
    return IngestionService(
        meta_store=_meta_store_uow,
        pipeline=IngestionPipeline(vector_store=_build_vector_store()),
    )


def get_search_service() -> SearchService:
    # Same vector store (embeddings + table) the corpus was indexed under.
    return SearchService(vector_store=_build_vector_store())


def get_answer_service() -> AnswerService:
    return AnswerService(
        search=SearchService(vector_store=_build_vector_store()),
        chat_model=build_chat_model(),
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
async def _user_store_uow() -> AsyncGenerator[UserStore]:
    async with get_session() as session:
        yield SqlUserStore(session)


async def bootstrap_owner() -> None:
    """Create the configured owner account at startup if it doesn't exist."""
    await ensure_owner(
        user_store_uow=_user_store_uow,
        email=settings.owner_email,
        password=settings.owner_password,
    )


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
