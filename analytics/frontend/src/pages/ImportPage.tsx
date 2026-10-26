import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Database, FileSpreadsheet, Plug, Server, Upload } from "lucide-react";
import { api, Dataset, DataType } from "../api/client";
import { Badge, Button, Card, cx, ErrorBox, inputCls, Label, PageHeader, Select, Spinner, Tabs, useAsync, useToast } from "../components/ui";
import { useWs } from "./WorkspaceLayout";

interface PreviewCol { source_name: string; name: string; display_name: string; inferred_type: DataType; null_count: number; distinct_count: number; parse_failures: number; samples: string[] }
interface Preview {
  upload_id: string; filename: string; sheets: string[]; sheet: string; empty: boolean; header_row: number; raw_top_rows: (string | null)[][];
  rows: any[][]; columns: PreviewCol[]; row_count: number; duplicate_rows: number; warnings: { level: string; code: string; message: string; column?: string }[];
}
interface ColSpec { source_name: string; name: string; display_name: string; data_type: DataType; include: boolean }
const TYPES: DataType[] = ["text", "integer", "decimal", "date", "datetime", "boolean"];

export default function ImportPage() {
  const [tab, setTab] = useState("file");
  return (
    <div>
      <PageHeader title="Import data" subtitle="Bring in Excel / CSV files or tables from a SQL database. Data is stored in PostgreSQL and survives restarts." />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "file", label: <span className="flex items-center gap-1.5"><FileSpreadsheet className="h-4 w-4" /> Files</span> }, { id: "db", label: <span className="flex items-center gap-1.5"><Server className="h-4 w-4" /> Databases</span> }]} />
      <div className="mt-4">{tab === "file" ? <FileImport /> : <DbImport />}</div>
    </div>
  );
}

