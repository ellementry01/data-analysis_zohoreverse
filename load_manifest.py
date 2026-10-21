"""
Loads every file listed in an exports MANIFEST.tsv, in a safe order, through the normal loader (dw.py loader load).

    python load_manifest.py <exports_dir> [--dry-run] [--only SOURCE ...]

Order: product master, then transactional files (oldest period first, so re-exports win), PO state exports,
stock snapshots, dispatch, platform sell-out. Snapshot / state / master rows must carry their as-of date in the
manifest. A file already loaded (same bytes) is skipped by the loader itself. The run stops at the first rejected file.
Use DW_DATABASE to load into another database (e.g. a trial copy).
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORDER = ["PRODUCT_MASTER", "ERP_RETAIL_SALES", "ERP_DOMESTIC_SALES", "ERP_RETAIL_RETURN", "ERP_DOMESTIC_RETURN",
         "ERP_STOCK_TRANSFER_OUT", "ERP_STOCK_TRANSFER_IN", "ERP_PURCHASE_ORDER", "ERP_INVENTORY_SNAPSHOT",
         "BLINKIT_INVENTORY", "INSTAMART_INVENTORY", "WMS_DISPATCH", "BLINKIT_SALES", "INSTAMART_SALES"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exports", type=Path); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", nargs="*"); ap.add_argument("--loaded-by", default="load_manifest")
    a = ap.parse_args(argv)
    rows = list(csv.DictReader(open(a.exports / "MANIFEST.tsv", encoding="utf-8"), delimiter="\t"))
    rows = [r for r in rows if r["source"] in ORDER and not r["file"].startswith("_originals/")   # as received, not loadable
            and (not a.only or r["source"] in a.only)]
    rows.sort(key=lambda r: (ORDER.index(r["source"]), r["as_of"] or "", r["file"]))
    for r in rows:
        cmd = [sys.executable, str(HERE / "dw.py"), "loader", "load", r["source"], str((a.exports / r["file"]).resolve()),
               "--loaded-by", a.loaded_by]
        if r["as_of"]:
            cmd += ["--as-of", r["as_of"]]
        if a.dry_run:
            cmd += ["--dry-run"]
        p = subprocess.run(cmd, capture_output=True, text=True)
        out = (p.stdout + p.stderr).strip().splitlines()
        print(f"[{p.returncode}] {r['file']}: {out[0] if out else ''}")
        for extra in out[1:]:
            print("     ", extra)
        if p.returncode not in (0, 3):                 # 3 = already loaded, nothing done
            print("stopped: fix the file or the contract, then run again (loaded files are skipped)")
            return p.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
