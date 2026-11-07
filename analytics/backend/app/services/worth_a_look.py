""""Worth a look" (Phase 5): what deserves attention when a dashboard opens.

Computed in code from what the app already calculates, never by a model, so every item can be traced to its numbers:
  * vs_last_year - a headline number (a KPI tile's governed metric, with the dashboard's own filters) moved at least
                   CHANGE_MIN (rates: RATE_POINTS_MIN points) against the same period last year;
  * unusual      - a recent full month far from the months around it (analytics.detect_anomalies on the monthly
                   series of that metric);
  * record       - the latest full month is the highest or lowest of the last 6 or more;
  * gap          - a month with no data inside the series;
  * stale        - the data behind the dashboard ends more than STALE_DAYS before today.
At most MAX_ITEMS, ranked by size and by whether the move is bad (from the metric's higher_is_better). Items are cached
per dashboard (models.DashboardInsight) with a fingerprint of the dashboard, its metrics, the data's row counts and
today's date; a background job recomputes them when the fingerprint changes (after a sync that changed the data), so
opening a dashboard costs nothing. A dashboard with nothing unusual gets no items.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timezone

import numpy as np
from sqlalchemy.orm import Session

from .. import models as m
from ..config import today as _today

log = logging.getLogger(__name__)

MAX_ITEMS = 5
CHANGE_MIN = 0.10
RATE_POINTS_MIN = 0.01
RECENT_MONTHS = 3
RECORD_MIN_MONTHS = 6
STALE_DAYS = 30
USER = "system:worth-a-look"


def _headline_widgets(dash: m.Dashboard, cat) -> list[tuple[m.DashboardWidget, str]]:
    """KPI-like tiles (no breakdown) whose first measure is a governed metric with a date column; one per metric."""
    seen, out = set(), []
    for w in dash.widgets:
        spec = w.spec or {}
        if spec.get("dimensions"):
            continue
        name = next((x.get("metric") for x in spec.get("measures") or [] if x.get("metric")), None)
        mt = cat.metrics.get(name) if name else None
        if mt is None or name in seen or not _time_column(cat, name):
            continue
        seen.add(name)
        out.append((w, name))
    return out


def _time_column(cat, name: str) -> str | None:
    mt = cat.metrics.get(name)
    if mt is None:
        return None
    if mt.time_column:
        return mt.time_column
    ds = cat.datasets.get(mt.dataset_id) if mt.dataset_id else None
    if ds is not None and ds.default_date:
        return ds.default_date
    if mt.kind == "composite":                       # a composite has its parts' dates
        import re

        parts = re.findall(r"\{(\w+)\}", mt.expression or "")
        return next((_time_column(cat, p) for p in parts if _time_column(cat, p)), None)
    return None


def fingerprint(db: Session, dash: m.Dashboard, cat) -> str:
    from .agent.context import _expand_composites, _metric_names

    names = _expand_composites(cat, [n for w in dash.widgets for n in _metric_names(w.spec or {})])
    payload = {"d": [dash.key, dash.filters, [[w.id, w.title, w.spec] for w in dash.widgets]],
               "m": sorted([n, cat.metrics[n].expression, cat.metrics[n].filters, cat.metrics[n].time_column,
                            cat.metrics[n].higher_is_better] for n in names),
               "rows": sorted((d.slug, d.row_count) for d in db.query(m.Dataset).filter_by(workspace_id=dash.workspace_id)),
               "t": _today().isoformat(), "v": 2}
    return hashlib.sha256(json.dumps(payload, default=str, sort_keys=True).encode()).hexdigest()


def _base_spec(dash: m.Dashboard, w: m.DashboardWidget):
    from .dashboards import apply_dashboard_filters
    from .spec import QuerySpec

    return apply_dashboard_filters(QuerySpec.model_validate(w.spec), dash.filters or [])


def _run(db, cat, spec) -> dict | None:
    from .analytics import QueryExecutionError, QueryError, UnsafeSQLError, run_spec

    try:
        return run_spec(db, cat, spec, USER, source="insight", today=_today())
    except (QueryError, QueryExecutionError, UnsafeSQLError, ValueError) as e:
        log.info("worth-a-look query skipped: %s", str(e).splitlines()[0][:200])
        db.rollback()
        return None


def _bad(mt, delta: float) -> bool:
    return (delta < 0) if mt.higher_is_better else (delta > 0)


def _month_label(v) -> str:
    try:
        d = date.fromisoformat(str(v)[:10])
        return d.strftime("%b %Y")
    except ValueError:
        return str(v)


def _period_text(spec) -> str:
    tr = spec.time_range
    if isinstance(tr, dict) and tr.get("from"):
        f = date.fromisoformat(str(tr["from"])[:10])
        t = date.fromisoformat(str(tr.get("to") or tr["from"])[:10])
        return f"{f.day} {f.strftime('%b %Y')} to {t.day} {t.strftime('%b %Y')}"
    return "the dashboard's period"


def _vs_last_year(db, cat, dash, w, name) -> dict | None:
    from .analytics import fmt

    mt = cat.metrics[name]
    spec = _base_spec(dash, w)
    spec.compare = "previous_year"
    res = _run(db, cat, spec)
    if not res or not res.get("rows"):
        return None
    cols, row = res["columns"], res["rows"][0]
    cur_i = next((i for i, c in enumerate(cols) if c["role"] == "measure" and not c.get("compare_of")), None)
    if cur_i is None:
        return None
    alias = cols[cur_i]["name"]
    prev_i = next((i for i, c in enumerate(cols) if c["name"] == f"{alias}__prev"), None)
    if prev_i is None or row[cur_i] is None or row[prev_i] is None:
        return None
    cur, prev = float(row[cur_i]), float(row[prev_i])
    f = cols[cur_i].get("format") or mt.format
    if f == "percent":
        delta = cur - prev
        if abs(delta) < RATE_POINTS_MIN:
            return None
        size = abs(delta) / max(abs(prev), 0.01)
        move = f"{'up' if delta > 0 else 'down'} {abs(delta) * 100:.1f} points"
    else:
        if not prev:
            return None
        delta = (cur - prev) / abs(prev)
        if abs(delta) < CHANGE_MIN:
            return None
        size = abs(delta)
        move = f"{'up' if delta > 0 else 'down'} {abs(delta):.1%}"
    bad = _bad(mt, delta)
    period = _period_text(spec)
    return {"kind": "vs_last_year", "widget_id": w.id, "widget": w.title, "metric": name,
            "tone": "bad" if bad else "good", "score": size * (1.5 if bad else 1.0),
            "text": f"{w.title}: {move} on the same period last year, {fmt(cur, f)} against {fmt(prev, f)} ({period}).",
            "question": f"Why is {w.title.lower()} {move} on the same period last year?",
            "values": {"current": cur, "previous": prev, "change": delta, "format": f, "period": period}}


def _data_end(cat, name: str) -> date | None:
    from .executor import run_readonly
    from .naming import q
    from .sql_safety import validate_select

    mt = cat.metrics.get(name)
    col = _time_column(cat, name)
    ds = cat.datasets.get(mt.dataset_id) if mt and mt.dataset_id else None
    if ds is None or not col or col not in ds.columns:
        return None
    try:
        sql = f"SELECT MAX({q(col)}) FROM {q(cat.schema)}.{q(ds.slug)}"
        validate_select(sql, cat.schema, {ds.slug})
        hi = run_readonly(sql, {}, cat.schema).rows[0][0]
        return date.fromisoformat(str(hi)[:10]) if hi else None
    except Exception as e:  # noqa: BLE001
        log.info("data end of %s unknown: %s", name, e)
        return None


def _monthly(db, cat, dash, w, name, end: date | None) -> list[dict]:
    from .analytics import detect_anomalies, fmt
    from .spec import Dimension

    mt = cat.metrics[name]
    spec = _base_spec(dash, w)
    spec.dimensions = [Dimension(field="@time", grain="month")]
    spec.compare, spec.sort, spec.limit = None, [], None
    res = _run(db, cat, spec)
    if not res or len(res.get("rows") or []) < 2:
        return []
    cols = res["columns"]
    vi = next((i for i, c in enumerate(cols) if c["role"] == "measure" and not c.get("compare_of")), None)
    if vi is None:
        return []
    f = cols[vi].get("format") or mt.format
    pts = sorted(((str(r[0])[:10], r[vi]) for r in res["rows"] if r[0] is not None), key=lambda p: p[0])
    # the month the data ends in is partial unless the data reaches its last days
    if end is not None and pts and pts[-1][0][:7] == end.isoformat()[:7] and end.day < 28:
        pts = pts[:-1]
    out: list[dict] = []
    # gaps: a month with no value inside the series
    months = [p[0][:7] for p in pts]
    if len(months) >= 2:
        y, mo = int(months[0][:4]), int(months[0][5:7])
        expected = []
        while f"{y:04d}-{mo:02d}" <= months[-1]:
            expected.append(f"{y:04d}-{mo:02d}")
            mo = 1 if mo == 12 else mo + 1
            y = y + 1 if mo == 1 else y
        missing = [x for x in expected if x not in months or dict((p[0][:7], p[1]) for p in pts).get(x) is None]
        if missing:
            labels = ", ".join(_month_label(x + "-01") for x in missing[:4])
            out.append({"kind": "gap", "widget_id": w.id, "widget": w.title, "metric": name, "tone": "bad",
                        "score": 0.6, "text": f"{w.title}: no data for {labels}{' and more' if len(missing) > 4 else ''}.",
                        "question": f"Why is there no {w.title.lower()} data for {labels}?",
                        "values": {"missing_months": missing}})
    vals_pts = [(p[0], float(p[1])) for p in pts if p[1] is not None]
    if len(vals_pts) >= 7:
        vals = np.array([v for _, v in vals_pts])
        recent = {x for x, _ in vals_pts[-RECENT_MONTHS:]}
        for a in detect_anomalies(w.title, vals_pts, vals, f):
            if a["x"] not in recent or not a["expected"]:
                continue
            delta = (a["value"] - a["expected"]) / abs(a["expected"])
            bad = _bad(mt, delta)
            out.append({"kind": "unusual", "widget_id": w.id, "widget": w.title, "metric": name,
                        "tone": "bad" if bad else "good", "score": min(abs(delta), 3.0) * (1.5 if bad else 1.0) + 0.2,
                        "text": f"{w.title}: {_month_label(a['x'])} stands out, {fmt(a['value'], f)} against about "
                                f"{fmt(a['expected'], f)} in the months around it.",
                        "question": f"What happened to {w.title.lower()} in {_month_label(a['x'])}?",
                        "values": {"month": a["x"], "value": a["value"], "expected": a["expected"], "format": f}})
    if len(vals_pts) >= RECORD_MIN_MONTHS and not mt.semi_additive:
        last_x, last_v = vals_pts[-1]
        others = [v for _, v in vals_pts[:-1]]
        if last_v > max(others) or last_v < min(others):
            high = last_v > max(others)
            bad = _bad(mt, 1 if high else -1)
            out.append({"kind": "record", "widget_id": w.id, "widget": w.title, "metric": name,
                        "tone": "bad" if bad else "good", "score": 0.5 * (1.5 if bad else 1.0),
                        "text": f"{w.title}: {_month_label(last_x)} was the {'highest' if high else 'lowest'} of the "
                                f"last {len(vals_pts)} full months ({fmt(last_v, f)}).",
                        "question": f"Why was {w.title.lower()} in {_month_label(last_x)} the {'highest' if high else 'lowest'} in {len(vals_pts)} months?",
                        "values": {"month": last_x, "value": last_v, "months": len(vals_pts), "format": f}})
    return out


def compute(db: Session, dash: m.Dashboard, cat) -> list[dict]:
    items: list[dict] = []
    ends: list[date] = []
    for w, name in _headline_widgets(dash, cat):
        end = _data_end(cat, name)
        if end:
            ends.append(end)
        yoy = _vs_last_year(db, cat, dash, w, name)
        if yoy:
            items.append(yoy)
        items += _monthly(db, cat, dash, w, name, end)
    if ends:
        latest = max(ends)
        age = (_today() - latest).days
        if age > STALE_DAYS:
            items.append({"kind": "stale", "widget_id": None, "widget": None, "metric": None, "tone": "neutral",
                          "score": 0.1, "text": f"The data behind this dashboard ends on {latest.day} {latest.strftime('%b %Y')} "
                                                f"({age} days ago): newer numbers are not loaded yet.",
                          "question": "Up to which date is the data on this dashboard?", "values": {"data_end": latest.isoformat(), "age_days": age}})
    items.sort(key=lambda x: -x["score"])
    for i, it in enumerate(items):
        it["id"] = hashlib.sha1(json.dumps([it["kind"], it["widget_id"], it.get("values")], default=str, sort_keys=True).encode()).hexdigest()[:10]
        it["score"] = round(it["score"], 3)
    return items[:MAX_ITEMS]


def refresh(db: Session, ws: m.Workspace, dash: m.Dashboard, force: bool = False) -> m.DashboardInsight:
    """Recompute one dashboard's items if its fingerprint changed. Runs without a person (full catalog)."""
    from .catalog import load_catalog
    from .permissions import acting

    if acting(ws)[0] is not None:
        raise RuntimeError("worth_a_look.refresh runs without an acting user")
    cat = load_catalog(db, ws)
    fp = fingerprint(db, dash, cat)
    row = db.query(m.DashboardInsight).filter_by(workspace_id=ws.id, dashboard_key=dash.key).one_or_none()
    if row is not None and row.fingerprint == fp and not force:
        return row
    items = compute(db, dash, cat)
    if row is None:
        row = m.DashboardInsight(workspace_id=ws.id, dashboard_key=dash.key)
        db.add(row)
    row.fingerprint, row.items, row.computed_at = fp, items, datetime.now(timezone.utc)
    db.commit()
    return row


