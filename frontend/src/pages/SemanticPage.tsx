import { useState } from "react";
import { BookOpen, Pencil, Plus, Shield, Sigma, Trash2 } from "lucide-react";
import { api, FilterRule, Metric } from "../api/client";
import { Badge, Button, Card, cx, inputCls, Label, Modal, PageHeader, Select, Tabs, useAsync, useToast } from "../components/ui";
import { OPS } from "../components/SpecBuilder";
import { useWs } from "./WorkspaceLayout";

interface Term { id: number; term: string; synonyms: string[]; target_type: "column" | "value" | "metric"; dataset_id: number | null; column: string | null; value: string | null; metric_name: string | null; description: string }
interface Rule { id: number; dataset_id: number; name: string; description: string; filters: FilterRule[]; enabled: boolean }

export default function SemanticPage() {
  const [tab, setTab] = useState("metrics");
  return (
    <div>
      <PageHeader title="Semantic layer" subtitle="Business definitions shared by reports, dashboards and the AI assistant: metrics with their calculation rules, vocabulary and row-level business rules." />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "metrics", label: "Metrics" }, { id: "glossary", label: "Glossary & synonyms" }, { id: "rules", label: "Business rules" }]} />
      <div className="mt-4">{tab === "metrics" ? <Metrics /> : tab === "glossary" ? <Glossary /> : <Rules />}</div>
    </div>
  );
}

function RuleEditor({ filters, columns, onChange }: { filters: FilterRule[]; columns: { value: string; label: string }[]; onChange: (f: FilterRule[]) => void }) {
  return (
    <div className="grid gap-1.5">
      {filters.map((f, i) => (
        <div key={i} className="grid grid-cols-[1fr_120px_1fr_auto] gap-1.5">
          <Select value={f.column} onChange={(v) => onChange(filters.map((x, j) => (j === i ? { ...x, column: v } : x)))} placeholder="Column" options={columns} />
          <Select value={f.op} onChange={(v) => onChange(filters.map((x, j) => (j === i ? { ...x, op: v } : x)))} options={OPS} />
          <input className={inputCls} value={Array.isArray(f.value) ? f.value.join(", ") : f.value ?? ""}
            onChange={(e) => onChange(filters.map((x, j) => (j === i ? { ...x, value: ["in", "not_in"].includes(x.op) ? e.target.value.split(",").map((s) => s.trim()) : e.target.value } : x)))} />
          <button onClick={() => onChange(filters.filter((_, j) => j !== i))} className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
        </div>
      ))}
      <button className="justify-self-start text-xs text-brand-600" onClick={() => onChange([...filters, { column: "", op: "eq", value: "" }])}>+ Add condition</button>
    </div>
  );
}

const blankMetric = (): Partial<Metric> => ({ name: "", label: "", description: "", kind: "simple", dataset_id: null, expression: "SUM()", filters: [], time_column: null, semi_additive: false, synonyms: [], format: "number", higher_is_better: true });

