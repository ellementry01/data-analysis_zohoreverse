"""Workspace & dataset lifecycle: create, import, refresh, derive, query tables, profiling, lineage."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..db import get_engine
from . import warehouse as wh
from .expressions import ExpressionError, validate_expression
from .ingest import IngestError, Sheet, build_frame, preview_sheet, read_grids
from .naming import humanize, is_ident, q, slugify
from .sql_safety import UnsafeSQLError, referenced_tables, validate_select
from .typeinfer import DATA_TYPES


class DatasetError(ValueError):
    pass


# ----------------------------------------------------------------------------------------------- workspaces

def create_workspace(db: Session, name: str, description: str, user: str) -> m.Workspace:
    ws = m.Workspace(name=name.strip() or "Untitled workspace", description=description, created_by=user,
                     schema_name=f"ws_{uuid.uuid4().hex[:12]}")
    ws.members.append(m.WorkspaceMember(user_email=user, role="admin"))
    db.add(ws)
    db.flush()
    with get_engine().begin() as conn:
        wh.ensure_schema(conn, ws.schema_name)
    db.commit()
    return ws


def delete_workspace(db: Session, ws: m.Workspace) -> None:
    schema = ws.schema_name
    db.delete(ws)
    db.commit()
    with get_engine().begin() as conn:
        wh.drop_schema(conn, schema)


# ----------------------------------------------------------------------------------------------- uploads

def save_upload(filename: str, data: bytes) -> dict:
    settings = get_settings()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise IngestError(f"File is larger than {settings.max_upload_mb} MB")
    os.makedirs(settings.upload_dir, exist_ok=True)
    upload_id = uuid.uuid4().hex
    safe = os.path.basename(filename).replace("..", "_")
    path = os.path.join(settings.upload_dir, f"{upload_id}__{safe}")
    with open(path, "wb") as f:
        f.write(data)
    sheets = read_grids(path, safe)
    meta = {"upload_id": upload_id, "filename": safe, "path": path, "sheets": [s.name for s in sheets]}
    with open(path + ".json", "w") as f:
        json.dump(meta, f)
    return meta


def _upload(upload_id: str) -> dict:
    settings = get_settings()
    if not upload_id or not all(c in "0123456789abcdef" for c in upload_id):
        raise IngestError("Invalid upload id")
    for fn in os.listdir(settings.upload_dir):
        if fn.startswith(upload_id + "__") and fn.endswith(".json"):
            return json.load(open(os.path.join(settings.upload_dir, fn)))
    raise IngestError("Upload not found; please upload the file again")


def _sheet(upload_id: str, sheet: str | None) -> tuple[dict, Sheet]:
    meta = _upload(upload_id)
    sheets = read_grids(meta["path"], meta["filename"])
    if sheet is None:
        return meta, sheets[0]
    for s in sheets:
        if s.name == sheet:
            return meta, s
    raise IngestError(f"Sheet '{sheet}' not found")


def preview_upload(upload_id: str, sheet: str | None, header_row: int | None) -> dict:
    meta, s = _sheet(upload_id, sheet)
    return {"upload_id": upload_id, "filename": meta["filename"], "sheets": meta["sheets"], **preview_sheet(s, header_row)}


def _unique_slug(db: Session, workspace_id: int, name: str) -> str:
    base = slugify(name, "t")[:50]
    slug, i = base, 2
    existing = {d.slug for d in db.query(m.Dataset.slug).filter_by(workspace_id=workspace_id)}
    while slug in existing:
        slug = f"{base}_{i}"
        i += 1
    return slug


def _detect_default_date(ds: m.Dataset) -> str | None:
    dates = [c for c in ds.columns if c.data_type in ("date", "datetime")]
    if not dates:
        return None
    pri = ("order_date", "date", "sale_date", "transaction_date", "invoice_date", "created_at", "snapshot_date")
    for p in pri:
        for c in dates:
            if c.name == p:
                return c.name
    for c in dates:
        if "date" in c.name:
            return c.name
    return dates[0].name


def import_upload(db: Session, ws: m.Workspace, req: dict) -> tuple[m.Dataset, dict]:
    """req: upload_id, sheet, header_row, name, columns[{source_name,name,display_name,data_type,include}],
    mode new|append|replace, dataset_id (append/replace), options{drop_duplicates}"""
    meta, sheet = _sheet(req["upload_id"], req.get("sheet"))
    header_row = int(req.get("header_row") or 0)
    mode = req.get("mode", "new")
    specs = req.get("columns")
    if not specs:
        prev = preview_sheet(sheet, header_row)
        specs = [{"source_name": c["source_name"], "name": c["name"], "display_name": c["display_name"],
                  "data_type": c["inferred_type"], "include": True} for c in prev["columns"]]
    for s in specs:
        s.setdefault("include", True)
        if s.get("include"):
            if not is_ident(s.get("name", "")):
                s["name"] = slugify(s.get("name") or s["source_name"])
            if s.get("data_type") not in DATA_TYPES:
                raise DatasetError(f"Invalid type for column {s['source_name']}")
    included = [s for s in specs if s.get("include")]
    if not included:
        raise DatasetError("Select at least one column to import")
    if len({s["name"] for s in included}) != len(included):
        raise DatasetError("Column names must be unique")

    df, clean_report = build_frame(sheet, header_row, specs, req.get("options") or {})
    engine = get_engine()

    if mode == "new":
        name = (req.get("name") or os.path.splitext(meta["filename"])[0]).strip()
        if len(meta["sheets"]) > 1 and not req.get("name"):
            name = f"{name} - {sheet.name}"
        ds = m.Dataset(workspace_id=ws.id, name=name, slug=_unique_slug(db, ws.id, name), kind="file",
                       source_info={"filename": meta["filename"], "sheet": sheet.name, "header_row": header_row,
                                    "column_map": {s["source_name"]: s["name"] for s in included}})
        for i, s in enumerate(included):
            ds.columns.append(m.DatasetColumn(name=s["name"], display_name=s.get("display_name") or humanize(s["name"]),
                                              data_type=s["data_type"], position=i, source_name=s["source_name"]))
        db.add(ds)
        db.flush()
        load_mode = "create"
    else:
        ds = db.get(m.Dataset, int(req.get("dataset_id") or 0))
        if not ds or ds.workspace_id != ws.id:
            raise DatasetError("Target dataset not found")
        if ds.kind == "query_table":
            raise DatasetError("Query tables cannot receive imported rows")
        existing = {c.name: c for c in ds.columns}
        pos = len(ds.columns)
        for s in included:  # new columns in the file are added
            if s["name"] not in existing:
                ds.columns.append(m.DatasetColumn(name=s["name"], display_name=s.get("display_name") or humanize(s["name"]),
                                                  data_type=s["data_type"], position=pos, source_name=s["source_name"]))
                pos += 1
        ds.source_info = {**(ds.source_info or {}), "filename": meta["filename"], "sheet": sheet.name, "header_row": header_row}
        load_mode = mode
        missing = [c.display_name for c in ds.columns if not c.is_derived and c.name not in df.columns]
        if missing:
            clean_report["missing_columns"] = missing

    with engine.begin() as conn:
        wh.ensure_schema(conn, ws.schema_name)
        load_report = wh.load_dataframe(db, conn, ws.schema_name, ds, df, load_mode)
        if load_mode in ("create", "replace"):
            msgs = wh.apply_transforms(conn, ws.schema_name, ds) if load_mode == "replace" else []
            load_report["transform_messages"] = msgs
        wh.rebuild_view(db, conn, ws.schema_name, ds)
        if load_mode == "replace":
            wh.rebuild_query_tables(db, conn, ws.schema_name, ws.id)
        wh.refresh_stats(conn, ws.schema_name, ds)
    ds.default_date_column = ds.default_date_column or _detect_default_date(ds)
    ds.last_refreshed_at = datetime.now(timezone.utc)
    ds.quality = compute_quality(ws, ds)
    db.commit()
    return ds, {**clean_report, **load_report}


def import_dataframe(db: Session, ws: m.Workspace, name: str, df: pd.DataFrame, kind: str, source_info: dict,
                     dataset: m.Dataset | None = None, source_types: dict[str, str] | None = None) -> m.Dataset:
    """Used by database connectors: load an already-typed DataFrame as a new dataset or replace one.
    `source_types` (column -> Ellementry type, from the source schema) wins over inference, which is unreliable
    for empty or sparse tables."""
    from .ingest import profile

    headers = [str(c) for c in df.columns]
    source_types = source_types or {}
    if dataset is None:
        prof = profile(df.rename(columns=dict(zip(df.columns, headers))), headers)
        ds = m.Dataset(workspace_id=ws.id, name=name, slug=_unique_slug(db, ws.id, name), kind=kind, source_info=source_info)
        for i, (h, c) in enumerate(zip(headers, prof["columns"])):
            dtype = source_types.get(h) or _pd_type(df[h], c["inferred_type"])
            ds.columns.append(m.DatasetColumn(name=c["name"], display_name=humanize(h), data_type=dtype,
                                              position=i, source_name=h))
        db.add(ds)
        db.flush()
        mode = "create"
    else:
        ds, mode = dataset, "replace"
        known = {c.source_name for c in ds.columns if c.source_name}
        new = [h for h in headers if h not in known]
        if new:  # the source gained columns (e.g. a warehouse view was extended): add them, as file imports do
            prof = profile(df[new].rename(columns=dict(zip(df[new].columns, new))), new)
            taken, pos = {c.name for c in ds.columns}, len(ds.columns)
            for h, c in zip(new, prof["columns"]):
                name, n = c["name"], 2
                while name in taken:
                    name, n = f"{c['name']}_{n}", n + 1
                taken.add(name)
                ds.columns.append(m.DatasetColumn(name=name, display_name=humanize(h),
                                                  data_type=source_types.get(h) or _pd_type(df[h], c["inferred_type"]),
                                                  position=pos, source_name=h))
                pos += 1
            db.flush()
    src_to_name = {c.source_name: c.name for c in ds.columns if c.source_name}
    frame = df.rename(columns={h: src_to_name.get(h, h) for h in headers})
    with get_engine().begin() as conn:
        wh.ensure_schema(conn, ws.schema_name)
        wh.load_dataframe(db, conn, ws.schema_name, ds, frame, mode)
        if mode == "replace":
            wh.apply_transforms(conn, ws.schema_name, ds)
        wh.rebuild_view(db, conn, ws.schema_name, ds)
        if mode == "replace":
            wh.rebuild_query_tables(db, conn, ws.schema_name, ws.id)
        wh.refresh_stats(conn, ws.schema_name, ds)
    ds.default_date_column = ds.default_date_column or _detect_default_date(ds)
    ds.last_refreshed_at = datetime.now(timezone.utc)
    ds.quality = compute_quality(ws, ds)
    db.commit()
    return ds


def _pd_type(s: pd.Series, inferred: str) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_integer_dtype(s):
        return "integer"
    if pd.api.types.is_float_dtype(s):
        return "decimal"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    return inferred


# ----------------------------------------------------------------------------------------------- column ops

def update_column(db: Session, ws: m.Workspace, ds: m.Dataset, name: str, changes: dict) -> m.DatasetColumn:
    col = next((c for c in ds.columns if c.name == name), None)
    if not col:
        raise DatasetError(f"Column '{name}' not found")
    if "display_name" in changes and changes["display_name"]:
        col.display_name = changes["display_name"].strip()[:200]
    if "description" in changes:
        col.description = changes["description"] or ""
    if "hidden" in changes:
        col.hidden = bool(changes["hidden"])
    if changes.get("data_type") and changes["data_type"] != col.data_type:
        if col.is_derived:
            raise DatasetError("Change the formula to change a derived column's type")
        apply_transform_step(db, ws, ds, "cast_type", {"column": name, "to": changes["data_type"]})
    if changes.get("expression") and col.is_derived:
        _set_derived(db, ws, ds, col, changes["expression"], changes.get("data_type") or col.data_type)
    db.commit()
    return col


def add_derived_column(db: Session, ws: m.Workspace, ds: m.Dataset, display_name: str, expression: str, data_type: str) -> m.DatasetColumn:
    if ds.kind == "query_table":
        raise DatasetError("Add calculated columns to the query table's SQL instead")
    if data_type not in DATA_TYPES:
        raise DatasetError("Invalid data type")
    name = slugify(display_name)
    if any(c.name == name for c in ds.columns):
        raise DatasetError(f"A column named '{name}' already exists")
    col = m.DatasetColumn(name=name, display_name=display_name, data_type=data_type, position=len(ds.columns), is_derived=True)
    ds.columns.append(col)
    _set_derived(db, ws, ds, col, expression, data_type)
    db.commit()
    return col


def _set_derived(db: Session, ws: m.Workspace, ds: m.Dataset, col: m.DatasetColumn, expression: str, data_type: str) -> None:
    from .typeinfer import PG_TYPES

    physical = {c.name for c in ds.columns if not c.is_derived}
    try:
        expr = validate_expression(expression, physical)
    except ExpressionError as e:
        raise DatasetError(str(e)) from e
    col.expression = f"CAST(({expr}) AS {PG_TYPES[data_type]})"
    col.data_type = data_type
    with get_engine().begin() as conn:
        sp = conn.begin_nested()
        try:
            wh.rebuild_view(db, conn, ws.schema_name, ds)
            conn.execute(text(f"SELECT {q(col.name)} FROM {q(ws.schema_name)}.{q(ds.slug)} LIMIT 50")).all()
            sp.commit()
        except Exception as e:
            sp.rollback()
            ds.columns.remove(col) if col.id is None else None
            raise DatasetError(f"Formula failed: {str(getattr(e, 'orig', e)).splitlines()[0]}") from e


def delete_column(db: Session, ws: m.Workspace, ds: m.Dataset, name: str) -> None:
    col = next((c for c in ds.columns if c.name == name), None)
    if not col:
        raise DatasetError(f"Column '{name}' not found")
    if col.is_derived:
        ds.columns.remove(col)
        with get_engine().begin() as conn:
            wh.rebuild_view(db, conn, ws.schema_name, ds)
        db.commit()
    else:
        apply_transform_step(db, ws, ds, "drop_column", {"column": name})


def apply_transform_step(db: Session, ws: m.Workspace, ds: m.Dataset, kind: str, params: dict) -> str:
    from .transforms import TransformError, apply_transform

    if ds.kind == "query_table":
        raise DatasetError("Transforms apply to imported datasets; edit the SQL of a query table instead")
    with get_engine().begin() as conn:
        try:
            msg = apply_transform(conn, ws.schema_name, ds, kind, params)
        except (TransformError, KeyError) as e:
            raise DatasetError(str(e)) from e
        except Exception as e:
            raise DatasetError(f"Step failed: {str(getattr(e, 'orig', e)).splitlines()[0]}") from e
        wh.rebuild_view(db, conn, ws.schema_name, ds)
        wh.refresh_stats(conn, ws.schema_name, ds)
    ds.transforms.append(m.Transform(kind=kind, params=params, position=len(ds.transforms), last_result=msg))
    ds.quality = compute_quality(ws, ds)
    db.commit()
    return msg


# ----------------------------------------------------------------------------------------------- query tables

def save_query_table(db: Session, ws: m.Workspace, name: str, sql: str, dataset: m.Dataset | None = None) -> m.Dataset:
    allowed = {d.slug for d in db.query(m.Dataset).filter_by(workspace_id=ws.id) if not dataset or d.id != dataset.id}
    try:
        clean = validate_select(sql, ws.schema_name, allowed)
    except UnsafeSQLError as e:
        raise DatasetError(str(e)) from e
    # qualify bare table names to the workspace schema so the view is independent of search_path
    import sqlglot
    from sqlglot import exp

    tree = sqlglot.parse_one(clean, read="postgres")
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if t.name not in ctes and not t.db:
            t.set("db", exp.to_identifier(ws.schema_name, quoted=True))
    clean = tree.sql(dialect="postgres")
    engine = get_engine()
    with engine.begin() as conn:
        try:
            res = conn.execute(text(f"SELECT * FROM ({clean}) _probe LIMIT 0"))
            cursor_desc = res.cursor.description
        except Exception as e:
            raise DatasetError(f"SQL error: {str(getattr(e, 'orig', e)).splitlines()[0]}") from e
    names = [d.name for d in cursor_desc]
    bad = [n for n in names if not is_ident(n)]
    if bad:
        raise DatasetError(f"Give every output column a simple lower_case alias (problem: {', '.join(bad[:3])})")
    if len(set(names)) != len(names):
        raise DatasetError("Output column names must be unique")
    oid_types = _column_types(cursor_desc)
    if dataset is None:
        ds = m.Dataset(workspace_id=ws.id, name=name, slug=_unique_slug(db, ws.id, name), kind="query_table")
        db.add(ds)
    else:
        ds = dataset
        ds.name = name or ds.name
        ds.columns.clear()
        db.flush()
    ds.query_sql = clean
    ds.source_info = {"depends_on": sorted(referenced_tables(clean) & allowed)}
    for i, n in enumerate(names):
        ds.columns.append(m.DatasetColumn(name=n, display_name=humanize(n), data_type=oid_types.get(n, "text"), position=i))
    db.flush()
    with engine.begin() as conn:
        conn.execute(text(f"DROP VIEW IF EXISTS {q(ws.schema_name)}.{q(ds.slug)} CASCADE"))
        wh.rebuild_view(db, conn, ws.schema_name, ds)
        wh.rebuild_query_tables(db, conn, ws.schema_name, ws.id)
        wh.refresh_stats(conn, ws.schema_name, ds)
    ds.default_date_column = _detect_default_date(ds)
    ds.last_refreshed_at = datetime.now(timezone.utc)
    db.commit()
    return ds


_OIDS = {16: "boolean", 20: "integer", 21: "integer", 23: "integer", 700: "decimal", 701: "decimal", 1700: "decimal",
         1082: "date", 1114: "datetime", 1184: "datetime"}


def _column_types(desc) -> dict[str, str]:
    return {d.name: _OIDS.get(d.type_code, "text") for d in desc}


def delete_dataset(db: Session, ws: m.Workspace, ds: m.Dataset) -> list[str]:
    dependants = [d.name for d in db.query(m.Dataset).filter_by(workspace_id=ws.id, kind="query_table")
                  if ds.slug in (d.source_info or {}).get("depends_on", [])]
    if dependants:
        raise DatasetError(f"Used by query table(s): {', '.join(dependants)}. Delete them first.")
    with get_engine().begin() as conn:
        conn.execute(text(f"DROP VIEW IF EXISTS {q(ws.schema_name)}.{q(ds.slug)} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {q(ws.schema_name)}.{q(wh.raw_table(ds.slug))} CASCADE"))
    db.query(m.Relationship).filter((m.Relationship.from_dataset_id == ds.id) | (m.Relationship.to_dataset_id == ds.id)).delete()
    db.delete(ds)
    db.commit()
    return []


# ----------------------------------------------------------------------------------------------- reading

def read_rows(ws: m.Workspace, ds: m.Dataset, page: int, page_size: int, search: str | None, sort: str | None,
              desc: bool, filters: list[dict] | None = None) -> dict:
    from .filters import build_condition

    cols = [c for c in ds.columns]
    names = {c.name: c for c in cols}
    where, params = [], {}
    if search:
        params["s"] = f"%{search}%"
        where.append("(" + " OR ".join(f"CAST({q(c.name)} AS TEXT) ILIKE :s" for c in cols) + ")")
    for i, f in enumerate(filters or []):
        c = names.get(f.get("column"))
        if c:
            where.append(build_condition(q(c.name), c.data_type, f, params, f"f{i}"))
    w = f" WHERE {' AND '.join(where)}" if where else ""
    order = f" ORDER BY {q(sort)} {'DESC' if desc else 'ASC'} NULLS LAST" if sort in names else ""
    page_size = max(1, min(page_size, 500))
    with get_engine().connect() as conn:
        total = conn.execute(text(f"SELECT count(*) FROM {q(ws.schema_name)}.{q(ds.slug)}{w}"), params).scalar()
        rows = conn.execute(text(f"SELECT {', '.join(q(c.name) for c in cols)} FROM {q(ws.schema_name)}.{q(ds.slug)}{w}{order} "
                                 f"LIMIT {page_size} OFFSET {max(0, page) * page_size}"), params).all()
    return {"total": total, "page": page, "page_size": page_size, "columns": [c.name for c in cols],
            "rows": [[wh.to_jsonable(v) for v in r] for r in rows]}


def profile_dataset(ws: m.Workspace, ds: m.Dataset) -> dict:
    tbl = f"{q(ws.schema_name)}.{q(ds.slug)}"
    out = []
    with get_engine().connect() as conn:
        total = conn.execute(text(f"SELECT count(*) FROM {tbl}")).scalar() or 0
        for c in ds.columns:
            col = q(c.name)
            stats = {"name": c.name, "label": c.display_name, "type": c.data_type}
            r = conn.execute(text(f"SELECT count({col}), count(DISTINCT {col}) FROM {tbl}")).one()
            stats.update(non_null=r[0], nulls=total - r[0], distinct=r[1], null_pct=round((total - r[0]) / total, 4) if total else 0)
            if c.data_type in ("integer", "decimal"):
                r = conn.execute(text(f"SELECT min({col}), max({col}), avg({col}), stddev({col}), "
                                      f"percentile_cont(0.5) WITHIN GROUP (ORDER BY {col}), sum({col}) FROM {tbl}")).one()
                stats.update({k: wh.to_jsonable(v) for k, v in zip(("min", "max", "mean", "stddev", "median", "sum"), r)})
                lo, hi = stats["min"], stats["max"]
                if lo is not None and hi is not None and hi > lo:
                    bins = conn.execute(text(f"SELECT width_bucket({col}, :lo, :hi, 10) b, count(*) FROM {tbl} WHERE {col} IS NOT NULL GROUP BY 1 ORDER BY 1"),
                                        {"lo": lo, "hi": hi + 1e-9}).all()
                    stats["histogram"] = [{"bucket": int(b), "count": n} for b, n in bins]
            elif c.data_type in ("date", "datetime"):
                r = conn.execute(text(f"SELECT min({col}), max({col}) FROM {tbl}")).one()
                stats.update(min=wh.to_jsonable(r[0]), max=wh.to_jsonable(r[1]))
            top = conn.execute(text(f"SELECT CAST({col} AS TEXT) v, count(*) n FROM {tbl} WHERE {col} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 8")).all()
            stats["top_values"] = [{"value": v, "count": n} for v, n in top]
            out.append(stats)
    return {"row_count": total, "columns": out}


def compute_quality(ws: m.Workspace, ds: m.Dataset) -> dict:
    """Data-quality warnings stored with the dataset (recomputed after import/transform)."""
    if ds.kind == "query_table":
        return {}
    tbl = f"{q(ws.schema_name)}.{q(ds.slug)}"
    warnings = []
    phys = [c for c in ds.columns if not c.is_derived]
    if not phys:
        return {"warnings": []}
    with get_engine().connect() as conn:
        total = conn.execute(text(f"SELECT count(*) FROM {tbl}")).scalar() or 0
        key = ", ".join(q(c.name) for c in phys)
        dup = conn.execute(text(f"SELECT coalesce(sum(n - 1), 0) FROM (SELECT count(*) n FROM {tbl} GROUP BY {key} HAVING count(*) > 1) d")).scalar()
        if dup:
            warnings.append({"level": "warning", "code": "duplicates", "message": f"{dup} duplicate rows", "count": int(dup)})
        for c in phys:
            nulls = conn.execute(text(f"SELECT count(*) FROM {tbl} WHERE {q(c.name)} IS NULL")).scalar()
            if total and nulls:
                lvl = "warning" if nulls / total > 0.2 else "info"
                warnings.append({"level": lvl, "code": "missing", "column": c.name,
                                 "message": f"{c.display_name}: {nulls} empty values ({nulls / total:.0%})", "count": int(nulls)})
            if c.data_type == "text":
                var = conn.execute(text(
                    f"SELECT lower(btrim({q(c.name)})) k, array_agg(DISTINCT {q(c.name)}) FROM {tbl} WHERE {q(c.name)} IS NOT NULL "
                    f"GROUP BY 1 HAVING count(DISTINCT {q(c.name)}) > 1 LIMIT 5")).all()
                if var:
                    ex = ", ".join(repr(v) for v in var[0][1][:3])
                    warnings.append({"level": "info", "code": "inconsistent_values", "column": c.name,
                                     "message": f"{c.display_name}: {len(var)}+ values spelled inconsistently (e.g. {ex})",
                                     "variants": {k: list(v) for k, v in var}})
            if c.data_type in ("integer", "decimal") and any(k in c.name for k in ("qty", "quantity", "price", "amount", "units")):
                neg = conn.execute(text(f"SELECT count(*) FROM {tbl} WHERE {q(c.name)} < 0")).scalar()
                if neg:
                    warnings.append({"level": "info", "code": "negative", "column": c.name,
                                     "message": f"{c.display_name}: {neg} negative values", "count": int(neg)})
    return {"row_count": total, "warnings": warnings, "checked_at": datetime.now(timezone.utc).isoformat()}


def lineage(db: Session, ws: m.Workspace) -> dict:
    nodes, edges = [], []
    datasets = db.query(m.Dataset).filter_by(workspace_id=ws.id).all()
    by_slug = {d.slug: d for d in datasets}
    for d in datasets:
        nodes.append({"id": f"ds{d.id}", "type": d.kind, "label": d.name, "dataset_id": d.id})
        src = d.source_info or {}
        if d.kind == "file":
            nodes.append({"id": f"file{d.id}", "type": "source", "label": f"{src.get('filename', 'file')}"
                          + (f" [{src.get('sheet')}]" if src.get("sheet") else "")})
            edges.append({"from": f"file{d.id}", "to": f"ds{d.id}", "label": f"import + {len(d.transforms)} prep steps"})
        if d.kind == "connector":
            nodes.append({"id": f"conn{d.id}", "type": "source", "label": f"{src.get('connector_name', 'database')}: {src.get('source_table')}"})
            edges.append({"from": f"conn{d.id}", "to": f"ds{d.id}", "label": "sync"})
        for dep in src.get("depends_on", []):
            if dep in by_slug:
                edges.append({"from": f"ds{by_slug[dep].id}", "to": f"ds{d.id}", "label": "SQL"})
    for r in db.query(m.Report).filter_by(workspace_id=ws.id):
        nodes.append({"id": f"rep{r.id}", "type": "report", "label": r.name})
        for slug in _spec_datasets(r.spec, db, ws):
            if slug in by_slug:
                edges.append({"from": f"ds{by_slug[slug].id}", "to": f"rep{r.id}", "label": ""})
    for dsh in db.query(m.Dashboard).filter_by(workspace_id=ws.id):
        nodes.append({"id": f"dash{dsh.id}", "type": "dashboard", "label": dsh.name})
        seen = set()
        for w in dsh.widgets:
            for slug in _spec_datasets(w.spec, db, ws):
                if slug in by_slug and slug not in seen:
                    seen.add(slug)
                    edges.append({"from": f"ds{by_slug[slug].id}", "to": f"dash{dsh.id}", "label": ""})
    return {"nodes": nodes, "edges": edges}


def _spec_datasets(spec: dict, db: Session, ws: m.Workspace) -> set[str]:
    out = set()
    for part in ("dimensions", "measures", "filters"):
        for item in (spec or {}).get(part, []) or []:
            f = item.get("field")
            if f and "." in f:
                out.add(f.split(".")[0])
            if item.get("metric"):
                mt = db.query(m.Metric).filter_by(workspace_id=ws.id, name=item["metric"]).first()
                if mt and mt.dataset_id:
                    d = db.get(m.Dataset, mt.dataset_id)
                    if d:
                        out.add(d.slug)
    return out
