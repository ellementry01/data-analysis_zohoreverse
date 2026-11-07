"""Finding numbers in text and checking that each one comes from the data.

Used by the assistant (an answer may only quote numbers its tools returned) and by the eval runner. Matching allows for
rounding and Indian display units: "₹3.86 Cr" matches 3,86,12,345; "7.8%" matches 0.0784; "25 hours" matches 25.4.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

_NUM = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?(?:\s*(?:cr|crore|crores|lakh|lakhs|l|k|%))?(?![\w])", re.I)
_MULT = {"cr": 1e7, "crore": 1e7, "crores": 1e7, "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "k": 1e3}
# dates, months and period labels are not data values
DATES = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}-\d{2}\b|"
                   r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(?:\s+\d{4})?\b|"
                   r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}\b|\bfy\s*\d{2,4}(?:\s*[-–]\s*\d{2,4})?\b|"
                   r"\b(?:19|20)\d{2}\b|\b\d{2}-\d{2}\b", re.I)

# references, not values: "(memory #12)", "#3", data issue codes "D-112"
REFS = re.compile(r"#\s*\d+(?!\d)|\b[A-Z]{1,4}-\d{1,5}\b")


@dataclass
class Num:
    token: str
    values: list[float]      # alternatives ("7.8%" -> 0.078 and 7.8)
    slack: list[float]       # rounding allowance for each alternative


def number_tokens(text: str) -> list[Num]:
    out = []
    for m in _NUM.finditer(text or ""):
        tok = m.group(0).strip()
        unit = re.search(r"(crores|crore|cr|lakhs|lakh|l|k|%)$", tok, re.I)
        mant = re.sub(r"[^\d.+-]", "", tok[: unit.start()] if unit else tok)
        try:
            num = float(mant)
        except ValueError:
            continue
        decimals = len(mant.split(".")[1]) if "." in mant else 0
        half = 0.5 * 10 ** -decimals
        u = unit.group(1).lower() if unit else ""
        if u == "%":
            out.append(Num(tok, [num / 100, num], [half / 100, half]))
        else:
            mult = _MULT.get(u, 1)
            out.append(Num(tok, [num * mult], [half * mult]))
    return out


def parse_numbers(text: str) -> list[float]:
    return [v for n in number_tokens(text) for v in n.values]


def matches(n: Num, target: float, tol: float = 0.005) -> bool:
    return any(abs(v - target) <= max(s, abs(target) * tol, 1e-9) for v, s in zip(n.values, n.slack))


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not (isinstance(v, float) and math.isnan(v))


def result_numbers(columns: list[dict], rows: list[list]) -> list[float]:
    """Numbers an answer may quote from one result: cells, numbers inside labels, the row count, and each measure's
    total, min, max and shares of the total."""
    out: list[float] = [float(len(rows))]
    for row in rows:
        for v in row:
            if _is_num(v):
                out.append(float(v))
            elif isinstance(v, str):
                out += parse_numbers(v)
    for i, c in enumerate(columns):
        if c.get("role") == "dimension":
            continue
        vals = [float(r[i]) for r in rows if i < len(r) and _is_num(r[i])]
        if not vals:
            continue
        total = sum(vals)
        out += [total, max(vals), min(vals)]
        if total:
            out += [v / total for v in vals] + [100 * v / total for v in vals]
    return out


def ungrounded(text: str, allowed: list[float]) -> list[str]:
    """Number tokens in `text` that match none of the allowed values (dates and small counts are skipped)."""
    bad = []
    for n in number_tokens(REFS.sub(" ", DATES.sub(" ", text or ""))):
        if all(v == int(v) and 0 <= v <= 12 for v in n.values):
            continue  # small counts and ranks ("top 5", "2 channels") are words more than data
        if not any(matches(n, a) for a in allowed):
            bad.append(n.token)
    return bad
