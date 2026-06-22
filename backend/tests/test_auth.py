from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api import auth, staff_deps
from passwords import hash_password


class FakeDB:
    def __init__(self, users):
        self.users = users

    async def fetchrow(self, query, *args):
        username = args[0]
        return self.users.get(username)


def build_user(username, password, role="admin", display_name="Test User", is_active=True):
    return {
        "username": username,
        "password_hash": hash_password(password),
        "role": role,
        "display_name": display_name,
        "is_active": is_active,
    }


def build_app(db):
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth")

    async def override_db():
        return db

    app.dependency_overrides[auth.get_db] = override_db
    app.dependency_overrides[staff_deps.get_db] = override_db

    @app.get("/admin-only")
    async def admin_only(staff=Depends(staff_deps.require_role(["admin"]))):
        return {"username": staff["username"], "role": staff["role"]}

    return app


def test_valid_login():
    db = FakeDB({"admin": build_user("admin", "admin123", display_name="O2C Admin")})
    client = TestClient(build_app(db))

    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})

    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["user"] == {
        "username": "admin",
        "display_name": "O2C Admin",
        "name": "O2C Admin",
        "role": "admin",
    }


def test_invalid_password():
    db = FakeDB({"admin": build_user("admin", "admin123")})
    client = TestClient(build_app(db))

    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})

    assert response.status_code == 401


def test_disabled_user():
    db = FakeDB({"admin": build_user("admin", "admin123", is_active=False)})
    client = TestClient(build_app(db))

    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})

    assert response.status_code == 403


def test_me_with_valid_token():
    db = FakeDB({"admin": build_user("admin", "admin123", display_name="O2C Admin")})
    client = TestClient(build_app(db))

    login_response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login_response.json()["access_token"]

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {
        "username": "admin",
        "display_name": "O2C Admin",
        "role": "admin",
    }


def test_protected_endpoint_without_token_returns_401():
    db = FakeDB({"admin": build_user("admin", "admin123")})
    client = TestClient(build_app(db))

    response = client.get("/admin-only")

    assert response.status_code == 401



def test_role_mismatch_returns_403():
    db = FakeDB({"controller": build_user("controller", "ctrl123", role="controller")})
    client = TestClient(build_app(db))

    login_response = client.post("/api/auth/login", json={"username": "controller", "password": "ctrl123"})
    token = login_response.json()["access_token"]

    response = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
