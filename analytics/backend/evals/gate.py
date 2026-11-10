"""The release gate (Phase 8): `python -m evals gate [--base ...]`.

For every set with a pass mark (docs/AI_ASSISTANTS_PLAN.md section 4) it reads the latest LIVE run recorded in the app
(`/api/admin/eval-runs`, written by `python -m evals run ... --live`) and fails when:
  * the set has never been run live, or its latest run is below the pass mark (or has invented numbers where none are
    allowed);
  * the assistant code changed after that run (a commit touching services/agent, services/nlq, prompts or tools is newer
    than the run): run that set live again, with the owner's OK, before releasing.
Exit code 0 = release may go ahead, 1 = blocked, 2 = could not check. It never calls Claude itself.
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from .runner import EvalError, Transport

# set -> (minimum share of cases passed, minimum share of numbers right, invented numbers allowed)
MARKS: dict[str, tuple[float, float, bool]] = {
    "dashboard_basic": (0.90, 0.90, False),
    "dashboard_deep": (0.85, 0.85, False),
    "memory": (0.85, 0.0, False),
    "issues": (0.90, 0.90, False),
    "global": (0.85, 0.85, False),
    "domain": (0.90, 0.90, False),
}
# code whose change means the assistants must be re-evaluated
WATCHED = ["app/services/agent", "app/services/nlq", "app/services/memory.py", "app/services/domain_agents.py",
           "app/services/worth_a_look.py", "app/services/data_issues.py"]
BACKEND = Path(__file__).resolve().parents[1]


def last_assistant_change() -> datetime | None:
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cI", "--", *WATCHED], cwd=BACKEND, capture_output=True,
                             text=True, timeout=30).stdout.strip()
        return datetime.fromisoformat(out) if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def check(runs: list[dict], changed: datetime | None) -> list[tuple[str, bool, str]]:
    """One line per set: (set, ok, why)."""
    out = []
    for name, (min_pass, min_numbers, invented_ok) in MARKS.items():
        live = [r for r in runs if r["set_name"] == name and r["live"]]
        if not live:
            out.append((name, False, "never run live"))
            continue
        r = max(live, key=lambda x: x["created_at"])
        rate = r["passed"] / r["total"] if r["total"] else 0
        nums = r["numbers_correct"] / r["numbers_checked"] if r["numbers_checked"] else 1
        when = r["created_at"][:10]
        line = f"{r['passed']}/{r['total']} passed, numbers {r['numbers_correct']}/{r['numbers_checked']}, invented {r['invented']} ({when})"
        if rate < min_pass:
            out.append((name, False, f"{line}: below the pass mark {min_pass:.0%}"))
        elif nums < min_numbers:
            out.append((name, False, f"{line}: numbers below {min_numbers:.0%}"))
        elif r["invented"] and not invented_ok:
            out.append((name, False, f"{line}: invented numbers"))
        elif changed and datetime.fromisoformat(r["created_at"]) < changed:
            out.append((name, False, f"{line}: the assistant code changed on {changed.date()}, after this run"))
        else:
            out.append((name, True, line))
    return out


def main(base: str, user: str | None) -> int:
    try:
        runs = Transport(base, user).get("/api/admin/eval-runs?live=true&limit=1000")
    except EvalError as e:
        print(f"cannot read the eval runs: {e}")
        return 2
    lines = check(runs, last_assistant_change())
    for name, ok, why in lines:
        print(f"{'PASS' if ok else 'BLOCK'}  {name:16} {why}")
    blocked = [n for n, ok, _ in lines if not ok]
    print("\nRelease gate: " + ("open" if not blocked else f"BLOCKED by {', '.join(blocked)}"))
    return 0 if not blocked else 1
