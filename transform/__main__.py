"""
Builds stg -> core -> mart from raw, in ONE transaction.

    python -m transform run <database> [--started-by NAME]

* Everything commits together or nothing does: dashboards never see half a build.
* Settings (period, partner_list_complete) are read from meta.pipeline_setting and
  recorded on the run.
* Data-quality checks are written to meta.dq_check_result for the run. Any check
  with severity ERROR that fails stops the run: the whole build is rolled back
  and the previous good state stays in place. The failed attempt is still logged.
* Dimensions keep their keys between runs (upsert by natural key); facts are rebuilt.
Exit codes: 0 succeeded | 1 data-quality ERROR (rolled back) | 4 other error (rolled back)
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql

import os
SQL_DIR = Path(os.environ.get("DW_TRANSFORM_SQL_DIR", Path(__file__).parent / "sql"))
CORE_TABLES = ["dim_product", "dim_location", "dim_channel", "dim_partner", "dim_order", "dim_courier",
               "fact_sales_line", "fact_return_line", "bridge_return_goods_receipt", "fact_stock_transfer_line",
               "fact_purchase_order_line", "fact_goods_receipt_line", "bridge_goods_receipt_grn", "fact_partner_sellout",
               "fact_inventory_snapshot", "fact_stock_movement", "fact_shipment", "bridge_shipment_sku"]


class QualityGateFailed(Exception):
    pass


def run(dbname: str, started_by: str) -> int:
    with psycopg.connect(dbname=dbname, autocommit=False) as conn:
        s = dict(conn.execute("SELECT setting_key, setting_value FROM meta.pipeline_setting").fetchall())
        conn.rollback()
        start, end = s["prototype_period_start"], s["prototype_period_end"]
        complete = s.get("partner_list_complete", "false").lower() == "true"
        try:
            run_id = conn.execute(
                "INSERT INTO meta.transform_run (period_start, period_end, partner_list_complete, started_by) "
                "VALUES (%s, %s, %s, %s) RETURNING transform_run_id", (start, end, complete, started_by)).fetchone()[0]
            # utility statements take no bind parameters: values are quoted as SQL literals
            conn.execute(sql.SQL("CREATE TEMP TABLE ctx ON COMMIT DROP AS SELECT {}::BIGINT AS run_id, {}::DATE AS period_start, "
                                 "{}::DATE AS period_end, {}::BOOLEAN AS partner_list_complete")
                         .format(sql.Literal(run_id), sql.Literal(start), sql.Literal(end), sql.Literal(complete)))
            for f in sorted(SQL_DIR.glob("*.sql")):
                t0 = time.time()
                conn.execute(f.read_text(encoding="utf-8"))
                print(f"  {f.name:32s} {time.time() - t0:5.1f}s")
            failed = conn.execute("SELECT check_name, details FROM meta.dq_check_result WHERE transform_run_id = %s "
                                  "AND severity = 'ERROR' AND outcome = 'FAIL'", (run_id,)).fetchall()
            if failed:
                raise QualityGateFailed("; ".join(f"{n}: {d}" for n, d in failed))
            counts = {t: conn.execute(f"SELECT count(*) FROM core.{t}").fetchone()[0] for t in CORE_TABLES}
            conn.execute("UPDATE meta.transform_run SET status='SUCCEEDED', finished_at=CURRENT_TIMESTAMP, row_counts=%s "
                         "WHERE transform_run_id=%s", (json.dumps(counts), run_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            conn.execute("INSERT INTO meta.transform_run (status, period_start, period_end, partner_list_complete, "
                         "started_by, finished_at, notes) VALUES ('FAILED', %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)",
                         (start, end, complete, started_by, f"{type(e).__name__}: {e}"[:2000]))
            conn.commit()
            print(f"RUN FAILED - rolled back, previous build unchanged.\n  {type(e).__name__}: {e}", file=sys.stderr)
            return 1 if isinstance(e, QualityGateFailed) else 4
        warns = conn.execute("SELECT check_name, failed_row_count, details FROM meta.dq_check_result "
                             "WHERE transform_run_id = %s AND outcome = 'FAIL' ORDER BY check_name", (run_id,)).fetchall()
    print(f"RUN {run_id} SUCCEEDED  (period {start} .. {end}, partner list complete: {complete})")
    for t, n in counts.items():
        print(f"  {t:30s} {n:8d}")
    if warns:
        print(f"  {len(warns)} warning(s):")
        for n, c, d in warns:
            print(f"    WARN {n} [{c}]: {d[:160]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m transform")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("database"); r.add_argument("--started-by", default=getpass.getuser())
    a = ap.parse_args()
    return run(a.database, a.started_by)


if __name__ == "__main__":
    sys.exit(main())
