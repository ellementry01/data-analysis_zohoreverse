import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ChevronLeft, ChevronRight, Download, Plus, RefreshCw, Trash2, Wand2 } from "lucide-react";
import { api, Column, Dataset, DataType } from "../api/client";
import { Badge, Button, Card, cx, ErrorBox, inputCls, Label, PageHeader, Select, Spinner, Tabs, useAsync, useToast } from "../components/ui";
import { fmtCell, fmtNumber, timeAgo, TYPE_ICON } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

const TYPES: DataType[] = ["text", "integer", "decimal", "date", "datetime", "boolean"];

export default function DatasetPage() {
  const { dsId } = useParams();
  const { ws, base, canEdit, reloadModel } = useWs();
  const q = useAsync(() => api.get<Dataset>(`/workspaces/${ws.id}/datasets/${dsId}`), [ws.id, dsId]);
  const [tab, setTab] = useState("data");
  const ds = q.data;
  const refresh = (d?: Dataset) => {
    if (d) q.setData(d);
    else q.reload();
    reloadModel();
  };
  if (q.error) return <ErrorBox error={q.error} />;
  if (!ds) return <Spinner />;
  const warnings = ds.quality?.warnings || [];
  return (
    <div>
      <Link to={`${base}/data`} className="mb-2 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-brand-700"><ArrowLeft className="h-3 w-3" /> Datasets</Link>
      <PageHeader title={<span className="flex items-center gap-2">{ds.name} <Badge tone={ds.kind === "file" ? "slate" : "violet"}>{ds.kind.replace("_", " ")}</Badge></span>}
        subtitle={`${ds.row_count.toLocaleString("en-IN")} rows · ${ds.columns.length} columns · table "${ds.slug}" · refreshed ${timeAgo(ds.last_refreshed_at)}`}
        actions={<>
          <Button size="sm" onClick={() => api.download(`/workspaces/${ws.id}/datasets/${ds.id}/export?format=csv`, undefined, `${ds.slug}.csv`)}><Download className="h-3.5 w-3.5" /> CSV</Button>
          <Button size="sm" onClick={() => api.download(`/workspaces/${ws.id}/datasets/${ds.id}/export?format=xlsx`, undefined, `${ds.slug}.xlsx`)}><Download className="h-3.5 w-3.5" /> Excel</Button>
        </>} />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "data", label: "Data" }, { id: "columns", label: "Columns" },
        ...(ds.kind !== "query_table" ? [{ id: "prepare", label: `Prepare (${ds.transforms.length})` }] : []),
        { id: "profile", label: "Profile" },
        ...(ds.kind !== "query_table" ? [{ id: "quality", label: <span>Quality {warnings.length > 0 && <Badge tone="amber">{warnings.length}</Badge>}</span> }] : []),
        { id: "settings", label: "Settings" },
      ]} />
      <div className="mt-4">
        {tab === "data" && <RowsTab ds={ds} />}
        {tab === "columns" && <ColumnsTab ds={ds} canEdit={canEdit} onChange={refresh} />}
        {tab === "prepare" && <PrepareTab ds={ds} canEdit={canEdit} onChange={refresh} />}
        {tab === "profile" && <ProfileTab ds={ds} />}
        {tab === "quality" && <QualityTab ds={ds} canEdit={canEdit} onChange={refresh} />}
        {tab === "settings" && <SettingsTab ds={ds} canEdit={canEdit} onChange={refresh} />}
      </div>
    </div>
  );
}

