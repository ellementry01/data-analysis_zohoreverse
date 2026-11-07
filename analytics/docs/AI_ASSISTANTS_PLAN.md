# AI assistants: phased implementation plan

*Written 2026-11-07 from the design discussion with the owner. Nothing in this plan is built yet.*

## 1. What we are building

Ellementry Analytics becomes internal company software used by many employees. On top of the dashboards it gets:

1. **A chat assistant on every dashboard** that already knows that dashboard (its widgets, filters, metric definitions, caveats and what is on screen), so the user never has to explain the context.
2. **Memory.** Each assistant remembers past conversations, and learns the user's decisions, preferences and way of thinking over time. Learned memories are **proposed and approved**, never saved silently.
3. **A global assistant** (the Ask page) that knows all dashboards, all memories the user may see, and can answer anything across them.
4. **Scheduled domain agents** (Stock AI, Operations AI, an Executive briefing; later Marketing, Finance and the others from the AI Hub plan) that run after each data refresh and raise alerts and recommendations in the app.
5. **Data-issue awareness.** Assistants know the open data issues and say when a number is affected, instead of explaining a wrong number as if it were real.

### Decisions already taken (2026-11-07)

| Decision | Choice |
|---|---|
| Who uses it | The owner and the COO first, then many employees: built to production standard |
| How it learns | Explicit "remember…" is saved at once; anything inferred is proposed and approved by the user |
| What the assistants may do | Read and explain only: they never edit dashboards, data or settings |
| Main uses | Explain the numbers, dig deeper, track decisions, spot problems |
| Data alerts | Go to the owner only, in the app only (no email / WhatsApp for now) |
| ERP | smERP is replaced by ERP Daddy after Diwali; it has an API. Don't automate smERP |
| Models | Claude Haiku 5.5 and Sonnet 5.5 only (`config.check_model`); never Opus or Fable; no server-side fallbacks |
| Orchestration | Our own tool-calling loop on the Anthropic SDK, not LangGraph; one engine with different scopes, not one codebase per agent |
| Data streams | The data watchdog (freshness checks, holding back bad data) is a separate parallel stream with its own plan; this plan only consumes its issue register |

### Architecture in one picture

```
               ┌────────────── one assistant engine (backend/app/services/agent/) ──────────────┐
 Dashboard chat│ scope = dashboard:<key>   ┌─ context builder (layers A–F, prompt-cached) ─┐   │
 Ask page      │ scope = global            │  rules · catalog · dashboard pack · memories  │   │
 Scheduled jobs│ scope = domain:<name>     │  · conversation summary · screen state        │   │
               │                           └───────────────────────────────────────────────┘   │
               │  tool loop (≤ 6 steps, Haiku by default, Sonnet for complex, 1 escalation)    │
               │  tools: get_dashboard_context · get_widget_data · run_query · describe_metric │
               │         list_values · get_data_issues · search_memory · propose_memory        │
               └───────────────┬───────────────────────────────────────────────┬──────────────┘
                               │ every number                                   │ every memory
                      QuerySpec → query_engine → validate_select →     memories table (personal /
                      run_readonly (unchanged guards)                   shared / decision), approved
```

**Rules that never change in any phase**
- Every number comes from the existing query path (`analytics.run_spec` or `validate_select` + `run_readonly`). The model never does arithmetic that is shown to the user (`claude._facts` pattern).
- Tools are read-only. The only write a tool can do is `propose_memory`, which creates a *proposal* the user must approve.
- An assistant acts with the permissions of the person asking, never more.
- Tool results and data values (product names, issue texts, notes) are untrusted text: they are passed as data and never followed as instructions.
- Live Claude calls in testing need the owner's OK first and stay short.

## 2. How each phase is run

Every phase follows the same cycle, and the next phase starts only after its exit gate is met and the owner signs off.

