import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, BarChart3, BookOpen, Database, FileUp, LayoutDashboard, MessageSquareText, Network, Send } from "lucide-react";
import { api, Dashboard, Dataset, Report } from "../api/client";
import { Badge, Card, inputCls, PageHeader, useAsync } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

export default function OverviewPage() {
  const { ws, model, base } = useWs();
  const nav = useNavigate();
  const ds = useAsync(() => api.get<Dataset[]>(`/workspaces/${ws.id}/datasets`), [ws.id]);
  const dashes = useAsync(() => api.get<Dashboard[]>(`/workspaces/${ws.id}/dashboards`), [ws.id]);
  const reports = useAsync(() => api.get<Report[]>(`/workspaces/${ws.id}/reports`), [ws.id]);
  const sugg = useAsync(() => api.get<string[]>(`/workspaces/${ws.id}/assistant/suggestions`), [ws.id]);
  const [q, setQ] = useState("");
  const ask = (text: string) => nav(`${base}/ask`, { state: { question: text } });
  const warnings = (ds.data || []).reduce((s, d) => s + d.warning_count, 0);

  const steps = [
    { done: model.datasets.length > 0, label: "Import data", to: "import", icon: FileUp },
    { done: model.relationships.length > 0 || model.datasets.length < 2, label: "Relate datasets", to: "model", icon: Network },
    { done: model.metrics.length > 0, label: "Define metrics", to: "semantic", icon: BookOpen },
    { done: (dashes.data || []).length > 0, label: "Build a dashboard", to: "dashboards", icon: LayoutDashboard },
  ];

  return (
    <div>
      <PageHeader title={ws.name} subtitle={ws.description} />
      <div className="mb-5 rounded-xl border border-brand-200 bg-gradient-to-r from-brand-50 to-white p-5">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-brand-900"><MessageSquareText className="h-4 w-4" /> Ask a question about your data</div>
        <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) ask(q); }} className="flex gap-2">
          <input className={inputCls + " py-2"} value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. What were total sales last month?" />
          <button className="rounded-md bg-brand-600 px-4 text-white hover:bg-brand-700" aria-label="Ask"><Send className="h-4 w-4" /></button>
        </form>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {(sugg.data || []).map((s) => (
            <button key={s} onClick={() => ask(s)} className="rounded-full border border-brand-200 bg-white px-2.5 py-0.5 text-xs text-brand-700 hover:bg-brand-50">{s}</button>
          ))}
        </div>
      </div>

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          { label: "Datasets", value: model.datasets.length, icon: Database, to: "data" },
          { label: "Rows stored", value: model.datasets.reduce((s, d) => s + d.row_count, 0).toLocaleString("en-IN"), icon: Database, to: "data" },
          { label: "Metrics", value: model.metrics.length, icon: BookOpen, to: "semantic" },
          { label: "Data-quality warnings", value: warnings, icon: Database, to: "data" },
        ].map((k) => (
          <Link to={`${base}/${k.to}`} key={k.label} className="rounded-lg border border-slate-200 bg-white p-4 shadow-card hover:border-brand-300">
            <div className="text-xs text-slate-500">{k.label}</div>
            <div className="mt-1 text-2xl font-semibold text-slate-900">{k.value}</div>
          </Link>
        ))}
      </div>

      {steps.some((s) => !s.done) && (
        <Card title="Getting started" className="mb-5">
          <div className="grid gap-2 md:grid-cols-4">
            {steps.map((s, i) => (
              <Link key={s.label} to={`${base}/${s.to}`} className="flex items-center gap-2 rounded-md border border-slate-200 p-3 text-sm hover:border-brand-300">
                <span className={"flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold " + (s.done ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600")}>{s.done ? "✓" : i + 1}</span>
                <s.icon className="h-4 w-4 text-slate-400" /> {s.label}
              </Link>
            ))}
          </div>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Dashboards" actions={<Link to={`${base}/dashboards`} className="text-xs text-brand-600">All <ArrowRight className="inline h-3 w-3" /></Link>}>
          {(dashes.data || []).filter((d) => !d.is_template).slice(0, 6).map((d) => (
            <Link key={d.id} to={`${base}/dashboards/${d.id}`} className="flex items-center justify-between border-b border-slate-100 py-2 text-sm last:border-0 hover:text-brand-700">
              <span className="flex items-center gap-2"><LayoutDashboard className="h-4 w-4 text-slate-400" />{d.name}</span>
              <span className="text-xs text-slate-400">{d.widget_count} widgets · {timeAgo(d.updated_at)}</span>
            </Link>
          ))}
          {!dashes.data?.length && <div className="text-sm text-slate-400">No dashboards yet.</div>}
        </Card>
        <Card title="Datasets" actions={<Link to={`${base}/data`} className="text-xs text-brand-600">All <ArrowRight className="inline h-3 w-3" /></Link>}>
          {(ds.data || []).slice(0, 8).map((d) => (
            <Link key={d.id} to={`${base}/data/${d.id}`} className="flex items-center justify-between border-b border-slate-100 py-2 text-sm last:border-0 hover:text-brand-700">
              <span className="flex items-center gap-2"><Database className="h-4 w-4 text-slate-400" />{d.name} {d.kind !== "file" && <Badge tone="violet">{d.kind.replace("_", " ")}</Badge>}</span>
              <span className="text-xs text-slate-400">{d.row_count.toLocaleString("en-IN")} rows {d.warning_count > 0 && <Badge tone="amber">{d.warning_count} warnings</Badge>}</span>
            </Link>
          ))}
          {!ds.data?.length && <div className="text-sm text-slate-400">No data yet. <Link className="text-brand-600" to={`${base}/import`}>Import a file</Link></div>}
        </Card>
        <Card title="Recent reports" actions={<Link to={`${base}/reports`} className="text-xs text-brand-600">All <ArrowRight className="inline h-3 w-3" /></Link>}>
          {(reports.data || []).slice(0, 6).map((r) => (
            <Link key={r.id} to={`${base}/reports/${r.id}`} className="flex items-center justify-between border-b border-slate-100 py-2 text-sm last:border-0 hover:text-brand-700">
              <span className="flex items-center gap-2"><BarChart3 className="h-4 w-4 text-slate-400" />{r.name}</span>
              <Badge>{r.chart_type}</Badge>
            </Link>
          ))}
          {!reports.data?.length && <div className="text-sm text-slate-400">No saved reports.</div>}
        </Card>
      </div>
    </div>
  );
}
