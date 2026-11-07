"""
Updates the widgets of existing dashboards in place from the definitions in build_executive_dashboards.py, so the
dashboard ids (and any links shared with management) stay the same. build_executive_dashboards.py instead deletes and
recreates every dashboard, which changes the ids (the keys stay the same).

    python scripts/update_dashboard_widgets.py "Stock" "Fulfilment" [--base http://localhost:8000] [--workspace 34]
    python scripts/update_dashboard_widgets.py --meta-only --all     # only set each dashboard's key and domain

Dashboards are found by key (DASHBOARD_META), else by name. Widgets are matched by title; descriptions and filters
are updated too. A widget whose title is new or renamed is not created here: run build_executive_dashboards.py for
that (and share the new ids). --meta-only changes nothing but the key and domain.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_executive_dashboards import DASHBOARD_META, DASHBOARDS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*"); ap.add_argument("--all", action="store_true")
    ap.add_argument("--meta-only", action="store_true", help="only set key and domain; widgets, filters and text untouched")
    ap.add_argument("--base", default="http://localhost:8000"); ap.add_argument("--workspace", type=int, default=34)
    a = ap.parse_args()
    if not a.names and not a.all:
        ap.error("name the dashboards to update, or pass --all")
    base = f"{a.base}/api/workspaces/{a.workspace}"

    def call(method, path, body=None):
        req = urllib.request.Request(base + path, method=method, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read() or b"null")

    live = call("GET", "/dashboards")
    by_key = {d.get("key"): d["id"] for d in live}
    by_name = {d["name"]: d["id"] for d in live}
    problems = 0
    for name, desc, filters, widgets in DASHBOARDS:
        if not a.all and name not in a.names:
            continue
        key, domain = DASHBOARD_META[name]
        did = by_key.get(key) or by_name.get(name)
        if not did:
            print(f"{name}: not found on the live workspace (run build_executive_dashboards.py)"); problems += 1
            continue
        d = call("GET", f"/dashboards/{did}")
        if a.meta_only:
            call("PUT", f"/dashboards/{did}", {"name": d["name"], "description": d["description"], "filters": d["filters"],
                                                "is_template": d.get("is_template", False), "key": key, "domain": domain})
            print(f"{name}: dashboard {did}, key {key}, domain {domain}")
            continue
        call("PUT", f"/dashboards/{did}", {"name": name, "description": desc, "is_template": d.get("is_template", False),
                                            "filters": filters, "key": key, "domain": domain})
        by_title = {w["title"]: w for w in d["widgets"]}
        missing = 0
        for title, ct, spec, _layout, options in widgets:
            w = by_title.get(title)
            if not w:
                print(f"  {name} / {title}: not on the live dashboard (run build_executive_dashboards.py)"); missing += 1
                continue
            call("PUT", f"/dashboards/{did}/widgets/{w['id']}",
                 {"title": title, "chart_type": ct, "spec": spec, "layout": w["layout"], "options": options})
        problems += missing
        print(f"{name}: dashboard {did} (key {key}), {len(widgets) - missing} widgets updated")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
