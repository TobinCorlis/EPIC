import hashlib, hmac, secrets
from datetime import timedelta
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session
from app.core.clock import utcnow
from app.core.config import settings
from app.core.database import get_db
from app.models.auth import AuthSession, User

def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 210_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt, expected = encoded.split("$", 2)
        actual = hash_password(password, salt).split("$", 2)[2]
        return hmac.compare_digest(actual, expected)
    except ValueError:
        return False

def token_digest(token: str) -> str:
    return hmac.new(settings.secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()

def create_session(db: Session, user: User):
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(hours=settings.session_hours)
    db.add(AuthSession(user_id=user.id, token_hash=token_digest(token), expires_at=expires))
    db.commit()
    return token, expires

def get_current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required")
    token = authorization.split(" ", 1)[1].strip()
    session = db.query(AuthSession).filter(AuthSession.token_hash == token_digest(token)).first()
    if not session or session.expires_at <= utcnow():
        raise HTTPException(401, "Session is invalid or expired")
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "User account is unavailable")
    return user
