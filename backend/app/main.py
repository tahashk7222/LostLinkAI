import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from app import models  # noqa: F401  (registers tables)
from app.api.routes import admin, auth, cases, flags, images, matches, notifications, reports
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine
from app.models import User
from app.models.enums import Role

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    s = get_settings()
    if s.admin_email and s.admin_password:
        with SessionLocal() as db:
            if not db.scalar(select(User).where(User.email == s.admin_email.lower())):
                db.add(User(name="Admin", email=s.admin_email.lower(),
                            password_hash=hash_password(s.admin_password), role=Role.ADMIN))
                db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="LostLink AI API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_error_handlers(app)
    for module in (auth, reports, matches, cases, notifications, images, flags, admin):
        app.include_router(module.router)

    @app.get("/health", tags=["system"])
    def health():
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "database": db_ok}

    return app


app = create_app()
