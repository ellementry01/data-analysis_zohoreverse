"""Identifier helpers. Every identifier that reaches SQL passes through here or through metadata lookups."""
import re
import unicodedata

_RESERVED = {
    "all", "and", "any", "as", "asc", "between", "by", "case", "cast", "check", "column", "constraint",
    "create", "cross", "current_date", "current_time", "current_timestamp", "current_user", "default",
    "desc", "distinct", "do", "else", "end", "except", "false", "fetch", "for", "foreign", "from",
    "grant", "group", "having", "in", "inner", "intersect", "into", "is", "join", "left", "like",
    "limit", "not", "null", "offset", "on", "only", "or", "order", "outer", "primary", "references",
    "right", "select", "table", "then", "to", "true", "union", "unique", "user", "using", "when",
    "where", "window", "with", "year", "month", "day", "date", "time", "timestamp", "value", "type",
}

IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def slugify(value: str, fallback: str = "col") -> str:
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    value = value.replace("%", " pct ").replace("#", " num ").replace("&", " and ")
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    value = re.sub(r"_+", "_", value)
    if not value:
        value = fallback
    if value[0].isdigit():
        value = f"{fallback}_{value}"
    if value in _RESERVED:
        value = f"{value}_"
    return value[:60]


DASHBOARD_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


def dashboard_key(name: str) -> str:
    """Kebab-case key for a dashboard name ("Sales & channels" -> "sales-channels"). Keys never change with a rename."""
    value = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:80].rstrip("-") or "dashboard"


def unique_dashboard_key(base: str, taken: set[str]) -> str:
    key, i = base, 2
    while key in taken:
        suffix = f"-{i}"
        key = base[:80 - len(suffix)] + suffix
        i += 1
    return key


def unique_names(names: list[str], fallback: str = "col") -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        base = slugify(n, fallback)
        candidate = base
        i = 2
        while candidate in seen:
            candidate = f"{base[:56]}_{i}"
            i += 1
        seen[candidate] = 1
        out.append(candidate)
    return out


def q(ident: str) -> str:
    """Quote a validated identifier."""
    if not IDENT_RE.match(ident):
        raise ValueError(f"Invalid identifier: {ident!r}")
    return f'"{ident}"'


def is_ident(value: str) -> bool:
    return bool(IDENT_RE.match(value or ""))


def humanize(name: str) -> str:
    name = re.sub(r"[_\s]+", " ", str(name)).strip()
    return name[:1].upper() + name[1:] if name else name
