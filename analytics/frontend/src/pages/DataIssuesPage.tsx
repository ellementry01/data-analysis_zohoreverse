import { useState } from "react";
import { AlertTriangle, Check, Pencil, Plus, Search, X } from "lucide-react";
import { api, Dashboard } from "../api/client";
import { Badge, Button, Card, cx, Empty, ErrorBox, inputCls, Label, PageHeader, Select, Spinner, Tabs, useAsync, useToast } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

interface Issue {
  code: string; title: string; area: string; status: "open" | "awaiting" | "parked" | "solved"; status_detail: string;
  severity: "high" | "medium" | "low"; summary: string; note: string; owner: string; source: string;
  affects: { dashboards?: string[]; metrics?: string[]; datasets?: string[] };
  opened_at: string; solved_at: string | null; updated_by: string; updated_at: string;
}

const STATUS_LABEL: Record<string, string> = { open: "Open", awaiting: "Awaiting confirmation", parked: "Parked", solved: "Solved" };
const SEV_TONE: Record<string, "red" | "amber" | "slate"> = { high: "red", medium: "amber", low: "slate" };

/** The data issue register: what is known to be wrong or incomplete in the data, and which tiles it touches. */
export default function DataIssuesPage() {
  const { ws, model } = useWs();
  const isAdmin = ws.role === "admin";
  const [tab, setTab] = useState("live");
  const [q, setQ] = useState("");
  const [dash, setDash] = useState("");
  const [adding, setAdding] = useState(false);
  const list = useAsync(() => api.get<Issue[]>(`/workspaces/${ws.id}/data-issues${tab === "all" ? "" : `?status=${tab}`}`), [ws.id, tab]);
  const dashes = useAsync(() => api.get<Dashboard[]>(`/workspaces/${ws.id}/dashboards`), [ws.id]);
  const names = Object.fromEntries((dashes.data || []).map((d) => [d.key, d.name]));
  const metricLabels = Object.fromEntries(model.metrics.map((mt) => [mt.name, mt.label]));
  const shown = (list.data || []).filter((i) => (!dash || (i.affects.dashboards || []).includes(dash))
    && (!q.trim() || `${i.code} ${i.title} ${i.summary} ${i.area}`.toLowerCase().includes(q.trim().toLowerCase())));

  if (list.error && String(list.error).includes("switched off")) {
    return <div><PageHeader title="Data issues" /><Empty title="Data issues are switched off">An administrator turns them on with ASSISTANT_DATA_ISSUES.</Empty></div>;
  }
  return (
    <div>
      <PageHeader title="Data issues" subtitle="Known problems in the data and the tiles they touch. Dashboards show a note on affected tiles, and the assistants mention them when they quote an affected number."
        actions={isAdmin && <Button variant="primary" onClick={() => setAdding(!adding)}><Plus className="h-4 w-4" /> Add an issue</Button>} />
      {adding && <IssueForm wsId={ws.id} dashes={dashes.data || []} metrics={model.metrics.map((mt) => ({ value: mt.name, label: mt.label }))}
        onDone={() => { setAdding(false); list.reload(); }} />}
      <Tabs tabs={[{ id: "live", label: "Open" }, { id: "parked", label: "Parked" }, { id: "solved", label: "Solved" }, { id: "all", label: "All" }]} value={tab} onChange={setTab} />
      <div className="mt-3 flex flex-wrap gap-2">
        <div className="relative min-w-[12rem] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search issues" className={cx(inputCls, "pl-8")} />
        </div>
        <Select className="w-56" value={dash} onChange={setDash} placeholder="Any dashboard"
          options={(dashes.data || []).map((d) => ({ value: d.key, label: d.name }))} />
      </div>
      <div className="mt-3 flex flex-col gap-2">
        {list.loading && <Spinner />}
        {list.error && <ErrorBox error={list.error} />}
        {!list.loading && shown.length === 0 && <Empty icon={<AlertTriangle className="h-6 w-6" />} title="No issues here">{tab === "live" ? "Nothing open is recorded. Import the issue log with scripts/import_issue_log.py." : "Nothing in this list."}</Empty>}
        {shown.map((i) => <IssueRow key={i.code} wsId={ws.id} i={i} isAdmin={isAdmin} names={names} metricLabels={metricLabels}
          dashes={dashes.data || []} metrics={model.metrics.map((mt) => ({ value: mt.name, label: mt.label }))} onChange={list.reload} />)}
      </div>
    </div>
  );
}

