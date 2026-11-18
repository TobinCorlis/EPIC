"""EPIC command line utilities.

Create the first administrator after the schema exists (``alembic upgrade head``
in production, or one local app start when automatic schema creation is on):

    cd backend
    python -m app.cli create-admin --email admin@example.com --name "EPIC Admin" --password "replace-this-password"
"""
from __future__ import annotations

import argparse

from app.core.database import SessionLocal
from app.core.email import normalize_email
from app.core.security import hash_password
from app.models.auth import User, UserRole


class AdminBootstrapError(Exception):
    pass


def create_first_admin(email: str, display_name: str, password: str) -> User:
    """Create an administrator account. Refuses once any administrator exists."""
    name = display_name.strip()
    if len(password) < 8:
        raise AdminBootstrapError("Password must be at least 8 characters.")
    try:
        normalized = normalize_email(email)
    except ValueError as exc:
        raise AdminBootstrapError(str(exc)) from exc
    if len(name) < 2:
        raise AdminBootstrapError("Display name must be at least 2 characters.")

    db = SessionLocal()
    try:
        if db.query(User).filter(User.role == UserRole.administrator).first():
            raise AdminBootstrapError("An administrator already exists.")
        if db.query(User).filter(User.email == normalized).first():
            raise AdminBootstrapError("A user with this email already exists.")
        user = User(
            email=normalized,
            display_name=name,
            password_hash=hash_password(password),
            role=UserRole.administrator,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="EPIC administration commands")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="Create the first administrator account")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--password", required=True)
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        try:
            user = create_first_admin(args.email, args.name, args.password)
        except AdminBootstrapError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"Created administrator {user.email} (id {user.id}).")


if __name__ == "__main__":
    main()
