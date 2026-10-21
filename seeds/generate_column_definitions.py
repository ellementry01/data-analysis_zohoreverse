"""Writes sql/095_column_definitions.sql: a COMMENT for every core / insight column, from
seeds/column_definitions.tsv. Fails if any column has no definition or any definition has no column.
Run against a database built with every migration except 990:  python seeds/generate_column_definitions.py <db>"""
import os, sys, psycopg
from pathlib import Path
HERE = Path(__file__).parent
defs, generic = {}, {}
for line in (HERE / "column_definitions.tsv").read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.startswith("#"):
        continue
    t, c, d = line.split("\t")
    (generic if t == "*" else defs)[(c,) if t == "*" else (t, c)] = d
conn = psycopg.connect(dbname=sys.argv[1])
cols = conn.execute("SELECT table_schema||'.'||table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema IN ('core','insight') ORDER BY table_schema, table_name, ordinal_position").fetchall()
out, missing, used = [], [], set()
for t, c in cols:
    d = defs.get((t, c)) or generic.get((c,))
    if d is None:
        missing.append(f"{t}.{c}")
        continue
    used.add((t, c)) if (t, c) in defs else used.add((c,))
    out.append(f"COMMENT ON COLUMN {t}.{c} IS '{d.replace(chr(39), chr(39)*2)}';")
unused = [f"{k[0]}.{k[1]}" for k in defs if k not in used]
if missing or unused:
    sys.exit(f"missing definitions: {missing}\ndefinitions for columns that do not exist: {unused}")
sql = ["-- =============================================================================",
       "-- 990_column_definitions.sql  |  GENERATED from seeds/column_definitions.tsv. Always the LAST file: re-applies every definition.",
       "-- Business definition of every core and insight column (feeds meta.column_dictionary).",
       "-- =============================================================================", ""] + out + ["",
       "INSERT INTO meta.schema_version (version, migration_file, description) VALUES ('2.2','990_column_definitions.sql','Column definitions (re-applied)') ON CONFLICT (migration_file) DO UPDATE SET applied_at = CURRENT_TIMESTAMP;", ""]
Path(os.environ.get("OUT_SQL", HERE.parent / "sql" / "990_column_definitions.sql")).write_text("\n".join(sql), encoding="utf-8")
print(f"{len(out)} column definitions written")
