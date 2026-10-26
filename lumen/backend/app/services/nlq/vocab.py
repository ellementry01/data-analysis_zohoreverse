"""Vocabulary for natural-language questions, built from the semantic layer and the data itself."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from sqlalchemy import text

from ...db import get_engine
from ..catalog import DS, Catalog
from ..naming import q

STOP_VALUES = {
    "all", "any", "new", "old", "yes", "no", "none", "other", "others", "total", "sale", "sales", "order", "orders",
    "return", "returns", "the", "and", "for", "with", "show", "by", "per", "month", "year", "week", "day", "last",
    "this", "next", "top", "bottom", "high", "low", "open", "closed", "active", "online", "offline", "true", "false",
    "na", "unknown", "in", "out", "a", "an", "of", "to", "on", "at", "is", "it", "or", "vs", "compare", "trend",
    "stock", "inventory", "product", "products", "customer", "customers", "warehouse", "channel", "spend", "revenue",
}
ID_HINT = re.compile(r"(^id$|_id$|^id_|_code$|^code$|_key$|^sku$|_no$|_number$)")
_VALUE_CACHE: dict[tuple, tuple[float, dict]] = {}


def norm_word(w: str) -> str:
    w = w.lower()
    if len(w) > 3 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss") and not w.endswith("us"):
        return w[:-1]
    return w


def tokenize(s: str) -> list[str]:
    s = s.lower().replace("&", " and ").replace("'s", "")
    return [norm_word(t) for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", s)]


def phrase_key(s: str) -> str:
    return " ".join(tokenize(re.sub(r"[_\-]+", " ", s)))


@dataclass
class Entry:
    kind: str  # metric | column | value | dataset
    phrase: str
    dataset_id: int | None = None
    column: str | None = None
    metric: str | None = None
    value: str | None = None
    weight: float = 1.0


@dataclass
class Vocab:
    entries: dict[str, list[Entry]] = field(default_factory=dict)
    max_len: int = 1

    def add(self, e: Entry) -> None:
        if not e.phrase:
            return
        lst = self.entries.setdefault(e.phrase, [])
        if not any(x.kind == e.kind and x.dataset_id == e.dataset_id and x.column == e.column and x.metric == e.metric
                   and x.value == e.value for x in lst):
            lst.append(e)
            self.max_len = max(self.max_len, len(e.phrase.split()))


def is_id_column(name: str) -> bool:
    return bool(ID_HINT.search(name))


def label_column(ds: DS) -> str | None:
    """The column that best names an entity (e.g. product_name for products)."""
    texts = [c for c in ds.columns.values() if c.type == "text"]
    singular = norm_word(ds.slug.split("_")[-1])
    for pref in (f"{singular}_name", "name", "title", f"{ds.slug}_name"):
        for c in texts:
            if c.name == pref:
                return c.name
    for c in texts:
        if "name" in c.name:
            return c.name
    for c in texts:
        if not is_id_column(c.name):
            return c.name
    return texts[0].name if texts else None


def value_index(cat: Catalog, max_distinct: int = 300) -> dict[tuple[int, str], list[str]]:
    """Distinct values of low-cardinality text columns (cached per dataset version)."""
    key = (cat.workspace_id, tuple(sorted((d.id, d.row_count) for d in cat.datasets.values())))
    hit = _VALUE_CACHE.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    out: dict[tuple[int, str], list[str]] = {}
    with get_engine().connect() as conn:
        for ds in cat.datasets.values():
            for c in ds.columns.values():
                if c.type != "text" or is_id_column(c.name):
                    continue
                try:
                    rows = conn.execute(text(
                        f"SELECT DISTINCT {q(c.name)} FROM {q(cat.schema)}.{q(ds.slug)} WHERE {q(c.name)} IS NOT NULL LIMIT {max_distinct + 1}"
                    )).all()
                except Exception:
                    conn.rollback()
                    continue
                if len(rows) <= max_distinct:
                    out[(ds.id, c.name)] = [str(r[0]) for r in rows]
    _VALUE_CACHE[key] = (time.time(), out)
    return out


def build_vocab(cat: Catalog, values: dict | None = None) -> Vocab:
    v = Vocab()
    for mt in cat.metrics.values():
        for p in [mt.name, mt.label, *(mt.synonyms or [])]:
            v.add(Entry("metric", phrase_key(p), metric=mt.name, dataset_id=mt.dataset_id, weight=3))
    for ds in cat.datasets.values():
        for p in {ds.name, ds.slug}:
            v.add(Entry("dataset", phrase_key(p), dataset_id=ds.id, weight=1))
        for c in ds.columns.values():
            w = 0.5 if is_id_column(c.name) else 2
            for p in {c.label, c.name}:
                v.add(Entry("column", phrase_key(p), dataset_id=ds.id, column=c.name, weight=w))
            # "product name" -> also reachable as "product"
            if c.name.endswith("_name"):
                v.add(Entry("column", phrase_key(c.name[:-5]), dataset_id=ds.id, column=c.name, weight=2.5))
    for g in cat.glossary:
        phrases = [g.term, *(g.synonyms or [])]
        for p in phrases:
            if g.target_type == "metric" and g.metric_name:
                v.add(Entry("metric", phrase_key(p), metric=g.metric_name, weight=3))
            elif g.target_type == "column" and g.dataset_id and g.column:
                v.add(Entry("column", phrase_key(p), dataset_id=g.dataset_id, column=g.column, weight=3))
            elif g.target_type == "value" and g.dataset_id and g.column and g.value is not None:
                v.add(Entry("value", phrase_key(p), dataset_id=g.dataset_id, column=g.column, value=g.value, weight=3))
    for (ds_id, col), vals in (values or {}).items():
        for val in vals:
            k = phrase_key(val)
            if not k or k in STOP_VALUES or len(k) < 3 or k.replace(" ", "").isdigit():
                continue
            v.add(Entry("value", k, dataset_id=ds_id, column=col, value=val, weight=1.5))
    return v
