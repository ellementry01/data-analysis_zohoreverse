"""Import the warehouse issue log into the app's data issue register (Phase 5).

    python scripts/import_issue_log.py [--log ../warehouse/docs/ISSUE_LOG.md] [--base http://localhost:8000]
                                       [--workspace 34] [--dry-run]

Reads the "Unsolved" and "Solved" tables of warehouse/docs/ISSUE_LOG.md, says for each unsolved issue what it affects
(dashboards, metrics, datasets of workspace 34: AREA_AFFECTS by area, refined per issue in ISSUE_AFFECTS), and sends
them to POST /api/workspaces/{ws}/data-issues/import. The app adds issues it doesn't have yet and marks solved the
ones the log lists as solved; it never overwrites what was edited in the app, so this can be re-run after the log
changes. With company sign-in on, set ELLEMENTRY_API_TOKEN (never printed).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

CODE = re.compile(r"^[A-Z]{1,4}-\d{1,5}$")
SEVERITIES = ("high", "medium", "low")

# What each area of the log touches by default (dashboard keys; metrics only where a tile's number itself is affected)
AREA_AFFECTS: dict[str, dict] = {
    "Domestic sales": {"dashboards": ["sales-channels"]},
    "Retail sales": {"dashboards": ["sales-channels"]},
    "Stock transfers": {"dashboards": ["purchasing-transfers"]},
    "Purchase orders": {"dashboards": ["purchasing-transfers"]},
    "Inventory": {"dashboards": ["stock"]},
    "Locations": {"dashboards": ["stock"]},
    "Product master": {"dashboards": ["stock"]},
    "Returns": {"dashboards": ["returns"]},
    "WMS dispatch": {"dashboards": ["fulfilment"]},
    "Quick commerce": {"dashboards": ["instamart"]},
}

# Per issue, where the log's area is too coarse: the tiles whose numbers it changes. An entry replaces the area default.
ISSUE_AFFECTS: dict[str, dict] = {
    "D-004": {"dashboards": ["stock"], "metrics": ["stock_value_cost_history"]},
    "D-005": {},                                   # parked: Blinkit set aside
    "D-006": {"dashboards": ["days-of-cover"], "metrics": ["partner_units_sold"]},
    "D-019": {"dashboards": ["sales-channels", "executive-overview"], "metrics": ["b2b_net_sales"]},
    "D-023": {"dashboards": ["sales-channels"]},
    "D-024": {"dashboards": ["sales-channels"]},
    "D-038": {"dashboards": ["purchasing-transfers"]},
    "D-039": {"dashboards": ["purchasing-transfers"], "metrics": ["units_in_transit"]},
    "D-050": {}, "D-092": {},                      # parked: Blinkit set aside
    "D-051": {"dashboards": ["stock"]},
    "D-052": {"dashboards": ["stock"]},
    "D-060": {},                                   # handled: IDs loaded as text
    "D-069": {},                                   # INR / IST stored as settings
    "D-073": {"dashboards": ["stock", "days-of-cover"], "metrics": ["sellable_stock"]},
    "D-079": {"dashboards": ["returns"], "metrics": ["amazon_units_returned"]},
    "D-080": {"dashboards": ["days-of-cover", "discontinued-slow-stock"], "metrics": ["partner_stock_balance"]},
    "D-089": {"dashboards": ["returns", "days-of-cover"], "metrics": ["partner_units_returned"]},
    "D-098": {},                                   # DOCID not used by the warehouse
    "D-111": {"dashboards": ["fulfilment"], "metrics": ["late_shipment_rate"]},
    "D-112": {"dashboards": ["fulfilment", "executive-overview"], "metrics": ["rto_rate"]},
    "D-113": {"dashboards": ["fulfilment"], "metrics": ["avg_ship_to_deliver_days"]},
    "D-118": {"dashboards": ["stock"], "metrics": ["stock_on_hand"]},
    "D-121": {"dashboards": ["purchasing-transfers"], "metrics": ["open_po_qty"]},
    "D-124": {"dashboards": ["stock", "data-health"], "metrics": ["unexplained_stock_qty"]},
    "D-125": {"dashboards": ["instamart"]},
    "D-036": {"dashboards": ["returns"], "metrics": ["avg_days_to_return"]},
}

_STATUS = (("solved", "solved"), ("parked", "parked"), ("awaiting", "awaiting"), ("open", "open"))


def parse(text: str) -> tuple[list[dict], list[str]]:
    """(unsolved rows, solved codes). Unsolved columns: ID | Area | Issue | What is needed | Status | Priority | Owner."""
    section, unsolved, solved = None, [], []
    for line in (text or "").splitlines():
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if not line.startswith("| ") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if not cells or not CODE.match(cells[0]):
            continue
        if section == "unsolved" and len(cells) >= 7:
            raw = cells[4]
            unsolved.append({"code": cells[0], "area": cells[1], "title": cells[2], "summary": cells[3],
                             "status": next((v for k, v in _STATUS if raw.lower().startswith(k)), "open"),
                             "status_detail": raw,
                             "severity": cells[5].lower() if cells[5].lower() in SEVERITIES else "medium",
                             "owner": cells[6]})
        elif section == "solved":
            solved.append(cells[0])
    return unsolved, solved


def affects_of(row: dict) -> dict:
    a = ISSUE_AFFECTS[row["code"]] if row["code"] in ISSUE_AFFECTS else AREA_AFFECTS.get(row["area"], {})
    return {"dashboards": list(a.get("dashboards") or []), "metrics": list(a.get("metrics") or []),
            "datasets": list(a.get("datasets") or [])}


def rows_for_import(text: str) -> tuple[list[dict], list[str]]:
    unsolved, solved = parse(text)
    return [{**r, "affects": affects_of(r), "note": r["title"]} for r in unsolved], solved


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=str(here.parent.parent / "warehouse" / "docs" / "ISSUE_LOG.md"))
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--workspace", type=int, default=34)
    ap.add_argument("--dry-run", action="store_true", help="print what would be sent, send nothing")
    a = ap.parse_args()
    rows, solved = rows_for_import(Path(a.log).read_text(encoding="utf-8"))
    print(f"{len(rows)} unsolved issues, {len(solved)} solved in {a.log}")
    if a.dry_run:
        for r in rows:
            print(f"  {r['code']} [{r['status']}, {r['severity']}] affects {json.dumps(r['affects'])}")
        return 0
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("ELLEMENTRY_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{a.base}/api/workspaces/{a.workspace}/data-issues/import", method="POST",
                                 headers=headers, data=json.dumps({"rows": rows, "solved": solved}).encode())
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}", file=sys.stderr)
        return 1
    print(f"added {len(out['added'])}, marked solved {len(out['solved'])}, already there {len(out['already_there'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
