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
- The key lives only in env: `ANTHROPIC_API_KEY` in `lumen/.env` (Docker) or `backend/.env` (local). It has a placeholder in both `.example` files. **Never print it.**

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
- If the explanation fails, `template_explanation` builds the text deterministically instead.

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
