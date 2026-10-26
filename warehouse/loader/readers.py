"""
Readers: turn a source file into (sheet_name -> list of rows), every cell as TEXT or None.

The one rule: the text must represent the cell's value EXACTLY. No trimming, no
rounding, no date re-interpretation. Cleaning belongs to staging, where it is
visible and tested.

Conversions (and only these):
  empty cell / ''          -> None
  int                      -> '123'
  float with integer value -> '124118580'   (Excel stores all numbers as floats;
                                             '124118580.0' would corrupt IDs)
  other float              -> shortest round-trip repr, e.g. 705.93 -> '705.93'
  bool                     -> 'TRUE' / 'FALSE'
  datetime / date / time   -> ISO 'YYYY-MM-DD HH:MM:SS' / 'YYYY-MM-DD' / 'HH:MM:SS'
  str                      -> unchanged (text dates like '08/04/2026;08/04/2026'
                                         arrive exactly as typed)
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import math
from pathlib import Path


class ReaderError(Exception):
    """Raised when a file cannot be read faithfully."""


def cell_to_text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):                      # before int: bool is a subclass of int
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            raise ReaderError(f"non-finite number in cell: {v!r}")
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, dt.date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, dt.time):
        return v.strftime("%H:%M:%S")
    if isinstance(v, str):
        return None if v == "" else v
    raise ReaderError(f"unsupported cell type {type(v).__name__}: {v!r}")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_xlsx(path: Path) -> dict[str, list[list[str | None]]]:
    from openpyxl import load_workbook
    # data_only=True: cached values, never formula text. read_only: streaming, low memory.
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        return {ws.title: [[cell_to_text(v) for v in row] for row in ws.iter_rows(values_only=True)]
                for ws in wb.worksheets}
    finally:
        wb.close()


def _read_xls(path: Path) -> dict[str, list[list[str | None]]]:
    import xlrd
    book = xlrd.open_workbook(path, on_demand=True)
    out = {}
    try:
        for name in book.sheet_names():
            sh = book.sheet_by_name(name)
            rows = []
            for r in range(sh.nrows):
                row = []
                for c in range(sh.ncols):
                    ctype, val = sh.cell_type(r, c), sh.cell_value(r, c)
                    if ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                        row.append(None)
                    elif ctype == xlrd.XL_CELL_DATE:
                        row.append(cell_to_text(xlrd.xldate_as_datetime(val, book.datemode)))
                    elif ctype == xlrd.XL_CELL_BOOLEAN:
                        row.append(cell_to_text(bool(val)))
                    elif ctype == xlrd.XL_CELL_ERROR:
                        row.append(xlrd.error_text_from_code.get(val, f"#ERR{val}"))
                    else:
                        row.append(cell_to_text(val))
                rows.append(row)
            out[name] = rows
            book.unload_sheet(name)
    finally:
        book.release_resources()
    return out


def _read_csv(path: Path) -> dict[str, list[list[str | None]]]:
    # utf-8-sig strips a BOM if present; any other encoding problem fails loudly.
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [[None if v == "" else v for v in row] for row in csv.reader(f)]
    return {"CSV": rows}


def read_workbook(path: Path) -> dict[str, list[list[str | None]]]:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):     # .xlsm: same format; cell values only, macros are never run
        return _read_xlsx(path)
    if suffix == ".xls":
        return _read_xls(path)
    if suffix == ".csv":
        return _read_csv(path)
    raise ReaderError(f"unsupported file type '{suffix}' (expected .xlsx, .xlsm, .xls or .csv)")


def is_empty_row(row) -> bool:
    return all(v is None or (isinstance(v, str) and v.strip() == "") for v in row)
