"""Evaluation runner for the assistants.

An eval set is a YAML file in evals/sets/. Each case asks one question and states what a correct answer contains:

    - id: locations-count
      question: How many locations are there?
      expect:
        sql: SELECT COUNT(*) FROM locations        # or  spec: {measures: [...], ...}  (a QuerySpec)
        column: null                               # which column holds the expected number (default: first numeric)
        tolerance: 0.005                           # relative, default 0.5% (covers "3.86 Cr" style rounding)
      must_mention: [locations]                    # every item must appear (an item may be a list = any of)
      must_not_mention: []

Expected numbers are computed at run time from the app database (through the read-only SQL console or the governed
query endpoint), never typed by hand, so a set stays valid when the data changes.

The default engine is the offline semantic engine, which costs nothing. --live uses Claude and needs EVAL_LIVE_OK=1
(live calls cost money and need the owner's OK).
"""
from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

SETS_DIR = Path(__file__).parent / "sets"
_NUM = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?\s*(?:cr|crore|l|lakh|lakhs|k|%)?(?![\w])", re.I)
_MULT = {"cr": 1e7, "crore": 1e7, "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "k": 1e3}


class Transport:
    """POST/GET JSON against the app (HTTP by default; tests pass an in-process client)."""

    def __init__(self, base: str, user: str | None = None):
        self.base, self.user = base.rstrip("/"), user

    def post(self, path: str, body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.user:
            headers["X-User-Email"] = self.user
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raise EvalError(f"{path}: HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e


class EvalError(RuntimeError):
    pass


@dataclass
class CaseResult:
    id: str
    passed: bool
    expected: float | None = None
    found: list[float] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    engine: str | None = None
    model: str | None = None
    cost_inr: float = 0.0
    seconds: float = 0.0


def load_set(name_or_path: str) -> list[dict]:
    import yaml

    p = Path(name_or_path)
    if not p.suffix:
        p = SETS_DIR / f"{name_or_path}.yaml"
    cases = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    ids = [c.get("id") for c in cases]
    if any(not i for i in ids) or len(ids) != len(set(ids)):
        raise EvalError(f"{p.name}: every case needs a unique id")
    return cases


def parse_numbers(text: str) -> list[float]:
    """Numbers in an answer, Indian style included: "1,23,456", "₹3.86 Cr", "53.2 L", "7.8%"."""
    out = []
    for m in _NUM.finditer(text or ""):
        tok = m.group(0).strip()
        unit = re.search(r"(cr|crore|lakhs|lakh|l|k|%)$", tok, re.I)
        num = float(re.sub(r"[^\d.+-]", "", tok[: unit.start()] if unit else tok) or "nan")
        if math.isnan(num):
            continue
        u = unit.group(1).lower() if unit else ""
        out.append(num / 100 if u == "%" else num * _MULT.get(u, 1))
        if u == "%":
            out.append(num)  # rates may be stored as 0.078 or as 7.8
    return out


def _numeric_cells(res: dict, column: str | None) -> list[float]:
    cols = [c.get("name") or c.get("label") for c in res.get("columns") or []]
    vals = []
    for row in res.get("rows") or []:
        for i, v in enumerate(row):
            if column and i < len(cols) and cols[i] != column:
                continue
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
                vals.append(float(v))
            elif isinstance(v, str):
                try:
                    vals.append(float(v))
                except ValueError:
                    pass
    return vals


def expected_value(t: Transport, ws: int, expect: dict) -> float | None:
    if "sql" in expect:
        res = t.post(f"/api/workspaces/{ws}/sql", {"sql": expect["sql"]})
    elif "spec" in expect:
        res = t.post(f"/api/workspaces/{ws}/query", expect["spec"])
    else:
        return None
    vals = _numeric_cells(res, expect.get("column"))
    if not vals:
        raise EvalError(f"the expected-value query returned no number: {json.dumps(expect)[:200]}")
    return vals[0]


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= max(abs(b) * tol, 1e-9)


def score(case: dict, answer: dict, expected: float | None) -> CaseResult:
    r = CaseResult(id=case["id"], passed=True, expected=expected, engine=answer.get("engine"), model=answer.get("model"))
    usage = answer.get("usage") or {}
    r.cost_inr = float(usage.get("cost_inr") or 0)
    if answer.get("type") == "error":
        r.problems.append(f"error answer: {answer.get('text', '')[:200]}")
    text = " ".join(str(answer.get(k) or "") for k in ("text", "title"))
    if expected is not None:
        tol = float((case.get("expect") or {}).get("tolerance", 0.005))
        found = _numeric_cells(answer, None) + parse_numbers(text)
        r.found = found[:20]
        if not any(_close(v, expected, tol) for v in found):
            r.problems.append(f"expected {expected:g} not found in the answer")
    low = text.lower()
    for item in case.get("must_mention") or []:
        options = item if isinstance(item, list) else [item]
        if not any(str(o).lower() in low for o in options):
            r.problems.append(f"does not mention {' / '.join(map(str, options))}")
    for item in case.get("must_not_mention") or []:
        if str(item).lower() in low:
            r.problems.append(f"mentions '{item}', which it must not")
    r.passed = not r.problems
    return r


def run_case(t: Transport, ws: int, case: dict, engine: str) -> CaseResult:
    started = time.monotonic()
    try:
        expected = expected_value(t, ws, case.get("expect") or {})
        answer = t.post(f"/api/workspaces/{ws}/assistant/ask", {"question": case["question"], "engine": engine})
        r = score(case, answer, expected)
    except EvalError as e:
        r = CaseResult(id=case["id"], passed=False, problems=[str(e)])
    r.seconds = round(time.monotonic() - started, 2)
    return r


def run_set(t: Transport, ws: int, cases: list[dict], engine: str = "semantic") -> list[CaseResult]:
    return [run_case(t, ws, c, engine) for c in cases]


def report(results: list[CaseResult]) -> str:
    lines = []
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        extra = f" [{r.engine}{' ' + r.model if r.model else ''}, {r.seconds}s, Rs {r.cost_inr:.2f}]"
        lines.append(f"{mark}  {r.id}{extra}")
        lines += [f"      - {p}" for p in r.problems]
    passed = sum(r.passed for r in results)
    cost = sum(r.cost_inr for r in results)
    lines.append(f"\n{passed}/{len(results)} passed ({passed / max(len(results), 1):.0%}); estimated cost Rs {cost:.2f}")
    return "\n".join(lines)
