"""Pure-function tests: insights, anomaly detection, chart suggestion and date-range math."""
from datetime import date

import numpy as np
import pytest

from app.services.analytics import detect_anomalies, fmt, insights, suggest_chart, _partial_period
from app.services.filters import FilterError, previous_period, resolve_date_range


def T(name="month", grain="month"):
    return {"name": name, "label": "Month", "role": "dimension", "type": "date", "grain": grain}


def D(name="region"):
    return {"name": name, "label": name.title(), "role": "dimension", "type": "text"}


def M(name="sales", fmt_="number", additive=True):
    return {"name": name, "label": name.title(), "role": "measure", "type": "decimal", "format": fmt_, "additive": additive}


def months(n, start=(2025, 1)):
    y, m = start
    out = []
    for _ in range(n):
        out.append(f"{y}-{m:02d}-01")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def by_type(ins, t):
    return [i for i in ins if i["type"] == t]


# ----------------------------------------------------------------------------------------------- insights

def test_rising_trend():
    rows = [[m, 100 + 10 * i] for i, m in enumerate(months(8))]
    ins = insights([T(), M()], rows)
    tr = by_type(ins, "trend")
    assert tr and tr[0]["direction"] == "up" and "rising" in tr[0]["text"]
    assert by_type(ins, "change")[0]["text"].endswith("+70.0%.")
    assert "Peak Sales: 170" in by_type(ins, "peak")[0]["text"]
    assert not by_type(ins, "partial")


def test_falling_and_flat_trend():
    rows = [[m, 200 - 15 * i] for i, m in enumerate(months(6))]
    assert by_type(insights([T(), M()], rows), "trend")[0]["direction"] == "down"
    rows = [[m, v] for m, v in zip(months(6), [100, 120, 90, 110, 95, 105])]
    assert by_type(insights([T(), M()], rows), "trend")[0]["direction"] == "flat"


def test_anomaly_detection_needs_seven_points():
    vals = [100, 102, 98, 101, 99, 500, 100, 103, 97, 101]
    rows = [[m, v] for m, v in zip(months(len(vals)), vals)]
    an = by_type(insights([T(), M()], rows), "anomaly")
    assert len(an) == 1 and an[0]["index"] == 5 and an[0]["x"] == rows[5][0] and "above" in an[0]["text"]
    # a dip is flagged as below
    vals2 = [100, 102, 98, 101, 99, 5, 100, 103]
    an2 = detect_anomalies("Sales", [(i, v) for i, v in enumerate(vals2)], np.array(vals2, dtype=float))
    assert len(an2) == 1 and an2[0]["index"] == 5 and "below" in an2[0]["text"]
    # fewer than 7 points: never flagged
    short = [100, 101, 99, 500, 100, 102]
    assert detect_anomalies("Sales", [(i, v) for i, v in enumerate(short)], np.array(short, dtype=float)) == []
    # smooth growth is not anomalous
    smooth = [100 * 1.05 ** i for i in range(12)]
    assert detect_anomalies("Sales", [(i, v) for i, v in enumerate(smooth)], np.array(smooth)) == []


def test_partial_period_excluded():
    # today is pinned to 2026-10-17: October 2026 is incomplete
    rows = [[m, v] for m, v in zip(months(4, (2026, 7)), [100, 200, 300, 5])]
    ins = insights([T(), M()], rows)
    assert by_type(ins, "partial") and "2026-10-01" in by_type(ins, "partial")[0]["text"]
    assert by_type(ins, "trend")[0]["direction"] == "up"  # the tiny partial October does not reverse the trend
    assert "(2026-09-01), +200.0%" in by_type(ins, "change")[0]["text"]
    # complete months only: no partial note
    assert not by_type(insights([T(), M()], rows[:3]), "partial")


@pytest.mark.parametrize("grain,value,partial", [
    ("month", "2026-10-01", True), ("month", "2026-09-01", False),
    ("day", "2026-10-17", True), ("day", "2026-10-16", False),
    ("week", "2026-10-12", True), ("week", "2026-10-05", False),
    ("quarter", "2026-10-01", True), ("quarter", "2026-07-01", False),
    ("year", "2026-01-01", True), ("year", "2025-01-01", False),
    (None, "2026-10-01", False), ("month", None, False), ("month", "garbage", False),
])
def test_partial_period_rules(grain, value, partial):
    assert _partial_period(grain, value) is partial


def test_top_bottom_and_share():
    rows = [["North", 500], ["South", 300], ["East", 200]]
    ins = insights([D(), M()], rows)
    assert "North has the highest Sales (500, 50% of the total)" in by_type(ins, "top")[0]["text"]
    assert "East has the lowest" in by_type(ins, "bottom")[0]["text"]
    # a top-N (limited) list does not claim a share of the total
    assert "% of the total" not in by_type(insights([D(), M()], rows, limited=True), "top")[0]["text"]


