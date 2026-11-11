"""python -m evals run <set> [--base http://localhost:8000] [--workspace 34] [--live] [--user email] [--json out.json]
                       [--no-record] [--note text]
python -m evals gate [--base ...]   (the release gate: the latest live run of every set against its pass mark)

Runs an eval set against a running app. Without --live the offline semantic engine answers (free). --live lets Claude
answer and refuses to start unless EVAL_LIVE_OK=1 is set: live calls cost money and need the owner's OK.
Every run is recorded in the app (/api/admin/eval-runs, platform admins; failures as case ids and problems, no answer
texts) for the monitoring page and the gate, unless --no-record.
Exit code: 0 when every case passes, 1 otherwise, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from .runner import EvalError, Transport, load_set, report, run_set, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run an eval set")
    run.add_argument("set", help="set name in evals/sets (without .yaml) or a path")
    run.add_argument("--base", default="http://localhost:8000")
    run.add_argument("--workspace", type=int, default=34)
    run.add_argument("--live", action="store_true", help="answer with Claude (needs EVAL_LIVE_OK=1)")
    run.add_argument("--user", default=None, help="X-User-Email to send (default: the app's default user)")
    run.add_argument("--json", default=None, help="also write the results to this JSON file")
    run.add_argument("--no-record", action="store_true", help="don't record the run in the app")
    run.add_argument("--note", default="", help="a note stored with the recorded run")
    gate = sub.add_parser("gate", help="the release gate: latest live runs against the pass marks")
    gate.add_argument("--base", default="http://localhost:8000")
    gate.add_argument("--user", default=None)
    a = ap.parse_args(argv)

    if a.cmd == "gate":
        from .gate import main as gate_main
        return gate_main(a.base, a.user)

    if a.live and os.environ.get("EVAL_LIVE_OK") != "1":
        print("--live calls Claude and costs money: set EVAL_LIVE_OK=1 after the owner has agreed.", file=sys.stderr)
        return 2
    try:
        cases = load_set(a.set)
    except (OSError, EvalError) as e:
        print(f"cannot load the set: {e}", file=sys.stderr)
        return 2
    t = Transport(a.base, a.user)
    results = run_set(t, a.workspace, cases, engine="auto" if a.live else "semantic")
    print(report(results))
    if not a.no_record:
        record(t, a.set, a.live, results, a.note)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in results], f, indent=2)
    return 0 if all(r.passed for r in results) else 1


def record(t: Transport, set_arg: str, live: bool, results, note: str = "") -> None:
    import subprocess

    s = summary(results)
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    name = os.path.splitext(os.path.basename(set_arg))[0].lower().replace(" ", "_")
    body = {"set_name": name, "live": live, "total": s["cases"], "passed": s["passed"],
            "numbers_checked": s["numeric_cases"], "numbers_correct": s["numbers_correct"], "invented": s["invented"],
            "cost_inr": s["cost_inr"], "median_seconds": s["median_seconds"], "git_commit": commit[:40], "note": note[:2000],
            "failures": [{"id": r.id[:120], "problems": [p[:300] for p in r.problems][:20]} for r in results if not r.passed]}
    try:
        t.post("/api/admin/eval-runs", body)
        print(f"recorded in the app as {name} ({'live' if live else 'offline'})")
    except EvalError as e:
        print(f"(not recorded in the app: {e})", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
