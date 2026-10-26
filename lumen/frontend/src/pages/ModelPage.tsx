import { useMemo, useState } from "react";
import { ArrowRight, Lightbulb, Plus, Trash2 } from "lucide-react";
import { api, Dataset, Relationship } from "../api/client";
import { EChart } from "../components/Chart";
import { escapeHtml } from "../lib/format";
import { Badge, Button, Card, ErrorBox, Label, PageHeader, Select, Spinner, useAsync, useToast } from "../components/ui";
import { useWs } from "./WorkspaceLayout";

interface Suggestion { from_dataset_id: number; from_dataset: string; from_column: string; to_dataset_id: number; to_dataset: string; to_column: string; match_rate: number; from_values: number }

export default function ModelPage() {
  const { ws, canEdit, reloadModel } = useWs();
  const toast = useToast();
  const ds = useAsync(() => api.get<Dataset[]>(`/workspaces/${ws.id}/datasets`), [ws.id]);
  const rels = useAsync(() => api.get<Relationship[]>(`/workspaces/${ws.id}/relationships`), [ws.id]);
  const sugg = useAsync(() => (canEdit ? api.get<Suggestion[]>(`/workspaces/${ws.id}/relationships/suggestions`) : Promise.resolve([])), [ws.id, rels.data?.length]);
  const [form, setForm] = useState({ from_dataset_id: "", from_column: "", to_dataset_id: "", to_column: "" });
  const [busy, setBusy] = useState(false);
  const byId = useMemo(() => new Map((ds.data || []).map((d) => [d.id, d])), [ds.data]);

  const create = async (body: any) => {
    setBusy(true);
    try {
      const r = await api.post<Relationship & { stats: any }>(`/workspaces/${ws.id}/relationships`, {
        ...body, from_dataset_id: Number(body.from_dataset_id), to_dataset_id: Number(body.to_dataset_id),
      });
      toast("success", `Relationship created — ${(r.stats.match_rate * 100).toFixed(1)}% of values match`);
      rels.reload();
      reloadModel();
      setForm({ from_dataset_id: "", from_column: "", to_dataset_id: "", to_column: "" });
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async (id: number) => {
    await api.del(`/workspaces/${ws.id}/relationships/${id}`);
    rels.reload();
    reloadModel();
  };

  const graph = useMemo(() => {
    const list = ds.data || [];
    const linked = new Set((rels.data || []).flatMap((r) => [r.from_dataset_id, r.to_dataset_id]));
    return {
      tooltip: {},
      series: [{
        type: "graph", layout: "force", roam: true, draggable: true, force: { repulsion: 420, edgeLength: [110, 190] },
        label: { show: true, fontSize: 11, color: "#1e293b" }, edgeSymbol: ["none", "arrow"], edgeSymbolSize: 8,
        lineStyle: { color: "#94a3b8", width: 1.5, curveness: 0.08 },
        data: list.map((d) => ({ name: d.name, id: String(d.id), symbolSize: Math.min(60, 22 + Math.log10(d.row_count + 10) * 7),
          itemStyle: { color: (rels.data || []).some((r) => r.to_dataset_id === d.id) ? "#14b8a6" : linked.has(d.id) ? "#2856c4" : "#cbd5e1" },
          tooltip: { formatter: `${escapeHtml(d.name)}<br/>${d.row_count.toLocaleString("en-IN")} rows` } })),
        links: (rels.data || []).map((r) => ({ source: String(r.from_dataset_id), target: String(r.to_dataset_id),
          tooltip: { formatter: `${escapeHtml(byId.get(r.from_dataset_id)?.name)}.${escapeHtml(r.from_column)} → ${escapeHtml(byId.get(r.to_dataset_id)?.name)}.${escapeHtml(r.to_column)}` } })),
      }],
    } as any;
  }, [ds.data, rels.data, byId]);

  if (ds.loading || rels.loading) return <Spinner />;
  const colOpts = (id: string) => (byId.get(Number(id))?.columns || []).map((c) => ({ value: c.name, label: `${c.display_name} (${c.data_type})` }));
  const dsOpts = (ds.data || []).map((d) => ({ value: String(d.id), label: d.name }));

  return (
    <div>
      <PageHeader title="Relationships" subtitle="Lookups connect a fact table (many rows) to a lookup table (one row per key). Reports and the AI then join them automatically, without double counting." />
      <ErrorBox error={ds.error || rels.error} />
      <div className="grid gap-4 xl:grid-cols-[1fr_420px]">
        <Card title="Data model" bodyClass="p-0" actions={<span className="flex gap-2 text-[11px] text-slate-500"><span className="text-brand-600">●</span> fact <span className="text-teal-500">●</span> lookup <span className="text-slate-300">●</span> unrelated</span>}>
          <div className="h-[460px]"><EChart option={graph} /></div>
        </Card>
        <div className="grid content-start gap-4">
          {canEdit && (sugg.data || []).length > 0 && (
            <Card title={<span className="flex items-center gap-1.5"><Lightbulb className="h-4 w-4 text-amber-500" /> Suggested</span>}>
              {sugg.data!.slice(0, 10).map((s, i) => (
                <div key={i} className="flex items-center gap-2 border-b border-slate-100 py-1.5 text-xs last:border-0">
                  <div className="flex-1">
                    <b>{s.from_dataset}</b>.{s.from_column} <ArrowRight className="inline h-3 w-3" /> <b>{s.to_dataset}</b>.{s.to_column}
                    <div className="text-slate-400">{(s.match_rate * 100).toFixed(1)}% of {s.from_values.toLocaleString("en-IN")} values match</div>
                  </div>
                  <Button size="sm" onClick={() => create(s)} disabled={busy}><Plus className="h-3 w-3" /> Add</Button>
                </div>
              ))}
            </Card>
          )}
          {canEdit && (
            <Card title="Add relationship">
              <div className="grid gap-2">
                <Label>Fact / child (many)</Label>
                <div className="grid grid-cols-2 gap-2">
                  <Select value={form.from_dataset_id} onChange={(v) => setForm({ ...form, from_dataset_id: v, from_column: "" })} placeholder="Dataset" options={dsOpts} />
                  <Select value={form.from_column} onChange={(v) => setForm({ ...form, from_column: v })} placeholder="Column" options={colOpts(form.from_dataset_id)} />
                </div>
                <Label>Lookup / parent (one)</Label>
                <div className="grid grid-cols-2 gap-2">
                  <Select value={form.to_dataset_id} onChange={(v) => setForm({ ...form, to_dataset_id: v, to_column: "" })} placeholder="Dataset" options={dsOpts} />
                  <Select value={form.to_column} onChange={(v) => setForm({ ...form, to_column: v })} placeholder="Key column" options={colOpts(form.to_dataset_id)} />
                </div>
                <Button variant="primary" onClick={() => create(form)} loading={busy} disabled={!form.from_column || !form.to_column}>Create</Button>
              </div>
            </Card>
          )}
          <Card title={`Relationships (${rels.data?.length || 0})`}>
            {(rels.data || []).map((r) => (
              <div key={r.id} className="flex items-center gap-2 border-b border-slate-100 py-1.5 text-xs last:border-0">
                <div className="flex-1">
                  <b>{byId.get(r.from_dataset_id)?.name}</b>.{r.from_column} <ArrowRight className="inline h-3 w-3 text-slate-400" /> <b>{byId.get(r.to_dataset_id)?.name}</b>.{r.to_column}
                </div>
                <Badge>many → one</Badge>
                {canEdit && <button onClick={() => remove(r.id)} className="text-slate-400 hover:text-red-600"><Trash2 className="h-3.5 w-3.5" /></button>}
              </div>
            ))}
            {!rels.data?.length && <div className="text-sm text-slate-400">None yet.</div>}
          </Card>
        </div>
      </div>
    </div>
  );
}
