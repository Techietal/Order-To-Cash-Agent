from fastapi import APIRouter, Depends, HTTPException
from database.postgres import get_db
from api.staff_deps import require_role

router = APIRouter()

CUSTOMER_READ_ROLES = ["admin", "dispute_manager", "collections_analyst"]


def sanitize_customer(row) -> dict:
    customer = dict(row)
    customer.pop("password_hash", None)
    return customer


@router.get("")
async def get_customers(db=Depends(get_db), staff=Depends(require_role(CUSTOMER_READ_ROLES))):
    rows = await db.fetch("SELECT * FROM customers ORDER BY customer_id")
    return {"customers": [sanitize_customer(r) for r in rows]}

@router.get("/{customer_id}")
async def get_customer(customer_id: str, db=Depends(get_db), staff=Depends(require_role(CUSTOMER_READ_ROLES))):
    row = await db.fetchrow("SELECT * FROM customers WHERE customer_id = $1", customer_id)
    if not row:
        raise HTTPException(404, f"Customer {customer_id} not found")
    return {"customer": sanitize_customer(row)}