type Opt = { value: string; label: string };

function IssueRow({ wsId, i, isAdmin, names, metricLabels, dashes, metrics, onChange }:
  { wsId: number; i: Issue; isAdmin: boolean; names: Record<string, string>; metricLabels: Record<string, string>; dashes: Dashboard[]; metrics: Opt[]; onChange: () => void }) {
  const toast = useToast();
  const [edit, setEdit] = useState(false);
  const setStatus = async (status: string) => {
    try {
      await api.patch(`/workspaces/${wsId}/data-issues/${i.code}`, { status });
      toast("success", `${i.code}: ${STATUS_LABEL[status]}`);
      onChange();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  if (edit) return <IssueForm wsId={wsId} issue={i} dashes={dashes} metrics={metrics} onDone={() => { setEdit(false); onChange(); }} />;
  const a = i.affects || {};
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 shadow-sm">
      <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
        <span className="font-mono text-xs font-semibold text-slate-800">{i.code}</span>
        <Badge tone={SEV_TONE[i.severity]}>{i.severity}</Badge>
        <span className="text-slate-500">{STATUS_LABEL[i.status]}{i.status_detail && i.status_detail.toLowerCase() !== STATUS_LABEL[i.status].toLowerCase() ? ` (${i.status_detail})` : ""}</span>
        {i.area && <span className="text-slate-400">· {i.area}</span>}
        {i.owner && <span className="text-slate-400">· {i.owner}</span>}
        <span className="ml-auto text-slate-400">updated {timeAgo(i.updated_at)}{i.updated_by ? ` by ${i.updated_by}` : ""}</span>
      </div>
      <div className="mt-1 text-sm font-medium text-slate-800">{i.title}</div>
      {i.note && i.note !== i.title && <div className="text-xs text-slate-600">Shown on tiles as: “{i.note}”</div>}
      {i.summary && <div className="mt-1 text-xs leading-relaxed text-slate-500">{i.summary}</div>}
      <div className="mt-1.5 flex flex-wrap gap-1 text-[11px]">
        {(a.dashboards || []).map((k) => <span key={k} className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">{names[k] || k}</span>)}
        {(a.metrics || []).map((k) => <span key={k} className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-800" title="Tiles using this metric get a note">{metricLabels[k] || k}</span>)}
        {(a.datasets || []).map((k) => <span key={k} className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-800">{k}</span>)}
        {!(a.dashboards || []).length && !(a.metrics || []).length && !(a.datasets || []).length && <span className="text-slate-400">Not linked to any dashboard</span>}
      </div>
      {isAdmin && (
        <div className="mt-1.5 flex flex-wrap gap-3 text-xs">
          <button onClick={() => setEdit(true)} className="inline-flex items-center gap-1 text-slate-600 hover:text-brand-700"><Pencil className="h-3 w-3" /> Edit</button>
          {i.status !== "solved" && <button onClick={() => setStatus("solved")} className="inline-flex items-center gap-1 text-emerald-700 hover:underline"><Check className="h-3 w-3" /> Mark solved</button>}
          {i.status === "solved" && <button onClick={() => setStatus("open")} className="text-slate-600 hover:text-brand-700">Reopen</button>}
          {i.status === "open" && <button onClick={() => setStatus("parked")} className="text-slate-600 hover:text-brand-700">Park</button>}
          {i.status === "parked" && <button onClick={() => setStatus("open")} className="text-slate-600 hover:text-brand-700">Unpark</button>}
        </div>
      )}
    </div>
  );
}

function IssueForm({ wsId, issue, dashes, metrics, onDone }: { wsId: number; issue?: Issue; dashes: Dashboard[]; metrics: Opt[]; onDone: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({
    code: issue?.code || "", title: issue?.title || "", area: issue?.area || "", severity: issue?.severity || "medium",
    status: issue?.status || "open", note: issue?.note || "", summary: issue?.summary || "",
    dashboards: issue?.affects.dashboards || [], metrics: issue?.affects.metrics || [],
  });
  const [busy, setBusy] = useState(false);
  const toggle = (k: "dashboards" | "metrics", v: string) => setF({ ...f, [k]: f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v] });
  const save = async () => {
    setBusy(true);
    const body = { title: f.title, area: f.area, severity: f.severity, status: f.status, note: f.note, summary: f.summary,
      affects: { dashboards: f.dashboards, metrics: f.metrics, datasets: issue?.affects.datasets || [] } };
    try {
      if (issue) await api.patch(`/workspaces/${wsId}/data-issues/${issue.code}`, body);
      else await api.post(`/workspaces/${wsId}/data-issues`, { ...body, code: f.code || null });
      toast("success", "Saved");
      onDone();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="mb-3" title={issue ? `Edit ${issue.code}` : "Add a data issue"}>
      <div className="grid gap-3 md:grid-cols-[120px_1fr_160px_160px]">
        <div><Label>Code</Label><input value={f.code} disabled={!!issue} placeholder="auto" onChange={(e) => setF({ ...f, code: e.target.value.toUpperCase() })} className={inputCls} /></div>
        <div><Label>Issue</Label><input value={f.title} maxLength={300} onChange={(e) => setF({ ...f, title: e.target.value })} className={inputCls} /></div>
        <div><Label>Severity</Label><Select value={f.severity} onChange={(severity) => setF({ ...f, severity: severity as any })} options={[{ value: "high", label: "High" }, { value: "medium", label: "Medium" }, { value: "low", label: "Low" }]} /></div>
        <div><Label>Status</Label><Select value={f.status} onChange={(status) => setF({ ...f, status: status as any })} options={Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label }))} /></div>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div><Label hint="one line for management, shown on tiles">Note</Label><input value={f.note} maxLength={500} onChange={(e) => setF({ ...f, note: e.target.value })} className={inputCls} /></div>
        <div><Label>Area</Label><input value={f.area} maxLength={80} onChange={(e) => setF({ ...f, area: e.target.value })} className={inputCls} /></div>
      </div>
      <div className="mt-3"><Label>What is needed / how it is handled meanwhile</Label><textarea rows={3} value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} className={inputCls} /></div>
      <div className="mt-3"><Label hint="a note on the whole dashboard">Dashboards it touches</Label>
        <div className="flex flex-wrap gap-1.5">{dashes.map((d) => (
          <button key={d.key} onClick={() => toggle("dashboards", d.key)} className={cx("rounded-full border px-2 py-0.5 text-xs", f.dashboards.includes(d.key) ? "border-brand-400 bg-brand-50 text-brand-800" : "border-slate-200 text-slate-600")}>{d.name}</button>
        ))}</div>
      </div>
      <div className="mt-3"><Label hint="every tile using one of these gets a note">Metrics whose numbers it changes</Label>
        <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">{metrics.map((mt) => (
          <button key={mt.value} onClick={() => toggle("metrics", mt.value)} className={cx("rounded-full border px-2 py-0.5 text-xs", f.metrics.includes(mt.value) ? "border-amber-400 bg-amber-50 text-amber-900" : "border-slate-200 text-slate-600")}>{mt.label}</button>
        ))}</div>
      </div>
      <div className="mt-3 flex gap-2">
        <Button variant="primary" loading={busy} disabled={f.title.trim().length < 3} onClick={save}><Check className="h-4 w-4" /> Save</Button>
        <Button variant="ghost" onClick={onDone}><X className="h-4 w-4" /> Cancel</Button>
      </div>
    </Card>
  );
}
