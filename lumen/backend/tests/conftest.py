import os

import pytest

# Tests run against a separate database (created by scripts/setup_db.ps1 or manually).
os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://dw_owner@localhost:5432/lumen_analytics_test"))
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ.setdefault("TODAY_OVERRIDE", "2026-10-17")
import tempfile  # noqa: E402
os.environ.setdefault("UPLOAD_DIR", os.path.join(tempfile.gettempdir(), "lumen_test_uploads"))
os.environ.pop("LLM_BASE_URL", None)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_engine, init_db  # noqa: E402
from app.main import app  # noqa: E402

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "sample_data")


def _reset_database():
    eng = get_engine()
    with eng.begin() as c:
        schemas = [r[0] for r in c.execute(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'ws\\_%' OR nspname = :m"),
                                           {"m": get_settings().meta_schema})]
        for s in schemas:
            c.execute(text(f'DROP SCHEMA "{s}" CASCADE'))
    init_db()


@pytest.fixture(scope="session")
def client():
    _reset_database()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def workspace(client):
    import uuid
    r = client.post("/api/workspaces", json={"name": f"t-{uuid.uuid4().hex[:6]}"})
    assert r.status_code == 201, r.text
    ws = r.json()
    yield ws
    client.delete(f"/api/workspaces/{ws['id']}")


@pytest.fixture(scope="session")
def demo(client):
    """The full demo workspace built from sample_data through the HTTP API (slow: built once per session)."""
    from app.demo import build_demo

    return build_demo(client, SAMPLE_DIR, name="demo-under-test", log=lambda *a, **k: None)


def api(ws_id: int, path: str = "") -> str:
    return f"/api/workspaces/{ws_id}{path}"


def upload_csv(client, ws_id: int, filename: str, content: str | bytes, **import_kw) -> dict:
    data = content.encode() if isinstance(content, str) else content
    r = client.post(f"/api/workspaces/{ws_id}/uploads", files={"file": (filename, data)})
    assert r.status_code == 200, r.text
    prev = r.json()
    body = {"upload_id": prev["upload_id"], "sheet": prev["sheet"], "header_row": prev["header_row"], **import_kw}
    r = client.post(f"/api/workspaces/{ws_id}/imports", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ----------------------------------------------------------------------------------------------- mini model
# A tiny star schema with hand-computable answers (today is pinned to 2026-10-17).

MINI_PRODUCTS = """sku,product_name,category
P1,Widget,Tools
P2,Gadget,Tools
P3,Gizmo,Toys
"""
MINI_CHANNELS = """channel,channel_type
Shopify,D2C
Amazon,Marketplace
"""
MINI_SALES = """sale_id,sale_date,sku,channel,qty,amount,txn_type
1,2026-07-10,P1,Shopify,2,200.00,Sale
2,2026-08-05,P1,Amazon,1,100.00,Sale
3,2026-08-20,P2,Shopify,3,450.00,Sale
4,2026-09-02,P1,Amazon,4,400.00,Sale
5,2026-09-15,P2,Amazon,1,150.00,Sale
6,2026-09-28,P3,Shopify,2,60.00,Sale
7,2026-09-30,P1,Shopify,5,500.00,Transfer
8,2026-10-05,P3,Amazon,1,30.00,Sale
"""
MINI_RETURNS = """return_id,return_date,sku,qty_returned
R1,2026-08-10,P1,1
R2,2026-09-10,P2,2
R3,2026-09-12,P1,1
"""
MINI_STOCK = """snapshot_date,sku,stock
2026-08-31,P1,7
2026-08-31,P2,8
2026-09-01,P1,10
2026-09-01,P2,20
2026-09-30,P1,15
2026-09-30,P2,5
"""
MINI_SPEND = """spend_date,channel,spend
2026-08-10,Amazon,30.00
2026-09-01,Shopify,100.00
2026-09-15,Amazon,50.00
"""


def build_mini(client, name: str = "mini") -> dict:
    import uuid

    r = client.post("/api/workspaces", json={"name": f"{name}-{uuid.uuid4().hex[:6]}"})
    assert r.status_code == 201, r.text
    ws = r.json()["id"]
    ds = {}
    for dname, content in (("Products", MINI_PRODUCTS), ("Channels", MINI_CHANNELS), ("Sales", MINI_SALES),
                           ("Returns", MINI_RETURNS), ("Stock", MINI_STOCK), ("Spend", MINI_SPEND)):
        d = upload_csv(client, ws, f"{dname.lower()}.csv", content, name=dname)["dataset"]
        ds[d["slug"]] = d["id"]
    for a, ac, b, bc in (("sales", "sku", "products", "sku"), ("returns", "sku", "products", "sku"),
                         ("stock", "sku", "products", "sku"), ("sales", "channel", "channels", "channel"),
                         ("spend", "channel", "channels", "channel")):
        r = client.post(api(ws, "/relationships"), json={"from_dataset_id": ds[a], "from_column": ac, "to_dataset_id": ds[b], "to_column": bc})
        assert r.status_code == 201, r.text
    sale = [{"column": "txn_type", "op": "eq", "value": "Sale"}]
    metrics = [
        dict(name="net_sales", label="Net sales", dataset_id=ds["sales"], expression="SUM(amount)", filters=sale, format="currency"),
        dict(name="units_sold", label="Units sold", dataset_id=ds["sales"], expression="SUM(qty)", filters=sale),
        dict(name="units_returned", label="Units returned", dataset_id=ds["returns"], expression="SUM(qty_returned)"),
        dict(name="stock_on_hand", label="Stock on hand", dataset_id=ds["stock"], expression="SUM(stock)",
             time_column="snapshot_date", semi_additive=True),
    ]
    for mt in metrics:
        r = client.post(api(ws, "/metrics"), json={"kind": "simple", **mt})
        assert r.status_code == 201, r.text
    r = client.post(api(ws, "/metrics"), json={"kind": "composite", "name": "return_rate", "label": "Return rate",
                                               "expression": "{units_returned} / NULLIF({units_sold}, 0)", "format": "percent"})
    assert r.status_code == 201, r.text
    return {"ws": ws, "ds": ds}
