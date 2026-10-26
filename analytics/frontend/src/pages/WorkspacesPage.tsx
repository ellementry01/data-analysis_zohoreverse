import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Database, LayoutDashboard, Plus, Sparkles, Trash2 } from "lucide-react";
import { api, Workspace } from "../api/client";
import { Button, Card, Empty, ErrorBox, inputCls, Label, Modal, Spinner, useAsync, useToast } from "../components/ui";
import { timeAgo } from "../lib/format";

export default function WorkspacesPage() {
  const q = useAsync(() => api.get<Workspace[]>("/workspaces"), []);
  const me = useAsync(() => api.get<{ email: string; llm: { enabled: boolean; model: string | null } }>("/me"), []);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const nav = useNavigate();
  const toast = useToast();

  const create = async () => {
    setBusy(true);
    try {
      const ws = await api.post<Workspace>("/workspaces", { name, description: desc });
      nav(`/w/${ws.id}/import`);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  const loadDemo = async () => {
    setDemoBusy(true);
    try {
      const r = await api.post<{ workspace_id: number; dashboard_id: number }>("/demo");
      toast("success", "Demo workspace created");
      nav(`/w/${r.workspace_id}/dashboards/${r.dashboard_id}`);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setDemoBusy(false);
    }
  };
  const remove = async (w: Workspace) => {
    if (!confirm(`Delete workspace "${w.name}" and all its data? This cannot be undone.`)) return;
    try {
      await api.del(`/workspaces/${w.id}`);
      q.reload();
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <div className="mb-8 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <img src="/favicon.svg" className="h-9 w-9" alt="" />
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">Ellementry Analytics</h1>
            <p className="text-sm text-slate-500">Local-first BI with a governed semantic layer and conversational analytics · signed in as {me.data?.email}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button onClick={loadDemo} loading={demoBusy} title="Imports the bundled synthetic home-goods dataset (≈1 min)"><Sparkles className="h-4 w-4" /> Load demo workspace</Button>
          <Button variant="primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New workspace</Button>
        </div>
      </div>
      {demoBusy && <div className="mb-4 rounded-md border border-brand-200 bg-brand-50 px-3 py-2 text-sm text-brand-800">Importing 11 messy spreadsheets, cleaning them, defining relationships, metrics and a dashboard… this takes about a minute.</div>}
      <ErrorBox error={q.error} />
      {q.loading ? <Spinner /> : q.data && q.data.length === 0 ? (
        <Empty icon={<Database className="h-8 w-8" />} title="No workspaces yet" action={<div className="flex gap-2"><Button variant="primary" onClick={() => setOpen(true)}>Create a workspace</Button><Button onClick={loadDemo} loading={demoBusy}>Load demo</Button></div>}>
          A workspace holds related datasets, the business definitions (metrics), reports and dashboards for one area of the business.
        </Empty>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {q.data?.map((w) => (
            <Card key={w.id} className="group transition hover:border-brand-300">
              <Link to={`/w/${w.id}`} className="block">
                <div className="text-base font-semibold text-slate-900 group-hover:text-brand-700">{w.name}</div>
                <div className="mt-1 line-clamp-2 min-h-[2.5rem] text-sm text-slate-500">{w.description || "No description"}</div>
                <div className="mt-3 flex gap-4 text-xs text-slate-500">
                  <span className="flex items-center gap-1"><Database className="h-3.5 w-3.5" /> {w.dataset_count} datasets</span>
                  <span className="flex items-center gap-1"><LayoutDashboard className="h-3.5 w-3.5" /> {w.dashboard_count} dashboards</span>
                </div>
              </Link>
              <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2 text-[11px] text-slate-400">
                <span>Created {timeAgo(w.created_at)} · {w.role}</span>
                {w.role === "admin" && <button onClick={() => remove(w)} className="text-slate-400 hover:text-red-600" title="Delete workspace"><Trash2 className="h-3.5 w-3.5" /></button>}
              </div>
            </Card>
          ))}
        </div>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="New workspace"
        footer={<><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" onClick={create} loading={busy} disabled={!name.trim()}>Create</Button></>}>
        <div className="grid gap-3">
          <div><Label>Name</Label><input autoFocus className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Sales & Inventory" onKeyDown={(e) => e.key === "Enter" && name.trim() && create()} /></div>
          <div><Label>Description</Label><textarea className={inputCls} rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} /></div>
        </div>
      </Modal>
    </div>
  );
}
