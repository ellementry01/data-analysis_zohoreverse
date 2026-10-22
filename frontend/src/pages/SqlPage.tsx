import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bookmark, Database, Play, Save, Table2, Trash2 } from "lucide-react";
import { api, Dataset, QueryResult } from "../api/client";
import { ResultPanel } from "../components/ResultPanel";
import { Button, Card, ErrorBox, inputCls, Label, Modal, PageHeader, useAsync, useToast } from "../components/ui";
import { useWs } from "./WorkspaceLayout";

interface Saved { id: number; name: string; sql: string; description: string }

export default function SqlPage() {
  const { ws, model, base, canEdit, reloadModel } = useWs();
  const toast = useToast();
  const [params] = useSearchParams();
  const editId = params.get("edit");
  const saved = useAsync(() => api.get<Saved[]>(`/workspaces/${ws.id}/saved-queries`), [ws.id]);
  const first = model.datasets[0];
  const [sql, setSql] = useState(first ? `SELECT *\nFROM ${first.slug}\nLIMIT 100` : "SELECT 1");
  const [res, setRes] = useState<QueryResult | null>(null);
  const [error, setError] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [chart, setChart] = useState("table");
  const [saveMode, setSaveMode] = useState<"" | "query" | "table">("");
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<Dataset | null>(null);
  const ta = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!editId) return;
    api.get<Dataset>(`/workspaces/${ws.id}/datasets/${editId}`).then((d) => {
      setEditing(d);
      setSql(d.query_sql || "");
      setName(d.name);
    });
  }, [editId, ws.id]);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<QueryResult>(`/workspaces/${ws.id}/sql`, { sql });
      setRes(r);
      setChart(r.suggested_chart === "kpi" ? "table" : r.suggested_chart);
    } catch (e) {
      setError(e);
      setRes(null);
    } finally {
      setBusy(false);
    }
  };
  const insert = (text: string) => {
    const el = ta.current;
    if (!el) return setSql(sql + text);
    const s = el.selectionStart, e = el.selectionEnd;
    setSql(sql.slice(0, s) + text + sql.slice(e));
    setTimeout(() => { el.focus(); el.selectionStart = el.selectionEnd = s + text.length; }, 0);
  };
  const doSave = async () => {
    try {
      if (saveMode === "query") {
        await api.post(`/workspaces/${ws.id}/saved-queries`, { name, sql });
        saved.reload();
        toast("success", "Query saved");
      } else if (editing) {
        await api.put(`/workspaces/${ws.id}/query-tables/${editing.id}`, { name, sql });
        toast("success", "Query table updated");
        reloadModel();
      } else {
        const d = await api.post<Dataset>(`/workspaces/${ws.id}/query-tables`, { name, sql });
        toast("success", `Query table "${d.name}" created — use it like any dataset`);
        reloadModel();
      }
      setSaveMode("");
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  return (
    <div>
      <PageHeader title={editing ? `Edit query table: ${editing.name}` : "SQL & query tables"}
        subtitle="Write read-only SQL (PostgreSQL dialect) against your datasets. Save it as a query — or as a query table that behaves like a dataset in reports, dashboards and the AI." />
      <div className="grid gap-4 lg:grid-cols-[250px_1fr]">
        <div className="grid content-start gap-3">
          <Card title="Tables" bodyClass="max-h-[340px] overflow-y-auto p-2">
            {model.datasets.map((d) => (
              <details key={d.slug} className="text-sm">
                <summary className="cursor-pointer rounded px-1 py-0.5 hover:bg-slate-50"><Table2 className="mr-1 inline h-3.5 w-3.5 text-slate-400" />
                  <button className="font-mono text-xs text-brand-700 hover:underline" onClick={(e) => { e.preventDefault(); insert(d.slug); }}>{d.slug}</button></summary>
                <div className="ml-5">
                  {d.fields.map((f) => <button key={f.name} onClick={() => insert(f.name)} className="block font-mono text-[11px] text-slate-600 hover:text-brand-700">{f.name} <span className="text-slate-400">{f.type}</span></button>)}
                </div>
              </details>
            ))}
          </Card>
          <Card title="Saved queries" bodyClass="p-2">
            {(saved.data || []).map((s) => (
              <div key={s.id} className="group flex items-center gap-1 rounded px-1 py-1 text-sm hover:bg-slate-50">
                <button onClick={() => { setSql(s.sql); setEditing(null); }} className="flex-1 truncate text-left"><Bookmark className="mr-1 inline h-3.5 w-3.5 text-slate-400" />{s.name}</button>
                {canEdit && <button onClick={async () => { await api.del(`/workspaces/${ws.id}/saved-queries/${s.id}`); saved.reload(); }} className="hidden text-slate-400 hover:text-red-600 group-hover:block"><Trash2 className="h-3.5 w-3.5" /></button>}
              </div>
            ))}
            {!saved.data?.length && <div className="px-1 text-xs text-slate-400">None yet</div>}
          </Card>
          <Card title="Query tables" bodyClass="p-2">
            {model.datasets.filter((d) => d.kind === "query_table").map((d) => (
              <Link key={d.id} to={`${base}/sql?edit=${d.id}`} className="block rounded px-1 py-1 text-sm hover:bg-slate-50"><Database className="mr-1 inline h-3.5 w-3.5 text-violet-500" />{d.name}</Link>
            ))}
            {!model.datasets.some((d) => d.kind === "query_table") && <div className="px-1 text-xs text-slate-400">None yet</div>}
          </Card>
        </div>
        <div className="grid content-start gap-3">
          <Card bodyClass="p-0">
            <textarea ref={ta} value={sql} onChange={(e) => setSql(e.target.value)} spellCheck={false}
              onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); run(); } }}
              className="h-56 w-full resize-y rounded-t-lg bg-slate-900 p-3 font-mono text-[13px] leading-relaxed text-slate-100 focus:outline-none" />
            <div className="flex items-center gap-2 border-t border-slate-200 px-3 py-2">
              <Button variant="primary" onClick={run} loading={busy}><Play className="h-4 w-4" /> Run <span className="text-[10px] opacity-70">Ctrl+Enter</span></Button>
              {canEdit && <Button onClick={() => { setSaveMode("query"); setName(""); }}><Bookmark className="h-4 w-4" /> Save query</Button>}
              {canEdit && <Button onClick={() => { setSaveMode("table"); if (!editing) setName(""); }}><Save className="h-4 w-4" /> {editing ? "Update query table" : "Save as query table"}</Button>}
              <span className="ml-auto text-[11px] text-slate-400">SELECT only · validated · read-only transaction · timeout & row limits</span>
            </div>
          </Card>
          <ErrorBox error={error} />
          {res && <Card><ResultPanel res={res} chartType={chart} onChartType={setChart} title="SQL result" wsId={ws.id} height={360} /></Card>}
        </div>
      </div>
      <Modal open={!!saveMode} onClose={() => setSaveMode("")} title={saveMode === "query" ? "Save query" : editing ? "Update query table" : "Save as query table"}
        footer={<><Button onClick={() => setSaveMode("")}>Cancel</Button><Button variant="primary" onClick={doSave} disabled={!name.trim()}>Save</Button></>}>
        <Label>Name</Label>
        <input autoFocus className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
        {saveMode === "table" && <p className="mt-2 text-xs text-slate-500">Give every output column a simple lower_case alias. The query table refreshes automatically when its source datasets change.</p>}
      </Modal>
    </div>
  );
}
