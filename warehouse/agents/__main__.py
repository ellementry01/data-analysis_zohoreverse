"""
Runs the rule-based agents after a successful build (PRD-001 section 2.2; AI assistants plan, Phase 7).

    python -m agents run <all|stock|operations> <database> [--started-by NAME]
    python dw.py agents run all                           # same, with the admin login from .env

* Preconditions, checked before anything is written: the latest transform run SUCCEEDED and the latest build has no
  failed ERROR check. The build's period end is the run's "as of" date.
* Each agent writes one insight.model_run. Its alerts are written in ONE transaction: the run either SUCCEEDS with all
  of them, or is marked FAILED and writes nothing else.
* Only active rules run (insight.alert_rule.is_active). A rule whose process has no data for the latest month
  (mart.v_data_coverage = NONE) is skipped and named in the run notes, and raises nothing.
* One open event per condition (identity_key): a condition that still holds refreshes its open event; a new one raises
  an event; an open event whose condition no longer holds (or whose rule was switched off) is RESOLVED by the agent.
* Same build + same settings = same alerts (no randomness, no clock in the rules).
Exit codes: 0 succeeded (or agent switched off) | 2 usage | 3 precondition failed | 4 run failed (rolled back)
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys

import psycopg

from .rules import AGENTS, RULES

MODEL_NAME = "rules"
MODEL_VERSION = "2026-11-10"
COLS = ["identity_key", "product_key", "location_key", "document_ref", "severity", "metric_value", "threshold_value",
        "message", "details"]


class PreconditionFailed(Exception):
    pass


def preconditions(conn) -> str:
    row = conn.execute("SELECT status, period_end FROM meta.transform_run ORDER BY transform_run_id DESC LIMIT 1").fetchone()
    if not row:
        raise PreconditionFailed("no build has run yet")
    if row[0] != "SUCCEEDED":
        raise PreconditionFailed(f"the latest build is {row[0]}, not SUCCEEDED")
    bad = conn.execute("SELECT count(*) FROM mart.v_data_quality_latest WHERE severity = 'ERROR' AND outcome = 'FAIL'").fetchone()[0]
    if bad:
        raise PreconditionFailed(f"the latest build has {bad} failed ERROR check(s)")
    return str(row[1])


def coverage(conn) -> dict[str, str]:
    return dict(conn.execute(
        "SELECT DISTINCT ON (process_name) process_name, coverage FROM mart.v_data_coverage "
        "ORDER BY process_name, period_month DESC").fetchall())


def run_agent(conn, agent: str, started_by: str) -> dict:
    settings = dict(conn.execute("SELECT setting_key, setting_value FROM meta.pipeline_setting").fetchall())
    switch = f"agent.{AGENTS[agent]}.enabled"
    if settings.get(switch, "false").lower() != "true":
        return {"agent": agent, "status": "SKIPPED", "notes": f"{switch} is not true"}
    as_of = preconditions(conn)
    rules = conn.execute("SELECT alert_code, is_active, process_name, coalesce(setting_keys, '') FROM insight.alert_rule "
                         "WHERE agent = %s ORDER BY alert_code", (agent,)).fetchall()
    used = {}
    for code, active, _p, keys in rules:
        for k in filter(None, keys.split(",")):
            if active and k not in settings:
                raise PreconditionFailed(f"setting {k} (rule {code}) is missing")
            if active:
                try:
                    float(settings[k])
                except ValueError:
                    raise PreconditionFailed(f"setting {k} = {settings[k]!r} is not a number") from None
                used[k] = settings[k]
    run_id = conn.execute(
        "INSERT INTO insight.model_run (agent, run_type, model_name, model_version, parameters, data_as_of_date, notes) "
        "VALUES (%s, 'ALERT_SCAN', %s, %s, %s, %s, %s) RETURNING run_id",
        (agent, MODEL_NAME, MODEL_VERSION, json.dumps(used, sort_keys=True), as_of, f"started by {started_by}")).fetchone()[0]
    conn.commit()
    try:
        cov = coverage(conn)
        handler = f"{AGENTS[agent]}_ai"
        notes, counts = [], {}
        for code, active, process, _k in rules:
            if not active:
                n = conn.execute("UPDATE insight.alert_event SET status = 'RESOLVED', handled_by = %s, handled_at = CURRENT_TIMESTAMP "
                                 "WHERE alert_code = %s AND status IN ('OPEN','ACKNOWLEDGED')", (handler + " (rule off)", code)).rowcount
                if n:
                    notes.append(f"{code} off: {n} resolved")
                continue
            if code not in RULES:
                notes.append(f"{code} has no implementation: skipped")
                continue
            if process and cov.get(process, "NONE") == "NONE":
                notes.append(f"{code} skipped: no {process} data")
                continue
            params = {"as_of": as_of, **used}
            rows = [dict(zip(COLS, r)) for r in conn.execute(RULES[code], params).fetchall()]
            seen = set()
            raised = refreshed = 0
            for r in rows:
                if r["identity_key"] in seen:            # a rule must return each condition once
                    raise RuntimeError(f"{code} returned {r['identity_key']} twice")
                seen.add(r["identity_key"])
                cur = conn.execute(
                    "UPDATE insight.alert_event SET severity = %(severity)s, metric_value = %(metric_value)s, "
                    "threshold_value = %(threshold_value)s, message = %(message)s, details = %(details)s, "
                    "last_seen_run_id = %(run_id)s, last_seen_at = CURRENT_TIMESTAMP "
                    "WHERE identity_key = %(identity_key)s AND status IN ('OPEN','ACKNOWLEDGED')", {**r, "run_id": run_id})
                if cur.rowcount:
                    refreshed += 1
                    continue
                conn.execute(
                    "INSERT INTO insight.alert_event (alert_code, run_id, product_key, location_key, metric_value, threshold_value, "
                    "message, severity, identity_key, document_ref, details, last_seen_run_id, last_seen_at) VALUES "
                    "(%(code)s, %(run_id)s, %(product_key)s, %(location_key)s, %(metric_value)s, %(threshold_value)s, %(message)s, "
                    "%(severity)s, %(identity_key)s, %(document_ref)s, %(details)s, %(run_id)s, CURRENT_TIMESTAMP)",
                    {**r, "code": code, "run_id": run_id})
                raised += 1
            resolved = conn.execute(
                "UPDATE insight.alert_event SET status = 'RESOLVED', handled_by = %s, handled_at = CURRENT_TIMESTAMP "
                "WHERE alert_code = %s AND status IN ('OPEN','ACKNOWLEDGED') AND NOT (identity_key = ANY(%s))",
                (handler, code, list(seen))).rowcount
            counts[code] = {"raised": raised, "still_open": refreshed, "resolved": resolved}
            notes.append(f"{code}: {raised} raised, {refreshed} still open, {resolved} resolved")
        conn.execute("UPDATE insight.model_run SET status = 'SUCCEEDED', finished_at = CURRENT_TIMESTAMP, notes = %s "
                     "WHERE run_id = %s", ((f"started by {started_by}; " + "; ".join(notes))[:1000], run_id))
        conn.commit()
        return {"agent": agent, "status": "SUCCEEDED", "run_id": run_id, "as_of": as_of, "counts": counts, "notes": notes}
    except Exception as e:
        conn.rollback()
        conn.execute("UPDATE insight.model_run SET status = 'FAILED', finished_at = CURRENT_TIMESTAMP, notes = %s WHERE run_id = %s",
                     (f"{type(e).__name__}: {e}"[:1000], run_id))
        conn.commit()
        raise


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m agents")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("agent", choices=["all", "stock", "operations"])
    r.add_argument("database")
    r.add_argument("--started-by", default=getpass.getuser())
    a = ap.parse_args(argv)
    agents = ["STOCK", "OPERATIONS"] if a.agent == "all" else [a.agent.upper()]
    code = 0
    with psycopg.connect(dbname=a.database, autocommit=False) as conn:
        for agent in agents:
            try:
                res = run_agent(conn, agent, a.started_by)
            except PreconditionFailed as e:
                conn.rollback()
                print(f"{agent}: NOT RUN - {e}", file=sys.stderr)
                return 3
            except Exception as e:  # noqa: BLE001 - reported, run marked FAILED
                print(f"{agent}: RUN FAILED - rolled back. {type(e).__name__}: {e}", file=sys.stderr)
                code = 4
                continue
            if res["status"] == "SKIPPED":
                print(f"{agent}: switched off ({res['notes']})")
                continue
            print(f"{agent}: run {res['run_id']} SUCCEEDED (as of {res['as_of']})")
            for n in res["notes"]:
                print(f"  {n}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
