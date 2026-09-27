"""The user directory.

``GET /users`` backs the "add someone" picker on the Members page: a moderator
should not have to remember an exact email address for an account that already
exists. The response is scoped to what the caller may see -- see
:mod:`service.core.directory` for the rule and why it leaks nothing new.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from service.api.dependencies import CurrentPrincipal, get_directory_stores
from service.core.directory import visible_users
from service.storage.store import ProjectStore, UserStore

router = APIRouter(prefix="/users", tags=["users"])

StoresDep = Annotated[
    tuple[UserStore, ProjectStore], Depends(get_directory_stores)
]


class DirectoryUser(BaseModel):
    user_id: str
    email: str
    username: str


@router.get("")
async def list_users(
    principal: CurrentPrincipal, stores: StoresDep
) -> list[DirectoryUser]:
    """Accounts this caller may add to a project.

    Empty for someone who moderates nothing -- they cannot add members
    anywhere, so there is nothing for them to pick from.
    """
    users, projects = stores
    entries = await visible_users(
        principal=principal, users=users, projects=projects
    )
    return [
        DirectoryUser(
            user_id=e.user_id, email=e.email, username=e.username
        )
        for e in entries
    ]
