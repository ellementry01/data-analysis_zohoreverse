"""Type inference and coercion for messy spreadsheet values."""
from __future__ import annotations

import re
import warnings

import numpy as np
import pandas as pd

DATA_TYPES = ("text", "integer", "decimal", "date", "datetime", "boolean")
PG_TYPES = {
    "text": "TEXT",
    "integer": "BIGINT",
    "decimal": "NUMERIC",
    "date": "DATE",
    "datetime": "TIMESTAMP",
    "boolean": "BOOLEAN",
}

_TRUE = {"true", "yes", "y", "t", "1"}
_FALSE = {"false", "no", "n", "f", "0"}
_NULLS = {"", "na", "n/a", "null", "none", "nan", "-", "--", "#n/a", "nil", "?", "#value!", "#ref!", "#div/0!"}
_NUM_CLEAN = re.compile(r"[\s,₹$€£¥]|(?i:rs\.?|inr|usd|eur)")
_DATE_FORMATS = [
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y",
    "%b %d, %Y", "%d-%b-%y", "%d/%m/%y", "%m/%d/%y", "%Y%m%d", "%B %d, %Y", "%d %B %Y",
]
_DATETIME_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M",
                     "%d-%m-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S.%f"]
THRESHOLD = 0.9


def normalize_nulls(s: pd.Series) -> pd.Series:
    """Strip text and convert common null markers to NaN (keeps non-string values untouched)."""
    def fix(v):
        if isinstance(v, str):
            v2 = re.sub(r"\s+", " ", v).strip()
            return np.nan if v2.lower() in _NULLS else v2
        return v
    return s.map(fix)


def _parse_number(v) -> float | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (bool, np.bool_)):
        return None
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    s = str(v).strip()
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    pct = s.endswith("%")
    if pct:
        s = s[:-1]
    s = _NUM_CLEAN.sub("", s)
    if s.endswith("-"):  # trailing minus (accounting exports)
        s, neg = s[:-1], True
    try:
        f = float(s)
    except ValueError:
        return None
    if pct:
        f /= 100
    return -f if neg else f


def parse_numbers(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.map(_parse_number), errors="coerce")


def _best_format(values: pd.Series, formats: list[str]) -> tuple[str | None, int]:
    best, best_ok = None, -1
    sample = values.head(500)
    for fmt in formats:
        ok = pd.to_datetime(sample, format=fmt, errors="coerce").notna().sum()
        if ok > best_ok:
            best, best_ok = fmt, ok
    return best, best_ok


def parse_dates(s: pd.Series, with_time: bool = False) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        out = pd.to_datetime(s, errors="coerce")
    else:
        strs = s.map(lambda v: v.isoformat() if hasattr(v, "isoformat") else (np.nan if pd.isna(v) else str(v).strip()))
        nonnull = strs.dropna()
        fmt, ok = _best_format(nonnull, _DATETIME_FORMATS + _DATE_FORMATS)
        if fmt and ok >= 1:
            out = pd.to_datetime(strs, format=fmt, errors="coerce")
            # values not matching the dominant format (files often mix ISO and dd/mm/yyyy): detect the
            # best format for the remainder instead of guessing month/day order
            dayfirst = fmt.startswith("%d")
            for _ in range(3):
                rest = out.isna() & strs.notna()
                if not rest.any():
                    break
                fmt2, ok2 = _best_format(strs[rest], _DATETIME_FORMATS + _DATE_FORMATS)
                if not fmt2 or ok2 == 0:
                    break
                dayfirst = dayfirst or fmt2.startswith("%d")
                out[rest] = pd.to_datetime(strs[rest], format=fmt2, errors="coerce")
            rest = out.isna() & strs.notna()
            if rest.any():
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    out[rest] = pd.to_datetime(strs[rest], errors="coerce", dayfirst=dayfirst)
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                out = pd.to_datetime(strs, errors="coerce", format="mixed")
    if not with_time:
        out = out.dt.normalize()
    return out


def parse_bools(s: pd.Series) -> pd.Series:
    def b(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        if isinstance(v, (bool, np.bool_)):
            return bool(v)
        t = str(v).strip().lower()
        if t in _TRUE:
            return True
        if t in _FALSE:
            return False
        return None
    return s.map(b).astype("object")


def infer_type(s: pd.Series, header: str = "") -> tuple[str, int]:
    """Return (type, number of non-null values that would fail conversion)."""
    nonnull = s.dropna()
    n = len(nonnull)
    if n == 0:
        return "text", 0
    if pd.api.types.is_bool_dtype(s):
        return "boolean", 0
    if pd.api.types.is_datetime64_any_dtype(s):
        has_time = (nonnull.dt.normalize() != nonnull).any()
        return ("datetime" if has_time else "date"), 0

    sample = nonnull.head(2000)
    m = len(sample)
    strs = sample.map(lambda v: str(v).strip().lower())
    distinct = set(strs.unique())
    if distinct and distinct <= (_TRUE | _FALSE) and not distinct <= {"1", "0"}:
        return "boolean", 0

    nums = sample.map(_parse_number)
    num_ok = nums.notna().sum()
    if num_ok >= m * THRESHOLD:
        vals = nums.dropna()
        # identifiers such as zip codes / phone numbers with leading zeros stay text
        lead_zero = strs.str.match(r"^0\d+$").mean() > 0.2
        if lead_zero:
            return "text", 0
        fails = int(len(nonnull) - parse_numbers(nonnull).notna().sum())
        # look for a decimal point after removing currency markers ("Rs.2,500" is a whole number)
        cleaned = strs.map(lambda v: _NUM_CLEAN.sub("", v))
        if (vals == vals.round()).all() and not cleaned.str.contains(r"\.\d", regex=True).any() and not strs.str.endswith("%").any():
            return "integer", fails
        return "decimal", fails

    looks_date = strs.str.contains(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{1,2}[ -][a-z]{3}|[a-z]{3,9} \d{1,2},? \d{4}", regex=True).mean()
    if looks_date >= THRESHOLD or any(k in header.lower() for k in ("date", "time", "day", "month", "_at", "dt")) and looks_date > 0.5:
        parsed = parse_dates(sample, with_time=True)
        ok = parsed.notna().sum()
        if ok >= m * THRESHOLD:
            full = parse_dates(nonnull, with_time=True)
            fails = int(full.isna().sum())
            valid = full.dropna()
            has_time = (valid.dt.normalize() != valid).any()
            return ("datetime" if has_time else "date"), fails
    return "text", 0


def coerce(s: pd.Series, dtype: str) -> tuple[pd.Series, int, list[str]]:
    """Convert a column; returns (series, failed count, sample of failing raw values)."""
    nonnull_mask = s.notna()
    if dtype == "text":
        out = s.map(lambda v: v if pd.isna(v) else (v.isoformat() if hasattr(v, "isoformat") else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))))
        return out.astype("object"), 0, []
    if dtype in ("integer", "decimal"):
        out = parse_numbers(s)
        if dtype == "integer":
            frac = out.notna() & (out != out.round())
            out = out.round().astype("Int64") if not frac.any() else out
    elif dtype in ("date", "datetime"):
        out = parse_dates(s, with_time=dtype == "datetime")
    elif dtype == "boolean":
        out = parse_bools(s)
    else:
        raise ValueError(f"Unknown type {dtype}")
    failed_mask = nonnull_mask & out.isna()
    bad = [str(v) for v in s[failed_mask].unique()[:5]]
    return out, int(failed_mask.sum()), bad