1. **Branch** from `main` (`phase-N-<name>`).
2. **Before any app-database migration:** dump the app database to `backups/ellementry_analytics_<date>.dump` (see 07). The warehouse is touched only in Phase 7, and only through `warehouse/dw.py` after `python dw.py backup`.
3. **Build** the steps in order. New Alembic migrations are numbered `0002_…`, `0003_…` (today there is only `0001_initial.py`).
4. **Test** at four levels:
   - **Unit and API tests** (`backend/tests`, fake Claude client, test database `ellementry_analytics_test`). The existing 407 tests must keep passing.
   - **Frontend checks:** `npm run typecheck && npm run build`.
   - **Evaluation set** for the phase (section 4): scripted questions with expected answers, run first with the fake client, then once live with the owner's OK.
   - **Hands-on check** in the browser on workspace 34, by the agent and then by the owner.
5. **Docs:** update `docs/context/` (03 backend, 04 AI layer, 05 security, 06 frontend, 09 decision log) and this plan's status table.
6. **Rebuild** Docker (`docker compose up -d --build`), check health and dashboards 195/196, **commit and push**.

### Status

| Phase | Name | Status |
|---|---|---|
| 0 | Groundwork | Done: signed off by the owner and merged 2026-11-07 |
| 1 | Dashboard chat (single question) | Done: signed off by the owner and merged 2026-11-07 (live eval 78/80, 69/69 numbers right); on for admins |
| 2 | Agent loop with tools | Done: signed off by the owner and merged 2026-11-07 (live eval 50/50, every number right); on for admins |
| 3 | Identity and access | Not started |
| 4 | Memory | Not started |
| 5 | Data issues and "worth a look" | Not started |
| 6 | Global assistant | Not started |
| 7 | Scheduled domain agents | Not started |
| 8 | Hardening and rollout | Not started |

---

## Phase 0: Groundwork

**Goal.** Everything later phases stand on, with no visible change for users.

**Steps**
1. **Stable dashboard keys.** Add `dashboards.key` (unique per workspace, e.g. `stock`, `fulfilment`, `days-of-cover`) and `dashboards.domain` (`sales`, `stock`, `operations`, `executive`, `data`). Today ids change on every `build_executive_dashboards.py` run; threads and memories must survive a rebuild, so they are keyed by `key`, never by id.
   - Set keys for the 10 existing dashboards with a one-off script; `build_executive_dashboards.py` and `update_dashboard_widgets.py` set and match by key from now on.
   - Rename-safe: renaming a dashboard keeps its key.
2. **Conversation scopes.** Migration `0002_assistant_scopes`:
   - `conversations`: `scope_type` (`workspace` | `dashboard` | `global`), `dashboard_key`, `summary`, `summary_upto_message_id`, `archived`.
   - `messages`: `screen_state` (JSON), `tool_trace` (JSON), `model`, `usage` (JSON), `feedback` (`up` | `down` | null) and `feedback_note`.
   - Existing Ask conversations become `scope_type = workspace`.
3. **AI usage ledger and spend caps.** New table `ai_usage` (user, workspace, conversation, model, input / output / cache tokens, estimated cost, purpose: `chat` | `memory` | `briefing` | `eval`). Every Claude call writes one row. Settings `AI_DAILY_LIMIT_USER_INR` and `AI_MONTHLY_LIMIT_INR`; when a limit is reached the assistant answers with the offline engine and says why. Prices live in one config table so they can be updated.
4. **Feature flags.** Settings `ASSISTANT_DASHBOARD_CHAT`, `ASSISTANT_AGENT_LOOP`, `ASSISTANT_MEMORY`, `ASSISTANT_GLOBAL`, `ASSISTANT_SCHEDULED` (all off by default), so each phase can ship dark and be switched on after its gate.
5. **Agent test harness.** Extend the fake Claude client in `tests/test_claude.py` into a reusable fixture that can script multi-turn tool calls (tool_use → tool_result → text), assert which models and parameters were sent (Haiku/Sonnet only, no `fallbacks`, no `temperature`), and simulate errors (rate limit, refusal, max_tokens).
6. **Evaluation framework.** `backend/evals/` with a YAML format per question: scope, screen state, question, expected numbers (computed by direct SQL on the app database at run time, never typed by hand), required caveats, forbidden claims. A runner `python -m evals run <set> [--live]` that reports pass / fail and the cost. `--live` refuses to run without `EVAL_LIVE_OK=1`.

