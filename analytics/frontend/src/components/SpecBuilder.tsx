import { useMemo, useState } from "react";
import { CalendarRange, ChevronDown, ChevronRight, Database, Filter as FilterIcon, GripVertical, Hash, Plus, Sigma, Type, X } from "lucide-react";
import type { Field, Model, QuerySpec, SpecFilter } from "../api/client";
import { PRESET_LABELS } from "../lib/format";
import { cx, inputCls, Label, Select } from "./ui";

export const AGGS = [
  { value: "sum", label: "Sum" }, { value: "avg", label: "Average" }, { value: "count", label: "Count" },
  { value: "count_distinct", label: "Distinct count" }, { value: "min", label: "Min" }, { value: "max", label: "Max" }, { value: "median", label: "Median" },
];
export const GRAINS = ["day", "week", "month", "quarter", "year"];
export const OPS = [
  { value: "in", label: "is any of" }, { value: "not_in", label: "is none of" }, { value: "eq", label: "=" }, { value: "neq", label: "≠" },
  { value: "gt", label: ">" }, { value: "gte", label: "≥" }, { value: "lt", label: "<" }, { value: "lte", label: "≤" },
  { value: "between", label: "between" }, { value: "contains", label: "contains" }, { value: "not_contains", label: "does not contain" },
  { value: "is_null", label: "is empty" }, { value: "not_null", label: "is not empty" },
];

export function fieldMap(model: Model) {
  const m = new Map<string, Field & { dataset: string; datasetSlug: string }>();
  model.datasets.forEach((d) => d.fields.forEach((f) => m.set(f.ref, { ...f, dataset: d.name, datasetSlug: d.slug })));
  return m;
}

export function fieldOptions(model: Model, filter?: (f: Field) => boolean) {
  return model.datasets.flatMap((d) => d.fields.filter((f) => !filter || filter(f)).map((f) => ({ value: f.ref, label: f.label, group: d.name })));
}

/** Datasets reachable from the measures' base datasets (base + lookups), for relevance hints. */
export function reachable(model: Model, spec: QuerySpec): Set<string> | null {
  const bases = new Set<string>();
  spec.measures.forEach((m) => {
    if (m.field) bases.add(m.field.split(".")[0]);
    if (m.metric) {
      const mt = model.metrics.find((x) => x.name === m.metric);
      const collect = (name: string, depth = 0) => {
        const x = model.metrics.find((y) => y.name === name);
        if (!x || depth > 4) return;
        if (x.kind === "composite") (x.expression.match(/\{([a-z_][a-z0-9_]*)\}/g) || []).forEach((t) => collect(t.slice(1, -1), depth + 1));
        else if (x.dataset_id) {
          const d = model.datasets.find((dd) => dd.id === x.dataset_id);
          if (d) bases.add(d.slug);
        }
      };
      if (mt) collect(mt.name);
    }
  });
  if (!bases.size) return null;
  const out = new Set<string>();
  bases.forEach((b) => {
    out.add(b);
    model.datasets.find((d) => d.slug === b)?.lookups.forEach((l) => out.add(l));
  });
  return out;
}

function FieldIcon({ f }: { f: Field }) {
  if (f.type === "date" || f.type === "datetime") return <CalendarRange className="h-3.5 w-3.5 text-amber-600" />;
  if (f.role === "measure") return <Hash className="h-3.5 w-3.5 text-teal-600" />;
  return <Type className="h-3.5 w-3.5 text-brand-500" />;
}

