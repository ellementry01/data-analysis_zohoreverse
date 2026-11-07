"""Dashboard helpers: stable keys that survive renames and rebuilds, and applying dashboard filters to a widget's spec."""
from sqlalchemy.orm import Session

from .. import models as m
from .naming import DASHBOARD_KEY_RE, dashboard_key, unique_dashboard_key
from .spec import Filter, QuerySpec


def filter_is_set(value) -> bool:
    return value not in (None, "", []) and value != {}


def apply_dashboard_filters(spec: QuerySpec, filters: list[dict]) -> QuerySpec:
    """What a dashboard does to each widget: its date range replaces the widget's, its value filters replace
    any widget filter on the same field."""
    spec = spec.model_copy(deep=True)
    for f in filters:
        v = f.get("value")
        if not filter_is_set(v):
            continue
        if f.get("type") == "date_range":
            spec.time_range = v
            if f.get("field") and f["field"] != "@time":
                spec.time_field = f["field"]
        elif f.get("type") == "values":
            vals = v if isinstance(v, list) else [v]
            spec.filters = [x for x in spec.filters if x.field != f["field"]] + [Filter(field=f["field"], op="in", value=vals)]
    return spec

DOMAINS = {"", "executive", "sales", "stock", "operations", "purchasing", "returns", "quick_commerce", "marketing",
           "finance", "customer", "product", "design", "data"}


class DashboardKeyError(ValueError):
    pass


def taken_keys(db: Session, ws_id: int, exclude_id: int | None = None) -> set[str]:
    q = db.query(m.Dashboard.key).filter(m.Dashboard.workspace_id == ws_id)
    if exclude_id is not None:
        q = q.filter(m.Dashboard.id != exclude_id)
    return {k for (k,) in q}


def new_key(db: Session, ws_id: int, name: str, requested: str | None = None) -> str:
    """Key for a new dashboard: the requested one (must be valid and free) or one derived from the name."""
    taken = taken_keys(db, ws_id)
    if requested:
        check_key(requested)
        if requested in taken:
            raise DashboardKeyError(f"Dashboard key '{requested}' is already used in this workspace")
        return requested
    return unique_dashboard_key(dashboard_key(name), taken)


def check_key(key: str) -> str:
    if not DASHBOARD_KEY_RE.match(key or ""):
        raise DashboardKeyError("A dashboard key is 1-80 lowercase letters, digits or dashes, starting with a letter or digit")
    return key


def check_domain(domain: str) -> str:
    if domain not in DOMAINS:
        raise DashboardKeyError(f"Unknown domain '{domain}'; use one of: {', '.join(sorted(d for d in DOMAINS if d))}")
    return domain
