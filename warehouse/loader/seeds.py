"""
Loads the reviewed seed CSVs (seeds/*.csv) into meta and ref, in ONE transaction.

Two kinds of content, handled differently on purpose:
  * REGISTERS (business rules, processes, gaps, source notes, partner types) are
    never deleted. Rows are inserted or updated; a row that exists in the
    database but is missing from its CSV stops the load: retire / close /
    supersede it in the CSV instead, so the history of decisions stays visible.
  * MAPPINGS (locations, channels, partners, lineage) are replaced wholesale.

Usage:  python -m loader.seeds <database>        (libpq env for host / user / password)
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import psycopg

import os
SEEDS = Path(os.environ.get("DW_SEEDS_DIR", Path(__file__).resolve().parent.parent / "seeds"))

# table -> (csv file, primary key columns), applied in this order
REGISTERS = [
    ("meta.business_rule",    "meta_business_rule.csv",    ["rule_id"]),
    ("meta.business_process", "meta_business_process.csv", ["process_code"]),
    ("meta.data_gap",         "meta_data_gap.csv",         ["gap_id"]),
    ("meta.source_note",      "meta_source_note.csv",      ["source_name", "note_id"]),
    ("ref.partner_type",      "ref_partner_type.csv",      ["partner_type"]),
]
# replaced in this order (parents first); deleted in reverse
MAPPINGS = [
    ("ref.channel_master",           "ref_channel_master.csv"),
    ("ref.location_master",          "ref_location_master.csv"),
    ("ref.location_alias",           "ref_location_alias.csv"),
    ("ref.document_prefix_location", "ref_document_prefix_location.csv"),
    ("ref.channel_alias",            "ref_channel_alias.csv"),
    ("ref.partner_default_rule",     "ref_partner_default_rule.csv"),
    ("ref.partner_list",             "ref_partner_list.csv"),
    ("ref.partner_type_channel",     "ref_partner_type_channel.csv"),
    ("ref.code_mapping",             "ref_code_mapping.csv"),
    ("meta.column_lineage",          "meta_column_lineage.csv"),
    ("meta.column_rule",             "meta_column_rule.csv"),
]


class SeedError(Exception):
    pass


def read_csv(name: str) -> tuple[list[str], list[list[str | None]]]:
    with open(SEEDS / name, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header, body = rows[0], rows[1:]
    return header, [[None if v == "" else v for v in r] for r in body if any(v != "" for v in r)]


def table_columns(conn, table: str) -> set[str]:
    schema, name = table.split(".")
    return {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s", (schema, name))}


def check_header(conn, table, header, fname):
    unknown = [h for h in header if h not in table_columns(conn, table)]
    if unknown:
        raise SeedError(f"{fname}: columns {unknown} do not exist in {table}")


def upsert(conn, table, fname, key) -> int:
    header, rows = read_csv(fname)
    check_header(conn, table, header, fname)
    keys_csv = {tuple(r[header.index(k)] for k in key) for r in rows}
    keys_db = {tuple(str(v) for v in r) for r in conn.execute(f"SELECT {', '.join(key)} FROM {table}")}
    gone = sorted(keys_db - keys_csv)
    if gone:
        raise SeedError(f"{table}: rows {gone[:5]} exist in the database but not in {fname}. "
                        "Registers are never deleted: set their status to RETIRED / CLOSED / SUPERSEDED instead.")
    deferred = "superseded_by" in header                        # self-reference: set after all rows exist
    cols = [h for h in header if not (deferred and h == "superseded_by")]
    upd = [c for c in cols if c not in key] or cols[:1]
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
           f"ON CONFLICT ({', '.join(key)}) DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in upd)
           + (", superseded_by = NULL" if deferred else ""))       # cleared together with status; re-set below where the CSV says so
    with conn.cursor() as cur:
        if deferred:     # status SUPERSEDED requires superseded_by: insert those as ACTIVE first, then fix both
            si = header.index("status")
            cur.executemany(sql, [[("ACTIVE" if (c == "status" and r[si] == "SUPERSEDED") else r[header.index(c)]) for c in cols] for r in rows])
            for r in rows:
                if r[header.index("superseded_by")]:
                    cur.execute(f"UPDATE {table} SET superseded_by = %s, status = %s WHERE rule_id = %s",
                                (r[header.index("superseded_by")], r[si], r[header.index("rule_id")]))
        else:
            cur.executemany(sql, [[r[header.index(c)] for c in cols] for r in rows])
    return len(rows)


def replace(conn, table, fname) -> int:
    header, rows = read_csv(fname)
    check_header(conn, table, header, fname)
    with conn.cursor() as cur:
        cur.executemany(f"INSERT INTO {table} ({', '.join(header)}) VALUES ({', '.join(['%s'] * len(header))})", rows)
    return len(rows)


def load(dbname: str) -> dict[str, int]:
    counts = {}
    with psycopg.connect(dbname=dbname) as conn:          # one transaction: all or nothing
        for table, _ in reversed(MAPPINGS):
            conn.execute(f"DELETE FROM {table}")
        for table, fname, key in REGISTERS:
            counts[table] = upsert(conn, table, fname, key)
        for table, fname in MAPPINGS:
            counts[table] = replace(conn, table, fname)
        conn.commit()
    return counts


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m loader.seeds <database>")
    try:
        for t, n in load(sys.argv[1]).items():
            print(f"  {t:32s} {n:5d}")
        print("Seeds loaded.")
    except (SeedError, psycopg.Error) as e:
        sys.exit(f"SEED LOAD FAILED, nothing changed: {e}")
