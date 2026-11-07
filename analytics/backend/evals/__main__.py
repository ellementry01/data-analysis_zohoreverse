"""python -m evals run <set> [--base http://localhost:8000] [--workspace 34] [--live] [--user email] [--json out.json]

Runs an eval set against a running app. Without --live the offline semantic engine answers (free). --live lets Claude
answer and refuses to start unless EVAL_LIVE_OK=1 is set: live calls cost money and need the owner's OK.
Exit code: 0 when every case passes, 1 otherwise, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from .runner import EvalError, Transport, load_set, report, run_set


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
    a = ap.parse_args(argv)

    if a.live and os.environ.get("EVAL_LIVE_OK") != "1":
        print("--live calls Claude and costs money: set EVAL_LIVE_OK=1 after the owner has agreed.", file=sys.stderr)
        return 2
    try:
        cases = load_set(a.set)
    except (OSError, EvalError) as e:
        print(f"cannot load the set: {e}", file=sys.stderr)
        return 2
    results = run_set(Transport(a.base, a.user), a.workspace, cases, engine="auto" if a.live else "semantic")
    print(report(results))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in results], f, indent=2)
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
