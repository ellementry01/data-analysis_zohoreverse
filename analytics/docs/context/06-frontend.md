# 06 — Frontend

`analytics/frontend/` uses React 18 with TypeScript (strict), Vite 7, Tailwind 3, ECharts 6.1, React Router 7 and react-grid-layout.

- **Dev:** `npm run dev` starts Vite on :5173 and proxies `/api` to :8000.
- **Build:** `npm run build`, which runs `tsc --noEmit` and then `vite build` into `dist/`. FastAPI serves `dist/` at :8000.
- **Checks:** `npm run typecheck`.

## Routes (`src/App.tsx`)
| Path | Page | Purpose |
|---|---|---|
| `/` | WorkspacesPage | List and create workspaces; "Load demo workspace" button (calls `POST /api/demo`) |
| `/w/:wsId` | WorkspaceLayout | Sidebar shell with the Ellementry branding; the index route is OverviewPage |
| `data`, `data/:dsId` | DataPage, DatasetPage | Dataset list; grid, columns, profile, quality, transforms, sync/schedule |
| `import` | ImportPage | File upload wizard and the **Databases** (connectors) tab |
| `model` | ModelPage | Relationship graph and suggestions |
| `sql` | SqlPage | SQL console and saved queries |
| `semantic` | SemanticPage | Metrics, glossary, business rules |
| `reports`, `reports/:reportId` | ReportsPage, ReportEditor | Shelf-based chart builder (`components/SpecBuilder.tsx`) |
| `dashboards`, `dashboards/:dashId` | DashboardsPage, DashboardView | Grid dashboards, filters, drill-down, export. With the dashboard chat on (`/api/me` `features.dashboard_chat`, admins only for now): an **Ask** button opens `AssistantPanel` beside the grid (full screen on phones), and each widget gets an "Ask about this" button that focuses the question on it. The page sends filter values, drill-downs and the focused widget as `screen_state` |
| `ask`, `ask/:convId` | AskPage | Ask AI chat. Engine dropdown (Claude auto-routed / Semantic engine), model badge with "(escalated)", routing reason, a "governed metrics" vs "validated SQL" tag, and SQL, data and insights tabs |
| `lineage` | LineagePage | Source → dataset → query table → report/dashboard |
| `history` | HistoryPage | Query history |
| `settings` | SettingsPage | User switcher (sets `X-User-Email`), members, Claude card showing the provider and models |

## Shared pieces
- **`api/client.ts`:** a fetch wrapper that adds `X-User-Email` from localStorage and handles errors and toasts. The app name lives here too.
- **`components/Chart.tsx`:** the ECharts renderer for kpi, line, area, bar, hbar, stacked, combo, pie, donut, scatter, heatmap, table and pivot. It escapes HTML in tooltips with `escapeHtml`.
  - `useEffect` bodies must be **block bodies**. An expression-bodied effect once returned a non-function and crashed with "r is not a function".
- **`components/ResultPanel.tsx`:** chart, table, SQL, insights and exports (CSV/Excel/PNG).
- **Sign-in:** any 401 sends the browser to `/api/auth/login?next=<this page>` (`api/client.ts`). `components/UserMenu.tsx` (sidebar and home page) shows who is signed in, Sign out (google mode) and an Administration link for platform admins. `/admin` -> `pages/AdminPage.tsx`: Users (switch on/off, make admin), API tokens (create once-shown tokens, revoke), Audit log (filter by action or email). Workspace Settings gets `components/AccessRulesCard.tsx` for admins; the "Local user" switcher shows only in dev mode.
- **`components/ChatMessage.tsx`:** one chat message (question, or answer with chart, assumptions, engine/model badge and thumbs up/down). Shared by AskPage and the dashboard chat.
- **`components/AssistantPanel.tsx`:** a dashboard's chat: starter questions, past threads for that dashboard, the focused-widget chip, feedback. With `features.agent_loop` it uses the streaming endpoint (`api.stream`) and shows each step live; answers carry a collapsible "How I worked this out" list (`StepList`) with each step's query.
- **`components/ui.tsx`:** Button, Empty, toast and similar primitives.
- **`lib/format.ts`:** number, currency and percent formatting. The INR format uses lakh/crore grouping.

## Branding
- User-facing text says "Ellementry Analytics": `index.html` title, WorkspacesPage, WorkspaceLayout and client.ts.
- The package name `ellementry-analytics-frontend` and other internal identifiers were deliberately left unchanged.
