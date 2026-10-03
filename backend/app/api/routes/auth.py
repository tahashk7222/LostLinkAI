from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.errors import AppError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UpdateProfileIn, UserOut
from app.services.audit import audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: DB):
    email = body.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise AppError(409, "An account with this email already exists")
    user = User(name=body.name, email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    audit(db, "user.register", user.id, "user", user.id)
    db.commit()
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: DB):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        audit(db, "user.login_failed", user.id if user else None, "user", user.id if user else None)
        db.commit()
        raise AppError(401, "Incorrect email or password")
    if not user.is_active:
        raise AppError(403, "This account has been deactivated")
    audit(db, "user.login", user.id, "user", user.id)
    db.commit()
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


@router.put("/me", response_model=UserOut)
def update_me(body: UpdateProfileIn, user: CurrentUser, db: DB):
    if body.name:
        user.name = body.name.strip()
    if body.new_password:
        if not body.current_password or not verify_password(body.current_password, user.password_hash):
            raise AppError(400, "Current password is incorrect")
        user.password_hash = hash_password(body.new_password)
        audit(db, "user.password_changed", user.id, "user", user.id)
    db.commit()
    return user
