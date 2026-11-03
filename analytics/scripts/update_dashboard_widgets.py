"""
Updates the widgets of existing dashboards in place from the definitions in build_executive_dashboards.py, so the
dashboard ids (and any links shared with management) stay the same. build_executive_dashboards.py instead deletes and
recreates every dashboard, which changes the ids.

    python scripts/update_dashboard_widgets.py "Stock" "Fulfilment" [--base http://localhost:8000] [--workspace 34]

Widgets are matched by title; descriptions and filters are updated too. A widget whose title is new or renamed is not
created here: run build_executive_dashboards.py for that (and share the new ids).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_executive_dashboards import DASHBOARDS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+"); ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--workspace", type=int, default=34)
    a = ap.parse_args()
    base = f"{a.base}/api/workspaces/{a.workspace}"

    def call(method, path, body=None):
        req = urllib.request.Request(base + path, method=method, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read() or b"null")

    live = {d["name"]: d["id"] for d in call("GET", "/dashboards")}
    missing = 0
    for name, desc, filters, widgets in DASHBOARDS:
        if name not in a.names:
            continue
        did = live[name]
        d = call("GET", f"/dashboards/{did}")
        call("PUT", f"/dashboards/{did}", {"name": name, "description": desc, "is_template": d.get("is_template", False), "filters": filters})
        by_title = {w["title"]: w for w in d["widgets"]}
        for title, ct, spec, _layout, options in widgets:
            w = by_title.get(title)
            if not w:
                print(f"  {name} / {title}: not on the live dashboard (run build_executive_dashboards.py)"); missing += 1
                continue
            call("PUT", f"/dashboards/{did}/widgets/{w['id']}",
                 {"title": title, "chart_type": ct, "spec": spec, "layout": w["layout"], "options": options})
        print(f"{name}: dashboard {did}, {len(widgets) - missing} widgets updated")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
