"""Validation of user-authored SQL expressions (derived columns, metrics, filters).

Expressions are parsed with sqlglot and accepted only if every node is on an allow-list and every
column reference exists. They are then re-rendered by sqlglot, never passed through verbatim.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

ALLOWED_FUNCS = {
    # math
    "abs", "round", "ceil", "ceiling", "floor", "power", "pow", "sqrt", "ln", "log", "exp", "mod", "sign", "greatest", "least",
    # text
    "lower", "upper", "trim", "ltrim", "rtrim", "length", "substring", "substr", "left", "right", "replace", "concat",
    "initcap", "split_part", "strpos", "lpad", "rpad", "position",
    # null / logic
    "coalesce", "nullif",
    # date
    "date_trunc", "extract", "date_part", "to_char", "now", "current_date", "age", "make_date",
    # aggregates (metrics only)
    "sum", "avg", "count", "min", "max", "stddev", "variance", "median", "percentile_cont",
}
AGGREGATES = {"sum", "avg", "count", "min", "max", "stddev", "variance", "median", "percentile_cont"}

ALLOWED_NODES = (
    exp.Column, exp.Identifier, exp.Literal, exp.Boolean, exp.Null, exp.Paren, exp.Neg, exp.Not,
    exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.DPipe, exp.IntDiv,
    exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.And, exp.Or, exp.Is, exp.In, exp.Between,
    exp.Like, exp.ILike, exp.Case, exp.If, exp.Cast, exp.DataType, exp.Interval, exp.Var, exp.Star,
    exp.Distinct, exp.Func, exp.Anonymous, exp.Tuple, exp.Filter, exp.Where, exp.Bracket,
    exp.CurrentDate, exp.CurrentTimestamp, exp.TryCast, exp.Extract, exp.WithinGroup, exp.Order, exp.Ordered,
    exp.DataTypeParam, exp.Coalesce,
)


class ExpressionError(ValueError):
    pass


def _func_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    return (node.sql_name() if hasattr(node, "sql_name") else node.key).lower()


def validate_expression(sql: str, columns: set[str], allow_aggregates: bool = False) -> str:
    """Return the normalised SQL for a safe scalar (or aggregate) expression."""
    if not sql or not sql.strip():
        raise ExpressionError("Expression is empty")
    if ";" in sql:
        raise ExpressionError("Semicolons are not allowed")
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except Exception as e:  # sqlglot raises several error types
        raise ExpressionError(f"Could not parse expression: {e}") from e
    if isinstance(tree, (exp.Select, exp.Subquery, exp.Query)):
        raise ExpressionError("Subqueries are not allowed in expressions")
    lowered = {c.lower() for c in columns}
    has_agg = False
    for node in tree.walk():
        if isinstance(node, (exp.Select, exp.Subquery, exp.Query, exp.Table, exp.Command)):
            raise ExpressionError("Subqueries and table references are not allowed")
        if not isinstance(node, ALLOWED_NODES):
            raise ExpressionError(f"'{node.key}' is not allowed in expressions")
        if isinstance(node, exp.Func) and not isinstance(node, (exp.Case, exp.If, exp.Cast, exp.TryCast, exp.Extract, exp.Coalesce, exp.CurrentDate, exp.CurrentTimestamp)):
            name = _func_name(node)
            if isinstance(node, exp.AggFunc) or name in AGGREGATES:
                has_agg = True
                if not allow_aggregates:
                    raise ExpressionError(f"Aggregate function {name.upper()} is only allowed in metrics")
            elif name not in ALLOWED_FUNCS and not isinstance(node, (exp.Round, exp.Abs, exp.Lower, exp.Upper, exp.Trim,
                                                                     exp.Length, exp.Substring, exp.Concat, exp.DateTrunc,
                                                                     exp.TimestampTrunc,  # postgres date_trunc() parses to this
                                                                     exp.Nullif, exp.Greatest, exp.Least, exp.Pow, exp.Sqrt,
                                                                     exp.Ln, exp.Log, exp.Exp, exp.Ceil, exp.Floor,
                                                                     exp.Initcap, exp.ToChar, exp.Left, exp.Right,
                                                                     exp.Mod, exp.Sign, exp.SplitPart, exp.StrPosition,
                                                                     exp.Pad, exp.Replace, exp.CurrentDate, exp.Median,
                                                                     exp.Stddev, exp.Variance, exp.PercentileCont)):
                raise ExpressionError(f"Function {name.upper()} is not allowed")
        if isinstance(node, exp.Column):
            if node.table:
                raise ExpressionError("Qualified column references are not allowed; use the column name")
            if node.name.lower() not in lowered:
                raise ExpressionError(f"Unknown column '{node.name}'")
    if allow_aggregates and not has_agg:
        raise ExpressionError("A metric expression must contain an aggregate such as SUM(...) or COUNT(...)")
    return tree.sql(dialect="postgres")


def referenced_columns(sql: str) -> set[str]:
    tree = sqlglot.parse_one(sql, read="postgres")
    return {c.name for c in tree.find_all(exp.Column)}


def qualify_columns(sql: str, alias: str) -> str:
    """Prefix every bare column reference with a table alias."""
    tree = sqlglot.parse_one(sql, read="postgres")

    def tf(node):
        if isinstance(node, exp.Column) and not node.table:
            return exp.column(node.name, table=alias, quoted=True)
        return node

    return tree.transform(tf).sql(dialect="postgres")