export function FieldList({ model, spec, onAdd }: { model: Model; spec: QuerySpec; onAdd: (shelf: "dimensions" | "measures" | "filters", payload: string) => void }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [q, setQ] = useState("");
  const reach = reachable(model, spec);
  const ql = q.toLowerCase();
  return (
    <div className="flex h-full flex-col">
      <input className={cx(inputCls, "mb-2")} placeholder="Search fields & metrics…" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="min-h-0 flex-1 overflow-y-auto pr-1 text-sm">
        {model.metrics.length > 0 && (
          <div className="mb-2">
            <div className="mb-1 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500"><Sigma className="h-3 w-3" /> Metrics</div>
            {model.metrics.filter((m) => !ql || m.label.toLowerCase().includes(ql) || m.name.includes(ql)).map((m) => (
              <div key={m.name} draggable onDragStart={(e) => e.dataTransfer.setData("text/ellementry", `metric:${m.name}`)}
                onDoubleClick={() => onAdd("measures", `metric:${m.name}`)} title={m.description || m.expression}
                className="group flex cursor-grab items-center gap-1.5 rounded px-1.5 py-1 hover:bg-violet-50">
                <Sigma className="h-3.5 w-3.5 text-violet-600" />
                <span className="flex-1 truncate">{m.label}</span>
                <button className="hidden text-slate-400 hover:text-violet-700 group-hover:block" onClick={() => onAdd("measures", `metric:${m.name}`)} title="Add as measure"><Plus className="h-3.5 w-3.5" /></button>
              </div>
            ))}
          </div>
        )}
        {model.datasets.map((d) => {
          const fields = d.fields.filter((f) => !ql || f.label.toLowerCase().includes(ql) || d.name.toLowerCase().includes(ql));
          if (!fields.length) return null;
          const isOpen = open[d.slug] ?? !!ql;
          const dim = reach && !reach.has(d.slug);
          return (
            <div key={d.slug} className={cx("mb-1", dim && "opacity-50")}>
              <button className="flex w-full items-center gap-1 rounded px-1 py-1 text-left font-medium text-slate-700 hover:bg-slate-100" onClick={() => setOpen({ ...open, [d.slug]: !isOpen })}>
                {isOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                <Database className="h-3.5 w-3.5 text-slate-400" /> <span className="truncate">{d.name}</span>
                {dim && <span className="ml-auto text-[10px] font-normal text-slate-400">not related</span>}
              </button>
              {isOpen && fields.map((f) => (
                <div key={f.ref} draggable onDragStart={(e) => e.dataTransfer.setData("text/ellementry", `field:${f.ref}`)}
                  onDoubleClick={() => onAdd(f.role === "measure" ? "measures" : "dimensions", `field:${f.ref}`)}
                  className="group ml-4 flex cursor-grab items-center gap-1.5 rounded px-1.5 py-0.5 hover:bg-slate-100">
                  <GripVertical className="h-3 w-3 text-slate-300" /><FieldIcon f={f} />
                  <span className="flex-1 truncate">{f.label}</span>
                  <span className="hidden gap-0.5 group-hover:flex">
                    <button title="Add as dimension" onClick={() => onAdd("dimensions", `field:${f.ref}`)} className="rounded px-1 text-[10px] text-brand-600 hover:bg-brand-100">D</button>
                    <button title="Add as measure" onClick={() => onAdd("measures", `field:${f.ref}`)} className="rounded px-1 text-[10px] text-teal-700 hover:bg-teal-100">M</button>
                    <button title="Add as filter" onClick={() => onAdd("filters", `field:${f.ref}`)} className="rounded px-1 text-[10px] text-slate-600 hover:bg-slate-200">F</button>
                  </span>
                </div>
              ))}
            </div>
          );
        })}
      </div>
      <div className="mt-2 text-[11px] text-slate-400">Drag fields onto the shelves, or double-click.</div>
    </div>
  );
}

export function addToSpec(spec: QuerySpec, model: Model, shelf: "dimensions" | "measures" | "filters", payload: string): QuerySpec {
  const [kind, value] = [payload.slice(0, payload.indexOf(":")), payload.slice(payload.indexOf(":") + 1)];
  const fm = fieldMap(model);
  const s: QuerySpec = JSON.parse(JSON.stringify(spec));
  if (kind === "metric") {
    if (!s.measures.some((m) => m.metric === value)) s.measures.push({ metric: value });
    return s;
  }
  const f = fm.get(value);
  if (!f) return s;
  if (shelf === "measures") {
    const agg = f.role === "measure" ? "sum" : f.type === "text" ? "count_distinct" : "count";
    s.measures.push({ field: value, agg });
  } else if (shelf === "dimensions") {
    if (!s.dimensions.some((d) => d.field === value)) s.dimensions.push({ field: value, grain: f.type === "date" || f.type === "datetime" ? "month" : null });
  } else {
    s.filters.push({ field: value, op: f.type === "text" ? "in" : f.type === "date" || f.type === "datetime" ? "between" : "gte", value: f.type === "text" ? [] : f.type === "date" ? ["", ""] : "" });
  }
  return s;
}

function Shelf({ title, icon, onDrop, children, empty }: { title: string; icon: React.ReactNode; onDrop: (p: string) => void; children: React.ReactNode; empty: string }) {
  const [over, setOver] = useState(false);
  return (
    <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const p = e.dataTransfer.getData("text/ellementry"); if (p) onDrop(p); }}
      className={cx("rounded-md border border-dashed p-2 transition", over ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-slate-50/50")}>
      <div className="mb-1.5 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{icon}{title}</div>
      <div className="flex flex-col gap-1.5">{children}</div>
      {!Array.isArray(children) || (children as any[]).length === 0 ? <div className="py-1 text-xs text-slate-400">{empty}</div> : null}
    </div>
  );
}

function Pill({ children, onRemove, tone }: { children: React.ReactNode; onRemove: () => void; tone: string }) {
  return (
    <div className={cx("flex items-center gap-1.5 rounded border bg-white px-1.5 py-1 text-xs shadow-sm", tone)}>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">{children}</div>
      <button onClick={onRemove} className="text-slate-400 hover:text-red-600" aria-label="Remove"><X className="h-3.5 w-3.5" /></button>
    </div>
  );
}

const mini = "rounded border border-slate-200 bg-white px-1 py-0.5 text-xs";

export function FilterValueInput({ f, type, onChange }: { f: SpecFilter; type?: string; onChange: (v: any) => void }) {
  if (f.op === "is_null" || f.op === "not_null") return null;
  if (f.op === "in" || f.op === "not_in") {
    const v = Array.isArray(f.value) ? f.value.join(", ") : f.value ?? "";
    return <input className={cx(mini, "min-w-0 flex-1")} placeholder="values, comma separated" defaultValue={v}
      onBlur={(e) => onChange(e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} />;
  }
  if (f.op === "between") {
    const [a, b] = Array.isArray(f.value) ? f.value : ["", ""];
    const t = type === "date" || type === "datetime" ? "date" : "number";
    return (
      <span className="flex items-center gap-1">
        <input type={t} className={cx(mini, "w-28")} value={a ?? ""} onChange={(e) => onChange([e.target.value, b])} />–
        <input type={t} className={cx(mini, "w-28")} value={b ?? ""} onChange={(e) => onChange([a, e.target.value])} />
      </span>
    );
  }
  return <input className={cx(mini, "min-w-0 flex-1")} type={type === "integer" || type === "decimal" ? "number" : type === "date" ? "date" : "text"}
    defaultValue={f.value ?? ""} onBlur={(e) => onChange(e.target.value)} />;
}

export function DateRangePicker({ value, onChange, presets }: { value: any; onChange: (v: any) => void; presets: string[] }) {
  const mode = !value ? "" : typeof value === "string" ? value : value.preset ? value.preset : "custom";
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <select className={cx(inputCls, "w-auto")} value={mode} onChange={(e) => {
        const v = e.target.value;
        onChange(v === "" ? null : v === "custom" ? { from: "", to: "" } : v);
      }}>
        <option value="">All time</option>
        {presets.filter((p) => p !== "all_time").map((p) => <option key={p} value={p}>{PRESET_LABELS[p] || p}</option>)}
        <option value="custom">Custom range…</option>
      </select>
      {mode === "custom" && (
        <>
          <input type="date" className={cx(inputCls, "w-36")} value={value.from || ""} onChange={(e) => onChange({ ...value, from: e.target.value })} />
          <span className="text-slate-400">→</span>
          <input type="date" className={cx(inputCls, "w-36")} value={value.to || ""} onChange={(e) => onChange({ ...value, to: e.target.value })} />
        </>
      )}
    </div>
  );
}

export function SpecShelves({ model, spec, onChange }: { model: Model; spec: QuerySpec; onChange: (s: QuerySpec) => void }) {
  const fm = useMemo(() => fieldMap(model), [model]);
  const set = (patch: Partial<QuerySpec>) => onChange({ ...spec, ...patch });
  const drop = (shelf: "dimensions" | "measures" | "filters") => (p: string) => onChange(addToSpec(spec, model, shelf, p));
  const outputs = [
    ...spec.dimensions.map((d) => ({ value: d.alias || "", label: d.label || fm.get(d.field)?.label || d.field })),
    ...spec.measures.map((m) => ({ value: m.alias || "", label: m.label || (m.metric ? model.metrics.find((x) => x.name === m.metric)?.label : fm.get(m.field || "")?.label) || "" })),
  ];
  return (
    <div className="grid gap-3">
      <Shelf title="Dimensions (group by)" icon={<Type className="h-3 w-3" />} onDrop={drop("dimensions")} empty="Drop a field to group by (rows / x-axis / series)">
        {spec.dimensions.map((d, i) => {
          const f = fm.get(d.field);
          const isDate = d.field === "@time" || f?.type === "date" || f?.type === "datetime";
          return (
            <Pill key={i} tone="border-brand-200" onRemove={() => set({ dimensions: spec.dimensions.filter((_, j) => j !== i) })}>
              <span className="font-medium text-brand-800">{d.field === "@time" ? "Date (each measure's own)" : f?.label || d.field}</span>
              <span className="text-slate-400">{f?.dataset}</span>
              {isDate && (
                <select className={mini} value={d.grain || ""} onChange={(e) => set({ dimensions: spec.dimensions.map((x, j) => j === i ? { ...x, grain: e.target.value || null } : x) })}>
                  {d.field !== "@time" && <option value="">exact</option>}
                  {GRAINS.map((g) => <option key={g} value={g}>by {g}</option>)}
                </select>
              )}
            </Pill>
          );
        })}
      </Shelf>
      {!spec.dimensions.some((d) => d.field === "@time") && spec.measures.length > 0 && (
        <button className="-mt-2 self-start text-xs text-brand-600 hover:underline" onClick={() => set({ dimensions: [{ field: "@time", grain: "month" }, ...spec.dimensions] })}>
          + Group by date (uses each measure's date column)
        </button>
      )}
      <Shelf title="Measures" icon={<Hash className="h-3 w-3" />} onDrop={drop("measures")} empty="Drop a metric or numeric field">
        {spec.measures.map((m, i) => {
          const mt = m.metric ? model.metrics.find((x) => x.name === m.metric) : null;
          const f = m.field ? fm.get(m.field) : null;
          return (
            <Pill key={i} tone={mt ? "border-violet-200" : "border-teal-200"} onRemove={() => set({ measures: spec.measures.filter((_, j) => j !== i) })}>
              {mt ? <><Sigma className="h-3 w-3 text-violet-600" /><span className="font-medium text-violet-800">{mt.label}</span></> : (
                <>
                  <select className={mini} value={m.agg || "sum"} onChange={(e) => set({ measures: spec.measures.map((x, j) => j === i ? { ...x, agg: e.target.value } : x) })}>
                    {AGGS.filter((a) => f?.role === "measure" || !["sum", "avg", "median"].includes(a.value)).map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
                  </select>
                  <span className="font-medium text-teal-800">{m.field?.endsWith(".*") ? "Rows" : f?.label || m.field}</span>
                  <span className="text-slate-400">{f?.dataset}</span>
                </>
              )}
            </Pill>
          );
        })}
      </Shelf>
      <Shelf title="Filters" icon={<FilterIcon className="h-3 w-3" />} onDrop={drop("filters")} empty="Drop a field to filter">
        {spec.filters.map((flt, i) => {
          const f = fm.get(flt.field);
          const upd = (patch: Partial<SpecFilter>) => set({ filters: spec.filters.map((x, j) => j === i ? { ...x, ...patch } : x) });
          return (
            <Pill key={i} tone="border-slate-300" onRemove={() => set({ filters: spec.filters.filter((_, j) => j !== i) })}>
              <span className="font-medium">{f?.label || flt.field}</span>
              <select className={mini} value={flt.op} onChange={(e) => upd({ op: e.target.value, value: ["in", "not_in"].includes(e.target.value) ? [] : e.target.value === "between" ? ["", ""] : "" })}>
                {OPS.filter((o) => f?.type === "text" ? !["gt", "gte", "lt", "lte", "between"].includes(o.value) : !["contains", "not_contains"].includes(o.value)).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <FilterValueInput f={flt} type={f?.type} onChange={(v) => upd({ value: v })} />
            </Pill>
          );
        })}
      </Shelf>
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <Label>Date range</Label>
          <DateRangePicker value={spec.time_range} presets={model.date_presets} onChange={(v) => set({ time_range: v })} />
        </div>
        <div>
          <Label hint="(optional)">Date column for range</Label>
          <Select value={spec.time_field || ""} onChange={(v) => set({ time_field: v || null })} placeholder="Each dataset's default"
            options={fieldOptions(model, (f) => f.type === "date" || f.type === "datetime")} />
        </div>
        <div>
          <Label>Compare with</Label>
          <Select value={spec.compare || ""} onChange={(v) => set({ compare: (v || null) as any })} placeholder="No comparison"
            options={[{ value: "previous_period", label: "Previous period" }, { value: "previous_year", label: "Same period last year" }]} />
        </div>
        <div>
          <Label>Sort by</Label>
          <div className="flex gap-1">
            <Select value={spec.sort[0]?.field || ""} placeholder="Default" onChange={(v) => set({ sort: v ? [{ field: v, dir: spec.sort[0]?.dir || "desc" }] : [] })}
              options={outputs.filter((o) => o.value).map((o) => ({ value: o.value, label: o.label }))} />
            <Select className="w-24" value={spec.sort[0]?.dir || "desc"} onChange={(v) => spec.sort[0] && set({ sort: [{ ...spec.sort[0], dir: v as any }] })}
              options={[{ value: "desc", label: "Desc" }, { value: "asc", label: "Asc" }]} />
          </div>
        </div>
        <div>
          <Label>Limit rows</Label>
          <input type="number" min={1} className={inputCls} value={spec.limit ?? ""} placeholder="All" onChange={(e) => set({ limit: e.target.value ? Number(e.target.value) : null })} />
        </div>
        <label className="col-span-2 flex items-center gap-2 text-xs text-slate-600">
          <input type="checkbox" checked={spec.apply_rules !== false} onChange={(e) => set({ apply_rules: e.target.checked })} />
          Apply dataset business rules
        </label>
      </div>
    </div>
  );
}

/** Give every dimension/measure a stable alias so sort settings can reference outputs. */
export function withAliases(spec: QuerySpec, model: Model): QuerySpec {
  const used = new Set<string>();
  const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40) || "c";
  const uniq = (b: string) => {
    let a = slug(b), i = 2;
    while (used.has(a)) a = `${slug(b)}_${i++}`;
    used.add(a);
    return a;
  };
  return {
    ...spec,
    dimensions: spec.dimensions.map((d) => ({ ...d, alias: uniq(d.alias || `${d.field === "@time" ? "period" : d.field.split(".")[1]}${d.grain ? "_" + d.grain : ""}`) })),
    measures: spec.measures.map((m) => ({ ...m, alias: uniq(m.alias || (m.metric ? m.metric : `${(m.field || "").replace(".*", "_rows").split(".").pop()}_${m.agg}`)) })),
  };
}
