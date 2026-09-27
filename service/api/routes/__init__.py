from .answer import router as answer_router
from .auth import router as auth_router
from .connectors import router as connectors_router
from .documents import router as documents_router
from .health import router as health_router
from .projects import router as projects_router
from .search import router as search_router
from .users import router as users_router

__all__ = [
    "answer_router",
    "auth_router",
    "connectors_router",
    "documents_router",
    "health_router",
    "projects_router",
    "search_router",
    "users_router",
]
