from . import models as m
from .services.connectors import public_config


def iso(d):
    return d.isoformat() if d else None


def workspace_out(ws: m.Workspace, user: str | None = None, stats: dict | None = None) -> dict:
    role = next((x.role for x in ws.members if x.user_email == user), None)
    return {"id": ws.id, "name": ws.name, "description": ws.description, "created_by": ws.created_by,
            "created_at": iso(ws.created_at), "role": role, **(stats or {})}


def column_out(c: m.DatasetColumn) -> dict:
    return {"id": c.id, "name": c.name, "display_name": c.display_name, "data_type": c.data_type, "position": c.position,
            "is_derived": c.is_derived, "expression": c.expression, "description": c.description, "hidden": c.hidden,
            "source_name": c.source_name}


def dataset_out(ds: m.Dataset, full: bool = True) -> dict:
    out = {"id": ds.id, "name": ds.name, "slug": ds.slug, "kind": ds.kind, "description": ds.description,
           "row_count": ds.row_count, "default_date_column": ds.default_date_column,
           "created_at": iso(ds.created_at), "updated_at": iso(ds.updated_at), "last_refreshed_at": iso(ds.last_refreshed_at),
           "source_info": ds.source_info or {}, "column_count": len(ds.columns),
           "warning_count": len((ds.quality or {}).get("warnings", []))}
    if full:
        out["columns"] = [column_out(c) for c in ds.columns]
        out["query_sql"] = ds.query_sql
        out["quality"] = ds.quality or {}
        out["transforms"] = [{"id": t.id, "kind": t.kind, "params": t.params, "position": t.position,
                              "created_at": iso(t.created_at), "last_result": t.last_result} for t in ds.transforms]
    return out


def relationship_out(r: m.Relationship) -> dict:
    return {"id": r.id, "from_dataset_id": r.from_dataset_id, "from_column": r.from_column,
            "to_dataset_id": r.to_dataset_id, "to_column": r.to_column, "cardinality": r.cardinality}


def metric_out(x: m.Metric) -> dict:
    return {"id": x.id, "name": x.name, "label": x.label, "description": x.description, "kind": x.kind,
            "dataset_id": x.dataset_id, "expression": x.expression, "filters": x.filters or [], "time_column": x.time_column,
            "semi_additive": x.semi_additive, "synonyms": x.synonyms or [], "format": x.format, "higher_is_better": x.higher_is_better}


def glossary_out(g: m.GlossaryTerm) -> dict:
    return {"id": g.id, "term": g.term, "synonyms": g.synonyms or [], "target_type": g.target_type, "dataset_id": g.dataset_id,
            "column": g.column, "value": g.value, "metric_name": g.metric_name, "description": g.description}


def rule_out(r: m.BusinessRule) -> dict:
    return {"id": r.id, "dataset_id": r.dataset_id, "name": r.name, "description": r.description,
            "filters": r.filters or [], "enabled": r.enabled}


def report_out(r: m.Report) -> dict:
    return {"id": r.id, "name": r.name, "description": r.description, "chart_type": r.chart_type, "spec": r.spec,
            "options": r.options or {}, "created_at": iso(r.created_at), "updated_at": iso(r.updated_at)}


def widget_out(w: m.DashboardWidget) -> dict:
    return {"id": w.id, "title": w.title, "chart_type": w.chart_type, "spec": w.spec, "options": w.options or {},
            "layout": w.layout or {}, "report_id": w.report_id}


def dashboard_out(d: m.Dashboard, full: bool = True) -> dict:
    out = {"id": d.id, "name": d.name, "description": d.description, "filters": d.filters or [], "is_template": d.is_template,
           "created_at": iso(d.created_at), "updated_at": iso(d.updated_at), "widget_count": len(d.widgets)}
    if full:
        out["widgets"] = [widget_out(w) for w in d.widgets]
    return out


def connector_out(c: m.Connector) -> dict:
    return {"id": c.id, "name": c.name, "kind": c.kind, "config": public_config(c.config), "created_at": iso(c.created_at),
            "last_tested_at": iso(c.last_tested_at), "last_status": c.last_status}
