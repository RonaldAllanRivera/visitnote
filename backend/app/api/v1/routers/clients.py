"""Care recipient routes.

Every handler passes the authenticated user's id to the repository, which filters on
it in SQL. A record belonging to someone else is indistinguishable from one that does
not exist -- a 403 would confirm it exists, which is itself a disclosure.
"""

import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.models import Client
from app.repositories.clients import ClientRepository
from app.schemas.client import ClientCreate, ClientRead, ClientUpdate

router = APIRouter(prefix="/clients", tags=["clients"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


@router.get("", response_model=list[ClientRead])
async def list_clients(user: CurrentUser, session: SessionDep) -> list[Client]:
    return list(await ClientRepository(session).list_for_owner(user.id))


@router.post("", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreate, user: CurrentUser, session: SessionDep
) -> Client:
    record = ClientRepository(session).add(Client(owner_id=user.id, label=payload.label))
    await session.commit()
    await session.refresh(record)
    return record


@router.get("/{client_id}", response_model=ClientRead)
async def get_client(client_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Client:
    record = await ClientRepository(session).get_for_owner(client_id, user.id)
    if record is None:
        raise _NOT_FOUND
    return record


@router.patch("/{client_id}", response_model=ClientRead)
async def update_client(
    client_id: uuid.UUID, payload: ClientUpdate, user: CurrentUser, session: SessionDep
) -> Client:
    record = await ClientRepository(session).get_for_owner(client_id, user.id)
    if record is None:
        raise _NOT_FOUND

    if payload.label is not None:
        record.label = payload.label

    await session.commit()
    await session.refresh(record)
    return record


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    """Deactivate rather than erase.

    Visits reference this row, and a signed note is a legal record. Removing the row
    would orphan documentation the user may be required to produce later.
    """
    record = await ClientRepository(session).get_for_owner(client_id, user.id)
    if record is None:
        raise _NOT_FOUND

    record.is_active = False
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