def test_multi_series_and_correlation():
    ms = months(6)
    rows = [[m, ch, v] for i, m in enumerate(ms) for ch, v in (("Amazon", 100 + 10 * i), ("Shopify", 50 + i))]
    ins = insights([T(), D("channel"), M()], rows)
    assert by_type(ins, "series_total")[0]["text"].startswith("Totals: Amazon")
    assert "Amazon leads in 6 of 6 periods" in by_type(ins, "leader")[0]["text"]
    rows = [[m, 100 + 10 * i, 50 + 5 * i] for i, m in enumerate(ms)]
    ins = insights([T(), M("sales"), M("spend")], rows)
    assert "strong positive" in by_type(ins, "correlation")[0]["text"]
    assert "0.50×" in by_type(ins, "ratio")[0]["text"]


def test_empty_result():
    assert insights([D(), M()], []) == [{"type": "empty", "text": "No rows match this question and its filters."}]


def test_fmt():
    assert fmt(1234567, "currency") == "₹12.35 L"
    assert fmt(123456789) == "12.35 Cr"
    assert fmt(0.1234, "percent") == "12.3%"
    assert fmt(42.5) == "42.50" and fmt(None) == "–" and fmt(-1500) == "-1,500"


# ----------------------------------------------------------------------------------------------- chart suggestion

def test_suggest_chart_rules():
    assert suggest_chart([M()], [[1]]) == "kpi"
    assert suggest_chart([T(), M()], [["2026-01-01", 1]]) == "line"
    assert suggest_chart([T(), D(), M()], [["2026-01-01", "a", 1]]) == "line"
    assert suggest_chart([T(), D(), D("x"), M()], []) == "table"
    few = [[c, 10] for c in "abc"]
    assert suggest_chart([D(), M()], few) == "pie"
    assert suggest_chart([D(), M()], [["a", 10], ["b", -5], ["c", 3]]) == "bar"  # negatives cannot be slices
    assert suggest_chart([D(), M()], [["a", 10]]) == "bar"
    assert suggest_chart([D(), M(additive=False)], few) == "bar"  # rates are not parts of a whole
    assert suggest_chart([D(), M()], [[c, 10] for c in "abcdefg"]) == "bar"
    assert suggest_chart([D(), M("a"), M("b")], [[c, 1, 2] for c in "abc"]) == "bar"
    assert suggest_chart([D(), M("a"), M("b")], [[c, 1, 2] for c in "abcdefghij"]) == "scatter"
    assert suggest_chart([D(), D("y"), M()], [["a", "b", 1]]) == "stacked_bar"
    grid = [[f"a{i}", f"b{j}", 1] for i in range(9) for j in range(9)]
    assert suggest_chart([D(), D("y"), M()], grid) == "heatmap"
    assert suggest_chart([D(), D("y"), M("a"), M("b")], []) == "table"
    assert suggest_chart([D()], [["a"], ["b"]]) == "table"  # dimension-only listing
    # comparison columns do not count as extra measures
    prev = {**M("sales__prev"), "compare_of": "sales"}
    assert suggest_chart([D(), M(), prev], [[c, 10, 5] for c in "abc"]) == "pie"


# ----------------------------------------------------------------------------------------------- date ranges

TODAY = date(2026, 10, 17)  # a Saturday


@pytest.mark.parametrize("preset,lo,hi", [
    ("today", date(2026, 10, 17), date(2026, 10, 18)),
    ("yesterday", date(2026, 10, 16), date(2026, 10, 17)),
    ("last_7_days", date(2026, 10, 11), date(2026, 10, 18)),
    ("last_30_days", date(2026, 9, 18), date(2026, 10, 18)),
    ("this_week", date(2026, 10, 12), date(2026, 10, 18)),
    ("last_week", date(2026, 10, 5), date(2026, 10, 12)),
    ("this_month", date(2026, 10, 1), date(2026, 10, 18)),
    ("last_month", date(2026, 9, 1), date(2026, 10, 1)),
    ("last_3_months", date(2026, 7, 1), date(2026, 10, 1)),
    ("last_6_months", date(2026, 4, 1), date(2026, 10, 1)),
    ("last_12_months", date(2025, 10, 1), date(2026, 10, 1)),
    ("this_quarter", date(2026, 10, 1), date(2026, 10, 18)),
    ("last_quarter", date(2026, 7, 1), date(2026, 10, 1)),
    ("this_year", date(2026, 1, 1), date(2026, 10, 18)),
    ("year_to_date", date(2026, 1, 1), date(2026, 10, 18)),
    ("last_year", date(2025, 1, 1), date(2026, 1, 1)),
])
def test_presets(preset, lo, hi):
    assert resolve_date_range(preset, TODAY) == (lo, hi)
    assert resolve_date_range({"preset": preset}, TODAY) == (lo, hi)


