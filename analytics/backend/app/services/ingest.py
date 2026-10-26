"""Reading Excel/CSV files, header detection, type inference and data-quality profiling."""
from __future__ import annotations

import csv
import io
import os
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .naming import humanize, unique_names
from .typeinfer import coerce, infer_type, normalize_nulls

ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
PREVIEW_ROWS = 50


class IngestError(ValueError):
    pass


@dataclass
class Sheet:
    name: str
    grid: pd.DataFrame  # raw cells, no header applied


def read_grids(path: str, filename: str) -> list[Sheet]:
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".csv", ".tsv", ".txt"):
        return [Sheet(os.path.splitext(filename)[0], _read_csv_grid(path, ext))]
    if ext in (".xlsx", ".xlsm", ".xls"):
        if ext != ".xls":
            _check_zip_bomb(path)
        engine = "xlrd" if ext == ".xls" else "openpyxl"
        try:
            sheets = pd.read_excel(path, sheet_name=None, header=None, engine=engine, dtype=object)
        except Exception as e:
            raise IngestError(f"Could not read workbook: {e}") from e
        out = [Sheet(str(n), g) for n, g in sheets.items()]
        if not out:
            raise IngestError("The workbook has no sheets")
        return out
    raise IngestError(f"Unsupported file type '{ext}'. Upload .csv, .tsv, .txt, .xlsx, .xlsm or .xls")


MAX_XLSX_UNCOMPRESSED = 2 * 1024 ** 3  # 2 GB of XML is far beyond any real workbook
MAX_XLSX_RATIO = 200  # typical xlsx compress ~5-20x; decompression bombs reach 1000x+


def _check_zip_bomb(path: str) -> None:
    """Reject .xlsx files whose declared uncompressed size is absurd before handing them to openpyxl."""
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            total = sum(i.file_size for i in zf.infolist())
    except zipfile.BadZipFile as e:
        raise IngestError("The file is not a valid Excel workbook") from e
    compressed = max(os.path.getsize(path), 1)
    if total > MAX_XLSX_UNCOMPRESSED or (total > 100 * 1024 ** 2 and total / compressed > MAX_XLSX_RATIO):
        raise IngestError("The workbook expands to an unreasonable size and was rejected")


def _read_csv_grid(path: str, ext: str) -> pd.DataFrame:
    raw = open(path, "rb").read()
    if not raw.strip():
        raise IngestError("The file is empty")
    text = None
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise IngestError("Could not decode file text")
    sample = text[:20000]
    delim = "\t" if ext == ".tsv" else ","
    if ext != ".tsv":
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delim = ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    width = max((len(r) for r in rows), default=0)
    rows = [r + [None] * (width - len(r)) for r in rows]
    df = pd.DataFrame(rows, dtype=object)
    return df.replace({"": None})


def detect_header_row(grid: pd.DataFrame) -> int:
    """Pick the first row (within 20) that looks like a header: mostly non-empty strings followed by data."""
    best, best_score = 0, -1.0
    limit = min(len(grid), 20)
    width = max(grid.shape[1], 1)
    for i in range(limit):
        row = grid.iloc[i]
        nonnull = row.dropna()
        if len(nonnull) == 0:
            continue
        strs = sum(isinstance(v, str) and not _looks_numeric(v) for v in nonnull)
        fill = len(nonnull) / width
        unique = nonnull.astype(str).nunique() / len(nonnull)
        score = fill * 0.5 + (strs / len(nonnull)) * 0.4 + unique * 0.1
        if score > best_score + 0.05:
            best, best_score = i, score
        if fill >= 0.8 and strs / len(nonnull) >= 0.8:
            return i
    return best


def _looks_numeric(v: str) -> bool:
    return bool(re.fullmatch(r"[\s$₹€£(-]*[\d,]+(\.\d+)?%?\)?\s*", v))


