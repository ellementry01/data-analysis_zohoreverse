import { Link } from "react-router-dom";
import { BarChart3, Plus, Trash2 } from "lucide-react";
import { api, Report } from "../api/client";
import { Badge, Button, Empty, ErrorBox, PageHeader, Spinner, useAsync, useToast } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

export default function ReportsPage() {
  const { ws, base, canEdit } = useWs();
  const toast = useToast();
  const q = useAsync(() => api.get<Report[]>(`/workspaces/${ws.id}/reports`), [ws.id]);
  const del = async (r: Report) => {
    if (!confirm(`Delete report "${r.name}"?`)) return;
    try {
      await api.del(`/workspaces/${ws.id}/reports/${r.id}`);
      q.reload();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  return (
    <div>
      <PageHeader title="Reports" subtitle="Saved charts and tables built with the visual query builder."
        actions={canEdit && <Link to={`${base}/reports/new`}><Button variant="primary"><Plus className="h-4 w-4" /> New report</Button></Link>} />
      <ErrorBox error={q.error} />
      {q.loading ? <Spinner /> : !q.data?.length ? (
        <Empty icon={<BarChart3 className="h-8 w-8" />} title="No reports yet" action={canEdit && <Link to={`${base}/reports/new`}><Button variant="primary">Create a report</Button></Link>}>
          Build charts by dragging metrics and fields — or ask the AI and save its answer.
        </Empty>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {q.data.map((r) => (
            <div key={r.id} className="group rounded-lg border border-slate-200 bg-white p-4 shadow-card hover:border-brand-300">
              <Link to={`${base}/reports/${r.id}`} className="block">
                <div className="flex items-center justify-between"><span className="font-medium text-slate-800 group-hover:text-brand-700">{r.name}</span><Badge>{r.chart_type}</Badge></div>
                <div className="mt-1 text-xs text-slate-500">
                  {r.spec.measures.map((m) => m.metric || m.field).join(", ")}{r.spec.dimensions.length > 0 && " by " + r.spec.dimensions.map((d) => d.field.split(".").pop() + (d.grain ? ` (${d.grain})` : "")).join(", ")}
                </div>
              </Link>
              <div className="mt-3 flex items-center justify-between text-[11px] text-slate-400">
                <span>Updated {timeAgo(r.updated_at)}</span>
                {canEdit && <button onClick={() => del(r)} className="hover:text-red-600"><Trash2 className="h-3.5 w-3.5" /></button>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
