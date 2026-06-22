from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import analytics, customers, invoices, ml_monitor, orders, portal, purchase_orders, products, staff_deps, inventory


class FakeDB:
    async def fetchrow(self, *args, **kwargs):
        return None

    async def fetch(self, *args, **kwargs):
        return []

    async def fetchval(self, *args, **kwargs):
        return 0


def build_app():
    app = FastAPI()
    app.include_router(orders.router, prefix="/api/orders")
    app.include_router(invoices.router, prefix="/api/invoices")
    app.include_router(customers.router, prefix="/api/customers")
    app.include_router(analytics.router, prefix="/api/analytics")
    app.include_router(ml_monitor.router, prefix="/api/ml")
    app.include_router(portal.router, prefix="/api/portal")
    app.include_router(purchase_orders.router, prefix="/api/purchase-orders")
    app.include_router(products.router, prefix="/api/products")
    app.include_router(inventory.router, prefix="/api/inventory")

    async def override_db():
        return FakeDB()

    for module in [orders, invoices, customers, analytics, portal, purchase_orders, products, staff_deps, inventory]:
        if hasattr(module, 'get_db'):
            app.dependency_overrides[module.get_db] = override_db

    return app


def test_staff_routes_without_token_return_401():
    client = TestClient(build_app())

    paths = [
        "/api/orders/",
        "/api/orders/ORD-0001/fulfill",
        "/api/orders/ORD-0001/cancel",
        "/api/invoices/",
        "/api/customers/",
        "/api/analytics/kpis",
        "/api/ml/models",
        "/api/portal/CUST-0001/summary",
        "/api/purchase-orders",
        "/api/purchase-orders/PO-0001/confirm",
        "/api/purchase-orders/PO-0001/receive",
        "/api/products",
        "/api/products/SKU-001",
        "/api/inventory/transactions",
        "/api/inventory/adjust",
        "/api/inventory/stock-summary",
        "/api/inventory/forecast/SKU-001",
        "/api/inventory/forecast/refresh",
        "/api/inventory/dashboard-summary",
        "/api/inventory/incoming",
    ]

    for path in paths:
        if path.endswith(("/fulfill", "/cancel", "/confirm", "/receive")):
            response = client.post(path)
        elif path in ("/api/inventory/forecast/refresh", "/api/inventory/adjust", "/api/purchase-orders"):
            response = client.post(path, json={"days": 30})
        else:
            response = client.get(path)
        assert response.status_code == 401, f"Expected 401 for {path}, got {response.status_code}"


def test_inventory_forecast_refresh_requires_auth():
    client = TestClient(build_app())
    response = client.post("/api/inventory/forecast/refresh", json={"days": 30})
    assert response.status_code == 401
