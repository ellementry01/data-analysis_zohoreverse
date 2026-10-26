"""Compiles a QuerySpec into a single parameterised PostgreSQL SELECT.

Design:
* Every measure is anchored to a base ("fact") dataset. Measures on the same fact share one aggregated CTE.
* Dimensions/filters on other datasets are reached by following child->parent lookups from the fact
  (LEFT JOIN, never fanning out). If a dataset is unreachable, a same-named column on the fact is used
  ("conformed dimension"), mirroring how blended reports match columns by name.
* "@time" (or any date dimension that is not reachable) maps to each fact's own date column, so
  "sales and marketing spend by month" aligns facts on the calendar.
* Metric business rules become FILTER (WHERE ...) clauses; dataset business rules become WHERE clauses.
* Semi-additive metrics (stock on hand) aggregate only the latest snapshot inside each group.
* Several facts are merged on their dimension keys (UNION of keys + LEFT JOINs).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

import sqlglot
from sqlglot import exp

from .catalog import DS, Catalog, Col
from .expressions import ExpressionError, qualify_columns, validate_expression
from .filters import FilterError, build_condition, resolve_date_range
from .naming import q, slugify
from .spec import Dimension, Measure, QuerySpec

AGG_SQL = {
    "sum": "SUM({x})", "avg": "AVG({x})", "count": "COUNT({x})", "count_distinct": "COUNT(DISTINCT {x})",
    "min": "MIN({x})", "max": "MAX({x})", "median": "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {x})",
}
NUMERIC = {"integer", "decimal"}
DEFAULT_LIMIT = 1000


class QueryError(ValueError):
    pass


@dataclass
class MeasureDef:
    alias: str
    label: str
    base: DS | None
    agg_sql: str = ""  # unqualified aggregate over base columns
    filters: list[dict] = field(default_factory=list)
    semi_additive: bool = False
    time_col: str | None = None
    fmt: str = "number"
    formula: str | None = None  # composite: SQL over {component_alias}
    hidden: bool = False
    higher_is_better: bool = True  # from the metric; decides whether a rise is shown as good or bad


@dataclass
class OutCol:
    name: str
    label: str
    role: str  # dimension | measure
    type: str
    format: str = "number"
    grain: str | None = None
    additive: bool = True
    higher_is_better: bool = True


@dataclass
class Compiled:
    sql: str
    params: dict
    columns: list[OutCol]
    warnings: list[str]
    date_range: tuple[date, date] | None
    measures: list[MeasureDef]


# ----------------------------------------------------------------------------------------------- helpers

def _alias(base: str, used: set[str]) -> str:
    a = slugify(base, "c")[:50]
    cand, i = a, 2
    while cand in used:
        cand = f"{a}_{i}"
        i += 1
    used.add(cand)
    return cand


def _wrap_aggs_with_filter(agg_sql: str, cond: str) -> str:
    tree = sqlglot.parse_one(agg_sql, read="postgres")

    def tf(node):
        if isinstance(node, exp.WithinGroup) or (isinstance(node, exp.AggFunc) and not isinstance(node.parent, exp.WithinGroup)):
            return exp.Filter(this=node.copy(), expression=exp.Where(this=exp.var(f"({cond})")))
        return node

    return tree.transform(tf, copy=True).sql(dialect="postgres")


def _grain_expr(col_sql: str, grain: str | None, ctype: str) -> str:
    if not grain:
        return col_sql
    if ctype not in ("date", "datetime"):
        raise QueryError("A date grouping (day/week/month/quarter/year) needs a date column")
    return f"CAST(DATE_TRUNC('{grain}', {col_sql}) AS DATE)"


# ----------------------------------------------------------------------------------------------- measures

def _expand_measure(cat: Catalog, ms: Measure, used: set[str], out: list[MeasureDef], depth: int = 0, hidden: bool = False) -> MeasureDef:
    if depth > 5:
        raise QueryError("Metric definitions are nested too deeply (circular reference?)")
    if ms.metric:
        mt = cat.metrics.get(ms.metric)
        if not mt:
            raise QueryError(f"Unknown metric '{ms.metric}'")
        if mt.kind == "composite":
            names = re.findall(r"\{([a-z_][a-z0-9_]*)\}", mt.expression)
            if not names:
                raise QueryError(f"Composite metric '{mt.name}' must reference other metrics like {{net_sales}}")
            comp_alias = {}
            for n in dict.fromkeys(names):
                existing = next((d for d in out if d.alias == f"_m_{n}"), None)
                if existing is None:
                    sub = _expand_measure(cat, Measure(metric=n, alias=f"_m_{n}"), used, out, depth + 1, hidden=True)
                    comp_alias[n] = sub.alias
                else:
                    comp_alias[n] = existing.alias
            formula = mt.expression
            for n, a in comp_alias.items():
                formula = formula.replace("{" + n + "}", f"__{a}__")
            try:
                validate_expression(formula, {f"__{a}__" for a in comp_alias.values()})
            except ExpressionError as e:
                raise QueryError(f"Composite metric '{mt.name}': {e}") from e
            d = MeasureDef(alias=ms.alias or _alias(mt.name, used), label=ms.label or mt.label, base=None,
                           fmt=mt.format, formula=formula, hidden=hidden, higher_is_better=mt.higher_is_better is not False)
            if ms.alias:
                used.add(ms.alias)
            out.append(d)
            return d
        base = cat.datasets.get(mt.dataset_id)
        if not base:
            raise QueryError(f"Metric '{mt.name}' points to a dataset that no longer exists")
        try:
            agg = validate_expression(mt.expression, set(base.columns), allow_aggregates=True)
        except ExpressionError as e:
            raise QueryError(f"Metric '{mt.name}': {e}") from e
        alias = ms.alias or _alias(mt.name, used)
        used.add(alias)
        d = MeasureDef(alias=alias, label=ms.label or mt.label, base=base, agg_sql=agg, filters=list(mt.filters or []),
                       semi_additive=mt.semi_additive, time_col=mt.time_column, fmt=mt.format, hidden=hidden,
                       higher_is_better=mt.higher_is_better is not False)
        out.append(d)
        return d

    if not ms.field:
        raise QueryError("Each measure needs a metric or a field")
    if ms.field.endswith(".*"):
        base = cat.by_slug.get(ms.field[:-2])
        if not base:
            raise QueryError(f"Unknown dataset '{ms.field[:-2]}'")
        agg, label = "COUNT(*)", ms.label or f"Number of {base.name} rows"
    else:
        try:
            base, col = cat.resolve_field(ms.field)
        except KeyError as e:
            raise QueryError(str(e)) from e
        if ms.agg in ("sum", "avg", "median") and col.type not in NUMERIC:
            raise QueryError(f"Cannot {ms.agg} '{col.label}' because it is {col.type}; use count or count_distinct")
        agg = AGG_SQL[ms.agg].format(x=q(col.name))
        nice = {"sum": "Total", "avg": "Average", "count": "Count of", "count_distinct": "Distinct", "min": "Min", "max": "Max", "median": "Median"}[ms.agg]
        label = ms.label or f"{nice} {col.label}"
    alias = ms.alias or _alias(label, used)
    used.add(alias)
    d = MeasureDef(alias=alias, label=label, base=base, agg_sql=agg, hidden=hidden)
    out.append(d)
    return d


# ----------------------------------------------------------------------------------------------- fact CTE

class _FactBuilder:
    def __init__(self, cat: Catalog, base: DS, params: dict, warnings: list[str], pkey: str):
        self.cat, self.base, self.params, self.warnings, self.pkey = cat, base, params, warnings, pkey
        self.paths = cat.parent_paths(base.id)
        self.joins: dict[int, str] = {}  # ds_id -> alias
        self.join_sql: list[str] = []
        self._n = 0

    def _pk(self) -> str:
        self._n += 1
        return f"{self.pkey}_{self._n}"

    def _join_to(self, ds_id: int) -> str:
        if ds_id == self.base.id:
            return "b"
        if ds_id in self.joins:
            return self.joins[ds_id]
        prev = "b"
        for e in self.paths[ds_id]:
            if e.to_ds not in self.joins:
                alias = f"j{e.to_ds}"
                tgt = self.cat.datasets[e.to_ds]
                self.join_sql.append(
                    f"LEFT JOIN {q(self.cat.schema)}.{q(tgt.slug)} {alias} ON {prev}.{q(e.from_col)} = {alias}.{q(e.to_col)}"
                )
                self.joins[e.to_ds] = alias
            prev = self.joins[e.to_ds]
        return self.joins[ds_id]

    def resolve(self, ref: str) -> tuple[str, Col] | None:
        """Column SQL for this fact, or None if the field cannot be related to it."""
        ds, col = self.cat.resolve_field(ref)
        if ds.id in self.paths:
            return f"{self._join_to(ds.id)}.{q(col.name)}", col
        if col.name in self.base.columns:  # conformed by name
            return f"b.{q(col.name)}", self.base.columns[col.name]
        for ds_id in self.paths:
            other = self.cat.datasets[ds_id]
            if col.name in other.columns and ds_id != self.base.id:
                return f"{self._join_to(ds_id)}.{q(col.name)}", other.columns[col.name]
        return None

    def time_column(self, md: MeasureDef | None, spec: QuerySpec) -> tuple[str, Col] | None:
        if md and md.time_col and md.time_col in self.base.columns:
            return f"b.{q(md.time_col)}", self.base.columns[md.time_col]
        if spec.time_field:
            try:
                r = self.resolve(spec.time_field)
            except KeyError:
                r = None
            if r and r[1].type in ("date", "datetime"):
                ds, _ = self.cat.resolve_field(spec.time_field)
                if ds.id in self.paths:
                    return r
        if self.base.default_date and self.base.default_date in self.base.columns:
            return f"b.{q(self.base.default_date)}", self.base.columns[self.base.default_date]
        dates = self.base.date_columns()
        if dates:
            return f"b.{q(dates[0])}", self.base.columns[dates[0]]
        return None

    def condition(self, col_sql: str, col: Col, f: dict) -> str:
        try:
            return build_condition(col_sql, col.type, f, self.params, self._pk())
        except FilterError as e:
            raise QueryError(f"Filter on '{col.label}': {e}") from e


def _build_fact_cte(cat: Catalog, spec: QuerySpec, base: DS, mds: list[MeasureDef], dims: list[tuple[Dimension, str]],
                    params: dict, warnings: list[str], idx: int, date_range) -> str:
    fb = _FactBuilder(cat, base, params, warnings, f"f{idx}")
    semi = mds[0].semi_additive
    time = fb.time_column(mds[0], spec)
    dim_sql = []
    for d, alias in dims:
        if d.field == "@time":
            if not time:
                raise QueryError(f"'{base.name}' has no date column to group by time")
            dim_sql.append((_grain_expr(time[0], d.grain or "month", time[1].type), alias))
            continue
        r = fb.resolve(d.field)
        if r is None:
            ds, col = cat.resolve_field(d.field)
            if col.type in ("date", "datetime") and time:
                dim_sql.append((_grain_expr(time[0], d.grain, time[1].type), alias))
                continue
            names = ", ".join(m.label for m in mds if not m.hidden) or "this measure"
            raise QueryError(
                f"Cannot break down {names} by '{col.label}': {base.name} has no relationship to {ds.name}. "
                f"Define a relationship (lookup) between them in the data model."
            )
        dim_sql.append((_grain_expr(r[0], d.grain, r[1].type), alias))

    where = []
    if spec.apply_rules:
        for rule in cat.rules.get(base.id, []):
            for f in rule.filters or []:
                c = base.columns.get(f.get("column"))
                if c:
                    where.append(fb.condition(f"b.{q(c.name)}", c, f))
    for f in spec.filters:
        try:
            r = fb.resolve(f.field)
        except KeyError as e:
            raise QueryError(str(e)) from e
        if r is None:
            warnings.append(f"Filter on '{f.field}' does not apply to {base.name} (no relationship)")
            continue
        where.append(fb.condition(r[0], r[1], f.model_dump()))
    if date_range:
        if time:
            k = fb._pk()
            params[f"{k}_lo"], params[f"{k}_hi"] = date_range
            where.append(f"{time[0]} >= :{k}_lo AND {time[0]} < :{k}_hi")
        else:
            warnings.append(f"{base.name} has no date column, so the date range was not applied to it")

    aggs = []
    for md in mds:
        qualified = qualify_columns(md.agg_sql, "s" if semi else "b")
        if md.filters:
            conds = []
            for f in md.filters:
                c = base.columns.get(f.get("column"))
                if not c:
                    raise QueryError(f"Metric '{md.label}' filters on unknown column '{f.get('column')}'")
                conds.append(fb.condition(f"{'s' if semi else 'b'}.{q(c.name)}", c, f))
            qualified = _wrap_aggs_with_filter(qualified, " AND ".join(conds))
        aggs.append(f"{qualified} AS {q(md.alias)}")

    src = f"{q(cat.schema)}.{q(base.slug)} b " + " ".join(fb.join_sql)
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""

    if semi:
        if not time:
            raise QueryError(f"Semi-additive metric on '{base.name}' needs a date column")
        inner_dims = ", ".join(f"{s} AS {q('__d_' + a)}" for s, a in dim_sql)
        part = ", ".join(s for s, _ in dim_sql)
        inner = (f"SELECT b.*, {inner_dims + ', ' if inner_dims else ''}{time[0]} AS __t, "
                 f"MAX({time[0]}) OVER ({'PARTITION BY ' + part if part else ''}) AS __tmax FROM {src}{where_sql}")
        outer_dims = ", ".join(f"s.{q('__d_' + a)} AS {q(a)}" for _, a in dim_sql)
        group = f" GROUP BY {', '.join(str(i + 1) for i in range(len(dim_sql)))}" if dim_sql else ""
        return f"SELECT {outer_dims + ', ' if outer_dims else ''}{', '.join(aggs)} FROM ({inner}) s WHERE s.__t = s.__tmax{group}"

    sel_dims = ", ".join(f"{s} AS {q(a)}" for s, a in dim_sql)
    group = f" GROUP BY {', '.join(str(i + 1) for i in range(len(dim_sql)))}" if dim_sql else ""
    return f"SELECT {sel_dims + ', ' if sel_dims else ''}{', '.join(aggs)} FROM {src}{where_sql}{group}"


# ----------------------------------------------------------------------------------------------- compile

def compile_query(cat: Catalog, spec: QuerySpec, today: date | None = None, max_rows: int = 5000) -> Compiled:
    if not spec.measures and not spec.dimensions:
        raise QueryError("Choose at least one measure or dimension")
    warnings: list[str] = []
    params: dict = {}
    used: set[str] = set()

    # dimensions
    dims: list[tuple[Dimension, str]] = []
    out_cols: list[OutCol] = []
    for d in spec.dimensions:
        if d.field == "@time":
            label = d.label or f"{(d.grain or 'month').title()}"
            ctype = "date"
        else:
            try:
                ds, col = cat.resolve_field(d.field)
            except KeyError as e:
                raise QueryError(str(e)) from e
            label = d.label or (f"{col.label} ({d.grain})" if d.grain else col.label)
            ctype = "date" if d.grain else col.type
        alias = d.alias or _alias(f"{d.field.split('.')[-1].replace('@', '')}_{d.grain}" if d.grain else d.field.split(".")[-1], used)
        used.add(alias)
        dims.append((d, alias))
        out_cols.append(OutCol(alias, label, "dimension", ctype, grain=d.grain or ("month" if d.field == "@time" else None)))

    # measures
    mdefs: list[MeasureDef] = []
    requested: list[MeasureDef] = []
    for ms in spec.measures:
        requested.append(_expand_measure(cat, ms, used, mdefs))

    if not mdefs:  # dimension-only listing: distinct values from the first dimension's dataset
        if any(d.field == "@time" for d, _ in dims):
            raise QueryError("Time grouping needs at least one measure")
        base, _ = cat.resolve_field(dims[0][0].field)
        mdefs.append(MeasureDef(alias="_rows", label="Rows", base=base, agg_sql="COUNT(*)", hidden=True))

    date_range = resolve_date_range(spec.time_range, today) if spec.time_range else None

    # group physical measures by fact (semi-additive measures get their own CTE)
    groups: dict[tuple, list[MeasureDef]] = {}
    for md in mdefs:
        if md.formula is None:
            groups.setdefault((md.base.id, md.semi_additive, md.time_col if md.semi_additive else None), []).append(md)
    ctes, cte_of = [], {}
    for i, ((ds_id, _, _), mds) in enumerate(groups.items()):
        sql = _build_fact_cte(cat, spec, cat.datasets[ds_id], mds, dims, params, warnings, i, date_range)
        ctes.append((f"f{i}", sql))
        for md in mds:
            cte_of[md.alias] = f"f{i}"

    dim_aliases = [a for _, a in dims]

    def ref(alias: str) -> str:
        return f"{cte_of[alias]}.{q(alias)}" if len(ctes) > 1 else q(alias)

    def measure_sql(md: MeasureDef) -> str:
        if md.formula is None:
            return ref(md.alias)
        f = md.formula
        for a in re.findall(r"__([a-z_][a-z0-9_]*)__", f):
            f = f.replace(f"__{a}__", f"CAST({measure_sql(next(x for x in mdefs if x.alias == a))} AS NUMERIC)")
        return f"({f})"

    visible = [md for md in requested if not md.hidden] or []
    select_parts = []
    if len(ctes) == 1:
        select_parts = [q(a) for a in dim_aliases]
        from_sql = "f0"
    else:
        if dim_aliases:
            keys = " UNION ".join(f"SELECT {', '.join(q(a) for a in dim_aliases)} FROM {n}" for n, _ in ctes)
            ctes.append(("k", keys))
            select_parts = [f"k.{q(a)}" for a in dim_aliases]
            from_sql = "k " + " ".join(
                f"LEFT JOIN {n} ON " + " AND ".join(f"{n}.{q(a)} IS NOT DISTINCT FROM k.{q(a)}" for a in dim_aliases)
                for n, _ in ctes[:-1]
            )
        else:
            from_sql = " CROSS JOIN ".join(n for n, _ in ctes)
    for md in visible:
        select_parts.append(f"{measure_sql(md)} AS {q(md.alias)}")
        additive = md.formula is None and not md.semi_additive and md.fmt != "percent" and not re.search(
            r"^(AVG|MIN|MAX|COUNT\(DISTINCT|PERCENTILE)", md.agg_sql.upper())
        out_cols.append(OutCol(md.alias, md.label, "measure", "decimal", md.fmt, additive=additive,
                               higher_is_better=md.higher_is_better))
    if not visible and not select_parts:
        select_parts = ["1"]

    # ordering
    order = []
    valid = {c.name for c in out_cols}
    for s in spec.sort:
        if s.field not in valid:
            raise QueryError(f"Cannot sort by unknown column '{s.field}'")
        order.append(f"{q(s.field)} {s.dir.upper()} NULLS LAST")
    if not order:
        time_dims = [c.name for c in out_cols if c.role == "dimension" and c.type in ("date", "datetime")]
        if time_dims:
            order = [f"{q(a)} ASC" for a in time_dims]
        elif visible and dims:
            order = [f"{q(visible[0].alias)} DESC NULLS LAST"]
        elif dims:
            order = [f"{q(dim_aliases[0])} ASC"]
    limit = min(spec.limit or DEFAULT_LIMIT, max_rows)

    with_sql = "WITH " + ", ".join(f"{n} AS ({s})" for n, s in ctes)
    sql = f"{with_sql} SELECT * FROM (SELECT {', '.join(select_parts)} FROM {from_sql}) r"
    if visible and dims:  # hide groups where every measure is empty (e.g. rows excluded by metric rules)
        sql += " WHERE NOT (" + " AND ".join(f"r.{q(md.alias)} IS NULL" for md in visible) + ")"
    if order:
        sql += " ORDER BY " + ", ".join(order)
    sql += f" LIMIT {int(limit)}"
    return Compiled(sql, params, out_cols, warnings, date_range, mdefs)