def refresh_job(db: Session, payload: dict) -> dict:
    from ..config import get_settings

    if not get_settings().assistant_data_issues:
        return {"skipped": "switched off"}
    ws = db.get(m.Workspace, int(payload["workspace_id"]))
    if ws is None:
        return {"skipped": "no workspace"}
    keys = payload.get("dashboard_keys")
    q = db.query(m.Dashboard).filter_by(workspace_id=ws.id)
    done = []
    for d in q:
        if not d.key or (keys and d.key not in keys):
            continue
        before = db.query(m.DashboardInsight.fingerprint).filter_by(workspace_id=ws.id, dashboard_key=d.key).scalar()
        row = refresh(db, ws, d)
        if row.fingerprint != before:
            done.append(d.key)
    return {"recomputed": done}


def queue(db: Session, ws_id: int, dashboard_key: str | None = None) -> None:
    from . import jobs

    jobs.enqueue(db, "worth_a_look", {"workspace_id": ws_id, "dashboard_keys": [dashboard_key] if dashboard_key else None},
                 dedupe_key=f"worth:{ws_id}:{dashboard_key or '*'}")


def for_user(db: Session, ws: m.Workspace, dash: m.Dashboard, cat) -> dict:
    """What a person sees: the cached items whose metrics they may see; queues a recompute when the data changed."""
    from .permissions import hidden_dataset_ids

    row = db.query(m.DashboardInsight).filter_by(workspace_id=ws.id, dashboard_key=dash.key).one_or_none()
    stale = row is None
    # the fingerprint covers the full definitions; a person who can't see every dataset has a smaller catalog, so only
    # people who see everything compare it (the hourly sync check recomputes for everyone else)
    if row is not None and not hidden_dataset_ids(db, ws):
        stale = row.fingerprint != fingerprint(db, dash, cat)
    if stale:
        queue(db, ws.id, dash.key)
    items = [it for it in (row.items if row else []) if not it.get("metric") or it["metric"] in cat.metrics]
    return {"items": items, "computed_at": row.computed_at.isoformat() if row else None,
            "status": "updating" if stale else "ready"}
