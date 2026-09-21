"""Operational commands.

Run as `python -m app.cli <command>`, and in production as a one-off container:

    docker compose run --rm api python -m app.cli create-staff-user --email ...

Staff privilege is granted here and nowhere else. There is deliberately no API route
that sets `is_staff`: anyone with shell access to the server is already trusted, so a
web endpoint granting admin would add attack surface without adding capability.
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionFactory, engine
from app.core.security import hash_password
from app.models import User
from app.repositories.users import UserRepository
from app.schemas.auth import MIN_PASSWORD_LENGTH


class StaffUserExistsError(Exception):
    """An account with this address already exists.

    Refusing rather than promoting is deliberate: silently granting staff rights to
    an existing account would turn a typo, or a known address, into an escalation.
    """

    def __init__(self, email: str) -> None:
        super().__init__(f"an account already exists for {email}; refusing to modify it")


async def create_staff_user(session: AsyncSession, *, email: str, password: str) -> User:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")

    users = UserRepository(session)
    if await users.exists_by_email(email):
        raise StaffUserExistsError(email)

    user = User(
        email=email.strip().lower(),
        password_hash=hash_password(password),
        is_staff=True,
        is_active=True,
    )
    users.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _run_create_staff_user(email: str, password: str | None) -> int:
    # Prompted rather than passed as an argument by default: a password on the command
    # line lands in shell history and in the process table, where any local user can
    # read it.
    secret = password or getpass.getpass("Password: ")

    async with SessionFactory() as session:
        try:
            user = await create_staff_user(session, email=email, password=secret)
        except (StaffUserExistsError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)  # noqa: T201 -- CLI output
            return 1

    print(f"created staff user {user.email} ({user.id})")  # noqa: T201 -- CLI output
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    staff = commands.add_parser("create-staff-user", help="Create an operator account.")
    staff.add_argument("--email", required=True)
    staff.add_argument(
        "--password",
        help="Omit to be prompted, which keeps the value out of shell history.",
    )

    args = parser.parse_args(argv)

    async def _dispatch() -> int:
        try:
            if args.command == "create-staff-user":
                return await _run_create_staff_user(args.email, args.password)
            parser.error(f"unknown command: {args.command}")
        finally:
            await engine.dispose()

    return asyncio.run(_dispatch())


if __name__ == "__main__":
    raise SystemExit(main())
