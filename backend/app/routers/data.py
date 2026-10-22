import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models as m
from ..db import get_engine, get_session
from ..deps import current_user, dataset_of, editor, viewer
from ..serializers import connector_out, dataset_out, iso, relationship_out
from ..services import datasets as dsvc
from ..services.connectors import REGISTRY, ConnectorError, get_connector, sanitize_config, sync_dataset, test_connection
from ..services.datasets import DatasetError
from ..services.ingest import IngestError
from ..services.naming import q
from ..services.transforms import TRANSFORM_KINDS
from ..services.typeinfer import DATA_TYPES
from ..services.warehouse import to_jsonable

router = APIRouter(prefix="/api/workspaces/{ws_id}", tags=["data"])


def _err(e: Exception) -> HTTPException:
    return HTTPException(400, str(e))


# ----------------------------------------------------------------------------------------------- uploads

@router.post("/uploads")
async def upload(file: UploadFile = File(...), ws: m.Workspace = Depends(editor)):
    from ..config import get_settings

    limit = get_settings().max_upload_mb * 1024 * 1024
    chunks, total = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:  # enforce the cap while streaming, before buffering the whole file in memory
            raise HTTPException(400, f"File is larger than {get_settings().max_upload_mb} MB")
        chunks.append(chunk)
    data = b"".join(chunks)
    try:
        meta = dsvc.save_upload(file.filename or "upload.csv", data)
        return dsvc.preview_upload(meta["upload_id"], None, None)
    except (IngestError, DatasetError) as e:
        raise _err(e)


@router.get("/uploads/{upload_id}/preview")
def upload_preview(upload_id: str, sheet: str | None = None, header_row: int | None = None, ws: m.Workspace = Depends(editor)):
    try:
        return dsvc.preview_upload(upload_id, sheet, header_row)
    except IngestError as e:
        raise _err(e)


class ColumnSpec(BaseModel):
    source_name: str
    name: str = ""
    display_name: str = ""
    data_type: str = "text"
    include: bool = True


class ImportIn(BaseModel):
    upload_id: str
    sheet: str | None = None
    header_row: int = 0
    name: str | None = None
    columns: list[ColumnSpec] | None = None
    mode: str = Field("new", pattern="^(new|append|replace)$")
    dataset_id: int | None = None
    options: dict = Field(default_factory=dict)


