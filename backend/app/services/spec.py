"""The analytical query specification shared by charts, dashboards and the AI assistant."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Grain = Literal["day", "week", "month", "quarter", "year"]
Agg = Literal["sum", "avg", "count", "count_distinct", "min", "max", "median"]


class Dimension(BaseModel):
    field: str  # "dataset.column" or "@time" (each measure's own date column)
    grain: Grain | None = None
    alias: str | None = None
    label: str | None = None


class Measure(BaseModel):
    metric: str | None = None  # semantic-layer metric name
    field: str | None = None  # "dataset.column" or "dataset.*" for row counts
    agg: Agg = "sum"
    alias: str | None = None
    label: str | None = None


class Filter(BaseModel):
    field: str
    op: str = "eq"
    value: Any = None


class SortBy(BaseModel):
    field: str  # output alias
    dir: Literal["asc", "desc"] = "desc"


class QuerySpec(BaseModel):
    dimensions: list[Dimension] = Field(default_factory=list)
    measures: list[Measure] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    time_range: Any = None  # preset string | {"preset"} | {"last": n, "unit"} | {"from","to"}
    time_field: str | None = None  # explicit date column for the time range
    compare: Literal["previous_period", "previous_year"] | None = None
    sort: list[SortBy] = Field(default_factory=list)
    limit: int | None = None
    apply_rules: bool = True
