import { createContext, useContext } from "react";
import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { BarChart3, BookOpen, Database, FileUp, GitBranch, History, Home, LayoutDashboard, MessageSquareText, Network, Settings, TerminalSquare } from "lucide-react";
import { api, Model, Workspace } from "../api/client";
import { cx, ErrorBox, Spinner, useAsync } from "../components/ui";

interface WsCtx {
  ws: Workspace;
  model: Model;
  reloadModel: () => void;
  base: string;
  canEdit: boolean;
}
const Ctx = createContext<WsCtx | null>(null);
export const useWs = () => useContext(Ctx)!;

const NAV = [
  { to: "", label: "Overview", icon: Home, end: true },
  { to: "ask", label: "Ask AI", icon: MessageSquareText },
  { to: "dashboards", label: "Dashboards", icon: LayoutDashboard },
  { to: "reports", label: "Reports", icon: BarChart3 },
  { sep: "Data" },
  { to: "data", label: "Datasets", icon: Database },
  { to: "import", label: "Import data", icon: FileUp },
  { to: "model", label: "Relationships", icon: Network },
  { to: "semantic", label: "Semantic layer", icon: BookOpen },
  { to: "sql", label: "SQL & query tables", icon: TerminalSquare },
  { sep: "Admin" },
  { to: "lineage", label: "Lineage", icon: GitBranch },
  { to: "history", label: "Query history", icon: History },
  { to: "settings", label: "Settings", icon: Settings },
] as const;

export default function WorkspaceLayout() {
  const { wsId } = useParams();
  const wsQ = useAsync(() => api.get<Workspace>(`/workspaces/${wsId}`), [wsId]);
  const modelQ = useAsync(() => api.get<Model>(`/workspaces/${wsId}/model`), [wsId]);
  if (wsQ.error) return <div className="p-8"><ErrorBox error={wsQ.error} /><Link className="mt-3 inline-block text-sm text-brand-600" to="/">← All workspaces</Link></div>;
  if (!wsQ.data || !modelQ.data) return <Spinner />;
  const base = `/w/${wsId}`;
  const ctx: WsCtx = { ws: wsQ.data, model: modelQ.data, reloadModel: modelQ.reload, base, canEdit: wsQ.data.role === "admin" || wsQ.data.role === "editor" };
  return (
    <Ctx.Provider value={ctx}>
      <div className="flex h-full">
        <aside className="no-print flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white">
          <Link to="/" className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
            <img src="/favicon.svg" className="h-6 w-6" alt="" />
            <span className="font-semibold text-slate-900">Ellementry</span>
            <span className="text-xs text-slate-400">Analytics</span>
          </Link>
          <div className="border-b border-slate-100 px-4 py-2.5">
            <div className="truncate text-sm font-medium text-slate-800" title={ctx.ws.name}>{ctx.ws.name}</div>
            <div className="text-[11px] text-slate-400">{ctx.model.datasets.length} datasets · role: {ctx.ws.role}</div>
          </div>
          <nav className="flex-1 overflow-y-auto px-2 py-2">
            {NAV.map((n, i) =>
              "sep" in n ? (
                <div key={i} className="mt-3 px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">{n.sep}</div>
              ) : (
                <NavLink key={n.to} to={n.to ? `${base}/${n.to}` : base} end={"end" in n}
                  className={({ isActive }) => cx("flex items-center gap-2 rounded-md px-2 py-1.5 text-sm", isActive ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-100")}>
                  <n.icon className="h-4 w-4" /> {n.label}
                </NavLink>
              ),
            )}
          </nav>
        </aside>
        <main className="print-full min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1500px] px-6 py-5">
            <Outlet />
          </div>
        </main>
      </div>
    </Ctx.Provider>
  );
}
