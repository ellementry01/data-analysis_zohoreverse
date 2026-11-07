# 04 — AI layer (Ask AI with Anthropic Claude)

Code: `backend/app/services/nlq/claude.py` (Anthropic) and `nlq/assistant.py` (orchestration). Tests: `backend/tests/test_claude.py`, 32 tests with a fake client.

## Hard policy (the user's explicit instruction)
- **Use only Claude Haiku 5.5 (`claude-haiku-5-5`) and Claude Sonnet 5.5 (`claude-sonnet-5-5`).**
- **Never use Opus or Fable.** Mythos is also refused.
- Enforced in `config.check_model()`:
  - The model ID must match `^claude-(haiku|sonnet)-[0-9a-z-]+$`, and IDs containing opus/fable/mythos are rejected.
  - It runs as a pydantic validator on `ANTHROPIC_SIMPLE_MODEL` / `ANTHROPIC_COMPLEX_MODEL`, so the app refuses to start with a bad model.
  - It runs again inside `route()` and `escalate()`.
- **No server-side `fallbacks` parameter and no `temperature`.** Fallbacks could route requests to Opus or Fable. The test fake asserts that neither is ever sent.
- The key lives only in env: `ANTHROPIC_API_KEY` in `analytics/.env` (Docker) or `backend/.env` (local). It has a placeholder in both `.example` files. **Never print it.**

## Routing (`claude.route`) — decided in code, with no extra API call
- **Complex → Sonnet 5.5 at effort `medium`** if any STRONG pattern matches:
  - why / root cause / drivers
  - opposing trends ("declining X but increasing Y")
  - cohort / retention / cumulative / running total / moving average / rolling
  - correlation / impact of / effect of / elasticity
  - share / percentage / proportion / contribution / mix of
  - top-N within each group
  - forecast / predict