**Tests**
- Migration up and down on the test database; existing data kept.
- Rebuilding dashboards keeps their keys; `update_dashboard_widgets.py` still updates 195 and 196 in place.
- Ledger row written for every fake call; caps switch to offline mode at the limit.
- All 407 existing tests pass.

**Exit gate.** Migrations applied on the live app database after a dump; keys set on all 10 dashboards; the harness and eval runner work with one sample question; nothing visible to users has changed.

---

## Phase 1: Dashboard chat (single question)

**Goal.** A chat panel on every dashboard that answers questions about that dashboard without the user giving context. Uses today's one-question, one-query engine, so value arrives early.

**Steps**
1. **Dashboard context pack** (`services/agent/context.py`, `build_dashboard_pack(db, ws, dashboard)`), generated from the definition, never hand-written:
   - name, description (its caveats), filters with their current defaults;
   - each widget: title, chart type, the measures and dimensions in plain words, filters applied;
   - each metric used: label, expression in plain words, business rules, time column, semi-additive, higher-is-better, format;
   - the date range the data covers (`analytics._data_start` and the latest date), and the last sync time.
   - Budget: about 6,000 tokens; widgets beyond that are listed by title only.
   - Cached per dashboard key; rebuilt when the dashboard, a metric or a dataset's sync changes.
