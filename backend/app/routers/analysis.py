import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as m
from ..db import get_session
from ..deps import current_user, editor, viewer
from ..serializers import dashboard_out, glossary_out, iso, metric_out, report_out, rule_out, widget_out
from ..services.analytics import QueryExecutionError, QueryError, UnsafeSQLError, insights, run_spec, suggest_chart
from ..services.catalog import load_catalog
from ..services.executor import log_query, run_readonly
from ..services.expressions import ExpressionError, validate_expression
from ..services.filters import PRESETS
from ..services.naming import is_ident, slugify
from ..services.nlq import assistant
from ..services.nlq.vocab import is_id_column, label_column
from ..services.spec import Filter, QuerySpec
from ..services.sql_safety import validate_select
from .data import tabular_response

router = APIRouter(prefix="/api/workspaces/{ws_id}", tags=["analysis"])
CHART_TYPES = {"kpi", "line", "bar", "hbar", "stacked_bar", "area", "pie", "donut", "table", "pivot", "scatter", "heatmap", "combo"}


def _run(db, ws, spec: QuerySpec, user: str, source: str = "chart") -> dict:
    cat = load_catalog(db, ws)
    try:
        return run_spec(db, cat, spec, user, source=source)
    except (QueryError, UnsafeSQLError, QueryExecutionError, ValueError) as e:
        raise HTTPException(400, str(e))


# ----------------------------------------------------------------------------------------------- model / fields

@router.get("/model")
def model(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    """Everything a chart builder or assistant UI needs: datasets, fields, reachability, metrics, presets."""
    cat = load_catalog(db, ws)
    datasets = []
    for ds in cat.datasets.values():
        reach = [cat.datasets[i].slug for i in cat.parent_paths(ds.id) if i != ds.id]
        datasets.append({
            "id": ds.id, "slug": ds.slug, "name": ds.name, "kind": ds.kind, "row_count": ds.row_count,
            "default_date_column": ds.default_date, "label_column": label_column(ds), "lookups": reach,
            "fields": [{"ref": f"{ds.slug}.{c.name}", "name": c.name, "label": c.label, "type": c.type, "derived": c.derived,
                        "role": "measure" if c.type in ("integer", "decimal") and not is_id_column(c.name) else "dimension"}
                       for c in ds.columns.values()],
        })
    return {"datasets": datasets, "metrics": [metric_out(x) for x in cat.metrics.values()], "date_presets": PRESETS,
            "relationships": [{"from": f"{cat.datasets[e.from_ds].slug}.{e.from_col}", "to": f"{cat.datasets[e.to_ds].slug}.{e.to_col}"}
                              for e in cat.edges if e.from_ds in cat.datasets and e.to_ds in cat.datasets]}


@router.post("/query")
def query(spec: QuerySpec, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), user: str = Depends(current_user)):
    return _run(db, ws, spec, user)


@router.post("/query/export")
def query_export(spec: QuerySpec, format: str = Query("csv", pattern="^(csv|xlsx)$"), ws: m.Workspace = Depends(viewer),
                 db: Session = Depends(get_session), user: str = Depends(current_user)):
    res = _run(db, ws, spec, user)
    return tabular_response("report", [c["label"] for c in res["columns"]], res["rows"], format)


# ----------------------------------------------------------------------------------------------- reports

class ReportIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    chart_type: str = "bar"
    spec: QuerySpec
    options: dict = Field(default_factory=dict)


@router.get("/reports")
def list_reports(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return [report_out(r) for r in db.query(m.Report).filter_by(workspace_id=ws.id).order_by(m.Report.updated_at.desc())]


def _check_chart(ct: str):
    if ct not in CHART_TYPES:
        raise HTTPException(400, f"Unknown chart type {ct}")


@router.post("/reports", status_code=201)
def create_report(body: ReportIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session), user: str = Depends(current_user)):
    _check_chart(body.chart_type)
    _run(db, ws, body.spec, user)  # validates the spec against the current model
    r = m.Report(workspace_id=ws.id, name=body.name, description=body.description, chart_type=body.chart_type,
                 spec=body.spec.model_dump(), options=body.options)
    db.add(r)
    db.commit()
    return report_out(r)