def test_presets_use_pinned_today():
    assert resolve_date_range("last_month") == (date(2026, 9, 1), date(2026, 10, 1))


@pytest.mark.parametrize("today,preset,lo,hi", [
    (date(2026, 1, 10), "last_month", date(2025, 12, 1), date(2026, 1, 1)),
    (date(2026, 1, 10), "last_quarter", date(2025, 10, 1), date(2026, 1, 1)),
    (date(2026, 2, 28), "last_6_months", date(2025, 8, 1), date(2026, 2, 1)),
    (date(2026, 3, 1), "last_30_days", date(2026, 1, 31), date(2026, 3, 2)),
    (date(2026, 12, 31), "this_quarter", date(2026, 10, 1), date(2027, 1, 1)),
    (date(2024, 3, 1), "yesterday", date(2024, 2, 29), date(2024, 3, 1)),
    (date(2024, 3, 1), "last_7_days", date(2024, 2, 24), date(2024, 3, 2)),
    (date(2024, 3, 15), "last_month", date(2024, 2, 1), date(2024, 3, 1)),
    (date(2024, 2, 29), "this_month", date(2024, 2, 1), date(2024, 3, 1)),
    (date(2026, 10, 12), "this_week", date(2026, 10, 12), date(2026, 10, 13)),  # Monday
])
def test_preset_boundaries(today, preset, lo, hi):
    assert resolve_date_range(preset, today) == (lo, hi)


@pytest.mark.parametrize("spec,lo,hi", [
    ({"last": 3, "unit": "months"}, date(2026, 7, 1), date(2026, 10, 1)),
    ({"last": 14, "unit": "months"}, date(2025, 8, 1), date(2026, 10, 1)),
    ({"last": 10, "unit": "days"}, date(2026, 10, 7), date(2026, 10, 18)),
    ({"last": 2, "unit": "weeks"}, date(2026, 9, 28), date(2026, 10, 12)),
    ({"last": 2, "unit": "quarters"}, date(2026, 4, 1), date(2026, 10, 1)),
    ({"last": 1, "unit": "years"}, date(2025, 1, 1), date(2026, 1, 1)),
    ({"from": "2024-02-01", "to": "2024-02-29"}, date(2024, 2, 1), date(2024, 3, 1)),
    ({"from": "2026-01-01"}, date(2026, 1, 1), date(3000, 1, 1)),
])
def test_relative_and_explicit_ranges(spec, lo, hi):
    assert resolve_date_range(spec, TODAY) == (lo, hi)


def test_invalid_ranges():
    for bad in ("fortnight", {"last": 2, "unit": "eons"}, 42, {"from": "31/12/2024"}):
        with pytest.raises((FilterError, ValueError)):
            resolve_date_range(bad, TODAY)


@pytest.mark.parametrize("lo,hi,mode,plo,phi", [
    (date(2026, 9, 1), date(2026, 10, 1), "previous_period", date(2026, 8, 1), date(2026, 9, 1)),
    (date(2026, 4, 1), date(2026, 10, 1), "previous_period", date(2025, 10, 1), date(2026, 4, 1)),
    (date(2026, 1, 1), date(2026, 2, 1), "previous_period", date(2025, 12, 1), date(2026, 1, 1)),
    (date(2024, 3, 1), date(2024, 4, 1), "previous_period", date(2024, 2, 1), date(2024, 3, 1)),  # Feb has 29 days
    (date(2026, 10, 11), date(2026, 10, 18), "previous_period", date(2026, 10, 4), date(2026, 10, 11)),
    (date(2024, 2, 1), date(2024, 3, 1), "previous_year", date(2023, 2, 1), date(2023, 3, 1)),
    (date(2026, 9, 1), date(2026, 10, 1), "previous_year", date(2025, 9, 1), date(2025, 10, 1)),
    (date(2024, 1, 1), date(2024, 2, 29), "previous_year", date(2023, 1, 1), date(2023, 3, 1)),  # Jan 1-Feb 28 2024
])
def test_previous_period(lo, hi, mode, plo, phi):
    assert previous_period(lo, hi, mode) == (plo, phi)


def test_previous_year_of_leap_day_keeps_length():
    plo, phi = previous_period(date(2024, 2, 29), date(2024, 3, 1), "previous_year")
    assert plo.year == 2023 and (phi - plo).days == 1