def frame_from_grid(grid: pd.DataFrame, header_row: int) -> tuple[pd.DataFrame, list[str]]:
    grid = grid.dropna(axis=1, how="all")
    if header_row >= len(grid):
        raise IngestError("Header row is beyond the end of the sheet")
    headers_raw = grid.iloc[header_row].tolist()
    headers = []
    for i, h in enumerate(headers_raw):
        h = "" if h is None or (isinstance(h, float) and np.isnan(h)) else re.sub(r"\s+", " ", str(h)).strip()
        headers.append(h or f"Column {i + 1}")
    # de-duplicate display headers
    seen: dict[str, int] = {}
    for i, h in enumerate(headers):
        if h in seen:
            seen[h] += 1
            headers[i] = f"{h} ({seen[h]})"
        else:
            seen[h] = 1
    body = grid.iloc[header_row + 1:].reset_index(drop=True)
    body.columns = headers
    body = body.apply(normalize_nulls)
    body = body.dropna(how="all").reset_index(drop=True)
    # drop repeated header lines (common in exported reports)
    is_header = body.apply(lambda r: sum(str(v) == h for v, h in zip(r, headers)) >= max(2, len(headers) // 2), axis=1)
    body = body[~is_header].reset_index(drop=True)
    # drop "Total"/"Grand total" footer rows
    first = body.columns[0] if len(body.columns) else None
    if first is not None and len(body):
        tot = body[first].astype(str).str.strip().str.lower().isin({"total", "grand total", "totals", "sum"})
        body = body[~tot].reset_index(drop=True)
    return body, headers


def profile(df: pd.DataFrame, headers: list[str]) -> dict:
    names = unique_names(headers)
    cols = []
    for h, name in zip(headers, names):
        s = df[h]
        dtype, fails = infer_type(s, h)
        nonnull = s.dropna()
        variants = {}
        if dtype == "text" and len(nonnull):
            norm = nonnull.astype(str).str.strip().str.lower()
            groups = nonnull.astype(str).groupby(norm).agg(lambda x: sorted(set(x)))
            variants = {k: v for k, v in groups.items() if len(v) > 1}
        cols.append({
            "source_name": h,
            "name": name,
            "display_name": humanize(h) if h.islower() or "_" in h else h,
            "inferred_type": dtype,
            "null_count": int(s.isna().sum()),
            "distinct_count": int(nonnull.astype(str).nunique()),
            "parse_failures": fails,
            "samples": [str(v) for v in nonnull.astype(str).unique()[:5]],
            "inconsistent_variants": dict(list(variants.items())[:5]),
        })
    dup = int(df.astype(str).duplicated().sum()) if len(df) else 0
    warnings = []
    if dup:
        warnings.append({"level": "warning", "code": "duplicates", "message": f"{dup} duplicate rows"})
    for c in cols:
        if len(df) and c["null_count"] / len(df) > 0.3:
            warnings.append({"level": "info", "code": "missing", "column": c["name"],
                             "message": f"{c['source_name']}: {c['null_count']} of {len(df)} values are empty"})
        if c["parse_failures"]:
            warnings.append({"level": "warning", "code": "type_conflict", "column": c["name"],
                             "message": f"{c['source_name']}: {c['parse_failures']} values do not match type {c['inferred_type']} and will be imported empty"})
        if c["inconsistent_variants"]:
            ex = next(iter(c["inconsistent_variants"].values()))
            warnings.append({"level": "info", "code": "inconsistent_values", "column": c["name"],
                             "message": f"{c['source_name']}: inconsistent spellings, e.g. {', '.join(map(repr, ex[:3]))}"})
        if c["source_name"].startswith("Column "):
            warnings.append({"level": "info", "code": "missing_header", "column": c["name"],
                             "message": f"A column had no header and was named '{c['source_name']}'"})
    return {"columns": cols, "row_count": int(len(df)), "duplicate_rows": dup, "warnings": warnings}


def preview_sheet(sheet: Sheet, header_row: int | None = None) -> dict:
    grid = sheet.grid
    if grid.empty or grid.dropna(how="all").empty:
        return {"sheet": sheet.name, "empty": True, "header_row": 0, "columns": [], "rows": [], "row_count": 0,
                "warnings": [{"level": "warning", "code": "empty", "message": "Sheet is empty"}]}
    hr = detect_header_row(grid) if header_row is None else header_row
    df, headers = frame_from_grid(grid, hr)
    prof = profile(df, headers)
    rows = df.head(PREVIEW_ROWS).astype(object).where(df.head(PREVIEW_ROWS).notna(), None)
    return {
        "sheet": sheet.name,
        "empty": False,
        "header_row": hr,
        "raw_top_rows": [[None if pd.isna(v) else str(v) for v in r] for r in grid.head(8).itertuples(index=False)],
        "rows": [[_cell(v) for v in r] for r in rows.itertuples(index=False)],
        **prof,
    }


def _cell(v):
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else float(v)
    return str(v)


def build_frame(sheet: Sheet, header_row: int, column_specs: list[dict], options: dict) -> tuple[pd.DataFrame, dict]:
    """Apply user column choices; returns frame keyed by physical names plus a cleaning report."""
    df, headers = frame_from_grid(sheet.grid, header_row)
    report = {"dropped_duplicates": 0, "source_rows": int(len(df))}
    keep = {}
    for spec in column_specs:
        if not spec.get("include", True):
            continue
        src = spec["source_name"]
        if src not in df.columns:
            raise IngestError(f"Column '{src}' not found in sheet")
        keep[spec["name"]] = df[src]
    out = pd.DataFrame(keep)
    if options.get("drop_duplicates", False) and len(out):
        before = len(out)
        out = out[~out.astype(str).duplicated()].reset_index(drop=True)
        report["dropped_duplicates"] = before - len(out)
    return out, report


def coerce_preview(series: pd.Series, dtype: str) -> dict:
    _, failed, bad = coerce(series, dtype)
    return {"failed": failed, "samples": bad}
