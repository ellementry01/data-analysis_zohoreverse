"""Load test (Phase 8): many people opening dashboards and asking questions at the same time, against the running app.

From analytics/ on the host:
    python scripts/load_test.py [--users 30] [--seconds 180] [--workspace 34] [--base http://localhost:8000]

Each virtual person is a temporary viewer (loadtest-NN@example.com, removed at the end with their conversations). In a
loop, with 2-6 s of "reading" between actions, they open a dashboard the way the browser does (the dashboard, then
every tile's data, six at a time) or ask a question on the Ask page with the free offline engine. Claude is never
called: live answers are limited per person, and their time is Claude's, not this server's.
While it runs, it samples the database connections and the background queue. The report gives response times
(median, 95th percentile, slowest), errors, and pass/fail against the targets below. Exit code 0 = targets met.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import subprocess
import sys
import time

import httpx

TARGETS = {  # 95th percentile, seconds
    "dashboard (all tiles)": 6.0,
    "one tile": 2.5,
    "question (offline)": 5.0,
}
MAX_ERROR_RATE = 0.01
QUESTIONS = [
    "net sales by channel", "net sales by month this year", "units sold by category", "top 10 products by net sales",
    "return rate by channel", "stock value by location", "units returned by month", "net sales at Bagru last month",
    "how many bills this year", "average bill value by month",
]
DB = ["docker", "exec", "ellementry-db-1", "sh", "-c"]


def psql(sql: str) -> str:
    r = subprocess.run(DB + [f'psql -U "$POSTGRES_USER" -d ellementry_analytics -Atc "{sql}"'], capture_output=True,
                       text=True, timeout=20)
    return r.stdout.strip()


class Stats:
    def __init__(self):
        self.times: dict[str, list[float]] = {k: [] for k in TARGETS}
        self.errors: dict[str, list[str]] = {k: [] for k in TARGETS}

    def add(self, kind: str, seconds: float, error: str | None = None):
        self.times[kind].append(seconds)
        if error:
            self.errors[kind].append(error)


async def call(c: httpx.AsyncClient, method: str, url: str, user: str, **kw):
    r = await c.request(method, url, headers={"X-User-Email": user}, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {url.split('?')[0]} -> {r.status_code}")
    return r.json() if r.content else None


async def person(c, base, ws, user, dashboards, stats: Stats, until: float, convs: list[int]):
    rnd = random.Random(user)
    await asyncio.sleep(rnd.uniform(0, 5))                  # people don't all arrive in the same second
    while time.monotonic() < until:
        if rnd.random() < 0.7:
            did = rnd.choice(dashboards)
            t0 = time.monotonic()
            err = None
            try:
                d = await call(c, "GET", f"{base}/api/workspaces/{ws}/dashboards/{did}", user)
                sem = asyncio.Semaphore(6)                  # a browser opens about six requests at once

                async def tile(w):
                    async with sem:
                        t1 = time.monotonic()
                        e = None
                        try:
                            await call(c, "POST", f"{base}/api/workspaces/{ws}/dashboards/{did}/widgets/{w['id']}/data", user,
                                       json={"filters": d.get("filters") or []})
                        except Exception as x:  # noqa: BLE001
                            e = str(x)
                        stats.add("one tile", time.monotonic() - t1, e)
                        return e

                errs = [e for e in await asyncio.gather(*(tile(w) for w in d["widgets"])) if e]
                err = errs[0] if errs else None
            except Exception as x:  # noqa: BLE001
                err = str(x)
            stats.add("dashboard (all tiles)", time.monotonic() - t0, err)
        else:
            t0 = time.monotonic()
            err = None
            try:
                a = await call(c, "POST", f"{base}/api/workspaces/{ws}/assistant/ask", user,
                               json={"question": rnd.choice(QUESTIONS), "engine": "semantic"})
                if a and a.get("conversation_id"):
                    convs.append((user, a["conversation_id"]))
            except Exception as x:  # noqa: BLE001
                err = str(x)
            stats.add("question (offline)", time.monotonic() - t0, err)
        await asyncio.sleep(rnd.uniform(2, 6))


async def sampler(until: float, samples: list[tuple[int, int, int]]):
    while time.monotonic() < until:
        try:
            conns = int(psql("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()") or 0)
            active = int(psql("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND state = 'active'") or 0)
            queued = int(psql("SELECT count(*) FROM ellementry_meta.jobs WHERE status = 'queued' AND run_after <= now()") or 0)
            samples.append((conns, active, queued))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        await asyncio.sleep(5)


def pct(v: list[float], p: float) -> float:
    s = sorted(v)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))] if s else 0.0


async def main(a) -> int:
    base = a.base.rstrip("/")
    users = [f"loadtest-{i:02d}@example.com" for i in range(1, a.users + 1)]
    async with httpx.AsyncClient(timeout=60, limits=httpx.Limits(max_connections=a.users * 6)) as c:
        dashboards = [d["id"] for d in (await c.get(f"{base}/api/workspaces/{a.workspace}/dashboards")).json()
                      if not d.get("is_template")]
        for u in users:
            r = await c.put(f"{base}/api/workspaces/{a.workspace}/members", json={"user_email": u, "role": "viewer"})
            r.raise_for_status()
        stats, samples, convs = Stats(), [], []
        print(f"{a.users} people, {a.seconds} s, {len(dashboards)} dashboards, workspace {a.workspace}...", flush=True)
        started = time.monotonic()
        until = started + a.seconds
        try:
            await asyncio.gather(sampler(until, samples),
                                 *(person(c, base, a.workspace, u, dashboards, stats, until, convs) for u in users))
        finally:
            for u, cid in convs:
                try:
                    await c.delete(f"{base}/api/workspaces/{a.workspace}/conversations/{cid}", headers={"X-User-Email": u})
                except httpx.HTTPError:
                    pass
            for u in users:
                await c.delete(f"{base}/api/workspaces/{a.workspace}/members/{u}")
        wall = time.monotonic() - started

    ok = True
    total = sum(len(v) for v in stats.times.values())
    errors = sum(len(v) for v in stats.errors.values())
    print(f"\n{total} timed requests in {wall:.0f} s ({total / wall:.1f}/s); {errors} errors\n")
    print(f"{'':24}{'count':>7}{'median':>9}{'p95':>8}{'slowest':>9}{'target p95':>12}")
    for kind, target in TARGETS.items():
        v = stats.times[kind]
        p95 = pct(v, 0.95)
        good = bool(v) and p95 <= target
        ok &= good
        print(f"{kind:24}{len(v):>7}{(statistics.median(v) if v else 0):>8.2f}s{p95:>7.2f}s{(max(v) if v else 0):>8.2f}s"
              f"{target:>10.1f}s  {'PASS' if good else 'FAIL'}")
    rate = errors / total if total else 1
    ok &= rate <= MAX_ERROR_RATE
    print(f"\nerror rate {rate:.2%} (target at most {MAX_ERROR_RATE:.0%})  {'PASS' if rate <= MAX_ERROR_RATE else 'FAIL'}")
    for kind, errs in stats.errors.items():
        for e in sorted(set(errs))[:5]:
            print(f"  {kind}: {e} (x{errs.count(e)})")
    if samples:
        print(f"database connections: max {max(s[0] for s in samples)}, busy at once max {max(s[1] for s in samples)}; "
              f"background jobs waiting: max {max(s[2] for s in samples)}, at the end {samples[-1][2]}")
    print("\nLoad test: " + ("targets met" if ok else "TARGETS MISSED"))
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=30)
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--workspace", type=int, default=34)
    ap.add_argument("--base", default="http://localhost:8000")
    sys.exit(asyncio.run(main(ap.parse_args())))
