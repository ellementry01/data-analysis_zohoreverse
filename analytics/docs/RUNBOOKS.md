# Runbooks: what to do when…

Short procedures for the people running Ellementry Analytics (Phase 8 of `AI_ASSISTANTS_PLAN.md`). Commands run from
`analytics/` on the server unless stated. Settings live in `analytics/.env`; after changing one, run
`docker compose up -d --force-recreate app`. Never paste a key or password into chat, a ticket or a commit.

Where to look first: **Administration → Monitoring** (cost, answer times, tool errors, thumbs-down answers, background
queue, evaluation runs) and **Administration → Audit log** (who did what). Server logs: `docker compose logs app --since 1h`
(secrets, e-mail addresses, phone numbers and URL query strings are scrubbed from them).

---

## 1. Claude is down or failing

**What people see.** Answers still come, from the free offline engine, with a note that the AI is unavailable. Dashboards,
alerts and "worth a look" do not depend on Claude. Briefings fall back to wording made by code.

1. Check https://status.anthropic.com. If Anthropic reports an incident, nothing to do: the app retries on the next question.
2. If Anthropic is fine: Monitoring → *Assistant tools* and the app log (`docker compose logs app --since 30m | grep -i claude`).
   - `401` / `authentication`: the key is wrong or revoked. Put a new one in `ANTHROPIC_API_KEY`, recreate the app.
   - `429` / `rate limit` from Anthropic: the organisation's API limit; wait, or raise it in the Anthropic console.
   - `budget` / "limit is used up": see runbook 2.
3. To switch the assistants off for everyone while it is sorted out, set the `ASSISTANT_*` flags to `false` and recreate
   the app; dashboards and the offline Ask page keep working.

## 2. The AI spending limit is reached

**What people see.** "Today's AI limit for you is used up" (per person, resets at midnight India time) or "this month's AI
limit for the company is used up" (resets on the 1st). They still get offline answers.

1. Monitoring → *Per person* shows who spent what. A single person far above the rest: ask what they were doing before
   raising anything (a loop in a script, a very long conversation).
2. To raise a limit: `AI_DAILY_LIMIT_USER_INR` (default 100) or `AI_MONTHLY_LIMIT_INR` (default 3,000) in `analytics/.env`,
   then recreate the app. Write down the old value and put it back when the need has passed.
3. "You have asked N questions in the last minute/hour" is the per-person question limit, not money:
   `ASSISTANT_RATE_PER_MINUTE` (10) and `ASSISTANT_RATE_PER_HOUR` (120); `0` switches it off. Refusals show in
   Monitoring (*Limited*) and the audit log (`rate limited`).

## 3. A memory is wrong

1. The person opens **Memory** in their workspace and edits or deletes it; "Retire" keeps it out of answers but keeps the
   record. A memory flagged "needs review" (its metric changed) is not used until someone confirms it.
2. A wrong **team fact** (shared with everyone): a workspace admin edits or retires it on the Memory page. Approving team
   facts is admin-only, so check who approved it (Audit log → `memory saved`).
3. A wrong **decision** recorded from an alert: the decision stays in the history (it is a record of what was decided);
   add a new decision or a corrected memory instead.
4. If an answer used the wrong memory, its 👎 in Monitoring shows the steps and the memories it cited.

## 4. Someone leaves the company

Do all of these on their last day:
1. **Administration → Users → Switch off.** Their sessions and API tokens stop working at once (also when sign-in is
   through Google: switching off beats a valid Google account).
2. **Administration → API tokens:** revoke any token they created for scripts, and replace it where the script runs.
3. In each workspace, **Settings → Members:** remove them (or `DELETE /api/workspaces/{id}/members/{email}`).
4. Their **personal memories and conversations** stay in the database until removed. Ask the owner whether to keep them
   (for decisions others rely on, share the decision first) or delete them on the Memory page / via the conversation list.
5. Remove them from the company Google Workspace as usual: they can no longer sign in at all.

## 5. A thumbs-down answer

1. Monitoring → *Answers marked wrong*: open it to see the question, the answer, the person's note and every step (tool,
   input, error).
2. Decide: wrong data (a data issue: add it on **Data issues**), wrong metric definition (fix it in the Semantic layer),
   wrong tool use or wording (add a case to the matching eval set in `backend/evals/sets/` so it stays fixed).
3. Prompt or tool changes need the eval sets run again before release (runbook 7).

## 6. Something is wrong after a release

1. Roll back to the previous release: `git log --merges --oneline -5`, then `git checkout <previous merge>`,
   `docker compose up -d --build`. Check `/api/health` and dashboards 195 (Stock) and 196 (Fulfilment).
2. If a database migration came with the release, restore the app database backup taken before it (07-operations,
   "Backups"): `backups/ellementry_analytics_<date>_pre-phaseN.dump`.
3. The warehouse is never changed by an app release; if a warehouse change went wrong, restore with `python dw.py` from
   `backups/ellementry_dw_<date>.dump` (08-ellementry-warehouse).

## 7. Releasing a change to the assistants

1. Push the branch: GitHub runs the free checks (`.github/workflows/checks.yml`): every backend test with a scripted
   Claude, the eval sets' format, the frontend typecheck and build, and an audit of browser dependencies.
2. With the owner's OK (live runs cost money; the full suite is about ₹60-80), run the sets the change touches live:
   `EVAL_LIVE_OK=1 python -m evals run <set> --live` from `backend/`. Each run is recorded in the app.
3. `python -m evals gate` from `backend/`: it checks the latest live run of every set against its pass mark and that the
   run is newer than the last change to the assistant code. Merge only when it says "Release gate: open".

## 8. The alert runner failed

The bell shows "The stock (or operations) agent's run failed" after a sync. On the warehouse PC, from `warehouse/`:
`python dw.py agents run all`. Exit code 3 = not run (the latest build failed, an ERROR data check, or a missing
setting: fix that first); 4 = a run failed and wrote nothing (read the message; the previous alerts stay as they were).
Never edit `insight.*` tables by hand; change thresholds only through `dw.py psql` after `python dw.py backup`.

## 9. A key or password may have leaked

1. **Anthropic key:** revoke it in the Anthropic console, create a new one, put it in `ANTHROPIC_API_KEY`, recreate the app.
2. **Read-only database login:** `python scripts/setup_readonly_role.py` makes a new password and updates `.env`; then
   `docker compose up -d --force-recreate app`.
3. **App database password** (`POSTGRES_PASSWORD`): change it in the database (`ALTER ROLE ellementry PASSWORD …` inside
   the db container) and in `.env` together, then recreate both containers.
4. **API tokens:** revoke on Administration → API tokens. **Google sign-in secret:** rotate in Google Cloud and update
   `GOOGLE_CLIENT_SECRET`.
5. Look in the Audit log for activity you don't recognise since the leak.
