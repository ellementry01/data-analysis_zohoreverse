import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Copy, LayoutDashboard, LayoutTemplate, Plus, Trash2 } from "lucide-react";
import { api, Dashboard } from "../api/client";
import { Badge, Button, Empty, ErrorBox, inputCls, Label, Modal, PageHeader, Spinner, useAsync, useToast } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

export default function DashboardsPage() {
  const { ws, base, canEdit } = useWs();
  const toast = useToast();
  const nav = useNavigate();
  const q = useAsync(() => api.get<Dashboard[]>(`/workspaces/${ws.id}/dashboards`), [ws.id]);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("");
  const create = async () => {
    try {
      const d = template
        ? await api.post<Dashboard>(`/workspaces/${ws.id}/dashboards/${template}/duplicate?name=${encodeURIComponent(name || "New dashboard")}`)
        : await api.post<Dashboard>(`/workspaces/${ws.id}/dashboards`, { name: name || "New dashboard", filters: [{ id: "date", type: "date_range", label: "Date range", field: "@time", value: null }] });
      nav(`${base}/dashboards/${d.id}`);
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const del = async (d: Dashboard) => {
    if (!confirm(`Delete dashboard "${d.name}"?`)) return;
    await api.del(`/workspaces/${ws.id}/dashboards/${d.id}`);
    q.reload();
  };
  const dashes = (q.data || []).filter((d) => !d.is_template);
  const templates = (q.data || []).filter((d) => d.is_template);
  return (
    <div>
      <PageHeader title="Dashboards" subtitle="Interactive, filterable boards of KPIs and charts."
        actions={canEdit && <Button variant="primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New dashboard</Button>} />
      <ErrorBox error={q.error} />
      {q.loading ? <Spinner /> : !dashes.length ? (
        <Empty icon={<LayoutDashboard className="h-8 w-8" />} title="No dashboards yet" action={canEdit && <Button variant="primary" onClick={() => setOpen(true)}>Create a dashboard</Button>}>
          Or ask the AI: “Create a dashboard showing monthly sales, returns and inventory”.
        </Empty>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {dashes.map((d) => (
            <div key={d.id} className="group rounded-lg border border-slate-200 bg-white p-4 shadow-card hover:border-brand-300">
              <Link to={`${base}/dashboards/${d.id}`}>
                <div className="flex items-center gap-2 font-medium text-slate-800 group-hover:text-brand-700"><LayoutDashboard className="h-4 w-4 text-slate-400" />{d.name}</div>
                <div className="mt-1 line-clamp-2 text-xs text-slate-500">{d.description || `${d.widget_count} widgets`}</div>
              </Link>
              <div className="mt-3 flex items-center justify-between text-[11px] text-slate-400">
                <span>{d.widget_count} widgets · {timeAgo(d.updated_at)}</span>
                {canEdit && <button onClick={() => del(d)} className="hover:text-red-600"><Trash2 className="h-3.5 w-3.5" /></button>}
              </div>
            </div>
          ))}
        </div>
      )}
      {templates.length > 0 && (
        <>
          <h2 className="mb-2 mt-8 flex items-center gap-1.5 text-sm font-semibold text-slate-700"><LayoutTemplate className="h-4 w-4" /> Templates</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {templates.map((d) => (
              <div key={d.id} className="rounded-lg border border-dashed border-slate-300 bg-white p-3 text-sm">
                <div className="flex items-center justify-between"><Link to={`${base}/dashboards/${d.id}`} className="font-medium hover:text-brand-700">{d.name}</Link><Badge tone="violet">template</Badge></div>
                <div className="mt-2 flex gap-2">
                  {canEdit && <Button size="sm" onClick={() => { setTemplate(String(d.id)); setName(d.name.replace(/^Template:\s*/, "")); setOpen(true); }}><Copy className="h-3 w-3" /> Use</Button>}
                  {canEdit && <Button size="sm" variant="ghost" onClick={() => del(d)}><Trash2 className="h-3 w-3" /></Button>}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      <Modal open={open} onClose={() => { setOpen(false); setTemplate(""); }} title={template ? "New dashboard from template" : "New dashboard"}
        footer={<><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" onClick={create}>Create</Button></>}>
        <Label>Name</Label>
        <input autoFocus className={inputCls} value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && create()} />
      </Modal>
    </div>
  );
}