def _report(db, ws, rid) -> m.Report:
    r = db.get(m.Report, rid)
    if not r or r.workspace_id != ws.id:
        raise HTTPException(404, "Report not found")
    return r


@router.get("/reports/{rid}")
def get_report(rid: int, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return report_out(_report(db, ws, rid))


@router.put("/reports/{rid}")
def update_report(rid: int, body: ReportIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session), user: str = Depends(current_user)):
    _check_chart(body.chart_type)
    r = _report(db, ws, rid)
    _run(db, ws, body.spec, user)
    r.name, r.description, r.chart_type, r.spec, r.options = body.name, body.description, body.chart_type, body.spec.model_dump(), body.options
    db.commit()
    return report_out(r)


@router.delete("/reports/{rid}", status_code=204)
def delete_report(rid: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    db.delete(_report(db, ws, rid))
    db.commit()


# ----------------------------------------------------------------------------------------------- dashboards

class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    filters: list[dict] = Field(default_factory=list)
    is_template: bool = False


class WidgetIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    chart_type: str = "bar"
    spec: QuerySpec | None = None
    report_id: int | None = None
    options: dict = Field(default_factory=dict)
    layout: dict = Field(default_factory=dict)


class LayoutItem(BaseModel):
    id: int
    x: int
    y: int
    w: int
    h: int


@router.get("/dashboards")
def list_dashboards(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return [dashboard_out(d, full=False) for d in db.query(m.Dashboard).filter_by(workspace_id=ws.id).order_by(m.Dashboard.updated_at.desc())]


@router.post("/dashboards", status_code=201)
def create_dashboard(body: DashboardIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    d = m.Dashboard(workspace_id=ws.id, name=body.name, description=body.description, filters=_clean_filters(body.filters),
                    is_template=body.is_template)
    db.add(d)
    db.commit()
    return dashboard_out(d)


def _dashboard(db, ws, did) -> m.Dashboard:
    d = db.get(m.Dashboard, did)
    if not d or d.workspace_id != ws.id:
        raise HTTPException(404, "Dashboard not found")
    return d


def _clean_filters(filters: list[dict]) -> list[dict]:
    out = []
    for i, f in enumerate(filters):
        if f.get("type") not in ("date_range", "values"):
            raise HTTPException(400, "Dashboard filters must be of type date_range or values")
        out.append({"id": f.get("id") or f"f{i}", "type": f["type"], "label": f.get("label") or f.get("field", ""),
                    "field": f.get("field") or "@time", "value": f.get("value")})
    return out


@router.get("/dashboards/{did}")
def get_dashboard(did: int, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return dashboard_out(_dashboard(db, ws, did))


@router.put("/dashboards/{did}")
def update_dashboard(did: int, body: DashboardIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    d = _dashboard(db, ws, did)
    d.name, d.description, d.filters, d.is_template = body.name, body.description, _clean_filters(body.filters), body.is_template
    db.commit()
    return dashboard_out(d)


@router.delete("/dashboards/{did}", status_code=204)
def delete_dashboard(did: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    db.delete(_dashboard(db, ws, did))
    db.commit()


@router.post("/dashboards/{did}/widgets", status_code=201)
def add_widget(did: int, body: WidgetIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session), user: str = Depends(current_user)):
    d = _dashboard(db, ws, did)
    _check_chart(body.chart_type)
    spec = body.spec
    if body.report_id:
        r = _report(db, ws, body.report_id)
        spec = QuerySpec.model_validate(r.spec)
    if spec is None:
        raise HTTPException(400, "A widget needs a spec or a report")
    _run(db, ws, spec, user)
    bottom = max([(w.layout or {}).get("y", 0) + (w.layout or {}).get("h", 4) for w in d.widgets] or [0])
    layout = body.layout or {"x": 0, "y": bottom, "w": 3 if body.chart_type == "kpi" else 6, "h": 2 if body.chart_type == "kpi" else 4}
    w = m.DashboardWidget(title=body.title, chart_type=body.chart_type, spec=spec.model_dump(), options=body.options,
                          layout=layout, report_id=body.report_id)
    d.widgets.append(w)
    db.commit()
    return widget_out(w)


@router.put("/dashboards/{did}/widgets/{wid}")
def update_widget(did: int, wid: int, body: WidgetIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session), user: str = Depends(current_user)):
    d = _dashboard(db, ws, did)
    w = next((x for x in d.widgets if x.id == wid), None)
    if not w:
        raise HTTPException(404, "Widget not found")
    _check_chart(body.chart_type)
    if body.spec:
        _run(db, ws, body.spec, user)
        w.spec = body.spec.model_dump()
    w.title, w.chart_type, w.options = body.title, body.chart_type, body.options
    if body.layout:
        w.layout = body.layout
    db.commit()
    return widget_out(w)


@router.delete("/dashboards/{did}/widgets/{wid}", status_code=204)
def delete_widget(did: int, wid: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    d = _dashboard(db, ws, did)
    w = next((x for x in d.widgets if x.id == wid), None)
    if not w:
        raise HTTPException(404, "Widget not found")
    d.widgets.remove(w)
    db.commit()


@router.put("/dashboards/{did}/layout")
def save_layout(did: int, items: list[LayoutItem], ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    d = _dashboard(db, ws, did)
    by_id = {w.id: w for w in d.widgets}
    for it in items:
        if it.id in by_id:
            by_id[it.id].layout = {"x": it.x, "y": it.y, "w": it.w, "h": it.h}
    db.commit()
    return dashboard_out(d)


class WidgetRunIn(BaseModel):
    filters: list[dict] = Field(default_factory=list)  # [{field, type, value}] current dashboard filter values
    drill: list[Filter] = Field(default_factory=list)
    drill_dimension: dict | None = None
    compare: str | None = None


def apply_dashboard_filters(spec: QuerySpec, filters: list[dict]) -> QuerySpec:
    spec = spec.model_copy(deep=True)
    for f in filters:
        v = f.get("value")
        if v in (None, "", []) or v == {}:
            continue
        if f.get("type") == "date_range":
            spec.time_range = v
            if f.get("field") and f["field"] != "@time":
                spec.time_field = f["field"]
        elif f.get("type") == "values":
            vals = v if isinstance(v, list) else [v]
            spec.filters = [x for x in spec.filters if x.field != f["field"]] + [Filter(field=f["field"], op="in", value=vals)]
    return spec


@router.post("/dashboards/{did}/widgets/{wid}/data")
def widget_data(did: int, wid: int, body: WidgetRunIn, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session),
                user: str = Depends(current_user)):
    d = _dashboard(db, ws, did)
    w = next((x for x in d.widgets if x.id == wid), None)
    if not w:
        raise HTTPException(404, "Widget not found")
    spec = apply_dashboard_filters(QuerySpec.model_validate(w.spec), body.filters)
    if body.drill:
        spec.filters = spec.filters + body.drill
    if body.drill_dimension:
        from ..services.spec import Dimension
        spec.dimensions = [Dimension.model_validate(body.drill_dimension)]
        spec.sort, spec.limit = [], None
    if body.compare in ("previous_period", "previous_year"):
        spec.compare = body.compare
    return _run(db, ws, spec, user, source="dashboard") | {"applied_spec": spec.model_dump()}


@router.post("/dashboards/{did}/duplicate", status_code=201)
def duplicate_dashboard(did: int, name: str | None = None, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    """Also used to create a dashboard from a template."""
    src = _dashboard(db, ws, did)
    d = m.Dashboard(workspace_id=ws.id, name=name or f"{src.name} (copy)", description=src.description,
                    filters=src.filters, is_template=False)
    for w in src.widgets:
        d.widgets.append(m.DashboardWidget(title=w.title, chart_type=w.chart_type, spec=w.spec, options=w.options,
                                           layout=w.layout, report_id=w.report_id))
    db.add(d)
    db.commit()
    return dashboard_out(d)


@router.get("/dashboards/{did}/values")
def filter_values(did: int, field: str, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), user: str = Depends(current_user)):
    """Distinct values for a dashboard 'values' filter."""
    from ..services.spec import Dimension
    res = _run(db, ws, QuerySpec(dimensions=[Dimension(field=field)], limit=500), user, source="dashboard")
    return [r[0] for r in res["rows"] if r[0] is not None]


# ----------------------------------------------------------------------------------------------- SQL console

class SqlIn(BaseModel):
    sql: str = Field(min_length=1, max_length=20000)


@router.post("/sql")
def run_sql(body: SqlIn, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), user: str = Depends(current_user)):
    cat = load_catalog(db, ws)
    try:
        safe = validate_select(body.sql, ws.schema_name, {d.slug for d in cat.datasets.values()})
    except UnsafeSQLError as e:
        log_query(db, ws.id, user, "sql", body.sql, "rejected", str(e))
        raise HTTPException(400, str(e))
    try:
        res = run_readonly(safe, {}, ws.schema_name)
    except QueryExecutionError as e:
        log_query(db, ws.id, user, "sql", safe, "error", str(e))
        raise HTTPException(400, str(e))
    log_query(db, ws.id, user, "sql", safe, "ok", duration_ms=res.duration_ms, row_count=res.row_count)
    cols = assistant._infer_columns(res.columns, res.rows)
    return {"columns": cols, "rows": res.rows, "row_count": res.row_count, "truncated": res.truncated,
            "duration_ms": res.duration_ms, "sql": safe, "suggested_chart": suggest_chart(cols, res.rows),
            "insights": insights(cols, res.rows)}


class SavedQueryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sql: str = Field(min_length=1, max_length=20000)
    description: str = ""


@router.get("/saved-queries")
def saved_queries(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return [{"id": s.id, "name": s.name, "sql": s.sql, "description": s.description, "created_at": iso(s.created_at)}
            for s in db.query(m.SavedQuery).filter_by(workspace_id=ws.id).order_by(m.SavedQuery.id.desc())]


@router.post("/saved-queries", status_code=201)
def save_query(body: SavedQueryIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    cat = load_catalog(db, ws)
    try:
        validate_select(body.sql, ws.schema_name, {d.slug for d in cat.datasets.values()})
    except UnsafeSQLError as e:
        raise HTTPException(400, str(e))
    s = m.SavedQuery(workspace_id=ws.id, name=body.name, sql=body.sql, description=body.description)
    db.add(s)
    db.commit()
    return {"id": s.id, "name": s.name, "sql": s.sql, "description": s.description, "created_at": iso(s.created_at)}


@router.delete("/saved-queries/{sid}", status_code=204)
def delete_saved_query(sid: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    s = db.get(m.SavedQuery, sid)
    if not s or s.workspace_id != ws.id:
        raise HTTPException(404, "Not found")
    db.delete(s)
    db.commit()


# ----------------------------------------------------------------------------------------------- semantic layer

class MetricIn(BaseModel):
    name: str = Field(min_length=1, max_length=63)
    label: str = Field(min_length=1, max_length=200)
    description: str = ""
    kind: str = Field("simple", pattern="^(simple|composite)$")
    dataset_id: int | None = None
    expression: str = Field(min_length=1, max_length=4000)
    filters: list[dict] = Field(default_factory=list)
    time_column: str | None = None
    semi_additive: bool = False
    synonyms: list[str] = Field(default_factory=list)
    format: str = Field("number", pattern="^(number|currency|percent)$")
    higher_is_better: bool = True


def _validate_metric(db, ws, body: MetricIn) -> None:
    if not is_ident(body.name):
        raise HTTPException(400, "Metric name must be lower_snake_case")
    if body.kind == "simple":
        ds = db.get(m.Dataset, body.dataset_id or 0)
        if not ds or ds.workspace_id != ws.id:
            raise HTTPException(400, "Choose the dataset this metric is calculated on")
        cols = {c.name: c for c in ds.columns}
        try:
            validate_expression(body.expression, set(cols), allow_aggregates=True)
        except ExpressionError as e:
            raise HTTPException(400, str(e))
        for f in body.filters:
            if f.get("column") not in cols:
                raise HTTPException(400, f"Filter column '{f.get('column')}' is not in {ds.name}")
        if body.time_column and (body.time_column not in cols or cols[body.time_column].data_type not in ("date", "datetime")):
            raise HTTPException(400, "Time column must be a date column of the dataset")
        if body.semi_additive and not (body.time_column or ds.default_date_column):
            raise HTTPException(400, "Semi-additive metrics need a date column")
    else:
        refs = re.findall(r"\{([a-z_][a-z0-9_]*)\}", body.expression)
        if not refs:
            raise HTTPException(400, "A composite metric combines other metrics, e.g. {returned_units} / NULLIF({units_sold}, 0)")
        existing = {x.name for x in db.query(m.Metric).filter_by(workspace_id=ws.id)}
        missing = [r for r in refs if r not in existing]
        if missing or body.name in refs:
            raise HTTPException(400, f"Unknown metric(s): {', '.join(missing) or body.name}")


@router.get("/metrics")
def list_metrics(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return [metric_out(x) for x in db.query(m.Metric).filter_by(workspace_id=ws.id).order_by(m.Metric.label)]


@router.post("/metrics", status_code=201)
def create_metric(body: MetricIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session), user: str = Depends(current_user)):
    _validate_metric(db, ws, body)
    if db.query(m.Metric).filter_by(workspace_id=ws.id, name=body.name).first():
        raise HTTPException(400, "A metric with this name exists")
    x = m.Metric(workspace_id=ws.id, **body.model_dump())
    if x.kind == "composite":
        x.dataset_id = None
    db.add(x)
    db.flush()
    try:
        run_spec(db, load_catalog(db, ws), QuerySpec(measures=[{"metric": x.name}]), user)
    except (QueryError, QueryExecutionError, UnsafeSQLError) as e:
        db.rollback()
        raise HTTPException(400, f"Metric does not compute: {e}")
    db.commit()
    return metric_out(x)


@router.put("/metrics/{mid}")
def update_metric(mid: int, body: MetricIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session), user: str = Depends(current_user)):
    x = db.get(m.Metric, mid)
    if not x or x.workspace_id != ws.id:
        raise HTTPException(404, "Metric not found")
    _validate_metric(db, ws, body)
    for k, v in body.model_dump().items():
        setattr(x, k, v)
    db.flush()
    try:
        run_spec(db, load_catalog(db, ws), QuerySpec(measures=[{"metric": x.name}]), user)
    except (QueryError, QueryExecutionError, UnsafeSQLError) as e:
        db.rollback()
        raise HTTPException(400, f"Metric does not compute: {e}")
    db.commit()
    return metric_out(x)


@router.delete("/metrics/{mid}", status_code=204)
def delete_metric(mid: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    x = db.get(m.Metric, mid)
    if not x or x.workspace_id != ws.id:
        raise HTTPException(404, "Metric not found")
    users = [y.name for y in db.query(m.Metric).filter_by(workspace_id=ws.id, kind="composite") if "{" + x.name + "}" in y.expression]
    if users:
        raise HTTPException(400, f"Used by composite metric(s): {', '.join(users)}")
    db.delete(x)
    db.commit()


class GlossaryIn(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    synonyms: list[str] = Field(default_factory=list)
    target_type: str = Field(pattern="^(column|value|metric)$")
    dataset_id: int | None = None
    column: str | None = None
    value: str | None = None
    metric_name: str | None = None
    description: str = ""


@router.get("/glossary")
def list_glossary(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return [glossary_out(g) for g in db.query(m.GlossaryTerm).filter_by(workspace_id=ws.id).order_by(m.GlossaryTerm.term)]


def _check_glossary(db, ws, body: GlossaryIn):
    if body.target_type == "metric":
        if not db.query(m.Metric).filter_by(workspace_id=ws.id, name=body.metric_name).first():
            raise HTTPException(400, "Unknown metric")
    else:
        ds = db.get(m.Dataset, body.dataset_id or 0)
        if not ds or ds.workspace_id != ws.id or body.column not in {c.name for c in ds.columns}:
            raise HTTPException(400, "Choose a dataset and column")
        if body.target_type == "value" and body.value is None:
            raise HTTPException(400, "Enter the data value this term refers to")


@router.post("/glossary", status_code=201)
def create_glossary(body: GlossaryIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    _check_glossary(db, ws, body)
    g = m.GlossaryTerm(workspace_id=ws.id, **body.model_dump())
    db.add(g)
    db.commit()
    return glossary_out(g)


@router.put("/glossary/{gid}")
def update_glossary(gid: int, body: GlossaryIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    g = db.get(m.GlossaryTerm, gid)
    if not g or g.workspace_id != ws.id:
        raise HTTPException(404, "Not found")
    _check_glossary(db, ws, body)
    for k, v in body.model_dump().items():
        setattr(g, k, v)
    db.commit()
    return glossary_out(g)


@router.delete("/glossary/{gid}", status_code=204)
def delete_glossary(gid: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    g = db.get(m.GlossaryTerm, gid)
    if not g or g.workspace_id != ws.id:
        raise HTTPException(404, "Not found")
    db.delete(g)
    db.commit()


class RuleIn(BaseModel):
    dataset_id: int
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    filters: list[dict] = Field(min_length=1)
    enabled: bool = True


def _check_rule(db, ws, body: RuleIn):
    ds = db.get(m.Dataset, body.dataset_id)
    if not ds or ds.workspace_id != ws.id:
        raise HTTPException(400, "Unknown dataset")
    cols = {c.name for c in ds.columns}
    for f in body.filters:
        if f.get("column") not in cols:
            raise HTTPException(400, f"Unknown column {f.get('column')}")


@router.get("/rules")
def list_rules(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    return [rule_out(r) for r in db.query(m.BusinessRule).filter_by(workspace_id=ws.id)]


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    _check_rule(db, ws, body)
    r = m.BusinessRule(workspace_id=ws.id, **body.model_dump())
    db.add(r)
    db.commit()
    return rule_out(r)


@router.put("/rules/{rid}")
def update_rule(rid: int, body: RuleIn, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    r = db.get(m.BusinessRule, rid)
    if not r or r.workspace_id != ws.id:
        raise HTTPException(404, "Not found")
    _check_rule(db, ws, body)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    db.commit()
    return rule_out(r)


@router.delete("/rules/{rid}", status_code=204)
def delete_rule(rid: int, ws: m.Workspace = Depends(editor), db: Session = Depends(get_session)):
    r = db.get(m.BusinessRule, rid)
    if not r or r.workspace_id != ws.id:
        raise HTTPException(404, "Not found")
    db.delete(r)
    db.commit()


# ----------------------------------------------------------------------------------------------- assistant

class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None
    engine: str = Field("auto", pattern="^(auto|semantic|llm)$")


@router.post("/assistant/ask")
def ask(body: AskIn, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), user: str = Depends(current_user)):
    return assistant.answer(db, ws, user, body.question, body.conversation_id, engine=body.engine)


@router.get("/assistant/suggestions")
def ask_suggestions(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    from ..services.nlq.parser import suggest_questions
    return suggest_questions(load_catalog(db, ws))


@router.get("/conversations")
def conversations(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), user: str = Depends(current_user)):
    return [{"id": c.id, "title": c.title, "created_at": iso(c.created_at), "updated_at": iso(c.updated_at),
             "message_count": len(c.messages)}
            for c in db.query(m.Conversation).filter_by(workspace_id=ws.id, user_email=user).order_by(m.Conversation.updated_at.desc()).limit(100)]


@router.get("/conversations/{cid}")
def conversation(cid: int, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), user: str = Depends(current_user)):
    c = db.get(m.Conversation, cid)
    if not c or c.workspace_id != ws.id or c.user_email != user:
        raise HTTPException(404, "Conversation not found")
    return {"id": c.id, "title": c.title, "messages": [{"id": x.id, "role": x.role, "content": x.content, "payload": x.payload,
                                                        "created_at": iso(x.created_at)} for x in c.messages]}


@router.delete("/conversations/{cid}", status_code=204)
def delete_conversation(cid: int, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), user: str = Depends(current_user)):
    c = db.get(m.Conversation, cid)
    if not c or c.workspace_id != ws.id or c.user_email != user:
        raise HTTPException(404, "Conversation not found")
    db.delete(c)
    db.commit()