function Metrics() {
  const { ws, model, canEdit, reloadModel } = useWs();
  const toast = useToast();
  const q = useAsync(() => api.get<Metric[]>(`/workspaces/${ws.id}/metrics`), [ws.id]);
  const [edit, setEdit] = useState<Partial<Metric> | null>(null);
  const [busy, setBusy] = useState(false);
  const ds = model.datasets.find((d) => d.id === edit?.dataset_id);
  const save = async () => {
    if (!edit) return;
    setBusy(true);
    try {
      const body = { ...edit, synonyms: (edit.synonyms || []).filter(Boolean), filters: (edit.filters || []).filter((f) => f.column) };
      if (edit.id) await api.put(`/workspaces/${ws.id}/metrics/${edit.id}`, body);
      else await api.post(`/workspaces/${ws.id}/metrics`, body);
      toast("success", "Metric saved and verified against the data");
      setEdit(null);
      q.reload();
      reloadModel();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  const del = async (m: Metric) => {
    if (!confirm(`Delete metric "${m.label}"?`)) return;
    try {
      await api.del(`/workspaces/${ws.id}/metrics/${m.id}`);
      q.reload();
      reloadModel();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  return (
    <>
      {canEdit && <div className="mb-3"><Button variant="primary" onClick={() => setEdit(blankMetric())}><Plus className="h-4 w-4" /> New metric</Button></div>}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {(q.data || []).map((m) => {
          const d = model.datasets.find((x) => x.id === m.dataset_id);
          return (
            <Card key={m.id} title={<span className="flex items-center gap-1.5"><Sigma className="h-4 w-4 text-violet-600" />{m.label}</span>}
              actions={canEdit && <><button onClick={() => setEdit(m)} className="text-slate-400 hover:text-slate-700"><Pencil className="h-3.5 w-3.5" /></button><button onClick={() => del(m)} className="text-slate-400 hover:text-red-600"><Trash2 className="h-3.5 w-3.5" /></button></>}>
              <div className="font-mono text-xs text-slate-700">{m.expression}{d && <span className="text-slate-400"> on {d.name}</span>}</div>
              {m.filters.length > 0 && <div className="mt-1 text-xs text-amber-700">only where {m.filters.map((f) => `${f.column} ${f.op.replace("_", " ")} ${Array.isArray(f.value) ? f.value.join("/") : f.value}`).join(" and ")}</div>}
              {m.description && <div className="mt-1 text-xs text-slate-500">{m.description}</div>}
              <div className="mt-2 flex flex-wrap gap-1">
                <Badge tone="violet">{m.name}</Badge>{m.kind === "composite" && <Badge tone="blue">composite</Badge>}{m.semi_additive && <Badge tone="amber">latest snapshot</Badge>}<Badge>{m.format}</Badge>
                {m.synonyms.map((s) => <Badge key={s} tone="green">{s}</Badge>)}
              </div>
            </Card>
          );
        })}
      </div>
      {!q.data?.length && !q.loading && <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
        <BookOpen className="mx-auto mb-2 h-6 w-6 text-slate-400" />Define metrics like “Net sales = SUM(net_amount) where transaction type is Sale” so every chart and AI answer uses the same definition.</div>}
      {edit && (
        <Modal open wide title={edit.id ? `Edit ${edit.label}` : "New metric"} onClose={() => setEdit(null)}
          footer={<><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" onClick={save} loading={busy}>Save & verify</Button></>}>
          <div className="grid gap-3 md:grid-cols-2">
            <div><Label>Label</Label><input className={inputCls} value={edit.label} onChange={(e) => setEdit({ ...edit, label: e.target.value, name: edit.id ? edit.name : e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") })} /></div>
            <div><Label hint="identifier">Name</Label><input className={inputCls + " font-mono"} value={edit.name} disabled={!!edit.id} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></div>
            <div><Label>Kind</Label><Select value={edit.kind!} onChange={(v) => setEdit({ ...edit, kind: v as any, expression: v === "composite" ? "{a} / NULLIF({b}, 0)" : "SUM()" })} options={[{ value: "simple", label: "Simple (aggregate over one dataset)" }, { value: "composite", label: "Composite (formula of other metrics)" }]} /></div>
            <div><Label>Format</Label><Select value={edit.format!} onChange={(v) => setEdit({ ...edit, format: v as any })} options={[{ value: "number", label: "Number" }, { value: "currency", label: "Currency (₹)" }, { value: "percent", label: "Percent" }]} /></div>
            {edit.kind === "simple" && <div><Label>Dataset</Label><Select value={String(edit.dataset_id || "")} onChange={(v) => setEdit({ ...edit, dataset_id: Number(v) || null })} placeholder="Choose…" options={model.datasets.map((d) => ({ value: String(d.id), label: d.name }))} /></div>}
            <div className={cx(edit.kind === "composite" && "md:col-span-2")}>
              <Label hint={edit.kind === "composite" ? "reference metrics as {name}" : "must contain SUM/COUNT/AVG/MIN/MAX"}>Expression</Label>
              <input className={inputCls + " font-mono"} value={edit.expression} onChange={(e) => setEdit({ ...edit, expression: e.target.value })} />
              {edit.kind === "simple" && ds && <div className="mt-1 flex flex-wrap gap-1">{ds.fields.map((f) => <button key={f.name} onClick={() => setEdit({ ...edit, expression: (edit.expression || "").replace(/\(\)$/, `(${f.name})`) })} className="rounded bg-slate-100 px-1 font-mono text-[10px] text-slate-600 hover:bg-brand-100">{f.name}</button>)}</div>}
              {edit.kind === "composite" && <div className="mt-1 flex flex-wrap gap-1">{model.metrics.filter((m) => m.name !== edit.name).map((m) => <span key={m.name} className="rounded bg-violet-50 px-1 font-mono text-[10px] text-violet-700">{`{${m.name}}`}</span>)}</div>}
            </div>
            {edit.kind === "simple" && ds && (
              <>
                <div className="md:col-span-2"><Label hint="business rule, e.g. transaction_type = Sale">Count only rows where</Label>
                  <RuleEditor filters={edit.filters || []} columns={ds.fields.map((f) => ({ value: f.name, label: f.label }))} onChange={(f) => setEdit({ ...edit, filters: f })} /></div>
                <div><Label>Date column</Label><Select value={edit.time_column || ""} onChange={(v) => setEdit({ ...edit, time_column: v || null })} placeholder={`Dataset default (${ds.default_date_column || "none"})`} options={ds.fields.filter((f) => f.type === "date" || f.type === "datetime").map((f) => ({ value: f.name, label: f.label }))} /></div>
                <label className="mt-5 flex items-center gap-2 text-sm"><input type="checkbox" checked={!!edit.semi_additive} onChange={(e) => setEdit({ ...edit, semi_additive: e.target.checked })} /> Semi-additive (use latest snapshot per period, e.g. stock on hand)</label>
              </>
            )}
            <div className="md:col-span-2"><Label hint="comma separated — words people use for this metric">Synonyms</Label>
              <input className={inputCls} value={(edit.synonyms || []).join(", ")} onChange={(e) => setEdit({ ...edit, synonyms: e.target.value.split(",").map((s) => s.trim()) })} /></div>
            <div className="md:col-span-2"><Label>Description</Label><input className={inputCls} value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></div>
          </div>
        </Modal>
      )}
    </>
  );
}

function Glossary() {
  const { ws, model, canEdit } = useWs();
  const toast = useToast();
  const q = useAsync(() => api.get<Term[]>(`/workspaces/${ws.id}/glossary`), [ws.id]);
  const [f, setF] = useState<any>({ term: "", synonyms: "", target_type: "value", dataset_id: "", column: "", value: "", metric_name: "" });
  const ds = model.datasets.find((d) => String(d.id) === String(f.dataset_id));
  const add = async () => {
    try {
      await api.post(`/workspaces/${ws.id}/glossary`, { ...f, synonyms: f.synonyms.split(",").map((s: string) => s.trim()).filter(Boolean), dataset_id: f.dataset_id ? Number(f.dataset_id) : null });
      setF({ ...f, term: "", synonyms: "", value: "" });
      q.reload();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
      <Card title="Vocabulary" bodyClass="p-0">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-3 py-2">Term</th><th className="px-3 py-2">Synonyms</th><th className="px-3 py-2">Means</th><th /></tr></thead>
          <tbody>
            {(q.data || []).map((t) => (
              <tr key={t.id} className="border-t border-slate-100">
                <td className="px-3 py-2 font-medium">{t.term}</td>
                <td className="px-3 py-2 text-xs text-slate-500">{t.synonyms.join(", ")}</td>
                <td className="px-3 py-2 text-xs">{t.target_type === "metric" ? <Badge tone="violet">{t.metric_name}</Badge> : <span>{model.datasets.find((d) => d.id === t.dataset_id)?.name}.{t.column}{t.target_type === "value" && <> = <b>{t.value}</b></>}</span>}</td>
                <td className="px-3 py-2">{canEdit && <button onClick={async () => { await api.del(`/workspaces/${ws.id}/glossary/${t.id}`); q.reload(); }} className="text-slate-400 hover:text-red-600"><Trash2 className="h-3.5 w-3.5" /></button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!q.data?.length && <div className="p-4 text-sm text-slate-400">Teach the assistant your words: “website” → channel = Shopify, “item” → product name…</div>}
      </Card>
      {canEdit && (
        <Card title="Add term">
          <div className="grid gap-2.5">
            <div><Label>Term</Label><input className={inputCls} value={f.term} onChange={(e) => setF({ ...f, term: e.target.value })} /></div>
            <div><Label hint="comma separated">Synonyms</Label><input className={inputCls} value={f.synonyms} onChange={(e) => setF({ ...f, synonyms: e.target.value })} /></div>
            <div><Label>Refers to</Label><Select value={f.target_type} onChange={(v) => setF({ ...f, target_type: v })} options={[{ value: "value", label: "A data value" }, { value: "column", label: "A column" }, { value: "metric", label: "A metric" }]} /></div>
            {f.target_type === "metric" ? (
              <Select value={f.metric_name} onChange={(v) => setF({ ...f, metric_name: v })} placeholder="Metric…" options={model.metrics.map((m) => ({ value: m.name, label: m.label }))} />
            ) : (
              <div className="grid grid-cols-2 gap-2">
                <Select value={String(f.dataset_id)} onChange={(v) => setF({ ...f, dataset_id: v, column: "" })} placeholder="Dataset" options={model.datasets.map((d) => ({ value: String(d.id), label: d.name }))} />
                <Select value={f.column} onChange={(v) => setF({ ...f, column: v })} placeholder="Column" options={(ds?.fields || []).map((x) => ({ value: x.name, label: x.label }))} />
              </div>
            )}
            {f.target_type === "value" && <div><Label>Value</Label><input className={inputCls} value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} /></div>}
            <Button variant="primary" onClick={add} disabled={!f.term}>Add</Button>
          </div>
        </Card>
      )}
    </div>
  );
}

function Rules() {
  const { ws, model, canEdit } = useWs();
  const toast = useToast();
  const q = useAsync(() => api.get<Rule[]>(`/workspaces/${ws.id}/rules`), [ws.id]);
  const [edit, setEdit] = useState<Partial<Rule> | null>(null);
  const ds = model.datasets.find((d) => d.id === edit?.dataset_id);
  const save = async () => {
    try {
      const body = { ...edit, filters: (edit!.filters || []).filter((f) => f.column) };
      if (edit!.id) await api.put(`/workspaces/${ws.id}/rules/${edit!.id}`, body);
      else await api.post(`/workspaces/${ws.id}/rules`, body);
      setEdit(null);
      q.reload();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const toggle = async (r: Rule) => {
    await api.put(`/workspaces/${ws.id}/rules/${r.id}`, { ...r, enabled: !r.enabled });
    q.reload();
  };
  return (
    <>
      <p className="mb-3 text-sm text-slate-600">Business rules filter a dataset in <b>every</b> chart, dashboard and AI answer (unless a report turns rules off) — e.g. exclude test orders or cancelled invoices. For metric-specific logic (consumer sales vs. transfers), put the condition on the metric instead.</p>
      {canEdit && <div className="mb-3"><Button variant="primary" onClick={() => setEdit({ name: "", description: "", filters: [{ column: "", op: "neq", value: "" }], enabled: true, dataset_id: model.datasets[0]?.id })}><Plus className="h-4 w-4" /> New rule</Button></div>}
      <div className="grid gap-2">
        {(q.data || []).map((r) => (
          <div key={r.id} className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-3 text-sm shadow-card">
            <Shield className={cx("h-4 w-4", r.enabled ? "text-emerald-600" : "text-slate-300")} />
            <div className="flex-1">
              <div className="font-medium">{r.name} <span className="text-xs font-normal text-slate-400">on {model.datasets.find((d) => d.id === r.dataset_id)?.name}</span></div>
              <div className="text-xs text-slate-500">{r.filters.map((f) => `${f.column} ${f.op} ${Array.isArray(f.value) ? f.value.join("/") : f.value}`).join(" AND ")} {r.description && `— ${r.description}`}</div>
            </div>
            {canEdit && <><Button size="sm" onClick={() => toggle(r)}>{r.enabled ? "Disable" : "Enable"}</Button><Button size="sm" variant="ghost" onClick={() => setEdit(r)}><Pencil className="h-3.5 w-3.5" /></Button>
              <Button size="sm" variant="ghost" onClick={async () => { await api.del(`/workspaces/${ws.id}/rules/${r.id}`); q.reload(); }}><Trash2 className="h-3.5 w-3.5" /></Button></>}
          </div>
        ))}
        {!q.data?.length && <div className="text-sm text-slate-400">No rules.</div>}
      </div>
      {edit && (
        <Modal open title={edit.id ? "Edit rule" : "New rule"} onClose={() => setEdit(null)} footer={<><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" onClick={save}>Save</Button></>}>
          <div className="grid gap-3">
            <div><Label>Name</Label><input className={inputCls} value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></div>
            <div><Label>Dataset</Label><Select value={String(edit.dataset_id || "")} onChange={(v) => setEdit({ ...edit, dataset_id: Number(v) })} options={model.datasets.map((d) => ({ value: String(d.id), label: d.name }))} /></div>
            <div><Label>Keep only rows where</Label><RuleEditor filters={edit.filters || []} columns={(ds?.fields || []).map((f) => ({ value: f.name, label: f.label }))} onChange={(f) => setEdit({ ...edit, filters: f })} /></div>
            <div><Label>Description</Label><input className={inputCls} value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></div>
          </div>
        </Modal>
      )}
    </>
  );
}
