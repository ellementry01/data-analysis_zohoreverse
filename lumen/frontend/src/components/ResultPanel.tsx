import { useRef, useState } from "react";
import type * as echarts from "echarts";
import { Code2, Download, Image, LayoutDashboard, Lightbulb, Table2 } from "lucide-react";
import { api, Dashboard, QueryResult, QuerySpec } from "../api/client";
import { ChartView, CHART_TYPES, PointClick } from "./Chart";
import { Button, cx, Modal, Select, useAsync, useToast } from "./ui";

export function exportPng(chart: echarts.ECharts | null, name: string) {
  if (!chart) return;
  const url = chart.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#fff" });
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name || "chart"}.png`;
  a.click();
}

export function AddToDashboard({ wsId, spec, chartType, title, open, onClose }: { wsId: number; spec: QuerySpec; chartType: string; title: string; open: boolean; onClose: () => void }) {
  const toast = useToast();
  const dashes = useAsync(() => (open ? api.get<Dashboard[]>(`/workspaces/${wsId}/dashboards`) : Promise.resolve([])), [open]);
  const [target, setTarget] = useState("");
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      let id = Number(target);
      if (!id) id = (await api.post<Dashboard>(`/workspaces/${wsId}/dashboards`, { name: newName || "New dashboard", filters: [{ id: "date", type: "date_range", label: "Date range", field: "@time", value: null }] })).id;
      await api.post(`/workspaces/${wsId}/dashboards/${id}/widgets`, { title: title || "Chart", chart_type: chartType, spec });
      toast("success", "Added to dashboard");
      onClose();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title="Add to dashboard" footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={go}>Add</Button></>}>
      <div className="grid gap-3">
        <Select value={target} onChange={setTarget} placeholder="➕ New dashboard" options={(dashes.data || []).filter((d) => !d.is_template).map((d) => ({ value: String(d.id), label: d.name }))} />
        {!target && <input className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm" placeholder="New dashboard name" value={newName} onChange={(e) => setNewName(e.target.value)} />}
      </div>
    </Modal>
  );
}

export function ResultPanel({ res, chartType, onChartType, spec, title, wsId, height = 380, onPoint, compact }:
  { res: QueryResult; chartType: string; onChartType?: (t: string) => void; spec?: QuerySpec | null; title: string; wsId: number; height?: number; onPoint?: (p: PointClick) => void; compact?: boolean }) {
  const [view, setView] = useState<"chart" | "table" | "sql">("chart");
  const [addOpen, setAddOpen] = useState(false);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const toast = useToast();
  const exportData = async (format: "csv" | "xlsx") => {
    try {
      if (spec) await api.download(`/workspaces/${wsId}/query/export?format=${format}`, spec, `${title || "report"}.${format}`);
      else {
        const csv = [res.columns.map((c) => c.label).join(","), ...res.rows.map((r) => r.map((v) => (v === null ? "" : `"${String(v).replace(/"/g, '""')}"`)).join(","))].join("\n");
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" }));
        a.download = `${title || "result"}.csv`;
        a.click();
      }
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  return (
    <div className="flex flex-col gap-2">
      <div className="no-print flex flex-wrap items-center gap-1.5">
        <div className="flex rounded-md border border-slate-200 bg-white p-0.5">
          {([["chart", "Chart"], ["table", "Data"], ["sql", "SQL"]] as const).map(([k, l]) => (
            <button key={k} onClick={() => setView(k)} className={cx("flex items-center gap-1 rounded px-2 py-0.5 text-xs", view === k ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-100")}>
              {k === "chart" ? <Image className="h-3 w-3" /> : k === "table" ? <Table2 className="h-3 w-3" /> : <Code2 className="h-3 w-3" />}{l}
            </button>
          ))}
        </div>
        {onChartType && <Select className="!w-40 !py-1 text-xs" value={chartType} onChange={onChartType} options={CHART_TYPES.map((c) => ({ value: c.id, label: c.label }))} />}
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant="ghost" onClick={() => exportData("csv")} title="Export CSV"><Download className="h-3.5 w-3.5" />CSV</Button>
          {spec && <Button size="sm" variant="ghost" onClick={() => exportData("xlsx")} title="Export Excel"><Download className="h-3.5 w-3.5" />Excel</Button>}
          {view === "chart" && !["kpi", "table", "pivot"].includes(chartType) && <Button size="sm" variant="ghost" onClick={() => exportPng(chartRef.current, title)}><Image className="h-3.5 w-3.5" />PNG</Button>}
          {spec && <Button size="sm" onClick={() => setAddOpen(true)}><LayoutDashboard className="h-3.5 w-3.5" /> Add to dashboard</Button>}
        </div>
      </div>
      <div style={{ height: view === "sql" ? "auto" : height }} className="min-h-[120px]">
        {view === "chart" && <ChartView type={chartType} res={res} onPoint={onPoint} onReady={(c) => (chartRef.current = c)} />}
        {view === "table" && <ChartView type="table" res={res} />}
        {view === "sql" && (
          <div>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-slate-900 p-3 text-[11px] leading-relaxed text-slate-100">{res.sql}</pre>
            <div className="mt-1 text-[11px] text-slate-400">Executed read-only in {res.duration_ms} ms · {res.row_count} rows{res.truncated && " (truncated)"} · values shown inline; execution used bound parameters</div>
          </div>
        )}
      </div>
      {res.warnings?.length > 0 && <div className="text-xs text-amber-700">⚠ {res.warnings.join(" · ")}</div>}
      {!compact && res.insights?.length > 0 && (
        <div className="rounded-md border border-amber-100 bg-amber-50/60 p-2.5">
          <div className="mb-1 flex items-center gap-1 text-xs font-semibold text-amber-800"><Lightbulb className="h-3.5 w-3.5" /> Insights</div>
          <ul className="grid gap-0.5 text-xs text-slate-700">{res.insights.slice(0, 6).map((i, k) => <li key={k}>• {i.text}</li>)}</ul>
        </div>
      )}
      {spec && <AddToDashboard wsId={wsId} spec={spec} chartType={chartType} title={title} open={addOpen} onClose={() => setAddOpen(false)} />}
    </div>
  );
}