- It also routes to Sonnet if **2 or more WEAK signals** are present:
  - compare / vs / against
  - several time windows
  - several conditions
  - more than 30 words
  - 3 or more measures, dimensions, or datasets (taken from the offline parser's spec hint)
- **Everything else → Haiku 5.5 at effort `low`.**
- **Escalation, at most once, to Sonnet medium:**
  - when Haiku's plan fails validation or execution, with the error passed back as feedback
  - when Haiku asks to clarify a question that the offline parser could already map
- **Explanations always use Haiku at effort low.**

## Planning call (`claude.plan` → `_call`)
- `client.messages.create(model, max_tokens, system=[instructions, schema_context + cache_control ephemeral], messages, output_config={"effort": …, "format": {"type": "json_schema", "schema": PLAN_SCHEMA}})`
- `PLAN_SCHEMA` fields: `kind` (spec / sql / clarify), `title`, `chart` (enum, including "auto"), `assumptions`, `clarification`, `spec` (a JSON **string** holding a QuerySpec), and `sql`. All are required, with `additionalProperties: false`.
- The **workspace schema context is prompt-cached**. It holds datasets, columns, relationships, metrics with their rules, glossary, and sample values. Today's date goes in the **user turn**, never in the cached system prefix.
- The last 6 history messages are included, so follow-ups work.
- `SYSTEM_PROMPT` rules:
  - Prefer a spec, so governed metrics and business rules apply; use SQL only when a spec can't express the question.
  - Never invent numbers. Clarify when the question is ambiguous.
  - **Counting rule** (added after the live check): count the rows of the dataset that lists X with `{"field":"<dataset>.*","agg":"count"}`. Use `count_distinct` on a name column only when the user asks for distinct names. For share or percentage questions, return the per-group values, because the tool computes exact shares.
- Errors:
  - SDK errors (connection, rate limit, 5xx) are mapped to `ClaudeUnavailable`, and the offline engine answers with a note.
  - A refusal or `max_tokens` stop is a `ClaudeError`.
- Usage (input, output and cache tokens) is logged and returned in the payload.

## Execution (`assistant._run_claude`)
- **spec:** `QuerySpec.model_validate` → `_assign_aliases` → `analytics.run_spec`. This is the same engine and the same guards as charts.
- **sql:** `validate_select(sql, schema, allowed=workspace views)` → `run_readonly("SELECT * FROM (…) _ai LIMIT 500")` → logged to `query_history`.
- There are 2 attempts in total; the second one is the escalation.
- If both attempts fail, the result is `type:"error"` with the message "I couldn't build a valid query…". Nothing unsafe ever runs.
- Response payload: `engine:"claude"`, `model`, `model_label`, `routing` (reasons), `escalated` and `usage`, plus columns, rows, sql, assumptions, insights and chart_type.

## Explanation (`claude.explain`)
- Haiku receives the question, columns, up to N rows, the assumptions, and **`computed_facts`**. `_facts()` computes `row_count` and, per measure, min, max and total. For additive measures it also computes `share_of_total_pct`; ratio measures get no total.
- `EXPLAIN_PROMPT` says to quote only the rows or computed_facts and **never do arithmetic**. This was added because the model once wrote "75 locations" when the true total was 76.
- Rows and facts reach the model **already formatted for display** (`claude._display`: ₹ with lakh/crore, %), and the prompt says to quote them exactly, never convert. Added 2026-11-07 after the live eval quoted raw values such as 0.0369 and 28,264,401.39.
- The prompt also says assumptions may be restated as caveats but never contradicted or commented on: one answer had claimed the dashboard "should be checked" because of its own interpretation note.
- If the explanation fails, `template_explanation` builds the text deterministically instead.

## Dashboard assistant (Phase 1, `services/agent/context.py`, 2026-11-07)
- Same planning and execution path as Ask (`assistant.answer` with an `AnswerScope`), plus three things:
  - **Dashboard pack** (`build_dashboard_pack`): the dashboard's description (caveats), filters with defaults, every widget in plain words, the definitions of the metrics used (rules, date column, stock-like, higher-is-better), and the dates each dataset covers. Generated from the definitions, ≤ 24,000 characters, cached by a fingerprint of the dashboard, its widgets, the metrics and the datasets' last sync. It goes into `claude.plan` as a third system block with `cache_control`, after the schema, preceded by `DASHBOARD_PROMPT`.
  - **Screen state** (`validate_screen`, `screen_summary`): filter values, drill-downs and the focused widget. Unknown filters, widgets or drill fields are refused. The server recomputes every widget with those filters (≤ 8,000 characters, the focused widget first with 15 rows, others 5) and puts that text in the **user turn** (never in the cached prefix). Cached for 10 minutes per screen.
  - **Filter inheritance** (`inherit_filters`, `assistant._run_scoped`): a question keeps the dashboard's date range unless its spec sets `time_range`, and its value filters unless the spec filters the same field. Each inherited filter becomes an assumption shown with the answer. When the engine skips a filter because the question's data has no link to that field (it warns "Filter on … does not apply"), the answer says so ("covers all values") instead of claiming the filter.
- The dashboard chat never creates or changes dashboards: a "create a dashboard" request gets a read-only note.
- Threads are `scope_type = dashboard` with the dashboard **key**; each user message stores its screen state, each answer its model and usage.

## Multi-step answers with tools (Phase 2, `services/agent/`, 2026-11-07)
- With `ASSISTANT_AGENT_LOOP=true`, the dashboard chat answers through `agent/engine.run`: a manual tool loop on the Anthropic SDK (`claude.call_with_tools`, same model allow-list, spend caps and ledger as every call). Routing as before (Haiku low / Sonnet medium); after 2 failed tool calls on Haiku the rest of the answer escalates once to Sonnet.
- **Tools** (`agent/tools.py`, all read-only): `run_query` (a QuerySpec through `_run_scoped`, so the dashboard's filters apply), `get_widget_data` (a widget exactly as a dashboard computes it, with optional filters and drill), `describe_metric`, `list_values`, `get_dashboard_context`, `get_data_issues` (empty until Phase 5). No SQL tool. Results reach the model formatted for display, at most 50 rows, with exact totals and shares in `facts`. Tools see only their workspace; per-dashboard access arrives with Phase 3 (`tools.can_see_dashboard`).
- **Limits:** 6 tool calls, 90 s, 300,000 tokens per answer; at a limit the model is told to answer with what it has (`tool_choice: none`).
- **Number check** (`agent/numbers.py`): every number in the final text must match a tool result (cells, labels, totals, shares; rounding and ₹ L/Cr/% aware), the question, the screen or the dashboard text. Otherwise one rewrite is requested; numbers still untraceable are listed in the answer's `warnings`.
- **Payload:** `steps` (each tool call: label, ok/error, rows, spec, SQL, notes) and the last data result as the answer card; `tool_trace` is stored on the message.
- **Streaming:** `POST /dashboards/key/{key}/assistant/ask/stream` sends `step`, `step_done`, `checking`, `escalated`, then `answer` or `error` as server-sent events; the panel shows each step live.
- **Answers match the dashboard:** the prompt forbids adding filters to a governed metric (the first live run had RTO 8.1% with a website filter against the tile's 7.97%), and asks for plain text; `engine._plain` strips any markdown bold.
- **Long threads:** past 12 messages since the last summary, all but the last 6 are summarised by Haiku into `conversations.summary` (`purpose = summary` in the ledger); the summary goes in the next user turn. Since Phase 4 this runs as a background job right after the answer (the answer never waits for it).

## Memory (Phase 4, `services/memory.py`, 2026-11-07)
- With `ASSISTANT_MEMORY=true` (and the agent loop on), the dashboard chat gets two more tools, `propose_memory` and `search_memory`, and a short memory instruction block (cached with the rules; the Phase 2 prompt is unchanged when memory is off).
- **Explicit saves:** whether the user asked to remember is decided **in code** from the user's own words (`memory.is_explicit`: "remember ...", "note ...", "from now on", "going forward", "I/we decided", not questions like "do you remember ...?"). Only then does `propose_memory` save as active; otherwise the model's save becomes a proposal the user must approve. Text inside data or tool results can therefore never create an active memory. At most 3 per answer; a near-identical memory of the same person is reused (word-set similarity 0.8). An explicit request with no data question goes straight to the agent (it would otherwise look like chit-chat).
- **Learned suggestions:** after each dashboard-chat answer an `extract_memories` job is (re)scheduled 30 minutes ahead (one per conversation). It sends Haiku the new messages (numbered user turns) and the person's known memories, with a JSON schema; at most 3 proposals, each tied to its user message; anything similar to a rejected memory, or from a message whose suggestion was rejected, is dropped; `memory_scanned_upto_message_id` moves on so nothing is read twice. Ledger purpose `memory`.
- **Retrieval** (`memory.retrieve`): active memories the person may see, in scope (this dashboard, its domain, global), ranked by scope match, PostgreSQL `ts_rank` against the question, kind (preferences and decisions first), recency and use; at most 15 and 4,500 characters, plus the profile (1,600 characters). They go in the question turn as `WHAT YOU REMEMBER` ("#12 [decision, days-of-cover dashboard, 3 Nov 2026] ... Why: ...") and `ABOUT THIS USER`. Memories cited in the answer as "memory #N" get their use count and last use updated and are returned as `memories_used`; `memories_saved` lists what the answer saved. The number check ignores "#N" references and allows numbers from the memory text.
- **Staleness:** a memory that names a metric stores its definition fingerprint; when the definition changes, retrieval marks it `needs_review` and leaves it out until its owner keeps (re-fingerprints) or retires it. A metric missing from a restricted person's catalog does not count as deleted; the hourly background check, which sees every metric, decides that.
- **Profile:** `update_profile` (Haiku) rewrites a 120-word profile from the person's active personal memories and decisions after every 10 approvals and weekly; a profile the user edited is passed back with "keep their wording".

## Usage ledger and spend caps (`services/ai_usage.py`, 2026-11-07)
- Every Claude call goes through `claude._call`, which first runs `ai_usage.check_budget()` and afterwards `ai_usage.record()`.
- `record()` writes one `ai_usage` row: user, workspace, conversation and purpose come from `ai_usage.ai_context(...)`, set by `assistant.answer` (`chat`), `claude.explain` (`explain`), the summary job (`summary`) and the memory jobs (`memory`). The estimated cost (rupees) is also returned in the answer's `usage.cost_inr`. A ledger failure is logged and never loses the answer.
- Prices are USD per million tokens in `ai_usage.PRICES` (Haiku 5.5: $0.10 in / $0.50 out up to a 100K-token prompt, $0.50 / $2.50 above; Sonnet 5.5: $2 / $10; cache reads 0.1×, cache writes 1.25× input), converted with `USD_INR_RATE`, overridable with `AI_PRICES_JSON`.
- Caps: `AI_DAILY_LIMIT_USER_INR` (per user, Indian calendar day) and `AI_MONTHLY_LIMIT_INR` (everyone). At the cap `check_budget` raises, `_call` turns that into `ClaudeUnavailable`, and the offline engine answers with "AI spend limit reached …".

## Engine selection (the Ask box dropdown)
- `auto` and `llm` use Claude when a key is set. Without a key they use the OpenAI-compatible LLM if `LLM_BASE_URL` is set, and otherwise the offline engine.
- `semantic` forces the offline engine.
- `/api/me` reports `provider:"anthropic"` and the model labels. The frontend shows a model badge, "(escalated)", the routing reason, and whether the answer came from "governed metrics" or "validated SQL".

## Live check results (2026-10-21, workspace 34, checked against direct SQL)
| Question | Model | Result |
|---|---|---|
| How many locations by location type? | Haiku | 76 total (29/22/11/4…) ✅ |
| "only the active ones" (follow-up) | Haiku | 57 ✅ |
| List active marketplace channels | Haiku (SQL path) | 12 ✅ |
| Total net sales last month | Haiku | honest "no data" (sales empty) ✅ |
| Share of channels per channel group | Sonnet (share-of) | 54.5 / 22.7 / 9.1 / 4.5 %, 3 of 3 runs consistent ✅ |
| Declining sales but increasing stock? | Sonnet (opposing trends) | Clarified correctly: `stock_position_latest` has only the latest snapshot ✅ |

- Other figures from the check: there are 22 channels in total and 16 distinct names.
- **Latency:** about 3–9 s per answer.
- **Cost:** about $0.045 for 6 questions. The cache write for Sonnet's own cache dominates, because prompt caches are per-model. Haiku questions cost a fraction of a cent once the cache is warm.

## Extending safely
- Routing changes go in `_STRONG` / `_WEAK`. Add parametrised cases to `test_simple_questions_route_to_haiku` / `test_complex_questions_route_to_sonnet`.
- Never add a model outside Haiku or Sonnet. Never add `fallbacks`.
- Keep the arithmetic in code (`_facts`, analytics), not in the model.
- Any new SQL path must go through `validate_select` + `run_readonly`.