@router.post("/imports", status_code=201)
def do_import(body: ImportIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    req = body.model_dump()
    if req["columns"] is not None:
        req["columns"] = [c for c in req["columns"]]
    try:
        ds, report = dsvc.import_upload(db, ws, req)
    except (IngestError, DatasetError) as e:
        db.rollback()
        raise _err(e)
    return {"dataset": dataset_out(ds), "report": report}


# ----------------------------------------------------------------------------------------------- datasets

@router.get("/datasets")
def list_datasets(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return [dataset_out(d, full=True) for d in db.query(m.Dataset).filter_by(workspace_id=ws.id).order_by(m.Dataset.name)]


@router.get("/datasets/{ds_id}")
def get_dataset(ds_id: int, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return dataset_out(dataset_of(db, ws, ds_id))


class DatasetPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    default_date_column: str | None = None


@router.patch("/datasets/{ds_id}")
def patch_dataset(ds_id: int, body: DatasetPatch, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    ds = dataset_of(db, ws, ds_id)
    if body.name:
        ds.name = body.name.strip()[:200]
    if body.description is not None:
        ds.description = body.description
    if body.default_date_column is not None:
        if body.default_date_column and body.default_date_column not in {c.name for c in ds.columns if c.data_type in ("date", "datetime")}:
            raise HTTPException(400, "Default date column must be a date column")
        ds.default_date_column = body.default_date_column or None
    db.commit()
    return dataset_out(ds)


@router.delete("/datasets/{ds_id}", status_code=204)
def delete_dataset(ds_id: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    try:
        dsvc.delete_dataset(db, ws, dataset_of(db, ws, ds_id))
    except DatasetError as e:
        raise _err(e)


@router.get("/datasets/{ds_id}/rows")
def dataset_rows(ds_id: int, page: int = 0, page_size: int = 100, search: str | None = None, sort: str | None = None,
                 desc: bool = False, filters: str | None = None, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    ds = dataset_of(db, ws, ds_id)
    try:
        flt = json.loads(filters) if filters else None
    except (ValueError, json.JSONDecodeError) as e:
        raise _err(e)
    if flt is not None and not isinstance(flt, list):
        raise HTTPException(400, "filters must be a JSON array")
    try:
        return dsvc.read_rows(ws, ds, page, page_size, search, sort, desc, flt)
    except (ValueError, json.JSONDecodeError) as e:
        raise _err(e)


@router.get("/datasets/{ds_id}/profile")
def dataset_profile(ds_id: int, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return dsvc.profile_dataset(ws, dataset_of(db, ws, ds_id))


@router.post("/datasets/{ds_id}/quality")
def recheck_quality(ds_id: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    ds = dataset_of(db, ws, ds_id)
    ds.quality = dsvc.compute_quality(ws, ds)
    db.commit()
    return ds.quality


@router.get("/datasets/{ds_id}/export")
def export_dataset(ds_id: int, format: str = Query("csv", pattern="^(csv|xlsx)$"), ws: m.Workspace = Depends(viewer),
                   db: Session = Depends(get_session)):
    ds = dataset_of(db, ws, ds_id)
    cols = [c for c in ds.columns]
    with get_engine().connect() as conn:
        rows = conn.execute(text(f"SELECT {', '.join(q(c.name) for c in cols)} FROM {q(ws.schema_name)}.{q(ds.slug)}")).all()
    headers = [c.display_name for c in cols]
    return tabular_response(ds.slug, headers, [[to_jsonable(v) for v in r] for r in rows], format)


def _csv_safe(v):
    """Neutralise spreadsheet formula injection: a cell beginning with = + - @ (or a leading tab/CR, per OWASP)
    is executed as a formula when the exported file is opened in Excel/Sheets. Prefix such text with a quote."""
    if isinstance(v, str) and v and v[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def tabular_response(name: str, headers: list[str], rows: list[list], fmt: str) -> StreamingResponse:
    headers = [_csv_safe(h) for h in headers]
    rows = [[_csv_safe(v) for v in r] for r in rows]
    if fmt == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        sh = wb.active
        sh.append(headers)
        for r in rows:
            sh.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    import csv

    sio = io.StringIO()
    w = csv.writer(sio)
    w.writerow(headers)
    w.writerows(rows)
    return StreamingResponse(iter([sio.getvalue().encode("utf-8-sig")]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


# ----------------------------------------------------------------------------------------------- columns

class ColumnPatch(BaseModel):
    display_name: str | None = None
    description: str | None = None
    data_type: str | None = None
    hidden: bool | None = None
    expression: str | None = None


@router.patch("/datasets/{ds_id}/columns/{name}")
def patch_column(ds_id: int, name: str, body: ColumnPatch, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    ds = dataset_of(db, ws, ds_id)
    if body.data_type and body.data_type not in DATA_TYPES:
        raise HTTPException(400, "Invalid data type")
    try:
        dsvc.update_column(db, ws, ds, name, body.model_dump(exclude_none=True))
    except DatasetError as e:
        db.rollback()
        raise _err(e)
    db.refresh(ds)
    return dataset_out(ds)


class DerivedIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    expression: str = Field(min_length=1, max_length=4000)
    data_type: str = "decimal"


@router.post("/datasets/{ds_id}/columns", status_code=201)
def add_column(ds_id: int, body: DerivedIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    ds = dataset_of(db, ws, ds_id)
    try:
        dsvc.add_derived_column(db, ws, ds, body.display_name, body.expression, body.data_type)
    except DatasetError as e:
        db.rollback()
        raise _err(e)
    db.refresh(ds)
    return dataset_out(ds)


@router.delete("/datasets/{ds_id}/columns/{name}")
def delete_column(ds_id: int, name: str, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    ds = dataset_of(db, ws, ds_id)
    try:
        dsvc.delete_column(db, ws, ds, name)
    except DatasetError as e:
        db.rollback()
        raise _err(e)
    db.refresh(ds)
    return dataset_out(ds)


# ----------------------------------------------------------------------------------------------- transforms

@router.get("/transform-kinds")
def transform_kinds(ws: m.Workspace = Depends(viewer)):
    return TRANSFORM_KINDS


class TransformIn(BaseModel):
    kind: str
    params: dict = Field(default_factory=dict)


@router.post("/datasets/{ds_id}/transforms")
def add_transform(ds_id: int, body: TransformIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    ds = dataset_of(db, ws, ds_id)
    if body.kind not in TRANSFORM_KINDS:
        raise HTTPException(400, f"Unknown transform {body.kind}")
    try:
        msg = dsvc.apply_transform_step(db, ws, ds, body.kind, body.params)
    except DatasetError as e:
        db.rollback()
        raise _err(e)
    db.refresh(ds)
    return {"message": msg, "dataset": dataset_out(ds)}


@router.delete("/datasets/{ds_id}/transforms/{t_id}")
def remove_transform(t_id: int, ds_id: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    """Removes a step from the recipe so it is no longer replayed on refresh (already-changed rows stay changed
    until the dataset is refreshed / re-imported)."""
    ds = dataset_of(db, ws, ds_id)
    t = next((x for x in ds.transforms if x.id == t_id), None)
    if not t:
        raise HTTPException(404, "Step not found")
    ds.transforms.remove(t)
    db.commit()
    return dataset_out(ds)


# ----------------------------------------------------------------------------------------------- query tables

class QueryTableIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sql: str = Field(min_length=1, max_length=20000)


@router.post("/query-tables", status_code=201)
def create_query_table(body: QueryTableIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    try:
        ds = dsvc.save_query_table(db, ws, body.name, body.sql)
    except DatasetError as e:
        db.rollback()
        raise _err(e)
    return dataset_out(ds)


@router.put("/query-tables/{ds_id}")
def update_query_table(ds_id: int, body: QueryTableIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    ds = dataset_of(db, ws, ds_id)
    if ds.kind != "query_table":
        raise HTTPException(400, "Not a query table")
    try:
        ds = dsvc.save_query_table(db, ws, body.name, body.sql, dataset=ds)
    except DatasetError as e:
        db.rollback()
        raise _err(e)
    return dataset_out(ds)


# ----------------------------------------------------------------------------------------------- relationships

class RelationshipIn(BaseModel):
    from_dataset_id: int
    from_column: str
    to_dataset_id: int
    to_column: str


@router.get("/relationships")
def list_relationships(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return [relationship_out(r) for r in db.query(m.Relationship).filter_by(workspace_id=ws.id)]


def _rel_stats(ws: m.Workspace, a: m.Dataset, ac: str, b: m.Dataset, bc: str) -> dict:
    with get_engine().connect() as conn:
        total, matched = conn.execute(text(
            f"SELECT count(a.{q(ac)}), count(a.{q(ac)}) FILTER (WHERE EXISTS (SELECT 1 FROM {q(ws.schema_name)}.{q(b.slug)} b WHERE b.{q(bc)} = a.{q(ac)})) "
            f"FROM {q(ws.schema_name)}.{q(a.slug)} a")).one()
        n, nd = conn.execute(text(f"SELECT count({q(bc)}), count(DISTINCT {q(bc)}) FROM {q(ws.schema_name)}.{q(b.slug)}")).one()
    return {"from_values": total, "matched": matched, "match_rate": round(matched / total, 4) if total else 0,
            "lookup_unique": n == nd}


@router.post("/relationships", status_code=201)
def create_relationship(body: RelationshipIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    a, b = dataset_of(db, ws, body.from_dataset_id), dataset_of(db, ws, body.to_dataset_id)
    if a.id == b.id:
        raise HTTPException(400, "A relationship needs two different datasets")
    ca = next((c for c in a.columns if c.name == body.from_column), None)
    cb = next((c for c in b.columns if c.name == body.to_column), None)
    if not ca or not cb:
        raise HTTPException(400, "Unknown column")
    num = {"integer", "decimal"}
    if ca.data_type != cb.data_type and not (ca.data_type in num and cb.data_type in num):
        raise HTTPException(400, f"Column types differ ({ca.data_type} vs {cb.data_type}); change one type first")
    if db.query(m.Relationship).filter_by(workspace_id=ws.id, from_dataset_id=a.id, to_dataset_id=b.id).first():
        raise HTTPException(400, "These datasets are already related; only one path per pair is allowed")
    stats = _rel_stats(ws, a, ca.name, b, cb.name)
    if not stats["lookup_unique"]:
        raise HTTPException(400, f"'{cb.display_name}' in {b.name} has duplicate values, so it cannot be a lookup key "
                                 f"(it would double-count). Remove duplicates or choose a unique column.")
    r = m.Relationship(workspace_id=ws.id, from_dataset_id=a.id, from_column=ca.name, to_dataset_id=b.id, to_column=cb.name)
    db.add(r)
    db.commit()
    return relationship_out(r) | {"stats": stats}


@router.delete("/relationships/{rel_id}", status_code=204)
def delete_relationship(rel_id: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    r = db.get(m.Relationship, rel_id)
    if not r or r.workspace_id != ws.id:
        raise HTTPException(404, "Relationship not found")
    db.delete(r)
    db.commit()


@router.get("/relationships/suggestions")
def suggest_relationships(ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    """Suggest lookups by matching column names (x_id -> x.id / same name) where the target column is unique."""
    from ..services.nlq.vocab import norm_word

    dss = db.query(m.Dataset).filter_by(workspace_id=ws.id).all()
    existing = {(r.from_dataset_id, r.to_dataset_id) for r in db.query(m.Relationship).filter_by(workspace_id=ws.id)}
    out = []
    for a in dss:
        for ca in a.columns:
            if ca.data_type not in ("integer", "text") or ca.is_derived:
                continue
            for b in dss:
                if a.id == b.id or (a.id, b.id) in existing or (b.id, a.id) in existing:
                    continue
                entity = norm_word(b.slug.split("_")[-1])
                for cb in b.columns:
                    if cb.data_type != ca.data_type:
                        continue
                    name_match = ca.name == cb.name and (ca.name.endswith("_id") or ca.name.endswith("_code") or ca.name in ("sku",))
                    id_match = cb.name in ("id", "code") and ca.name in (f"{entity}_id", f"{entity}_{cb.name}")
                    if not (name_match or id_match):
                        continue
                    try:
                        st = _rel_stats(ws, a, ca.name, b, cb.name)
                    except Exception:
                        continue
                    if st["lookup_unique"] and st["match_rate"] > 0.5:
                        out.append({"from_dataset_id": a.id, "from_dataset": a.name, "from_column": ca.name,
                                    "to_dataset_id": b.id, "to_dataset": b.name, "to_column": cb.name, **st})
    return sorted(out, key=lambda x: -x["match_rate"])


# ----------------------------------------------------------------------------------------------- lineage

@router.get("/lineage")
def lineage(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return dsvc.lineage(db, ws)


# ----------------------------------------------------------------------------------------------- connectors

class ConnectorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str
    config: dict = Field(default_factory=dict)


@router.get("/connector-kinds")
def connector_kinds(ws: m.Workspace = Depends(viewer)):
    return [{"kind": k, "label": c.label} for k, c in REGISTRY.items()]


@router.get("/connectors")
def list_connectors(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return [connector_out(c) for c in db.query(m.Connector).filter_by(workspace_id=ws.id)]


@router.post("/connectors", status_code=201)
def create_connector(body: ConnectorIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    try:
        cfg = sanitize_config(body.kind, body.config)
    except ConnectorError as e:
        raise _err(e)
    c = m.Connector(workspace_id=ws.id, name=body.name, kind=body.kind, config=cfg)
    db.add(c)
    db.commit()
    return connector_out(c)


def _connector(db, ws, cid) -> m.Connector:
    c = db.get(m.Connector, cid)
    if not c or c.workspace_id != ws.id:
        raise HTTPException(404, "Connector not found")
    return c


@router.delete("/connectors/{cid}", status_code=204)
def delete_connector(cid: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    db.delete(_connector(db, ws, cid))
    db.commit()


@router.post("/connectors/{cid}/test")
def test_connector(cid: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    c = _connector(db, ws, cid)
    try:
        res = test_connection(c)
    except ConnectorError as e:
        raise _err(e)
    db.commit()
    return res


@router.get("/connectors/{cid}/tables")
def connector_tables(cid: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    try:
        return get_connector(_connector(db, ws, cid)).list_tables()
    except ConnectorError as e:
        raise _err(e)
    except Exception as e:
        raise HTTPException(400, f"Could not list tables: {str(getattr(e, 'orig', e)).splitlines()[0]}")


@router.get("/connectors/{cid}/preview")
def connector_preview(cid: int, table: str, schema: str | None = None, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    try:
        df = get_connector(_connector(db, ws, cid)).read_table(schema, table, limit=50)
    except ConnectorError as e:
        raise _err(e)
    except Exception as e:
        raise HTTPException(400, f"Could not read table: {str(getattr(e, 'orig', e)).splitlines()[0]}")
    return {"columns": [str(c) for c in df.columns], "rows": [[to_jsonable(v) for v in r] for r in df.itertuples(index=False)]}


class ConnectorImportIn(BaseModel):
    tables: list[dict]  # [{schema, table, name?}]
    refresh_minutes: int | None = None


@router.post("/connectors/{cid}/import", status_code=201)
def connector_import(cid: int, body: ConnectorImportIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    c = _connector(db, ws, cid)
    conn = get_connector(c)
    created = []
    for t in body.tables:
        try:
            df = conn.read_table(t.get("schema"), t["table"])
        except ConnectorError as e:
            raise _err(e)
        except Exception as e:
            raise HTTPException(400, f"Could not read {t['table']}: {str(getattr(e, 'orig', e)).splitlines()[0]}")
        info = {"connector_id": c.id, "connector_name": c.name, "source_schema": t.get("schema"), "source_table": t["table"]}
        try:
            types = conn.column_types(t.get("schema"), t["table"])
        except Exception:  # some drivers cannot reflect views; fall back to inference
            types = None
        ds = dsvc.import_dataframe(db, ws, t.get("name") or t["table"], df, "connector", info, source_types=types)
        if body.refresh_minutes:
            db.add(m.RefreshSchedule(workspace_id=ws.id, dataset_id=ds.id, interval_minutes=max(5, body.refresh_minutes),
                                     last_run_at=datetime.now().astimezone()))
            db.commit()
        created.append(dataset_out(ds, full=False))
    return created


@router.post("/datasets/{ds_id}/sync")
def sync(ds_id: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    ds = dataset_of(db, ws, ds_id)
    if ds.kind != "connector":
        raise HTTPException(400, "Only database-connected datasets can be synced; use Replace data for files")
    try:
        res = sync_dataset(db, ws, ds)
    except ConnectorError as e:
        raise _err(e)
    return res | {"dataset": dataset_out(ds)}


class ScheduleIn(BaseModel):
    interval_minutes: int = Field(ge=5, le=60 * 24 * 7)
    enabled: bool = True


@router.put("/datasets/{ds_id}/schedule")
def set_schedule(ds_id: int, body: ScheduleIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    ds = dataset_of(db, ws, ds_id)
    if ds.kind != "connector":
        raise HTTPException(400, "Schedules apply to database-connected datasets")
    s = db.query(m.RefreshSchedule).filter_by(dataset_id=ds.id).first()
    if not s:
        s = m.RefreshSchedule(workspace_id=ws.id, dataset_id=ds.id)
        db.add(s)
    s.interval_minutes, s.enabled = body.interval_minutes, body.enabled
    db.commit()
    return {"interval_minutes": s.interval_minutes, "enabled": s.enabled, "last_run_at": iso(s.last_run_at), "last_status": s.last_status}


@router.get("/schedules")
def schedules(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return [{"id": s.id, "dataset_id": s.dataset_id, "interval_minutes": s.interval_minutes, "enabled": s.enabled,
             "last_run_at": iso(s.last_run_at), "last_status": s.last_status}
            for s in db.query(m.RefreshSchedule).filter_by(workspace_id=ws.id)]
