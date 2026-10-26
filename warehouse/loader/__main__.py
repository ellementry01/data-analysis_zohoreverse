"""
Usage
  python -m loader load  <SOURCE> <FILE> [--as-of YYYY-MM-DD] [--loaded-by NAME] [--dry-run] [--accept-draft]
  python -m loader batches [--source SOURCE] [--limit N]
  python -m loader sources

Exit codes: 0 loaded / checked OK | 1 file rejected (contract) | 2 refused (usage / policy)
            3 already loaded, nothing done | 4 unexpected error (nothing committed)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from .load import AlreadyLoaded, LoadRefused, connect, load_file
from .validate import CONTRACT_DIR, ContractError


def _date(s: str) -> dt.date:
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{s}' is not a date in YYYY-MM-DD form")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m loader", description="Land source exports in the raw layer.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ld = sub.add_parser("load", help="check a file against its contract and load it")
    ld.add_argument("source"); ld.add_argument("file", type=Path)
    ld.add_argument("--as-of", type=_date, help="snapshot / state / master exports: the date the export represents")
    ld.add_argument("--as-of-assumed", action="store_true",
                    help="the as-of date is an assumption, not the known export date (dashboards flag it)")
    ld.add_argument("--loaded-by", help="who is loading (defaults to your OS user name)")
    ld.add_argument("--dry-run", action="store_true", help="check only; touch nothing in the database")
    ld.add_argument("--accept-draft", action="store_true", help="allow a DRAFT contract (first real file only)")
    bt = sub.add_parser("batches", help="list recent loads")
    bt.add_argument("--source"); bt.add_argument("--limit", type=int, default=20)
    sub.add_parser("sources", help="list sources with contracts")
    a = ap.parse_args(argv)

    if a.cmd == "sources":
        for p in sorted(CONTRACT_DIR.glob("*.json")):
            c = json.loads(p.read_text(encoding="utf-8"))
            print(f"{c['source_name']:24s} {c['status']:8s} as-of {'required' if c['as_of_required'] else 'no      '}  "
                  f"{c.get('verified_against') or c.get('draft_note', '')}")
        return 0

    if a.cmd == "batches":
        with connect() as conn:
            q = ("SELECT batch_id, source_name, status, rows_loaded, period_start, period_end, as_of_date, "
                 "to_char(started_at,'YYYY-MM-DD HH24:MI'), file_name, left(coalesce(notes,''),80) "
                 "FROM meta.load_batch " + ("WHERE source_name = %s " if a.source else "") +
                 "ORDER BY batch_id DESC LIMIT %s")
            rows = conn.execute(q, ((a.source, a.limit) if a.source else (a.limit,))).fetchall()
        for r in rows:
            period = f"{r[4]}..{r[5]}" if r[4] else f"as of {r[6]}" if r[6] else "-"
            print(f"#{r[0]:<5} {r[1]:24s} {r[2]:10s} rows={str(r[3] or 0):>7s}  {period:24s} {r[7]}  {r[8]}  {r[9]}")
        return 0

    try:
        o = load_file(a.source, a.file, as_of=a.as_of, loaded_by=a.loaded_by, dry_run=a.dry_run, accept_draft=a.accept_draft,
                      as_of_assumed=a.as_of_assumed)
    except ContractError as e:
        print(f"REJECTED  {a.source}  {a.file.name}\n  {e}", file=sys.stderr); return 1
    except LoadRefused as e:
        print(f"REFUSED   {e}", file=sys.stderr); return 2
    except AlreadyLoaded as e:
        print(f"SKIPPED   {e}", file=sys.stderr); return 3
    except Exception as e:
        print(f"ERROR     {type(e).__name__}: {e}\n  Nothing was committed; the attempt is recorded as FAILED where possible.",
              file=sys.stderr); return 4

    period = f"{o.period[0]} .. {o.period[1]}" if o.period else f"as of {o.as_of}"
    head = "CHECKED (dry run, nothing written)" if o.dry_run else f"LOADED    batch {o.batch_id}"
    print(f"{head}  {o.source}  sheet '{o.sheet}'  {o.rows_read} source rows -> {o.rows_loaded} raw rows  ({period})")
    for name, details, _ in o.warnings:
        print(f"  WARN {name}: {details}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
