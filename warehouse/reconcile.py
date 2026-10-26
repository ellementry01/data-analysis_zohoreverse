"""
Independent reconciliation: totals computed straight from the export files with pandas (no warehouse code), compared with
the warehouse after a transform run. Prints one line per check and exits 1 if any check differs.

    python reconcile.py <exports_dir>           (DW_DATABASE selects the database, default the one in .env)

Rules applied here are the documented ones, written independently of the SQL:
  retail value excl. GST = PRODDOCVALUE (BR-002); domestic = Taxable (BR-003); only lines with quantity > 0 and a value >= 0;
  business dates within the period setting (BR-020); returns dated by RETURNDATE (retail) / BILLDATE (domestic, BR-023);
  Blinkit counts DELIVERED only (BR-018); dispatch counted per outbound delivery.
"""
from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


def sql(q: str) -> list[list[str]]:
    p = subprocess.run([sys.executable, str(HERE / "dw.py"), "psql", "-At", "-F", "\t", "-c", q], capture_output=True, text=True)
    if p.returncode:
        sys.exit(p.stderr)
    return [l.split("\t") for l in p.stdout.strip().splitlines() if l]


def files(exports: Path, source: str) -> list[Path]:
    rows = csv.DictReader(open(exports / "MANIFEST.tsv", encoding="utf-8"), delimiter="\t")
    return [exports / r["file"] for r in rows if r["source"] == source and not r["file"].startswith("_originals/")]


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def main(exports: Path) -> int:
    start, end = [pd.Timestamp(v) for v in sql("SELECT max(setting_value) FILTER (WHERE setting_key = 'prototype_period_start'), "
                                               "max(setting_value) FILTER (WHERE setting_key = 'prototype_period_end') FROM meta.pipeline_setting")[0]]
    inside = lambda d: (d >= start) & (d <= end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
    checks = []

    def check(name, ours, theirs, tol=0.01):
        ok = abs(float(ours) - float(theirs)) <= tol
        checks.append(ok)
        print(f"{'OK  ' if ok else 'DIFF'} {name:58s} files {float(ours):>18,.2f}   warehouse {float(theirs):>18,.2f}")

    # ---- sales: re-exports overlap by bill number; the latest file per bill wins, as in staging
    def lines(source, date_col, value_col, qty_col, key="BILLNUM"):
        frames = []
        for i, f in enumerate(files(exports, source)):
            d = pd.read_excel(f, sheet_name="Sheet1", dtype=str); d["_file"] = i; frames.append(d)
        d = pd.concat(frames, ignore_index=True)
        d["_latest"] = d.groupby(d[key].str.strip())["_file"].transform("max")
        d = d[d["_file"] == d["_latest"]]
        d["_date"] = pd.to_datetime(d[date_col], errors="coerce"); d["_v"] = num(d[value_col]); d["_q"] = num(d[qty_col])
        return d[inside(d["_date"]) & (d["_q"] > 0)]

    r = lines("ERP_RETAIL_SALES", "BILLDATE", "PRODDOCVALUE", "PRODCONTACTQTY")
    check("retail invoice lines in period", len(r), sql("SELECT count(*) FROM core.fact_sales_line WHERE source_name = 'ERP_RETAIL_SALES'")[0][0], 0)
    check("retail invoices excl. GST (PRODDOCVALUE >= 0)", r.loc[r["_v"] >= 0, "_v"].sum(),
          sql("SELECT sum(net_sales_amount) FROM core.fact_sales_line WHERE source_name = 'ERP_RETAIL_SALES' AND net_amount_method = 'SOURCE'")[0][0])
    d = lines("ERP_DOMESTIC_SALES", "BILLDATETIME", "Taxable", "Quantity")
    check("domestic invoice lines in period", len(d), sql("SELECT count(*) FROM core.fact_sales_line WHERE source_name = 'ERP_DOMESTIC_SALES'")[0][0], 0)
    check("domestic invoices excl. GST (Taxable >= 0)", d.loc[d["_v"] >= 0, "_v"].sum(),
          sql("SELECT sum(net_sales_amount) FROM core.fact_sales_line WHERE source_name = 'ERP_DOMESTIC_SALES' AND net_amount_method = 'SOURCE'")[0][0])
    rr = lines("ERP_RETAIL_RETURN", "RETURNDATE", "PRODDOCVALUE", "PRODCONTACTQTY", key="RETURNNUM")
    check("retail return lines in period", len(rr), sql("SELECT count(*) FROM core.fact_return_line WHERE source_name = 'ERP_RETAIL_RETURN'")[0][0], 0)
    check("retail returns excl. GST", rr.loc[rr["_v"] >= 0, "_v"].sum(),
          sql("SELECT sum(net_return_amount) FROM core.fact_return_line WHERE source_name = 'ERP_RETAIL_RETURN' AND net_amount_method = 'SOURCE'")[0][0])

    # ---- monthly retail invoices (what a sales chart shows)
    wh = dict((m, float(v)) for m, v in sql(
        "SELECT to_char(d.month_start_date, 'YYYY-MM'), sum(s.net_sales_amount) FROM core.fact_sales_line s "
        "JOIN core.dim_date d ON d.date_key = s.bill_date_key WHERE s.source_name = 'ERP_RETAIL_SALES' AND s.net_amount_method = 'SOURCE' GROUP BY 1"))
    pos = r[r["_v"] >= 0]
    for m, v in pos.groupby(pos["_date"].dt.strftime("%Y-%m"))["_v"].sum().items():
        check(f"retail invoices excl. GST, {m}", v, wh.get(m, 0))

    # ---- dispatch
    w = pd.concat((pd.read_excel(f, dtype={"Outbound Delivery No": str}) for f in files(exports, "WMS_DISPATCH")), ignore_index=True)
    w = w.drop_duplicates("Outbound Delivery No", keep="last")
    w = w[inside(pd.to_datetime(w["Order Date"]))]
    check("dispatch deliveries in period", len(w), sql("SELECT count(*) FROM core.fact_shipment")[0][0], 0)
    check("dispatch RTO deliveries", w["Status"].isin(["RTO Delivered", "isRTOInitiated"]).sum(),
          sql("SELECT count(*) FROM core.fact_shipment WHERE is_rto")[0][0], 0)

    # ---- platform sell-out (demand)
    i = pd.concat((pd.read_excel(f, sheet_name="Sales Report") for f in files(exports, "INSTAMART_SALES")), ignore_index=True)
    i = i[inside(pd.to_datetime(i["ORDERED_DATE"])) & i["STORE_ID"].notna()]
    check("Instamart units sold in period", num(i["UNITS_SOLD"]).sum(),
          sql("SELECT coalesce(sum(units_sold), 0) FROM core.fact_partner_sellout WHERE source_name = 'INSTAMART_SALES'")[0][0])
    b = pd.concat((pd.read_excel(f, sheet_name="Sheet1", dtype=str) for f in files(exports, "BLINKIT_SALES")), ignore_index=True)
    b = b[inside(pd.to_datetime(b["Order Date"])) & (b["Order Status"].str.upper().str.strip() == "DELIVERED")]
    check("Blinkit delivered units in period", num(b["Quantity"]).sum(),
          sql("SELECT coalesce(sum(units_sold), 0) FROM core.fact_partner_sellout WHERE source_name = 'BLINKIT_SALES'")[0][0])

    print(f"\n{sum(checks)} of {len(checks)} checks agree")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
