# Ellementry Analytics

Dashboards and reports on all of Ellementry's company data, for senior management, built on the company's
own data warehouse. Managers open it in a browser on the office network; analysts can also build reports, use a
SQL console, and ask questions in plain English (answers show the SQL behind them).

The repository holds two parts that work together:

| Folder | What it is |
|---|---|
| [`lumen/`](lumen/) | **Ellementry Analytics**, the BI application: FastAPI + PostgreSQL backend, React + TypeScript + ECharts frontend, Docker setup |
| [`warehouse/`](warehouse/) | **`ellementry_dw`**, the PostgreSQL data warehouse: file loader, transform, data-quality gate, business-rule mart views |
| [`research/`](research/) | Notes from a study of Zoho Analytics' public help pages, used to shape the app's features (no Zoho code or content) |

> The app's internal names (`lumen` folder, Docker project, database, `LUMEN_*` variables) are kept from its
> original name. Renaming them would orphan existing data.

## How the data flows

```
ERP / WMS / marketplace exports (Excel)
        │  loader: every file checked against a contract, stored as received (raw)
        ▼
ellementry_dw:  raw → stg (typed) → core (dimensions, facts, stock ledger) → quality gate → mart views
        │  read-only role ellementry_metrics, schema mart only
        ▼
Ellementry Analytics (workspace "Ellementry (live warehouse)"): datasets synced hourly,
governed metrics, executive dashboards, reports, Ask AI
```

Business definitions live once, in the warehouse `mart` views; the app never redefines them:

- **Money excludes GST.**
- **Net sales = invoices − returns.**
- **Quick-commerce sell-out (Blinkit, Instamart) is demand, never revenue.**
- **Missing data is shown as "no data", never as 0.**

## What is built

**Executive dashboards:**
- **Executive overview**
- **Sales & channels**
- **Returns**
- **Stock**
- **Fulfilment**
- **Purchasing & transfers**

They cover Apr 2025 – 15 Sep 2026. Every KPI has been checked against direct SQL, and the warehouse reconciles
28 of 28 control totals against the source files.

**Data loaded:**
- ERP retail and domestic sales and returns
- stock transfers
- pending purchase orders
- the stock report (15 Sep 2026)
- the product masters
- the WMS dispatch report
- Blinkit and Instamart sell-out

**Warehouse:** schema **2.4**. See [`warehouse/README.md`](warehouse/README.md) for what each version added.

Known data gaps and what the business needs to supply are listed in
[`lumen/docs/context/08-ellementry-warehouse.md`](lumen/docs/context/08-ellementry-warehouse.md). The main gaps:
- daily stock history
- the partner and factory lists
- marketplace RTO and delivery data
- receiving locations on goods receipts

## Quick start (Windows)

### App
```powershell
cd lumen
copy .env.docker.example .env        # set POSTGRES_PASSWORD; optional ANTHROPIC_API_KEY for Ask AI
docker compose up -d --build         # app on http://localhost:8000
```
Running without Docker, and connecting to a warehouse: see [`lumen/README.md`](lumen/README.md).

### Warehouse
```powershell
cd warehouse
# .env (git-ignored) holds ADMIN_DATABASE_URL; dw.py reads it and never prints it
python dw.py backup                          # always before changing ellementry_dw
python load_manifest.py ../exports           # load new export files listed in exports/MANIFEST.tsv
python dw.py transform run                   # rebuild stg -> core -> marts, all or nothing
python reconcile.py ../exports               # file totals vs warehouse totals
```
Fresh database: `python dw.py build <new_db>`, then `python dw.py seeds <new_db>`.

### Dashboards
```powershell
cd lumen
python scripts/configure_warehouse_workspace.py   # sync datasets, metrics for warehouse 2.4
python scripts/build_executive_dashboards.py      # (re)build the six dashboards, checks every widget has data
```

## Tests

```powershell
cd lumen/backend; python -m pytest -q                               # app
cd lumen/frontend; npm run typecheck; npm run build                 # UI
cd warehouse; $env:DW_DATABASE="dw_test"; python dw.py pytest -q    # warehouse, never against ellementry_dw
```

## Not in this repository

| Not included | Why |
|---|---|
| `exports/` (the company's source files) | Contains customer data. Each machine keeps its own copy, listed in `exports/MANIFEST.tsv`, with the originals as received in `exports/_originals/` |
| `reports/` | Generated working files |
| `.env` files and database backups | Never committed; set the variables named in the `.example` files |

## Rules for anyone working on this

- Never print, copy or commit secrets: `.env` values, API keys, database passwords.
- The app reads the warehouse read-only, and only the `mart` schema. The warehouse changes only through
  `warehouse/` tooling (numbered migrations, seeds, loader, transform), after a backup.
- Ask AI uses Claude Haiku 5.5 and Sonnet 5.5 only.
- Every AI- or user-written SQL statement goes through the app's read-only SQL guard.

## Documentation

- **Start here:**
  - [`CLAUDE.md`](CLAUDE.md)
  - [`lumen/CLAUDE.md`](lumen/CLAUDE.md)
- **Full context**, in [`lumen/docs/context/`](lumen/docs/context/):
  - overview
  - architecture
  - backend
  - AI layer
  - security
  - frontend
  - operations
  - warehouse connection
  - decisions
- **Warehouse:**
  - [`warehouse/README.md`](warehouse/README.md)
  - business documents in `warehouse/docs/`: PRD, business rules register, data model, issues log
- **Plans:**
  - [`lumen/docs/EXECUTIVE_DASHBOARD_PLAN.md`](lumen/docs/EXECUTIVE_DASHBOARD_PLAN.md)
  - [`lumen/docs/WAREHOUSE_SCHEMA_REVIEW.md`](lumen/docs/WAREHOUSE_SCHEMA_REVIEW.md)
  - [`lumen/docs/WAREHOUSE_LOAD_FIX_PLAN.md`](lumen/docs/WAREHOUSE_LOAD_FIX_PLAN.md)