function FileImport() {
  const { ws, base, reloadModel } = useWs();
  const toast = useToast();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const target = params.get("target");
  const datasets = useAsync(() => api.get<Dataset[]>(`/workspaces/${ws.id}/datasets`), [ws.id]);
  const [queue, setQueue] = useState<File[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [cols, setCols] = useState<ColSpec[]>([]);
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"new" | "append" | "replace">((params.get("mode") as any) || "new");
  const [targetId, setTargetId] = useState(target || "");
  const [dedupe, setDedupe] = useState(false);
  const [busy, setBusy] = useState<"" | "upload" | "preview" | "import">("");
  const [error, setError] = useState<any>(null);
  const [done, setDone] = useState<{ dataset: Dataset; report: any }[]>([]);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const applyPreview = (p: Preview, keepName = false) => {
    setPreview(p);
    setCols(p.columns.map((c) => ({ source_name: c.source_name, name: c.name, display_name: c.display_name, data_type: c.inferred_type, include: !(c.null_count === p.row_count && p.row_count > 0) })));
    if (!keepName) setName(p.filename.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").replace(/\b\w/g, (m) => m.toUpperCase()) + (p.sheets.length > 1 ? ` - ${p.sheet}` : ""));
    setDedupe(p.duplicate_rows > 0);
  };

  const upload = async (file: File) => {
    setBusy("upload");
    setError(null);
    try {
      applyPreview(await api.upload<Preview>(`/workspaces/${ws.id}/uploads`, file));
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  };
  useEffect(() => {
    if (!preview && queue.length && !busy) upload(queue[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queue, preview]);

  const repreview = async (sheet: string, header: number | null) => {
    if (!preview) return;
    setBusy("preview");
    try {
      const p = await api.get<Preview>(`/workspaces/${ws.id}/uploads/${preview.upload_id}/preview?sheet=${encodeURIComponent(sheet)}${header !== null ? `&header_row=${header}` : ""}`);
      applyPreview(p, header !== null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  };

  const doImport = async () => {
    if (!preview) return;
    setBusy("import");
    setError(null);
    try {
      const r = await api.post<{ dataset: Dataset; report: any }>(`/workspaces/${ws.id}/imports`, {
        upload_id: preview.upload_id, sheet: preview.sheet, header_row: preview.header_row, name, columns: cols, mode,
        dataset_id: mode === "new" ? null : Number(targetId), options: { drop_duplicates: dedupe },
      });
      setDone((d) => [...d, r]);
      toast("success", `Imported ${r.dataset.name}: ${r.dataset.row_count.toLocaleString("en-IN")} rows`);
      reloadModel();
      datasets.reload();
      setPreview(null);
      setQueue((q) => q.slice(1));
      if (target) nav(`${base}/data/${r.dataset.id}`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  };

  const failures = useMemo(() => {
    const m = new Map<string, PreviewCol>();
    preview?.columns.forEach((c) => m.set(c.source_name, c));
    return m;
  }, [preview]);

  return (
    <div className="grid gap-4">
      {!preview && (
        <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); setQueue(Array.from(e.dataTransfer.files)); }}
          onClick={() => inputRef.current?.click()}
          className={cx("flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed bg-white px-6 py-14 text-center transition", drag ? "border-brand-500 bg-brand-50" : "border-slate-300 hover:border-brand-400")}>
          <Upload className="mb-3 h-8 w-8 text-slate-400" />
          <div className="font-medium text-slate-800">{busy === "upload" ? "Reading file…" : "Drop Excel or CSV files here, or click to browse"}</div>
          <div className="mt-1 text-sm text-slate-500">.xlsx, .xls, .csv, .tsv · multiple files are imported one after another{target && " · will update the selected dataset"}</div>
          <input ref={inputRef} type="file" multiple accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls" className="hidden" onChange={(e) => setQueue(Array.from(e.target.files || []))} />
        </div>
      )}
      <ErrorBox error={error} />
      {busy === "upload" && <Spinner label="Uploading and profiling…" />}
      {queue.length > 1 && <div className="text-xs text-slate-500">Queue: {queue.map((f) => f.name).join(", ")}</div>}

      {preview && (
        <>
          <Card title={<span className="flex items-center gap-2"><FileSpreadsheet className="h-4 w-4 text-emerald-600" />{preview.filename}</span>}
            actions={<Button size="sm" variant="ghost" onClick={() => { setPreview(null); setQueue((q) => q.slice(1)); }}>Skip file</Button>}>
            <div className="grid gap-3 md:grid-cols-4">
              <div><Label>Sheet</Label><Select value={preview.sheet} onChange={(v) => repreview(v, null)} options={preview.sheets.map((s) => ({ value: s, label: s }))} /></div>
              <div><Label hint="0 = first row">Header row</Label>
                <input type="number" min={0} className={inputCls} value={preview.header_row} onChange={(e) => repreview(preview.sheet, Number(e.target.value))} /></div>
              <div><Label>Import as</Label>
                <Select value={mode} onChange={(v) => setMode(v as any)} options={[{ value: "new", label: "New dataset" }, { value: "append", label: "Append to existing" }, { value: "replace", label: "Replace existing" }]} /></div>
              {mode === "new" ? (
                <div><Label>Dataset name</Label><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} /></div>
              ) : (
                <div><Label>Target dataset</Label><Select value={targetId} onChange={setTargetId} placeholder="Choose…" options={(datasets.data || []).filter((d) => d.kind === "file").map((d) => ({ value: String(d.id), label: d.name }))} /></div>
              )}
            </div>
            {preview.raw_top_rows?.length > 0 && preview.header_row > 0 && (
              <div className="mt-3 rounded-md bg-slate-50 p-2 text-xs text-slate-500">
                Skipped rows above the header: {preview.raw_top_rows.slice(0, preview.header_row).map((r) => r.filter(Boolean).join(" · ")).filter(Boolean).join(" | ") || "(blank)"}
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
              <Badge tone="blue">{preview.row_count.toLocaleString("en-IN")} rows</Badge>
              <Badge>{preview.columns.length} columns</Badge>
              {preview.duplicate_rows > 0 && (
                <label className="flex items-center gap-1.5 text-xs text-slate-600"><input type="checkbox" checked={dedupe} onChange={(e) => setDedupe(e.target.checked)} /> Drop {preview.duplicate_rows} duplicate rows while importing</label>
              )}
            </div>
            {preview.warnings.length > 0 && (
              <div className="mt-3 grid gap-1">
                {preview.warnings.map((w, i) => (
                  <div key={i} className={cx("flex items-center gap-2 text-xs", w.level === "warning" ? "text-amber-700" : "text-slate-500")}><AlertTriangle className="h-3.5 w-3.5" />{w.message}</div>
                ))}
              </div>
            )}
          </Card>

          <Card title="Columns" bodyClass="p-0" actions={<span className="text-xs text-slate-400">Types were detected automatically — correct them here</span>}>
            <div className="max-h-[420px] overflow-auto">
              <table className="min-w-full text-sm">
                <thead className="sticky top-0 bg-slate-50 text-left text-xs font-semibold text-slate-500">
                  <tr><th className="px-3 py-2">Import</th><th className="px-3 py-2">Source header</th><th className="px-3 py-2">Display name</th><th className="px-3 py-2">SQL name</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Empty</th><th className="px-3 py-2">Sample values</th></tr>
                </thead>
                <tbody>
                  {cols.map((c, i) => {
                    const pc = failures.get(c.source_name);
                    const upd = (patch: Partial<ColSpec>) => setCols(cols.map((x, j) => (j === i ? { ...x, ...patch } : x)));
                    return (
                      <tr key={c.source_name} className={cx("border-t border-slate-100", !c.include && "opacity-40")}>
                        <td className="px-3 py-1.5 text-center"><input type="checkbox" checked={c.include} onChange={(e) => upd({ include: e.target.checked })} /></td>
                        <td className="px-3 py-1.5 text-xs text-slate-500">{c.source_name}</td>
                        <td className="px-3 py-1.5"><input className={inputCls} value={c.display_name} onChange={(e) => upd({ display_name: e.target.value })} /></td>
                        <td className="px-3 py-1.5"><input className={inputCls + " font-mono text-xs"} value={c.name} onChange={(e) => upd({ name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })} /></td>
                        <td className="px-3 py-1.5">
                          <select className={inputCls} value={c.data_type} onChange={(e) => upd({ data_type: e.target.value as DataType })}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select>
                          {pc && pc.parse_failures > 0 && c.data_type === pc.inferred_type && <div className="text-[10px] text-amber-600">{pc.parse_failures} values won't convert</div>}
                        </td>
                        <td className="px-3 py-1.5 text-xs tabular-nums text-slate-500">{pc?.null_count ?? 0}</td>
                        <td className="max-w-[260px] truncate px-3 py-1.5 text-xs text-slate-500" title={pc?.samples.join(" | ")}>{pc?.samples.join(" · ")}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title={`Preview (first ${preview.rows.length} rows)`} bodyClass="p-0">
            <div className="max-h-72 overflow-auto">
              <table className="min-w-full text-xs">
                <thead className="sticky top-0 bg-slate-50"><tr>{preview.columns.map((c) => <th key={c.source_name} className="whitespace-nowrap border-b border-slate-200 px-2 py-1 text-left font-semibold text-slate-600">{c.source_name}</th>)}</tr></thead>
                <tbody>{preview.rows.map((r, i) => <tr key={i} className="odd:bg-white even:bg-slate-50/50">{r.map((v, j) => <td key={j} className={cx("whitespace-nowrap border-b border-slate-100 px-2 py-0.5", v === null && "text-slate-300")}>{v === null ? "∅" : String(v)}</td>)}</tr>)}</tbody>
              </table>
            </div>
          </Card>

          <div className="flex justify-end gap-2">
            <Button variant="primary" onClick={doImport} loading={busy === "import"} disabled={(mode === "new" && !name.trim()) || (mode !== "new" && !targetId)}>
              <Database className="h-4 w-4" /> {mode === "new" ? "Import into PostgreSQL" : mode === "append" ? "Append rows" : "Replace data"}
            </Button>
          </div>
        </>
      )}

      {done.length > 0 && (
        <Card title="Imported">
          {done.map(({ dataset, report }) => (
            <div key={dataset.id + "-" + dataset.updated_at} className="flex items-start gap-2 border-b border-slate-100 py-2 text-sm last:border-0">
              <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" />
              <div className="flex-1">
                <Link className="font-medium text-brand-700" to={`${base}/data/${dataset.id}`}>{dataset.name}</Link> — {report.rows_loaded?.toLocaleString("en-IN")} rows loaded
                {report.dropped_duplicates > 0 && `, ${report.dropped_duplicates} duplicates dropped`}
                {Object.keys(report.conversion_failures || {}).length > 0 && (
                  <div className="text-xs text-amber-700">Values that could not be converted were left empty: {Object.entries(report.conversion_failures).map(([k, v]: any) => `${k} (${v.count}: ${v.samples.join(", ")})`).join("; ")}</div>
                )}
                {report.missing_columns?.length > 0 && <div className="text-xs text-amber-700">Missing in the new file (left empty): {report.missing_columns.join(", ")}</div>}
              </div>
            </div>
          ))}
          <div className="mt-3 flex gap-2">
            <Link to={`${base}/model`}><Button size="sm">Next: relate datasets →</Button></Link>
            <Link to={`${base}/data`}><Button size="sm" variant="ghost">View datasets</Button></Link>
          </div>
        </Card>
      )}
    </div>
  );
}

interface Connector { id: number; name: string; kind: string; config: any; last_status: string; last_tested_at: string | null }

function DbImport() {
  const { ws, base, reloadModel, canEdit } = useWs();
  const toast = useToast();
  const conns = useAsync(() => api.get<Connector[]>(`/workspaces/${ws.id}/connectors`), [ws.id]);
  const [form, setForm] = useState<any>({ kind: "postgresql", name: "", host: "localhost", port: "5432", database: "", user: "", password: "", password_env: "", schema: "", url: "" });
  const [sel, setSel] = useState<Connector | null>(null);
  const [tables, setTables] = useState<{ schema: string; table: string; type: string }[] | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<{ columns: string[]; rows: any[][] } | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<any>(null);

  const create = async () => {
    setBusy("create");
    setError(null);
    try {
      const { kind, name, ...rest } = form;
      const config = kind === "postgresql" ? { host: rest.host, port: rest.port, database: rest.database, user: rest.user, schema: rest.schema, password: rest.password || undefined, password_env: rest.password_env }
        : { url: rest.url, password: rest.password || undefined, password_env: rest.password_env };
      const c = await api.post<Connector>(`/workspaces/${ws.id}/connectors`, { name: name || rest.database || "Database", kind, config });
      conns.reload();
      setForm({ ...form, password: "" });
      open(c);
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  };
  const open = async (c: Connector) => {
    setSel(c);
    setTables(null);
    setPreview(null);
    setPicked(new Set());
    setBusy("tables");
    setError(null);
    try {
      const t = await api.post<{ status: string }>(`/workspaces/${ws.id}/connectors/${c.id}/test`);
      if (t.status !== "ok") throw new Error(t.status);
      setTables(await api.get(`/workspaces/${ws.id}/connectors/${c.id}/tables`));
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
      conns.reload();
    }
  };
  const doPreview = async (t: { schema: string; table: string }) => {
    try {
      setPreview(await api.get(`/workspaces/${ws.id}/connectors/${sel!.id}/preview?schema=${encodeURIComponent(t.schema)}&table=${encodeURIComponent(t.table)}`));
    } catch (e) {
      setError(e);
    }
  };
  const doImport = async () => {
    setBusy("import");
    setError(null);
    try {
      const list = Array.from(picked).map((k) => { const [schema, table] = k.split("."); return { schema, table }; });
      const r = await api.post<Dataset[]>(`/workspaces/${ws.id}/connectors/${sel!.id}/import`, { tables: list, refresh_minutes: refresh || null });
      toast("success", `Imported ${r.length} table(s)`);
      reloadModel();
      setPicked(new Set());
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  };
  const f = (k: string, label: string, type = "text", hint?: string) => (
    <div><Label hint={hint}>{label}</Label><input type={type} className={inputCls} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} autoComplete="off" /></div>
  );
  return (
    <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
      <div className="grid content-start gap-4">
        <Card title="Connections">
          {conns.data?.length === 0 && <div className="text-sm text-slate-400">No connections yet.</div>}
          {conns.data?.map((c) => (
            <button key={c.id} onClick={() => open(c)} className={cx("flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm hover:bg-slate-50", sel?.id === c.id && "bg-brand-50")}>
              <Plug className="h-4 w-4 text-slate-400" />
              <div className="min-w-0 flex-1"><div className="truncate font-medium">{c.name}</div><div className="truncate text-[11px] text-slate-400">{c.kind} · {c.config.host || c.config.url} {c.config.database}</div></div>
              {c.last_status && <Badge tone={c.last_status === "ok" ? "green" : "red"}>{c.last_status === "ok" ? "ok" : "error"}</Badge>}
            </button>
          ))}
        </Card>
        {canEdit && (
          <Card title="New connection">
            <div className="grid gap-2.5">
              <div><Label>Type</Label><Select value={form.kind} onChange={(v) => setForm({ ...form, kind: v })} options={[{ value: "postgresql", label: "PostgreSQL" }, { value: "sqlalchemy", label: "Other SQL (SQLAlchemy URL)" }]} /></div>
              {f("name", "Connection name")}
              {form.kind === "postgresql" ? <>
                <div className="grid grid-cols-[1fr_90px] gap-2">{f("host", "Host")}{f("port", "Port")}</div>
                {f("database", "Database")}{f("user", "User")}{f("schema", "Schema", "text", "(optional)")}
              </> : f("url", "SQLAlchemy URL", "text", "no password inside")}
              {f("password", "Password", "password", "saved encrypted; needs ELLEMENTRY_SECRET_KEY")}
              {f("password_env", "…or password environment variable", "text", "e.g. ERP_DB_PASSWORD")}
              <p className="text-[11px] text-slate-400">For PostgreSQL you can also leave the password empty and rely on pgpass.conf. Connections are opened read-only.</p>
              <Button variant="primary" onClick={create} loading={busy === "create"}>Save & connect</Button>
            </div>
          </Card>
        )}
      </div>
      <div className="grid content-start gap-4">
        <ErrorBox error={error} />
        {busy === "tables" && <Spinner label="Connecting…" />}
        {sel && tables && (
          <Card title={`Tables in ${sel.name}`} actions={<span className="text-xs text-slate-400">{picked.size} selected</span>}>
            <div className="max-h-80 overflow-auto">
              {tables.map((t) => {
                const k = `${t.schema}.${t.table}`;
                return (
                  <div key={k} className="flex items-center gap-2 border-b border-slate-100 py-1.5 text-sm">
                    <input type="checkbox" checked={picked.has(k)} onChange={(e) => { const s = new Set(picked); if (e.target.checked) s.add(k); else s.delete(k); setPicked(s); }} />
                    <span className="text-slate-400">{t.schema}.</span><span className="font-medium">{t.table}</span><Badge>{t.type}</Badge>
                    <button onClick={() => doPreview(t)} className="ml-auto text-xs text-brand-600 hover:underline">Preview</button>
                  </div>
                );
              })}
            </div>
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <div><Label hint="0 = manual">Auto-sync every (min)</Label><input type="number" min={0} className={inputCls + " w-32"} value={refresh} onChange={(e) => setRefresh(Number(e.target.value))} /></div>
              <Button variant="primary" disabled={!picked.size} loading={busy === "import"} onClick={doImport}>Import {picked.size || ""} table(s)</Button>
              <Link to={`${base}/data`} className="text-sm text-brand-600">View datasets →</Link>
            </div>
          </Card>
        )}
        {preview && (
          <Card title="Preview" bodyClass="p-0">
            <div className="max-h-72 overflow-auto">
              <table className="min-w-full text-xs">
                <thead className="sticky top-0 bg-slate-50"><tr>{preview.columns.map((c) => <th key={c} className="border-b px-2 py-1 text-left">{c}</th>)}</tr></thead>
                <tbody>{preview.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className="whitespace-nowrap border-b border-slate-100 px-2 py-0.5">{v === null ? "∅" : String(v)}</td>)}</tr>)}</tbody>
              </table>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
