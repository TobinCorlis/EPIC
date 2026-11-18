from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import token_digest
from app.models.auth import AuthSession, User, UserRole


def get_optional_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    if not authorization:
        return None
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split(" ", 1)[1].strip()
    session = db.query(AuthSession).filter(AuthSession.token_hash == token_digest(token)).first()
    if not session:
        raise HTTPException(status_code=401, detail="Session is invalid or expired")
    from datetime import datetime
    if session.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=401, detail="Session is invalid or expired")
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User account is unavailable")
    return user


def require_authenticated(user: User | None = Depends(get_optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_role(*roles: UserRole):
    def dependency(user: User = Depends(require_authenticated)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient account permissions")
        return user
    return dependency


def enforce_write_access(user: User | None) -> None:
    if settings.enforce_authorization and user is None:
        raise HTTPException(status_code=401, detail="Authentication required")


def require_enforced_writer(user: User | None = Depends(get_optional_user)) -> User | None:
    """Dependency for knowledge writes. Login is required only when enforcement is on."""
    enforce_write_access(user)
    return user


def require_enforced_staff(user: User | None = Depends(get_optional_user)) -> User | None:
    """Review actions require a moderator or administrator when enforcement is on."""
    enforce_write_access(user)
    if settings.enforce_authorization and user.role not in {UserRole.moderator, UserRole.administrator}:
        raise HTTPException(status_code=403, detail="Only a moderator or administrator may perform this action")
    return user


def enforce_debate_participant_write(debate, user: User | None, participant) -> None:
    """Argument and challenge creation: owner, staff, or the linked participant."""
    enforce_write_access(user)
    if not settings.enforce_authorization:
        return
    if user.role in {UserRole.moderator, UserRole.administrator}:
        return
    if debate.owner_user_id is not None and debate.owner_user_id == user.id:
        return
    if participant is not None and participant.user_id == user.id:
        return
    raise HTTPException(status_code=403, detail="You do not have permission to write in this debate")


def enforce_debate_manager(debate, user: User | None) -> None:
    """Resolving a challenge is limited to the debate owner or platform staff."""
    enforce_write_access(user)
    if not settings.enforce_authorization:
        return
    if user.role in {UserRole.moderator, UserRole.administrator}:
        return
    if debate.owner_user_id is not None and debate.owner_user_id == user.id:
        return
    raise HTTPException(status_code=403, detail="Only the debate owner or platform staff may resolve this challenge")