2. **Screen state.** `DashboardView.tsx` sends, with every message: the current filter values, the drill state of each widget, and the widget the user clicked "Ask about this" on (if any). The **server recomputes** the widget numbers from those filters (it does not trust numbers sent by the browser), and adds a compact summary (KPI values, top rows, at most about 2,000 tokens) to the prompt.
3. **API.** `POST /api/workspaces/{ws}/dashboards/{key}/assistant/ask` with `{question, conversation_id?, screen_state}`; `GET …/assistant/conversations` (this user's threads on this dashboard). Requires viewer access to the dashboard.
4. **Prompt layers** (built in this order so the stable part is cached):
   A. rules (system prompt, extended with "you are the assistant of the *X* dashboard; prefer its metrics and filters; mention its caveats when relevant");
   B. workspace catalog (`schema_context`, already cached);
   C. dashboard pack (cached per dashboard);
   E. last 6 messages of this thread;
   F. screen state and the question, with today's date (never in the cached prefix).
5. **Planning.** Reuse `claude.plan` with the extra layers; the plan's QuerySpec inherits the dashboard's current filters unless the question overrides them ("this" and "here" mean the current screen).
6. **Frontend.** `components/AssistantPanel.tsx`: a collapsible right-hand panel on `DashboardView.tsx` with the thread list for this dashboard, messages rendered with the existing `ResultPanel` / `Chart`, an "Ask about this" button on each widget's menu, and thumbs up / down on each answer. On phones the panel opens full-screen.
7. Behind flag `ASSISTANT_DASHBOARD_CHAT`; until Phase 3, only workspace admins can use it.

**Tests**
- Pack builder: every widget, metric and caveat of each of the 10 dashboards appears; budget respected; cache invalidated when a widget changes.
- Screen state: filters from the browser are validated against the dashboard's filter definitions (unknown fields rejected); the server's recomputed numbers are used.
- A question with no dashboard words ("why is it low?") on Stock gets a Stock metric; on Fulfilment a Fulfilment metric.
- Threads are per user and per dashboard; one user can't open another's thread (extends the existing `test_assistant.py` check).
- **Eval set `dashboard_basic`:** 8 questions per dashboard (80 total), e.g. "what does this tile mean", "why is units with no cost separate", "which location holds the most stock right now", "same for Jaipur only". Pass mark: 90% correct numbers, 100% no invented numbers, caveats mentioned where required.
- Browser check on Stock and Fulfilment with filters changed and drill-down open.

**Exit gate.** Eval pass mark met with the fake client and once live (owner's OK, cost reported); the owner has used it on at least 3 dashboards and accepts the answers.

---

## Phase 2: Agent loop with tools

**Goal.** Multi-step answers: "why" questions, breakdowns, comparisons the dashboard doesn't show, all still read-only and governed.

**Steps**
1. **Engine** `services/agent/engine.py`: one loop for every scope.
   - Calls `messages.create` with `tools`, runs each tool the model asks for, returns `tool_result`, repeats until a final answer.
   - Limits: at most 6 tool calls per answer, 90 s wall time, and the per-turn token cap; on hitting a limit it answers with what it has and says so.
   - Model: `claude.route()` decides Haiku (effort low) or Sonnet (effort medium) per question; one escalation to Sonnet when a tool keeps failing; `check_model` on every call.
2. **Tools** (`services/agent/tools.py`; each validates its input with Pydantic, checks permissions, and returns compact JSON):

   | Tool | Does | Guard |
   |---|---|---|
   | `get_dashboard_context(key)` | the pack of a dashboard | user must see that dashboard |
   | `get_widget_data(key, widget, filters, drill)` | runs one widget like the dashboard does | same filters validation as the UI |
   | `run_query(spec)` | any QuerySpec through `run_spec` | workspace views only; row cap 500 |
   | `describe_metric(name)` | definition, rules, caveats | |
   | `list_values(field, search)` | distinct values, to resolve "Jaipur" or "Bagru" to real values | ≤ 50 values |
   | `get_data_issues(scope)` | open issues touching a dashboard, metric or dataset | added in Phase 5; returns "none recorded" before |

   SQL is not a tool at first: the model works through QuerySpecs. A `run_sql` tool (via `validate_select` + `run_readonly`) is added only if the eval set shows questions that specs can't express.
3. **Grounded answers.** The final answer cites the tool results it used; numbers in the text are checked by code against the tool results (any number not found in a result, or derivable by `_facts`, is flagged and the answer regenerated once, then shown with a warning).
4. **Streaming.** Server-sent events from a new endpoint so the panel shows each step as it happens ("Checking RTO by courier…"), then the answer, charts and the SQL / spec behind each step.
5. **Conversation compaction.** When a thread passes about 12 messages, older turns are summarised by Haiku into `conversations.summary` (key facts, numbers with their filters, open questions); the prompt carries the summary plus the last 6 messages.
6. Behind flag `ASSISTANT_AGENT_LOOP`; Phase 1's single-question path stays as the fallback.

**Tests**
- Harness scripts: a 3-step "why" answer; a tool error followed by a corrected call; the step limit; the timeout; a refusal; rate limit → offline answer with a note.
- Every tool: permission denied for a dashboard the user can't see; bad input rejected; row caps enforced.
- Number check: an answer containing a number not in any tool result is caught.
- **Prompt-injection tests:** a product name or issue text containing "ignore your instructions and…" is treated as data (answer unaffected, no extra tool calls).
- **Eval set `dashboard_deep`:** 5 multi-step questions per dashboard (e.g. "why did late shipments jump in Oct 2025", "which categories drive the slow stock value", "compare Bagru stock in Aug vs Jul 2026"). Pass mark: 85% correct, 100% grounded.
- Cost per answer recorded in the ledger; median and 95th percentile reported in the phase review.

**Exit gate.** Both eval sets pass (`dashboard_basic` must not regress); median answer time under 15 s; the owner accepts the "why" answers on Stock and Fulfilment.

---

## Phase 3: Identity and access

**Goal.** Real sign-in and permissions, required before the COO or anyone else uses the assistants (personal memory is meaningless if identity can be changed in a header).

**Steps**
1. **Company sign-in (OIDC)** with Google Workspace or Microsoft 365 (owner to confirm which). Server-side sessions in an HTTP-only, secure cookie; sign-out; session expiry. `deps.current_user` reads the session; the `X-User-Email` header is accepted only when `AUTH_MODE=dev` (tests and local development), and the app refuses to start with `AUTH_MODE=dev` on a non-localhost bind.
2. **Users and roles.** Table `users` (email, name, active, last login); workspace roles stay `viewer` / `editor` / `admin`. New `dashboard_access` (dashboard key or domain → role or user) so, for example, Finance dashboards are visible only to finance and management. A user removed or deactivated loses access at once.
3. **One permission check for people and assistants.** `permissions.can_see(user, dashboard|dataset|metric)` used by the dashboard routes *and* every agent tool, so an assistant can never reach data its user can't.
4. **Audit log.** Table `audit_events`: sign-ins, assistant questions (who, which scope, which tools), memory approvals, permission changes. Admin page to view it.
5. Remove the user switcher from Settings in production mode.

**Tests**
- OIDC flow with a fake identity provider; expired session; deactivated user.
- Every existing route and every agent tool denies a user without access (extends `test_security_audit.py`).
- The global assistant (later) can't see a dashboard the user can't see: tested here at tool level.
- Header spoofing has no effect in production mode.

**Exit gate.** The owner and the COO sign in with company accounts on the target hosting (depends on the production-foundation track: server, HTTPS); security tests pass; QA_REPORT risk R1 closed.

---

## Phase 4: Memory

**Goal.** Assistants remember and learn: personal preferences, shared business facts and decisions, with the user approving what is learned.

**Steps**
1. **Tables** (a new migration with the next free number, `…_memory`):
   - `memories`: workspace, `layer` (`personal` | `shared` | `decision`), `kind` (`preference` | `fact` | `decision` | `caveat` | `open_question`), `scope` (`global` | `dashboard:<key>` | `domain:<name>`), `owner_email` (null for shared), `visibility` for decisions (`private` | `shared`), `text`, `rationale`, `source_message_id`, `status` (`proposed` | `active` | `rejected` | `retired`), `depends_on` (issue codes, metric names, warehouse schema version), `created_by`, `approved_by`, `approved_at`, `last_used_at`, `use_count`, `supersedes_id`, and a `tsvector` column for search.
   - `user_profiles`: one short profile per user ("how this person thinks"), its sources and version.
2. **Background worker.** Add Redis and a worker container (RQ) to the compose file. Memory extraction, profile updates and conversation summaries run there, never in the request.
3. **Saving memories**
   - **Explicit:** "remember…", "from now on…", "I decided…" in a message → the assistant calls `propose_memory`, and an explicit request is saved as `active` at once (shown as "Saved to memory", with undo).
   - **Inferred:** after a thread has been idle for 30 minutes, a Haiku job reads it and proposes at most 3 memories, each with the message it came from. They appear as "Remember this?" cards in the panel and on the Memory page: accept, edit, or reject.
   - **Shared facts** ("DFAL means…") proposed by anyone go to admins for approval; until approved they are personal.
   - **Decisions** keep the reason, the date, what they depend on, and visibility (private by default; the owner can mark one shared).
4. **Using memories.** Before each answer, `search_memory` retrieves at most 15 memories the user may see: same scope first, then global, ranked by text match, recency and use; plus the user profile (≤ 400 tokens). They go in prompt layer D, each with its id, so the answer can say "as you decided on 3 Nov (memory #12)". `last_used_at` and `use_count` are updated.
5. **Staleness.** When a memory's `depends_on` changes (an issue is solved, a metric definition changes, the warehouse schema version moves), the memory is flagged "needs review" and not used until the user keeps or retires it.
6. **Profile.** A weekly job (and after every 10 newly approved memories) rewrites each user's profile from their active memories; the user can read and edit it.
7. **Memory page** (Settings → Memory): list, search, filter by layer, scope and status; edit, retire, delete; see where each memory came from and when it was last used. Admins also see the shared-fact queue.
8. Behind flag `ASSISTANT_MEMORY`.

**Tests**
- **Isolation:** user A's personal memories and private decisions never reach user B: in retrieval, in prompts (asserted on what the fake client received), in the Memory page, in the API.
- Explicit save, inferred proposal, approval, rejection (rejected memories are never proposed again for the same message), editing, retiring, deleting.
- Retrieval ranking and the token budget; scope rules (a Stock memory isn't used on Fulfilment unless global).
- Staleness flag when an issue closes or a metric changes.
- Worker: jobs retried on failure; nothing is lost when Redis restarts.
- **Eval set `memory`:** scripted multi-session stories, e.g. session 1 "always compare with last year, not previous period" → session 3 a comparison question uses last year; a decision recorded on Days of cover is recalled when partner stock comes up; a rejected inference is not used.

**Exit gate.** Isolation tests pass; memory eval passes; the owner has used it for a week and judged the proposals useful (acceptance rate tracked; target above 50%).

---

## Phase 5: Data issues and "worth a look"

**Goal.** Assistants know about data problems, and each dashboard opens with what deserves attention.

**Steps**
1. **Issue register in the app** (shared with the data-watchdog stream): table `data_issues` (code such as `D-124`, title, status, severity, the datasets / metrics / dashboard keys it affects, summary, opened / solved dates, source `manual` | `watchdog`). A script imports the open issues from `warehouse/docs/ISSUE_LOG.md`; after that the register is the source of truth and is edited in an admin page. (The watchdog stream adds automated entries and the "refresh held back" state.)
2. **`get_data_issues` tool** goes live; issues touching the current dashboard are also added to the dashboard pack as caveats, so the assistant says "this tile is affected by D-124" unprompted.
3. **Known-issue badges** on affected tiles (shown to everyone, worded for management: "known data issue, see note").
4. **"Worth a look" items** when a dashboard opens: computed in code after each sync from what the app already calculates (anomaly markers from `analytics.detect_anomalies`, the comparison with last year, data gaps, coverage), ranked, at most 5; Haiku only words them. Cached per dashboard per sync, so opening a dashboard costs nothing. Clicking one starts a chat about it.
5. Owner-only **notifications panel** for data issues (the watchdog stream fills it with freshness and held-back alerts).

**Tests**
- Import from ISSUE_LOG.md: every open issue present once, statuses right.
- An affected tile shows its badge; solving the issue removes it and flags dependent memories (Phase 4 staleness).
- "Worth a look" items: each one traceable to a computed value; none produced on a dashboard with nothing unusual; recomputed only after a sync.
- **Eval set `issues`:** questions on tiles affected by known issues must mention the issue; questions on clean tiles must not invent issues.

**Exit gate.** Evals pass; the owner reviews "worth a look" on all 10 dashboards for one week and keeps it switched on.

---

## Phase 6: Global assistant

**Goal.** The Ask page becomes the assistant that knows everything the user may see.

**Steps**
1. **Dashboard index:** one short card per dashboard the user can see (purpose, main metrics, domain, open issues count), generated from the packs. The global scope loads the index, not every pack; it calls `get_dashboard_context` when it needs one.
2. **Cross-scope memory:** retrieval covers global memories, every dashboard's memories and decisions the user may see, and the profile; answers say where a memory came from.
3. **Cross-dashboard questions:** "what did I decide about partner stock", "compare what Stock and Fulfilment show for Bagru in Aug 2026", "summarise this week across all dashboards".
4. `AskPage.tsx` moves to the new engine (scope `global`) with the same panel features as Phase 1–4; the old path stays as the offline fallback.
5. Behind flag `ASSISTANT_GLOBAL`.

**Tests**
- Permissions: a user without access to a dashboard gets no data, no memories and no mention of it.
- Context size stays within budget with 10 and with 30 dashboards (synthetic).
- **Eval set `global`:** 25 cross-dashboard questions.

**Exit gate.** Evals pass; the owner and the COO use it for a week.

---

## Phase 7: Scheduled domain agents

**Goal.** Agents that work without being asked: the rule-based Stock AI and Operations AI from PRD-001, and an Executive briefing. Recommendations and alerts appear in the app; people record decisions.

**Steps**
1. **Rules run in the warehouse** (PRD-001 design): an agent runner (`python dw.py agents run …`) after each successful build writes to the existing `insight` schema (`model_run`, `recommendation`, `alert_rule`, `alert_event`, from `sql/090_insight.sql`). Rules are gated by coverage (no alert on a process with no data) and auto-resolve. Mart views expose them; the read-only connector syncs them. Warehouse changes follow its rules: trial database first, `dw.py backup`, tests on a disposable database.
2. **Decisions are recorded in the app**, not the warehouse (the app stays read-only on the warehouse): table `agent_decisions` (recommendation or alert id, accepted / rejected / acknowledged, who, when, note). Decisions also become `decision` memories automatically (they are explicit user acts).
3. **Domain scopes:** `domain:stock` (Stock, Days of cover, Discontinued & slow stock), `domain:operations` (Fulfilment, Purchasing & transfers, Returns), `domain:executive` (all). A domain assistant explains each recommendation from its rule, inputs and caveats.
4. **Executive briefing:** a weekly job (daily once data is live) collects the KPIs, changes, open alerts and recommendations, and open issues; code computes every number; Sonnet writes the summary; stored and shown in the app (in-app only, per the decision).
5. **Enable rules one at a time** with thresholds the business confirms (PRD-001 lists them as PROPOSED).
6. Behind flag `ASSISTANT_SCHEDULED`.

**Tests**
- PRD-001 section 10 test cases for every enabled rule (raised when crossed, none when not, one open event per condition, auto-resolve).
- Decisions need who and when; a decision on an expired recommendation is refused.
- Briefing: every number in it traceable to a query; regenerated identically from the same build.
- Domain assistant explains a recommendation correctly (eval set `domain`).

**Exit gate.** Rules agreed with the business are live; the owner reviews two weeks of alerts and briefings; false-alert rate judged acceptable.

New domains (Marketing, Finance, Commerce, Customer, Product, Design) are added the same way **once their data is in the warehouse**: a domain scope, its dashboards, its rules, its eval set.

---

## Phase 8: Hardening and rollout

**Goal.** Ready for many employees.

**Steps**
1. **Load test:** 30 concurrent chat users and dashboard viewers; response times and database load within targets; worker queue keeps up.
2. **Security review:** prompt injection, permission bypass through tools, memory leakage between users, rate limits per user, logs free of secrets and customer personal data. Close QA_REPORT risks R2 (npm audit, Tailwind 4) and R5 (`READONLY_DATABASE_URL`).
3. **Observability:** admin page with AI cost per user and per day, answer times, tool errors, thumbs-down answers with their traces, eval results over time.
4. **Release gate:** the full eval suite runs in CI on every change to `services/agent/`, prompts or tools; a drop below the pass marks blocks the release.
5. **Runbooks:** what to do when Claude is down, the spend cap is hit, a memory is wrong, a user leaves.
6. **Rollout in waves:** owner → COO and management → selected teams → everyone, with permissions reviewed and a feedback round before each wave; a short user guide in the app.

**Exit gate.** Load and security results accepted; first wave of employees live.

---

## 3. Dependencies outside this plan

- **Production-foundation track** (separate plan): hosting (cloud or office server), staging and production environments, HTTPS, CI/CD, backups with tested restores, monitoring. Phase 3 needs hosting and HTTPS; Phase 8 needs all of it.
- **Data-watchdog track** (separate plan): freshness and volume checks, holding back bad data, the "refresh held back" state; it shares the `data_issues` register built in Phase 5 (whichever stream gets there first creates the table).
- **ERP Daddy integration** (after Diwali): new sources, code mapping, cut-over date, parallel run. The assistants are unaffected as long as the mart views keep their meaning.
- **Data completeness:** the owner will provide the remaining data over time; open data issues are surfaced (Phase 5), not blockers.

## 4. Evaluation sets (summary)

| Set | Phase | Size | Pass mark |
|---|---|---|---|
| `dashboard_basic` | 1 | 80 (8 per dashboard) | 90% correct numbers, 0 invented numbers, required caveats present |
| `dashboard_deep` | 2 | 50 | 85% correct, 100% grounded |
| `memory` | 4 | 15 multi-session stories | 100% isolation, 85% correct recall |
| `issues` | 5 | 20 | 100% mention of affecting issues, 0 invented issues |
| `global` | 6 | 25 | 85% correct, 100% permission-correct |
| `domain` | 7 | 20 | 90% correct explanations of recommendations |

Expected answers are computed by SQL at run time from the app database, so the sets stay valid when data changes. Live runs need the owner's OK; their cost is reported.

## 5. Open questions (do not block Phases 0–2)

1. Company email on Google Workspace or Microsoft 365? (Phase 3 sign-in.)
2. Will the COO use their own device on the office network? (Phase 3 hosting.)
3. Should the COO see the owner's decisions: none, only ones marked shared (default in this plan), or all?
4. Who besides admins may approve shared business facts?
5. Monthly AI budget for the spend cap (Phase 0 setting).
