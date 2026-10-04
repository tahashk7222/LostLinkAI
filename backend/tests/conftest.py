import os
import shutil
import tempfile

# Configure an isolated database/storage BEFORE the app is imported.
_tmp = tempfile.mkdtemp(prefix="lostlink-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["STORAGE_DIR"] = os.path.join(_tmp, "storage")
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret-123"
os.environ["ADMIN_EMAIL"] = ""
os.environ["ADMIN_PASSWORD"] = ""
# Tests never use the production Cloudinary account, even when backend/.env holds real credentials.
# Cloudinary-specific tests configure it explicitly with mocked SDK calls (tests/test_storage_cloud.py).
os.environ["CLOUDINARY_CLOUD_NAME"] = ""
os.environ["CLOUDINARY_API_KEY"] = ""
os.environ["CLOUDINARY_API_SECRET"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from sqlalchemy import text  # noqa: E402

from app.db.migrate import run_migrations  # noqa: E402
from app.db.session import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    # Build the schema through the real Alembic migrations, as production does.
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    run_migrations(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    shutil.rmtree(_tmp, ignore_errors=True)


def register(client, name="Alice", email="alice@example.com", password="password123"):
    r = client.post("/auth/register", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
