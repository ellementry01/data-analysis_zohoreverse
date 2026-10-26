# Ellementry Analytics — agent entry point

Ellementry Analytics is a local-first AI analytics platform. It is built with FastAPI, SQLAlchemy and PostgreSQL on the backend and React, TS, Vite, Tailwind and ECharts on the frontend. Ask AI uses Anthropic Claude. It currently reads the company's `ellementry_dw` warehouse (read-only) as workspace 34.

**Read these before changing anything** (in `docs/context/`):
1. [01-project-overview.md](docs/context/01-project-overview.md): what the project is, its history, its current status, and what is and isn't built
2. [02-architecture.md](docs/context/02-architecture.md): stack, folder layout, storage model, request flow
3. [03-backend-reference.md](docs/context/03-backend-reference.md): tables, API routes, QuerySpec, ingestion, connectors, offline NL parser
4. [04-ai-layer.md](docs/context/04-ai-layer.md): Claude routing (Haiku/Sonnet), planning, explaining, live-check results
5. [05-security.md](docs/context/05-security.md): security model, the rules agents must follow, accepted risks
6. [06-frontend.md](docs/context/06-frontend.md): routes, pages, components
7. [07-operations.md](docs/context/07-operations.md): Docker, local run, env vars, tests
8. [08-ellementry-warehouse.md](docs/context/08-ellementry-warehouse.md): the warehouse connection, datasets, metrics, relationships
9. [09-decisions-and-gotchas.md](docs/context/09-decisions-and-gotchas.md): why things are the way they are, pitfalls, next steps

Also see `README.md` (user guide), `QA_REPORT.md` (security audit), `../research/` (the Zoho Analytics study, from public pages only), `../warehouse/README.md` (the data warehouse feeding workspace 34), and the plans in `docs/` (`EXECUTIVE_DASHBOARD_PLAN.md`, `WAREHOUSE_SCHEMA_REVIEW.md`, `WAREHOUSE_LOAD_FIX_PLAN.md`).

## Non-negotiable rules
- **Never print or copy secrets** from `.env` or `backend/.env`: the Anthropic key, DB passwords, `ELLEMENTRY_CONN_*`. Never ask the user for passwords, keys or auth codes in chat; tell them which variable to set.
- **AI models: only Claude Haiku 5.5 (`claude-haiku-5-5`) and Sonnet 5.5 (`claude-sonnet-5-5`). Never Opus or Fable.** No server-side `fallbacks`.
- Every AI- or user-supplied SQL statement goes through `sql_safety.validate_select` and `executor.run_readonly`. Never weaken these guards.
- The **app** reads `ellementry_dw` read-only: only as `ellementry_metrics`, only schema `mart`. The warehouse itself changes only through `../warehouse` tooling (`dw.py`, numbered migrations, seeds, loader, transform), always after `python dw.py backup`, and tests never run against `ellementry_dw`.
- Don't claim a feature works unless it's implemented and tested. Don't copy Zoho's code or branding.
- Identifiers are `ellementry` throughout: compose project, database `ellementry_analytics`, schema `ellementry_meta`, `ELLEMENTRY_*` env vars. Never rename a database, schema or Docker volume without a backup and a data migration.
- Live Claude calls cost money: keep checks short, and get the user's OK first.

## Quick commands
```bash
# Docker (from analytics/) — app on http://localhost:8000
docker compose up -d --build
docker compose up -d --force-recreate app   # after editing .env
# Backend tests (from analytics/backend) — expect 404 passed
TODAY_OVERRIDE=2026-10-17 python -m pytest -q
# Frontend checks (from analytics/frontend)
npm run typecheck && npm run build
```

Last updated: 2026-10-22. Keep `docs/context/` current when you change behaviour, and add a line to 09's decision log.
