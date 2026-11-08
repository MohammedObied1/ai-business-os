import os

os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_bizos.db"
os.environ["ALLOW_PUBLIC_SIGNUP"] = "true"
os.environ["PLATFORM_ADMIN_EMAIL"] = "root@platform.test"
os.environ["PLATFORM_ADMIN_PASSWORD"] = "rootpass1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    # the suite drops every table: refuse to run against anything but the throw-away test database
    if engine.url.get_backend_name() != "sqlite" or not str(engine.url.database).endswith("test_bizos.db"):
        pytest.exit(f"Refusing to run tests against {engine.url} — only ./test_bizos.db may be wiped", returncode=2)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)
    engine.dispose()  # release pooled connections so Windows can delete the file
    if os.path.exists("test_bizos.db"):
        os.remove("test_bizos.db")


def register(client, company, email):
    r = client.post("/api/auth/register", json={"company_name": company, "owner_name": "Owner", "owner_email": email, "password": "pass1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def company_a(client):
    return register(client, "Company A", "a@a.com")


@pytest.fixture(scope="session")
def company_b(client):
    return register(client, "Company B", "b@b.com")
