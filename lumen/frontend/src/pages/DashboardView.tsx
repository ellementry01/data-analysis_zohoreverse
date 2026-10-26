import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import GridLayout, { Layout, WidthProvider } from "react-grid-layout";
import type * as echarts from "echarts";
import { ArrowLeft, ChevronLeft, Copy, Download, Filter, GripHorizontal, Image, LayoutTemplate, Maximize2, Pencil, Plus, Printer, RefreshCw, Settings2, Trash2, X } from "lucide-react";
import { api, Dashboard, DashFilter, emptySpec, QueryResult, QuerySpec, Report, SpecFilter, Widget } from "../api/client";
import { ChartView, CHART_TYPES, PointClick } from "../components/Chart";
import { exportPng } from "../components/ResultPanel";
import { addToSpec, DateRangePicker, fieldMap, FieldList, fieldOptions, SpecShelves, withAliases } from "../components/SpecBuilder";
import { Badge, Button, cx, ErrorBox, inputCls, Label, Modal, Select, Spinner, Tabs, useAsync, useToast } from "../components/ui";
import { describeRange, fmtDateLabel } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

const Grid = WidthProvider(GridLayout);

interface DrillStep { label: string; filters: SpecFilter[]; dimension?: any; time_range?: any }

export default function DashboardView() {
  const { dashId } = useParams();
  const { ws, base, canEdit, model } = useWs();
  const toast = useToast();
  const q = useAsync(() => api.get<Dashboard>(`/workspaces/${ws.id}/dashboards/${dashId}`), [ws.id, dashId]);
  const [edit, setEdit] = useState(false);
  const [filterValues, setFilterValues] = useState<Record<string, any>>({});
  const [compare, setCompare] = useState<string>("");
  const [tick, setTick] = useState(0);
  const [editing, setEditing] = useState<Widget | "new" | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [full, setFull] = useState<Widget | null>(null);
  const layoutTimer = useRef<any>(null);
  const d = q.data;

  useEffect(() => {
    if (d) setFilterValues(Object.fromEntries(d.filters.map((f) => [f.id, f.value])));
  }, [d?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeFilters = useMemo(() => (d?.filters || []).map((f) => ({ ...f, value: filterValues[f.id] ?? f.value })), [d?.filters, filterValues]);

  const onLayout = (layout: Layout[]) => {
    if (!edit || !d) return;
    clearTimeout(layoutTimer.current);
    layoutTimer.current = setTimeout(() => {
      api.put(`/workspaces/${ws.id}/dashboards/${d.id}/layout`, layout.map((l) => ({ id: Number(l.i), x: l.x, y: l.y, w: l.w, h: l.h })))
        .catch((e) => toast("error", e.message));
    }, 500);
  };
  const saveDefaults = async () => {
    if (!d) return;
    try {
      await api.put(`/workspaces/${ws.id}/dashboards/${d.id}`, { name: d.name, description: d.description, is_template: d.is_template, filters: activeFilters });
      toast("success", "Current filter values saved as the dashboard defaults");
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const removeWidget = async (w: Widget) => {
    if (!confirm(`Remove "${w.title}"?`)) return;
    await api.del(`/workspaces/${ws.id}/dashboards/${dashId}/widgets/${w.id}`);
    q.reload();
  };
  const saveAsTemplate = async () => {
    if (!d) return;
    const copy = await api.post<Dashboard>(`/workspaces/${ws.id}/dashboards/${d.id}/duplicate?name=${encodeURIComponent("Template: " + d.name)}`);
    await api.put(`/workspaces/${ws.id}/dashboards/${copy.id}`, { name: copy.name, description: copy.description, filters: copy.filters, is_template: true });
    toast("success", "Saved as template");
  };
  const duplicate = async () => {
    if (!d) return;
    const copy = await api.post<Dashboard>(`/workspaces/${ws.id}/dashboards/${d.id}/duplicate`);
    toast("success", `Created "${copy.name}"`);
  };

  if (q.error) return <ErrorBox error={q.error} />;
  if (!d) return <Spinner />;
  const layout: Layout[] = d.widgets.map((w) => ({ i: String(w.id), x: w.layout.x ?? 0, y: w.layout.y ?? 0, w: w.layout.w ?? 6, h: w.layout.h ?? 4, minW: 2, minH: 2 }));

  return (
    <div>
      <div className="no-print mb-3 flex flex-wrap items-center gap-2">
        <Link to={`${base}/dashboards`} className="text-slate-400 hover:text-slate-700"><ArrowLeft className="h-4 w-4" /></Link>
        {edit ? (
          <input className={inputCls + " max-w-sm text-lg font-semibold"} defaultValue={d.name}
            onBlur={(e) => e.target.value !== d.name && api.put(`/workspaces/${ws.id}/dashboards/${d.id}`, { ...d, name: e.target.value, filters: d.filters }).then(() => q.reload())} />
        ) : <h1 className="text-xl font-semibold text-slate-900">{d.name}</h1>}
        {d.is_template && <Badge tone="violet">template</Badge>}
        <div className="ml-auto flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setTick((t) => t + 1)} title="Refresh data"><RefreshCw className="h-3.5 w-3.5" /></Button>
          <Button size="sm" onClick={() => window.print()} title="Print or save as PDF"><Printer className="h-3.5 w-3.5" /> PDF</Button>
          {canEdit && <Button size="sm" onClick={duplicate}><Copy className="h-3.5 w-3.5" /> Duplicate</Button>}
          {canEdit && <Button size="sm" onClick={saveAsTemplate}><LayoutTemplate className="h-3.5 w-3.5" /> Save as template</Button>}
          {canEdit && edit && <Button size="sm" onClick={() => setFiltersOpen(true)}><Settings2 className="h-3.5 w-3.5" /> Filters</Button>}
          {canEdit && edit && <Button size="sm" onClick={() => setEditing("new")}><Plus className="h-3.5 w-3.5" /> Add widget</Button>}
          {canEdit && <Button size="sm" variant={edit ? "primary" : "secondary"} onClick={() => { setEdit(!edit); if (edit) q.reload(); }}><Pencil className="h-3.5 w-3.5" /> {edit ? "Done" : "Edit"}</Button>}
        </div>
      </div>
      <h1 className="mb-2 hidden text-xl font-semibold print:block">{d.name}</h1>

      <div className="no-print mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-card">
        <Filter className="h-4 w-4 text-slate-400" />
        {activeFilters.map((f) => (
          <div key={f.id} className="flex items-center gap-1.5 text-sm">
            <span className="text-xs font-medium text-slate-500">{f.label}</span>
            {f.type === "date_range" ? (
              <DateRangePicker value={f.value} presets={model.date_presets} onChange={(v) => setFilterValues({ ...filterValues, [f.id]: v })} />
            ) : (
              <ValuesFilter wsId={ws.id} dashId={d.id} filter={f} onChange={(v) => setFilterValues({ ...filterValues, [f.id]: v })} />
            )}
          </div>
        ))}
        <div className="flex items-center gap-1.5 text-sm">
          <span className="text-xs font-medium text-slate-500">Compare</span>
          <Select className="!w-auto" value={compare} onChange={setCompare} placeholder="Off" options={[{ value: "previous_period", label: "Previous period" }, { value: "previous_year", label: "Last year" }]} />
        </div>
        {canEdit && <button onClick={saveDefaults} className="ml-auto text-xs text-brand-600 hover:underline">Save as default view</button>}
      </div>
      <div className="mb-2 hidden text-xs text-slate-500 print:block">Filters: {activeFilters.map((f) => `${f.label}: ${f.type === "date_range" ? describeRange(f.value) : (f.value || []).join(", ") || "All"}`).join(" · ")}</div>

      {d.widgets.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-12 text-center text-sm text-slate-500">
          This dashboard is empty. {canEdit && <button className="text-brand-600" onClick={() => { setEdit(true); setEditing("new"); }}>Add a widget</button>}
        </div>
      ) : (
        <Grid className="layout -mx-2" layout={layout} cols={12} rowHeight={64} margin={[12, 12]} isDraggable={edit} isResizable={edit}
          draggableHandle=".drag-handle" onLayoutChange={onLayout} compactType="vertical">
          {d.widgets.map((w) => (
            <div key={String(w.id)}>
              <WidgetCard w={w} dashId={d.id} filters={activeFilters} compare={compare} tick={tick} edit={edit}
                onEdit={() => setEditing(w)} onRemove={() => removeWidget(w)} onFull={() => setFull(w)} />
            </div>
          ))}
        </Grid>
      )}

      {editing && <WidgetEditor dash={d} widget={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); q.reload(); }} />}
      {filtersOpen && <FiltersEditor dash={d} onClose={() => setFiltersOpen(false)} onSaved={() => { setFiltersOpen(false); q.reload(); }} />}
      {full && (
        <Modal open wide title={full.title} onClose={() => setFull(null)}>
          <div className="h-[60vh]"><WidgetBody w={full} dashId={d.id} filters={activeFilters} compare={compare} tick={tick} /></div>
        </Modal>
      )}
    </div>
  );
}

function ValuesFilter({ wsId, dashId, filter, onChange }: { wsId: number; dashId: number; filter: DashFilter; onChange: (v: any[]) => void }) {
  const [open, setOpen] = useState(false);
  const vals = useAsync(() => (open ? api.get<any[]>(`/workspaces/${wsId}/dashboards/${dashId}/values?field=${encodeURIComponent(filter.field)}`) : Promise.resolve([])), [open, filter.field]);
  const sel: any[] = filter.value || [];
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} className={cx(inputCls, "w-auto min-w-[120px] text-left")}>{sel.length ? sel.join(", ") : "All"}</button>
      {open && (
        <div className="absolute z-30 mt-1 max-h-72 w-64 overflow-auto rounded-md border border-slate-200 bg-white p-2 shadow-lg">
          <div className="mb-1 flex justify-between text-xs"><button className="text-brand-600" onClick={() => onChange([])}>Clear</button><button onClick={() => setOpen(false)}><X className="h-3.5 w-3.5" /></button></div>
          {vals.loading && <div className="text-xs text-slate-400">Loading…</div>}
          {(vals.data || []).map((v) => (
            <label key={String(v)} className="flex items-center gap-2 py-0.5 text-sm">
              <input type="checkbox" checked={sel.includes(v)} onChange={(e) => onChange(e.target.checked ? [...sel, v] : sel.filter((x) => x !== v))} /> {String(v)}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}


/** Apply a drill step's date window: override the dashboard date filter, or add one if the board has none. */
function withDrillRange(filters: DashFilter[], last?: DrillStep): DashFilter[] {
  if (!last?.time_range) return filters;
  if (filters.some((f) => f.type === "date_range")) return filters.map((f) => (f.type === "date_range" ? { ...f, value: last.time_range } : f));
  return [...filters, { id: "__drill", type: "date_range", label: "Drill", field: "@time", value: last.time_range }];
}

function useWidgetData(w: Widget, dashId: number, filters: DashFilter[], compare: string, tick: number, drill: DrillStep[]) {
  const { ws } = useWs();
  const [res, setRes] = useState<QueryResult | null>(null);
  const [err, setErr] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const key = JSON.stringify([w.spec, filters, compare, tick, drill]);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    const last = drill[drill.length - 1];
    const fl = withDrillRange(filters, last);
    api.post<QueryResult>(`/workspaces/${ws.id}/dashboards/${dashId}/widgets/${w.id}/data`, {
      filters: fl, drill: drill.flatMap((s) => s.filters), drill_dimension: last?.dimension || null, compare: compare || (w.spec.compare ?? null),
    }).then((r) => { if (alive) { setRes(r); setErr(null); } }).catch((e) => alive && setErr(e)).finally(() => alive && setLoading(false));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return { res, err, loading };
}

function nextDrill(w: Widget, model: any, p: PointClick, depth: number): DrillStep | null {
  const spec = w.spec;
  const dim = spec.dimensions[0];
  if (!dim || p.value === null || p.value === undefined) return null;
  const path: string[] = w.options?.drill_path || [];
  const lbl = p.column.type === "date" ? fmtDateLabel(p.value, p.column.grain) : String(p.value);
  if (p.column.type === "date" && p.column.grain && p.column.grain !== "day") {
    const s = new Date(String(p.value).slice(0, 10) + "T00:00:00");
    const e = new Date(s);
    const g = p.column.grain;
    if (g === "year") e.setFullYear(e.getFullYear() + 1); else if (g === "quarter") e.setMonth(e.getMonth() + 3); else if (g === "month") e.setMonth(e.getMonth() + 1); else e.setDate(e.getDate() + 7);
    e.setDate(e.getDate() - 1);
    const iso = (x: Date) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
    const nextGrain = ({ year: "month", quarter: "month", month: "day", week: "day" } as any)[g];
    return { label: lbl, filters: [], time_range: { from: iso(s), to: iso(e) }, dimension: { ...dim, grain: nextGrain, alias: dim.alias } };
  }
  const field = depth === 0 ? dim.field : (path[depth - 1] || dim.field);
  if (field === "@time") return null;
  const nextField = path[depth];
  const fm = fieldMap(model);
  const fallback = !nextField && field.split(".")[0] === "products" && fm.has("products.product_name") && field !== "products.product_name" ? "products.product_name" : null;
  return { label: lbl, filters: [{ field, op: "in", value: [p.value] }], dimension: nextField || fallback ? { field: nextField || fallback } : undefined };
}

function WidgetBody({ w, dashId, filters, compare, tick, drill = [], onPoint, onChart }:
  { w: Widget; dashId: number; filters: DashFilter[]; compare: string; tick: number; drill?: DrillStep[]; onPoint?: (p: PointClick) => void; onChart?: (c: echarts.ECharts) => void }) {
  const { res, err, loading } = useWidgetData(w, dashId, filters, compare, tick, drill);
  if (err) return <div className="p-2 text-xs text-red-600">{err.message}</div>;
  if (!res) return <div className="flex h-full items-center justify-center text-xs text-slate-400">Loading…</div>;
  const type = w.chart_type === "kpi" || drill.length === 0 ? w.chart_type : ["pie", "donut", "heatmap", "pivot"].includes(w.chart_type) ? "bar" : w.chart_type;
  return (
    <div className={cx("h-full", loading && "opacity-60")}>
      <ChartView type={type} res={res} onPoint={onPoint} onReady={onChart} />
    </div>
  );
}

function WidgetCard({ w, dashId, filters, compare, tick, edit, onEdit, onRemove, onFull }:
  { w: Widget; dashId: number; filters: DashFilter[]; compare: string; tick: number; edit: boolean; onEdit: () => void; onRemove: () => void; onFull: () => void }) {
  const { ws, model } = useWs();
  const [drill, setDrill] = useState<DrillStep[]>([]);
  const chart = useRef<echarts.ECharts | null>(null);
  const onPoint = useCallback((p: PointClick) => {
    if (edit || w.chart_type === "kpi") return;
    const step = nextDrill(w, model, p, drill.length);
    if (step) setDrill((d) => [...d, step]);
  }, [edit, w, model, drill.length]);
  const csv = () => {
    const last = drill[drill.length - 1];
    const fl = withDrillRange(filters, last);
    api.post<QueryResult>(`/workspaces/${ws.id}/dashboards/${dashId}/widgets/${w.id}/data`, { filters: fl, drill: drill.flatMap((s) => s.filters), drill_dimension: last?.dimension || null })
      .then((r) => api.download(`/workspaces/${ws.id}/query/export?format=xlsx`, r.applied_spec, `${w.title}.xlsx`));
  };
  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-200 bg-white shadow-card">
      <div className={cx("flex items-center gap-1.5 border-b border-slate-100 px-3 py-1.5", edit && "drag-handle bg-slate-50")}>
        {edit && <GripHorizontal className="h-3.5 w-3.5 text-slate-400" />}
        {drill.length > 0 && <button onClick={() => setDrill(drill.slice(0, -1))} className="text-brand-600" title="Back"><ChevronLeft className="h-4 w-4" /></button>}
        <div className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-700" title={w.title}>
          {w.title}{drill.map((s, i) => <span key={i} className="font-normal text-brand-600"> › {s.label}</span>)}
        </div>
        <div className="no-print flex items-center gap-0.5 text-slate-400">
          {!["kpi", "table", "pivot"].includes(w.chart_type) && <button onClick={() => exportPng(chart.current, w.title)} title="Download PNG" className="rounded p-0.5 hover:bg-slate-100 hover:text-slate-700"><Image className="h-3.5 w-3.5" /></button>}
          <button onClick={csv} title="Export data to Excel" className="rounded p-0.5 hover:bg-slate-100 hover:text-slate-700"><Download className="h-3.5 w-3.5" /></button>
          <button onClick={onFull} title="Expand" className="rounded p-0.5 hover:bg-slate-100 hover:text-slate-700"><Maximize2 className="h-3.5 w-3.5" /></button>
          {edit && <button onClick={onEdit} title="Edit" className="rounded p-0.5 hover:bg-slate-100 hover:text-slate-700"><Pencil className="h-3.5 w-3.5" /></button>}
          {edit && <button onClick={onRemove} title="Remove" className="rounded p-0.5 hover:bg-red-50 hover:text-red-600"><Trash2 className="h-3.5 w-3.5" /></button>}
        </div>
      </div>
      <div className="min-h-0 flex-1 p-2">
        <WidgetBody w={w} dashId={dashId} filters={filters} compare={compare} tick={tick} drill={drill} onPoint={onPoint} onChart={(c) => (chart.current = c)} />
      </div>
    </div>
  );
}

function WidgetEditor({ dash, widget, onClose, onSaved }: { dash: Dashboard; widget: Widget | null; onClose: () => void; onSaved: () => void }) {
  const { ws, model } = useWs();
  const toast = useToast();
  const [tab, setTab] = useState(widget ? "build" : "build");
  const [title, setTitle] = useState(widget?.title || "");
  const [chart, setChart] = useState(widget?.chart_type || "bar");
  const [spec, setSpec] = useState<QuerySpec>(widget ? { ...emptySpec(), ...widget.spec } : emptySpec());
  const [drillPath, setDrillPath] = useState<string>((widget?.options?.drill_path || []).join(","));
  const [reportId, setReportId] = useState("");
  const [busy, setBusy] = useState(false);
  const reports = useAsync(() => api.get<Report[]>(`/workspaces/${ws.id}/reports`), [ws.id]);
  const save = async () => {
    setBusy(true);
    try {
      const options = { ...(widget?.options || {}), drill_path: drillPath.split(",").map((s) => s.trim()).filter(Boolean) };
      if (tab === "report" && reportId) {
        const r = reports.data!.find((x) => String(x.id) === reportId)!;
        await api.post(`/workspaces/${ws.id}/dashboards/${dash.id}/widgets`, { title: title || r.name, chart_type: r.chart_type, report_id: r.id, options });
      } else {
        const body = { title: title || "Chart", chart_type: chart, spec: withAliases(spec, model), options, layout: widget?.layout };
        if (widget) await api.put(`/workspaces/${ws.id}/dashboards/${dash.id}/widgets/${widget.id}`, body);
        else await api.post(`/workspaces/${ws.id}/dashboards/${dash.id}/widgets`, { ...body, layout: undefined });
      }
      onSaved();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open wide title={widget ? "Edit widget" : "Add widget"} onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={save} loading={busy}>Save widget</Button></>}>
      {!widget && <Tabs value={tab} onChange={setTab} tabs={[{ id: "build", label: "Build" }, { id: "report", label: "From saved report" }]} />}
      <div className="mt-3 grid gap-3">
        <div className="grid grid-cols-2 gap-3">
          <div><Label>Title</Label><input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} /></div>
          {tab === "build" && <div><Label>Visualization</Label><Select value={chart} onChange={setChart} options={CHART_TYPES.map((c) => ({ value: c.id, label: c.label }))} /></div>}
        </div>
        {tab === "report" ? (
          <Select value={reportId} onChange={setReportId} placeholder="Choose a report…" options={(reports.data || []).map((r) => ({ value: String(r.id), label: `${r.name} (${r.chart_type})` }))} />
        ) : (
          <div className="grid gap-3 md:grid-cols-[220px_1fr]">
            <div className="h-[420px]"><FieldList model={model} spec={spec} onAdd={(s, p) => setSpec(addToSpec(spec, model, s, p))} /></div>
            <div className="max-h-[420px] overflow-y-auto pr-1"><SpecShelves model={model} spec={withAliases(spec, model)} onChange={setSpec} /></div>
          </div>
        )}
        <div><Label hint="comma-separated fields, e.g. products.category,products.product_name">Drill-down path</Label>
          <input className={inputCls} value={drillPath} onChange={(e) => setDrillPath(e.target.value)} list="field-refs" />
          <datalist id="field-refs">{fieldOptions(model).map((o) => <option key={o.value} value={o.value} />)}</datalist>
        </div>
      </div>
    </Modal>
  );
}

function FiltersEditor({ dash, onClose, onSaved }: { dash: Dashboard; onClose: () => void; onSaved: () => void }) {
  const { ws, model } = useWs();
  const toast = useToast();
  const [filters, setFilters] = useState<DashFilter[]>(dash.filters);
  const save = async () => {
    try {
      await api.put(`/workspaces/${ws.id}/dashboards/${dash.id}`, { name: dash.name, description: dash.description, is_template: dash.is_template, filters });
      onSaved();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const fm = fieldMap(model);
  return (
    <Modal open title="Dashboard filters" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={save}>Save</Button></>}>
      <p className="mb-3 text-xs text-slate-500">Filters apply to every widget whose data is related to the chosen field. Date filters use each widget's own date column unless you pick one.</p>
      <div className="grid gap-2">
        {filters.map((f, i) => (
          <div key={f.id} className="flex items-center gap-2 rounded-md border border-slate-200 p-2">
            <Badge tone={f.type === "date_range" ? "amber" : "blue"}>{f.type === "date_range" ? "date" : "values"}</Badge>
            <input className={inputCls} value={f.label} onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
            <span className="w-48 truncate text-xs text-slate-500">{f.field === "@time" ? "each widget's date" : fm.get(f.field)?.label || f.field}</span>
            <button onClick={() => setFilters(filters.filter((_, j) => j !== i))} className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
          </div>
        ))}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button size="sm" onClick={() => setFilters([...filters, { id: `d${Date.now()}`, type: "date_range", label: "Date range", field: "@time", value: null }])}><Plus className="h-3 w-3" /> Date range filter</Button>
        <Select value="" placeholder="+ Values filter on…" onChange={(v) => v && setFilters([...filters, { id: `v${Date.now()}`, type: "values", label: fm.get(v)?.label || v, field: v, value: [] }])}
          options={fieldOptions(model, (f) => f.type === "text")} />
      </div>
    </Modal>
  );
}
