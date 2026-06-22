"""Shared staff authentication dependencies for O2C Agent v2.0.

Roles defined:
  admin               — full access to all endpoints
  dispute_manager     — Disputes (full), Orders (read), AR Ledger (read), Customer 360
  collections_analyst — Collections (full), Cash App (full), AR Ledger (full), Customer 360
  controller          — HITL (full), Fraud (full), AR Ledger (full), Analytics, Compliance
  inventory_manager   — Inventory, Products, Purchase Orders, and order inventory visibility
"""
from typing import List, Callable
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from config import settings
from database.postgres import get_db

security = HTTPBearer(auto_error=False)


async def get_current_staff(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db=Depends(get_db),
) -> dict:
    """Decode the JWT and return the active staff user.

    Raises 401 if no token is present or the token is invalid/expired.
    Human staff tokens are checked against staff_users so disabled users lose access.
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated — Bearer token required",
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid or expired token: {exc}",
        )

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Token missing subject")

    if username == "o2c-service":
        role = payload.get("role", "")
        if not role:
            raise HTTPException(status_code=401, detail="Token missing role claim")
        return {"username": username, "display_name": "O2C Service", "role": role}

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

    role = user.get("role", "")
    if not role:
        raise HTTPException(status_code=401, detail="Token missing role claim")

    return {
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "role": role,
    }


def require_role(allowed: List[str]) -> Callable:
    """Dependency factory — raises 403 if the JWT role is not in *allowed*.

    Usage::

        @router.post("/resolve")
        async def resolve(
            staff=Depends(require_role(["admin", "dispute_manager"]))
        ):
            ...  # staff["username"] and staff["role"] are available
    """
    async def _check(staff: dict = Depends(get_current_staff)) -> dict:
        if staff["role"] not in allowed:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Role '{staff['role']}' does not have permission for this action. "
                    f"Required: {allowed}"
                ),
            )
        return staff

    return _check


def create_service_token(expires_minutes: int = 5) -> str:
    """Return a short-lived service-to-service JWT with admin role.

    Used by background workers (email intake, HITL callbacks) so they can
    call RBAC-protected staff endpoints without a human login session.
    """
    return jwt.encode(
        {"sub": "o2c-service", "role": "admin", "exp": datetime.utcnow() + timedelta(minutes=expires_minutes)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


# Convenience alias — kept for backward compatibility with any existing callers
async def require_admin(staff: dict = Depends(require_role(["admin"]))) -> dict:
    return staff
