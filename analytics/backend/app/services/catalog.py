"""In-memory view of a workspace's semantic model: datasets, columns, relationships, metrics, rules."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .. import models as m


@dataclass
class Col:
    name: str
    label: str
    type: str
    derived: bool = False
    description: str = ""


@dataclass
class DS:
    id: int
    slug: str
    name: str
    kind: str
    columns: dict[str, Col]
    default_date: str | None
    row_count: int
    description: str = ""

    def date_columns(self) -> list[str]:
        return [c.name for c in self.columns.values() if c.type in ("date", "datetime")]


@dataclass
class Edge:
    from_ds: int
    from_col: str
    to_ds: int
    to_col: str
    id: int = 0


@dataclass
class Catalog:
    workspace_id: int
    schema: str
    datasets: dict[int, DS]
    edges: list[Edge]
    metrics: dict[str, m.Metric]
    rules: dict[int, list[m.BusinessRule]]
    glossary: list[m.GlossaryTerm] = field(default_factory=list)

    @property
    def by_slug(self) -> dict[str, DS]:
        return {d.slug: d for d in self.datasets.values()}

    def resolve_field(self, ref: str) -> tuple[DS, Col]:
        """'dataset_slug.column' -> (DS, Col). Raises KeyError with a helpful message."""
        if "." not in ref:
            raise KeyError(f"Field '{ref}' must look like dataset.column")
        slug, col = ref.split(".", 1)
        ds = self.by_slug.get(slug)
        if not ds:
            raise KeyError(f"Unknown dataset '{slug}'")
        c = ds.columns.get(col)
        if not c:
            raise KeyError(f"Unknown column '{col}' in {ds.name}")
        return ds, c

    def parent_paths(self, start: int) -> dict[int, list[Edge]]:
        """Datasets reachable from `start` by following child->parent (many-to-one) lookups.
        Returns {dataset_id: [edges]} with the shortest path (direct path wins)."""
        paths: dict[int, list[Edge]] = {start: []}
        dq = deque([start])
        while dq:
            cur = dq.popleft()
            for e in self.edges:
                if e.from_ds == cur and e.to_ds not in paths:
                    paths[e.to_ds] = paths[cur] + [e]
                    dq.append(e.to_ds)
        return paths

    def related(self, ds_id: int) -> set[int]:
        """Datasets connected in either direction (used for suggestions)."""
        out = {ds_id}
        changed = True
        while changed:
            changed = False
            for e in self.edges:
                if e.from_ds in out and e.to_ds not in out or e.to_ds in out and e.from_ds not in out:
                    out |= {e.from_ds, e.to_ds}
                    changed = True
        return out


def load_catalog(db: Session, workspace: m.Workspace) -> Catalog:
    """The semantic catalog of a workspace, as the person acting on it may see it (access rules hide datasets, and the
    metrics, relationships and rules that depend on them)."""
    from .permissions import hidden_dataset_ids

    hidden = hidden_dataset_ids(db, workspace)
    datasets = {}
    from sqlalchemy.orm import selectinload

    # columns in one query for all datasets (not one per dataset): this runs on every dashboard tile
    for d in db.query(m.Dataset).options(selectinload(m.Dataset.columns)).filter_by(workspace_id=workspace.id).all():
        if d.id in hidden:
            continue
        cols = {c.name: Col(c.name, c.display_name, c.data_type, c.is_derived, c.description) for c in d.columns if not c.hidden}
        datasets[d.id] = DS(d.id, d.slug, d.name, d.kind, cols, d.default_date_column, d.row_count, d.description)
    edges = [Edge(r.from_dataset_id, r.from_column, r.to_dataset_id, r.to_column, r.id)
             for r in db.query(m.Relationship).filter_by(workspace_id=workspace.id).all()
             if r.from_dataset_id not in hidden and r.to_dataset_id not in hidden]
    metrics = {x.name: x for x in db.query(m.Metric).filter_by(workspace_id=workspace.id).all()
               if x.dataset_id is None or x.dataset_id not in hidden}
    if hidden:  # composites built on a hidden metric go too
        import re

        changed = True
        while changed:
            changed = False
            for name, mt in list(metrics.items()):
                if mt.kind == "composite" and any(ref not in metrics for ref in re.findall(r"\{(\w+)\}", mt.expression or "")):
                    del metrics[name]
                    changed = True
    rules: dict[int, list[m.BusinessRule]] = {}
    for r in db.query(m.BusinessRule).filter_by(workspace_id=workspace.id, enabled=True).all():
        if r.dataset_id not in hidden:
            rules.setdefault(r.dataset_id, []).append(r)
    glossary = db.query(m.GlossaryTerm).filter_by(workspace_id=workspace.id).all()
    return Catalog(workspace.id, workspace.schema_name, datasets, edges, metrics, rules, glossary)
