from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from datetime import datetime, timedelta
from jose import JWTError, jwt
from config import settings
from database.postgres import get_db
from passwords import verify_password

router = APIRouter()
security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


def _create_staff_token(username: str, role: str) -> str:
    return jwt.encode(
        {
            "sub": username,
            "role": role,
            "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


@router.post("/login")
async def login(req: LoginRequest, db=Depends(get_db)):
    row = await db.fetchrow(
        """SELECT username, password_hash, role, display_name, is_active
           FROM staff_users
           WHERE username = $1""",
        req.username,
    )
    if not row:
        raise HTTPException(401, "Invalid credentials")

    user = dict(row)
    if not user.get("is_active", True):
        raise HTTPException(403, "User account is disabled")
    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")

    token = _create_staff_token(user["username"], user["role"])
    display_name = user.get("display_name") or user["username"]
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "username": user["username"],
            "display_name": display_name,
            "name": display_name,
            "role": user["role"],
        },
    }

@router.get("/me")
async def me(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db=Depends(get_db),
):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated — Bearer token required")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Token missing subject")

    row = await db.fetchrow(
        """SELECT username, display_name, role, is_active
           FROM staff_users
           WHERE username = $1""",
        username,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Staff user not found")

    user = dict(row)
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="User account is disabled")

    display_name = user.get("display_name") or user["username"]
    return {
        "username": user["username"],
        "display_name": display_name,
        "role": user["role"],
    }