function RowsTab({ ds }: { ds: Dataset }) {
  const { ws } = useWs();
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [sort, setSort] = useState<{ col: string; desc: boolean } | null>(null);
  const q = useAsync(() => api.get<{ total: number; rows: any[][]; columns: string[]; page_size: number }>(
    `/workspaces/${ws.id}/datasets/${ds.id}/rows?page=${page}&page_size=100${term ? `&search=${encodeURIComponent(term)}` : ""}${sort ? `&sort=${sort.col}&desc=${sort.desc}` : ""}`), [ds.id, page, term, sort?.col, sort?.desc]);
  const cols = ds.columns;
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;
  return (
    <Card bodyClass="p-0">
      <div className="flex items-center justify-between gap-2 border-b border-slate-100 p-2">
        <form onSubmit={(e) => { e.preventDefault(); setPage(0); setTerm(search); }} className="flex gap-2">
          <input className={inputCls + " w-72"} placeholder="Search all columns…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <Button size="sm" type="submit">Search</Button>
        </form>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          {q.data && <span>{q.data.total.toLocaleString("en-IN")} rows</span>}
          <Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage(page - 1)}><ChevronLeft className="h-4 w-4" /></Button>
          <span>Page {page + 1} / {pages}</span>
          <Button size="sm" variant="ghost" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}><ChevronRight className="h-4 w-4" /></Button>
        </div>
      </div>
      <ErrorBox error={q.error} />
      <div className="max-h-[65vh] overflow-auto">
        <table className="min-w-full text-xs">
          <thead className="sticky top-0 bg-slate-50">
            <tr>
              {cols.map((c) => (
                <th key={c.name} onClick={() => setSort(sort?.col === c.name ? { col: c.name, desc: !sort.desc } : { col: c.name, desc: false })}
                  className="cursor-pointer whitespace-nowrap border-b border-slate-200 px-2.5 py-1.5 text-left font-semibold text-slate-600">
                  <span className="mr-1 text-[10px] text-slate-400">{TYPE_ICON[c.data_type]}</span>{c.display_name}{c.is_derived && <span className="ml-1 text-violet-500">ƒ</span>}
                  {sort?.col === c.name && (sort.desc ? " ↓" : " ↑")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className={cx(q.loading && "opacity-50")}>
            {q.data?.rows.map((r, i) => (
              <tr key={i} className="odd:bg-white even:bg-slate-50/50">
                {r.map((v, j) => (
                  <td key={j} className={cx("max-w-[280px] truncate whitespace-nowrap border-b border-slate-100 px-2.5 py-1", ["integer", "decimal"].includes(cols[j]?.data_type) && "text-right tabular-nums", v === null && "text-slate-300")}>
                    {v === null ? "∅" : fmtCell(v, cols[j]?.data_type)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ColumnsTab({ ds, canEdit, onChange }: { ds: Dataset; canEdit: boolean; onChange: (d?: Dataset) => void }) {
  const { ws } = useWs();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [form, setForm] = useState({ display_name: "", expression: "", data_type: "decimal" });
  const patch = async (c: Column, body: any) => {
    setBusy(c.name);
    try {
      onChange(await api.patch<Dataset>(`/workspaces/${ws.id}/datasets/${ds.id}/columns/${c.name}`, body));
      toast("success", body.data_type ? `Converted ${c.display_name} to ${body.data_type}` : "Saved");
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(null);
    }
  };
  const addDerived = async () => {
    setBusy("__new");
    try {
      onChange(await api.post<Dataset>(`/workspaces/${ws.id}/datasets/${ds.id}/columns`, form));
      setForm({ display_name: "", expression: "", data_type: "decimal" });
      toast("success", "Calculated column added");
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(null);
    }
  };
  const del = async (c: Column) => {
    if (!confirm(`Remove column "${c.display_name}"?${c.is_derived ? "" : " The data in it will be deleted."}`)) return;
    try {
      onChange(await api.del<Dataset>(`/workspaces/${ws.id}/datasets/${ds.id}/columns/${c.name}`));
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  return (
    <div className="grid gap-4">
      <Card bodyClass="p-0">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold text-slate-500">
            <tr><th className="px-3 py-2">Column (SQL name)</th><th className="px-3 py-2">Display name</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Description</th><th className="px-3 py-2">Hidden</th><th /></tr>
          </thead>
          <tbody>
            {ds.columns.map((c) => (
              <tr key={c.name} className={cx("border-t border-slate-100", busy === c.name && "opacity-50")}>
                <td className="px-3 py-1.5 font-mono text-xs text-slate-600">{c.name}{c.is_derived && <div className="max-w-xs truncate text-[10px] text-violet-600" title={c.expression || ""}>ƒ {c.expression}</div>}
                  {c.source_name && c.source_name !== c.display_name && <div className="text-[10px] text-slate-400">from "{c.source_name}"</div>}</td>
                <td className="px-3 py-1.5"><input className={inputCls} defaultValue={c.display_name} disabled={!canEdit} onBlur={(e) => e.target.value !== c.display_name && patch(c, { display_name: e.target.value })} /></td>
                <td className="px-3 py-1.5">
                  <select className={inputCls} value={c.data_type} disabled={!canEdit || c.is_derived || ds.kind === "query_table"}
                    onChange={(e) => confirm(`Convert "${c.display_name}" to ${e.target.value}? Values that cannot be converted become empty.`) && patch(c, { data_type: e.target.value })}>
                    {TYPES.map((t) => <option key={t}>{t}</option>)}
                  </select>
                </td>
                <td className="px-3 py-1.5"><input className={inputCls} defaultValue={c.description} disabled={!canEdit} placeholder="Helps people and the AI" onBlur={(e) => e.target.value !== c.description && patch(c, { description: e.target.value })} /></td>
                <td className="px-3 py-1.5 text-center"><input type="checkbox" checked={c.hidden} disabled={!canEdit} onChange={(e) => patch(c, { hidden: e.target.checked })} /></td>
                <td className="px-3 py-1.5">{canEdit && ds.kind !== "query_table" && <button onClick={() => del(c)} className="text-slate-400 hover:text-red-600" title="Remove column"><Trash2 className="h-4 w-4" /></button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {canEdit && ds.kind !== "query_table" && (
        <Card title="Add calculated column">
          <div className="grid gap-3 md:grid-cols-[1fr_2fr_140px_auto] md:items-end">
            <div><Label>Name</Label><input className={inputCls} value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} placeholder="Gross margin" /></div>
            <div><Label hint="SQL expression over this dataset's columns">Formula</Label><input className={inputCls + " font-mono"} value={form.expression} onChange={(e) => setForm({ ...form, expression: e.target.value })}
              placeholder={`e.g. ${ds.columns.filter((c) => ["integer", "decimal"].includes(c.data_type)).slice(0, 2).map((c) => c.name).join(" * ") || "CASE WHEN ... THEN ... END"}`} /></div>
            <div><Label>Type</Label><select className={inputCls} value={form.data_type} onChange={(e) => setForm({ ...form, data_type: e.target.value })}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select></div>
            <Button variant="primary" onClick={addDerived} loading={busy === "__new"} disabled={!form.display_name || !form.expression}><Plus className="h-4 w-4" /> Add</Button>
          </div>
          <p className="mt-2 text-xs text-slate-500">Supports + − × ÷, CASE WHEN, COALESCE, ROUND, LOWER/UPPER/TRIM, DATE_TRUNC, EXTRACT and more. Calculated columns are computed live, so they stay correct after refreshes.</p>
        </Card>
      )}
    </div>
  );
}

const TRANSFORM_HELP: Record<string, string> = {
  trim_whitespace: "Trim spaces in all text columns (or the selected one)", change_case: "Convert text case", replace_values: "Find & replace",
  fill_nulls: "Fill empty values", remove_duplicates: "Remove duplicate rows", delete_rows: "Delete rows matching a condition",
  standardize_values: "Map spelling variants to one value", cast_type: "Change column type", drop_column: "Remove a column",
};

function PrepareTab({ ds, canEdit, onChange }: { ds: Dataset; canEdit: boolean; onChange: (d?: Dataset) => void }) {
  const { ws } = useWs();
  const toast = useToast();
  const [kind, setKind] = useState("trim_whitespace");
  const [p, setP] = useState<any>({});
  const [busy, setBusy] = useState(false);
  const cols = ds.columns.filter((c) => !c.is_derived);
  useEffect(() => {
    setP({});
  }, [kind]);
  const run = async () => {
    setBusy(true);
    try {
      const params = { ...p };
      if (kind === "standardize_values") params.mapping = { [p.target]: String(p.variants || "").split(",").map((s: string) => s.trim()).filter(Boolean) };
      if (kind === "delete_rows") params.filters = [{ column: p.column, op: p.op || "eq", value: p.value }];
      if (kind === "remove_duplicates" && p.column) params.columns = [p.column];
      if (kind === "trim_whitespace" && p.column) params.columns = [p.column];
      delete params.target; delete params.variants;
      if (kind === "delete_rows") { delete params.column; delete params.op; delete params.value; }
      if (kind === "remove_duplicates" || kind === "trim_whitespace") delete params.column;
      const r = await api.post<{ message: string; dataset: Dataset }>(`/workspaces/${ws.id}/datasets/${ds.id}/transforms`, { kind, params });
      toast("success", r.message);
      onChange(r.dataset);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  const removeStep = async (id: number) => {
    try {
      onChange(await api.del<Dataset>(`/workspaces/${ws.id}/datasets/${ds.id}/transforms/${id}`));
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const colSel = (key = "column", optional = false) => (
    <div><Label>Column</Label><Select value={p[key] || ""} onChange={(v) => setP({ ...p, [key]: v })} placeholder={optional ? "All columns" : "Choose…"} options={cols.map((c) => ({ value: c.name, label: c.display_name }))} /></div>
  );
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
      <Card title="Preparation recipe" actions={<span className="text-xs text-slate-400">Steps re-run automatically after every refresh or replace</span>}>
        {!ds.transforms.length && <div className="text-sm text-slate-400">No steps yet.</div>}
        <ol className="grid gap-2">
          {ds.transforms.map((t, i) => (
            <li key={t.id} className="flex items-start gap-3 rounded-md border border-slate-200 p-2.5 text-sm">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-100 text-[11px] font-semibold text-brand-700">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="font-medium text-slate-800">{TRANSFORM_HELP[t.kind] || t.kind}</div>
                <div className="truncate font-mono text-[11px] text-slate-500">{JSON.stringify(t.params)}</div>
                <div className={cx("text-xs", t.last_result.startsWith("failed") ? "text-red-600" : "text-emerald-700")}>{t.last_result}</div>
              </div>
              {canEdit && <button onClick={() => removeStep(t.id)} className="text-slate-400 hover:text-red-600" title="Remove from recipe"><Trash2 className="h-4 w-4" /></button>}
            </li>
          ))}
        </ol>
      </Card>
      {canEdit && (
        <Card title="Add a step">
          <div className="grid gap-3">
            <div><Label>Operation</Label><Select value={kind} onChange={setKind} options={Object.entries(TRANSFORM_HELP).map(([k, v]) => ({ value: k, label: v }))} /></div>
            {kind === "trim_whitespace" && colSel("column", true)}
            {kind === "change_case" && <>{colSel()}<div><Label>Case</Label><Select value={p.mode || "title"} onChange={(v) => setP({ ...p, mode: v })} options={[{ value: "title", label: "Title Case" }, { value: "upper", label: "UPPER" }, { value: "lower", label: "lower" }]} /></div></>}
            {kind === "replace_values" && <>{colSel()}<div><Label>Find</Label><input className={inputCls} value={p.find || ""} onChange={(e) => setP({ ...p, find: e.target.value })} /></div>
              <div><Label>Replace with</Label><input className={inputCls} value={p.replace || ""} onChange={(e) => setP({ ...p, replace: e.target.value })} /></div>
              <div><Label>Match</Label><Select value={p.match || "exact"} onChange={(v) => setP({ ...p, match: v })} options={[{ value: "exact", label: "Whole value" }, { value: "contains", label: "Part of text" }]} /></div></>}
            {kind === "fill_nulls" && <>{colSel()}<div><Label>Value</Label><input className={inputCls} value={p.value || ""} onChange={(e) => setP({ ...p, value: e.target.value })} /></div></>}
            {kind === "remove_duplicates" && colSel("column", true)}
            {kind === "delete_rows" && <>{colSel()}<div className="grid grid-cols-2 gap-2"><Select value={p.op || "eq"} onChange={(v) => setP({ ...p, op: v })} options={[{ value: "eq", label: "=" }, { value: "neq", label: "≠" }, { value: "lt", label: "<" }, { value: "gt", label: ">" }, { value: "is_null", label: "is empty" }, { value: "contains", label: "contains" }]} />
              <input className={inputCls} value={p.value || ""} onChange={(e) => setP({ ...p, value: e.target.value })} placeholder="value" /></div></>}
            {kind === "standardize_values" && <>{colSel()}<div><Label>Correct value</Label><input className={inputCls} value={p.target || ""} onChange={(e) => setP({ ...p, target: e.target.value })} placeholder="Amazon" /></div>
              <div><Label hint="comma separated, case-insensitive">Variants</Label><input className={inputCls} value={p.variants || ""} onChange={(e) => setP({ ...p, variants: e.target.value })} placeholder="amazon, Amazon.in, AMZN" /></div></>}
            {kind === "cast_type" && <>{colSel()}<div><Label>New type</Label><Select value={p.to || ""} onChange={(v) => setP({ ...p, to: v })} placeholder="Choose…" options={TYPES.map((t) => ({ value: t, label: t }))} /></div></>}
            {kind === "drop_column" && colSel()}
            <Button variant="primary" onClick={run} loading={busy}><Wand2 className="h-4 w-4" /> Apply step</Button>
          </div>
        </Card>
      )}
    </div>
  );
}

function ProfileTab({ ds }: { ds: Dataset }) {
  const { ws } = useWs();
  const q = useAsync(() => api.get<{ row_count: number; columns: any[] }>(`/workspaces/${ws.id}/datasets/${ds.id}/profile`), [ds.id]);
  if (q.loading) return <Spinner label="Profiling…" />;
  if (q.error) return <ErrorBox error={q.error} />;
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {q.data!.columns.map((c) => {
        const maxTop = Math.max(...c.top_values.map((t: any) => t.count), 1);
        const maxH = Math.max(...(c.histogram || []).map((h: any) => h.count), 1);
        return (
          <Card key={c.name} title={<span>{c.label} <span className="text-xs font-normal text-slate-400">{c.type}</span></span>}>
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div><div className="text-slate-400">Distinct</div><div className="font-semibold">{c.distinct.toLocaleString("en-IN")}</div></div>
              <div><div className="text-slate-400">Empty</div><div className={cx("font-semibold", c.null_pct > 0.2 && "text-amber-600")}>{(c.null_pct * 100).toFixed(1)}%</div></div>
              {c.mean !== undefined && <div><div className="text-slate-400">Mean</div><div className="font-semibold">{fmtNumber(c.mean)}</div></div>}
              {c.min !== undefined && <div><div className="text-slate-400">Min</div><div className="font-semibold">{typeof c.min === "number" ? fmtNumber(c.min) : c.min}</div></div>}
              {c.max !== undefined && <div><div className="text-slate-400">Max</div><div className="font-semibold">{typeof c.max === "number" ? fmtNumber(c.max) : c.max}</div></div>}
              {c.median !== undefined && <div><div className="text-slate-400">Median</div><div className="font-semibold">{fmtNumber(c.median)}</div></div>}
            </div>
            {c.histogram && (
              <div className="mt-3 flex h-12 items-end gap-0.5">
                {c.histogram.map((h: any) => <div key={h.bucket} className="flex-1 rounded-t bg-teal-400/70" style={{ height: `${(h.count / maxH) * 100}%` }} title={`${h.count}`} />)}
              </div>
            )}
            {!c.histogram && c.top_values.length > 0 && (
              <div className="mt-3 grid gap-1">
                {c.top_values.slice(0, 5).map((t: any) => (
                  <div key={t.value} className="flex items-center gap-2 text-xs">
                    <div className="w-28 truncate text-slate-600" title={t.value}>{t.value}</div>
                    <div className="h-2 flex-1 rounded bg-slate-100"><div className="h-2 rounded bg-brand-400" style={{ width: `${(t.count / maxTop) * 100}%` }} /></div>
                    <div className="w-12 text-right tabular-nums text-slate-500">{t.count}</div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}

function QualityTab({ ds, canEdit, onChange }: { ds: Dataset; canEdit: boolean; onChange: (d?: Dataset) => void }) {
  const { ws } = useWs();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const warnings = ds.quality?.warnings || [];
  const fix = async (kind: string, params: any) => {
    setBusy(true);
    try {
      const r = await api.post<{ message: string; dataset: Dataset }>(`/workspaces/${ws.id}/datasets/${ds.id}/transforms`, { kind, params });
      toast("success", r.message);
      onChange(r.dataset);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  const recheck = async () => {
    await api.post(`/workspaces/${ws.id}/datasets/${ds.id}/quality`);
    onChange();
  };
  return (
    <Card title="Data-quality checks" actions={<Button size="sm" onClick={recheck}><RefreshCw className="h-3.5 w-3.5" /> Re-check</Button>}>
      {!warnings.length && <div className="text-sm text-emerald-700">No issues found.</div>}
      <div className="grid gap-2">
        {warnings.map((w, i) => (
          <div key={i} className={cx("flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm", w.level === "warning" ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50")}>
            <div>
              <Badge tone={w.level === "warning" ? "amber" : "slate"}>{w.code.replace("_", " ")}</Badge> <span className="ml-1 text-slate-700">{w.message}</span>
              {w.variants && <div className="mt-1 text-xs text-slate-500">{Object.values(w.variants).slice(0, 3).map((v) => v.join(" / ")).join(" · ")}</div>}
            </div>
            {canEdit && w.code === "duplicates" && <Button size="sm" loading={busy} onClick={() => fix("remove_duplicates", {})}>Remove duplicates</Button>}
            {canEdit && w.code === "inconsistent_values" && w.variants && w.column && (
              <Button size="sm" loading={busy} onClick={() => {
                const mapping: Record<string, string[]> = {};
                Object.values(w.variants!).forEach((vs) => {
                  const best = [...vs].sort((a, b) => (/^[A-Z]/.test(b) ? 1 : 0) - (/^[A-Z]/.test(a) ? 1 : 0) || a.length - b.length)[0].trim();
                  mapping[best] = vs;
                });
                fix("standardize_values", { column: w.column, mapping });
              }}>Standardize</Button>
            )}
            {canEdit && w.code === "missing" && w.column && <Link to="#" onClick={(e) => { e.preventDefault(); const v = prompt(`Fill empty "${w.column}" values with:`); if (v !== null) fix("fill_nulls", { column: w.column, value: v }); }}><Button size="sm">Fill empty…</Button></Link>}
          </div>
        ))}
      </div>
      {ds.quality?.checked_at && <div className="mt-3 text-xs text-slate-400">Checked {timeAgo(ds.quality.checked_at)}</div>}
    </Card>
  );
}

function SettingsTab({ ds, canEdit, onChange }: { ds: Dataset; canEdit: boolean; onChange: (d?: Dataset) => void }) {
  const { ws, base, reloadModel } = useWs();
  const toast = useToast();
  const nav = useNavigate();
  const [name, setName] = useState(ds.name);
  const [desc, setDesc] = useState(ds.description);
  const [dateCol, setDateCol] = useState(ds.default_date_column || "");
  const [interval, setInterval_] = useState(60);
  const [busy, setBusy] = useState("");
  const save = async () => {
    setBusy("save");
    try {
      onChange(await api.patch<Dataset>(`/workspaces/${ws.id}/datasets/${ds.id}`, { name, description: desc, default_date_column: dateCol }));
      toast("success", "Saved");
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy("");
    }
  };
  const sync = async () => {
    setBusy("sync");
    try {
      const r = await api.post<{ rows: number; dataset: Dataset }>(`/workspaces/${ws.id}/datasets/${ds.id}/sync`);
      toast("success", `Synced ${r.rows} rows`);
      onChange(r.dataset);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy("");
    }
  };
  const schedule = async () => {
    try {
      await api.put(`/workspaces/${ws.id}/datasets/${ds.id}/schedule`, { interval_minutes: interval, enabled: true });
      toast("success", `Will sync every ${interval} minutes`);
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const del = async () => {
    if (!confirm(`Delete dataset "${ds.name}" and its data?`)) return;
    try {
      await api.del(`/workspaces/${ws.id}/datasets/${ds.id}`);
      reloadModel();
      nav(`${base}/data`);
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  return (
    <div className="grid max-w-3xl gap-4">
      <Card title="General">
        <div className="grid gap-3">
          <div><Label>Name</Label><input className={inputCls} value={name} disabled={!canEdit} onChange={(e) => setName(e.target.value)} /></div>
          <div><Label hint="used by people and the AI assistant">Description</Label><textarea className={inputCls} rows={2} value={desc} disabled={!canEdit} onChange={(e) => setDesc(e.target.value)} /></div>
          <div><Label hint="used for date ranges and time grouping">Default date column</Label>
            <Select value={dateCol} onChange={setDateCol} disabled={!canEdit} placeholder="None" options={ds.columns.filter((c) => ["date", "datetime"].includes(c.data_type)).map((c) => ({ value: c.name, label: c.display_name }))} /></div>
          {canEdit && <div><Button variant="primary" onClick={save} loading={busy === "save"}>Save</Button></div>}
        </div>
      </Card>
      {canEdit && ds.kind === "file" && (
        <Card title="Refresh data">
          <p className="mb-3 text-sm text-slate-600">Upload a newer version of <b>{ds.source_info.filename}</b>. Choose <i>Replace</i> to swap all rows (your preparation steps re-run automatically) or <i>Append</i> to add rows.</p>
          <div className="flex gap-2">
            <Link to={`${base}/import?target=${ds.id}&mode=replace`}><Button>Replace data…</Button></Link>
            <Link to={`${base}/import?target=${ds.id}&mode=append`}><Button>Append rows…</Button></Link>
          </div>
        </Card>
      )}
      {canEdit && ds.kind === "connector" && (
        <Card title="Database sync">
          <div className="mb-3 text-sm text-slate-600">Source: {ds.source_info.connector_name} · {ds.source_info.source_schema}.{ds.source_info.source_table}</div>
          <div className="flex flex-wrap items-end gap-2">
            <Button onClick={sync} loading={busy === "sync"}><RefreshCw className="h-4 w-4" /> Sync now</Button>
            <div className="ml-4"><Label>Sync every (minutes)</Label><input type="number" min={5} className={inputCls + " w-28"} value={interval} onChange={(e) => setInterval_(Number(e.target.value))} /></div>
            <Button onClick={schedule}>Save schedule</Button>
          </div>
        </Card>
      )}
      {ds.kind === "query_table" && (
        <Card title="SQL">
          <pre className="max-h-64 overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">{ds.query_sql}</pre>
          <Link to={`${base}/sql?edit=${ds.id}`} className="mt-2 inline-block text-sm text-brand-600">Edit in SQL workspace →</Link>
        </Card>
      )}
      {canEdit && <Card title="Danger zone"><Button variant="danger" onClick={del}><Trash2 className="h-4 w-4" /> Delete dataset</Button></Card>}
    </div>
  );
}
