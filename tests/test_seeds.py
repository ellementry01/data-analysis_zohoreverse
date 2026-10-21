"""Seed loader tests: registers are never deleted; a bad seed changes nothing.
Needs DW_TEST_DATABASE (a disposable database built with build_db.sh and seeded once) and PG env."""
import csv, importlib, os, shutil
from pathlib import Path
import pytest

DB = os.environ.get("DW_TEST_DATABASE")
pytestmark = pytest.mark.skipif(not DB, reason="set DW_TEST_DATABASE")
REAL = Path(__file__).resolve().parent.parent / "seeds"


@pytest.fixture
def seeds(tmp_path, monkeypatch):
    d = tmp_path / "seeds"
    shutil.copytree(REAL, d)
    monkeypatch.setenv("DW_SEEDS_DIR", str(d))
    import loader.seeds as S
    importlib.reload(S)
    S.load(DB)                       # baseline: the real seeds
    yield d, S
    monkeypatch.setenv("DW_SEEDS_DIR", str(REAL)); importlib.reload(S); S.load(DB)


def edit(path, fn):
    rows = list(csv.reader(open(path, newline="", encoding="utf-8")))
    rows = fn(rows)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def count(S, sql):
    import psycopg
    with psycopg.connect(dbname=DB) as c:
        return c.execute(sql).fetchone()[0]


def test_reload_is_repeatable(seeds):
    d, S = seeds
    a = S.load(DB); b = S.load(DB)
    assert a == b


def test_deleting_a_rule_is_refused(seeds):
    d, S = seeds
    edit(d / "meta_business_rule.csv", lambda r: [x for x in r if x[0] != "BR-030"])
    with pytest.raises(S.SeedError, match="never deleted"):
        S.load(DB)
    assert count(S, "SELECT count(*) FROM meta.business_rule WHERE rule_id='BR-030'") == 1


def test_retiring_a_rule_is_allowed(seeds):
    d, S = seeds
    edit(d / "meta_business_rule.csv", lambda r: [x[:8] + ["RETIRED", ""] if x[0] == "BR-030" else x for x in r])
    S.load(DB)
    assert count(S, "SELECT count(*) FROM meta.business_rule WHERE rule_id='BR-030' AND status='RETIRED'") == 1


def test_superseding_a_rule_records_its_replacement(seeds):
    d, S = seeds
    edit(d / "meta_business_rule.csv", lambda r: [x[:8] + ["SUPERSEDED", "BR-026"] if x[0] == "BR-030" else x for x in r])
    S.load(DB)
    assert count(S, "SELECT count(*) FROM meta.business_rule WHERE rule_id='BR-030' AND superseded_by='BR-026'") == 1


def test_mapping_citing_unknown_rule_changes_nothing(seeds):
    d, S = seeds
    before = count(S, "SELECT count(*) FROM ref.location_alias")
    edit(d / "ref_location_alias.csv", lambda r: [r[0]] + [x[:-1] + ["BR-999"] for x in r[1:2]] + r[2:])
    edit(d / "ref_location_alias.csv", lambda r: r[:-1])           # also drop a row: must NOT be applied either
    with pytest.raises(Exception):
        S.load(DB)
    assert count(S, "SELECT count(*) FROM ref.location_alias") == before


def test_unknown_csv_column_refused(seeds):
    d, S = seeds
    edit(d / "ref_channel_master.csv", lambda r: [r[0] + ["colour"]] + [x + ["red"] for x in r[1:]])
    with pytest.raises(S.SeedError, match="do not exist"):
        S.load(DB)
