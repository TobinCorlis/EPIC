from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import create_session, get_current_user, hash_password, token_digest, verify_password
from app.models.auth import AuthSession, User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenRead, UserRead

router = APIRouter(prefix="/auth", tags=["authentication"])

@router.post("/register", response_model=TokenRead, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    user = User(email=payload.email.lower(), display_name=payload.display_name.strip(), password_hash=hash_password(payload.password))
    db.add(user)
    try: db.commit()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "An account with this email already exists") from exc
    db.refresh(user)
    token, expires = create_session(db, user)
    return TokenRead(access_token=token, expires_at=expires, user=user)

@router.post("/login", response_model=TokenRead)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    token, expires = create_session(db, user)
    return TokenRead(access_token=token, expires_at=expires, user=user)

@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)): return user

@router.post("/logout", status_code=204)
def logout(authorization: str | None = Header(default=None), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    token = authorization.split(" ", 1)[1].strip()
    session = db.query(AuthSession).filter(AuthSession.token_hash == token_digest(token)).first()
    if session:
        db.delete(session); db.commit()
    return None
