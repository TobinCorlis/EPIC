from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.authorization import require_role
from app.core.database import get_db
from app.models.auth import User, UserRole
from app.schemas.auth import UserRead

router = APIRouter(prefix="/admin", tags=["administration"])


@router.get("/users", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.administrator)),
):
    return db.query(User).order_by(User.id).all()


@router.patch("/users/{user_id}/role", response_model=UserRead)
def set_user_role(
    user_id: int,
    role: UserRole,
    db: Session = Depends(get_db),
    actor: User = Depends(require_role(UserRole.administrator)),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == actor.id and role != UserRole.administrator:
        raise HTTPException(status_code=409, detail="Administrators cannot remove their own administrator role")
    user.role = role
    db.commit()
    db.refresh(user)
    return user
