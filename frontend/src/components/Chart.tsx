import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import { ArrowDownRight, ArrowUpRight, ChevronDown, ChevronUp } from "lucide-react";
import type { Insight, QueryResult, ResultColumn } from "../api/client";
import { escapeHtml, fmtCell, fmtDateLabel, fmtNumber } from "../lib/format";
import { cx } from "./ui";

export const CHART_TYPES: { id: string; label: string }[] = [
  { id: "kpi", label: "KPI card" }, { id: "line", label: "Line" }, { id: "area", label: "Area" }, { id: "bar", label: "Bar" },
  { id: "hbar", label: "Horizontal bar" }, { id: "stacked_bar", label: "Stacked bar" }, { id: "combo", label: "Bar + line" },
  { id: "pie", label: "Pie" }, { id: "donut", label: "Donut" }, { id: "scatter", label: "Scatter" }, { id: "heatmap", label: "Heatmap" },
  { id: "table", label: "Table" }, { id: "pivot", label: "Pivot table" },
];

export const PALETTE = ["#2856c4", "#14b8a6", "#f59e0b", "#e11d48", "#8b5cf6", "#0ea5e9", "#84cc16", "#f97316", "#64748b", "#db2777"];

export interface PointClick { column: ResultColumn; value: any; seriesValue?: any; seriesColumn?: ResultColumn }

function label(c: ResultColumn, v: any) {
  return c.type === "date" || c.type === "datetime" ? fmtDateLabel(v, c.grain) : v === null || v === undefined ? "(blank)" : String(v);
}

export function buildOption(type: string, res: QueryResult, insights: Insight[] = []): echarts.EChartsOption | null {
  const cols = res.columns;
  const dims = cols.filter((c) => c.role === "dimension");
  const meas = cols.filter((c) => c.role === "measure" && !c.compare_of);
  const prevCols = cols.filter((c) => c.compare_of && c.name.endsWith("__prev"));
  const idx = (c: ResultColumn) => cols.indexOf(c);
  const rows = res.rows;
  if (!meas.length && type !== "table") return null;
  const tooltipFmt = (fmt?: string) => (v: any) => fmtNumber(v, fmt, false);
  const base: echarts.EChartsOption = {
    color: PALETTE,
    textStyle: { fontFamily: "Inter, Segoe UI, system-ui, sans-serif" },
    grid: { left: 12, right: 18, top: 34, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", confine: true },
    legend: { type: "scroll", top: 0, left: 0, textStyle: { fontSize: 11 } },
    animationDuration: 300,
  };

  if (type === "pie" || type === "donut") {
    const d = dims[0];
    const m = meas[0];
    if (!d) return null;
    return {
      ...base,
      tooltip: { trigger: "item", valueFormatter: tooltipFmt(m.format) as any },
      legend: { type: "scroll", orient: "vertical", right: 0, top: "middle", textStyle: { fontSize: 11 } },
      series: [{
        type: "pie", radius: type === "donut" ? ["45%", "72%"] : "72%", center: ["40%", "52%"], avoidLabelOverlap: true,
        itemStyle: { borderColor: "#fff", borderWidth: 1 }, label: { formatter: "{d}%", fontSize: 11 },
        data: rows.map((r) => ({ name: label(d, r[idx(d)]), value: r[idx(m)], raw: r[idx(d)] })),
      }],
    };
  }

  if (type === "scatter") {
    const [mx, my] = [meas[0], meas[1] || meas[0]];
    const d = dims[0];
    return {
      ...base,
      tooltip: { trigger: "item", formatter: (p: any) => `${escapeHtml(p.data[2] ?? "")}<br/>${escapeHtml(mx.label)}: ${fmtNumber(p.data[0], mx.format, false)}<br/>${escapeHtml(my.label)}: ${fmtNumber(p.data[1], my.format, false)}` },
      xAxis: { type: "value", name: mx.label, nameLocation: "middle", nameGap: 26, axisLabel: { formatter: (v: number) => fmtNumber(v, mx.format) } },
      yAxis: { type: "value", name: my.label, axisLabel: { formatter: (v: number) => fmtNumber(v, my.format) } },
      grid: { ...(base.grid as object), bottom: 30 },
      series: [{ type: "scatter", symbolSize: 10, data: rows.map((r) => [r[idx(mx)], r[idx(my)], d ? label(d, r[idx(d)]) : ""]) }],
    };
  }

  if (type === "heatmap") {
    const [dx, dy] = dims;
    const m = meas[0];
    if (!dx || !dy) return null;
    const xs = Array.from(new Set(rows.map((r) => label(dx, r[idx(dx)]))));
    const ys = Array.from(new Set(rows.map((r) => label(dy, r[idx(dy)]))));
    const vals = rows.map((r) => r[idx(m)]).filter((v) => v !== null) as number[];
    return {
      ...base,
      tooltip: { trigger: "item", formatter: (p: any) => `${escapeHtml(xs[p.data[0]])} · ${escapeHtml(ys[p.data[1]])}<br/>${escapeHtml(m.label)}: <b>${fmtNumber(p.data[2], m.format, false)}</b>` },
      grid: { left: 12, right: 12, top: 8, bottom: 46, containLabel: true },
      xAxis: { type: "category", data: xs, splitArea: { show: true }, axisLabel: { fontSize: 10, interval: 0, rotate: xs.length > 6 ? 30 : 0 } },
      yAxis: { type: "category", data: ys, splitArea: { show: true }, axisLabel: { fontSize: 10 } },
      visualMap: { min: Math.min(...vals, 0), max: Math.max(...vals, 1), calculable: true, orient: "horizontal", left: "center", bottom: 0, itemHeight: 120,
        inRange: { color: ["#eef4ff", "#5b8def", "#162a5a"] }, textStyle: { fontSize: 10 }, formatter: (v: any) => fmtNumber(v, m.format) },
      legend: { show: false },
      series: [{ type: "heatmap", data: rows.map((r) => [xs.indexOf(label(dx, r[idx(dx)])), ys.indexOf(label(dy, r[idx(dy)])), r[idx(m)]]),
        label: { show: xs.length * ys.length <= 60, fontSize: 10, formatter: (p: any) => fmtNumber(p.data[2], m.format) } }],
    };
  }

  // cartesian charts
  const horizontal = type === "hbar";
  const isBar = ["bar", "hbar", "stacked_bar"].includes(type);
  const stacked = type === "stacked_bar" || (type === "area" && dims.length > 1);
  const xDim = dims[0];
  const categories: any[] = xDim ? Array.from(new Set(rows.map((r) => r[idx(xDim)]))) : [""];
  const catLabels = categories.map((v) => (xDim ? label(xDim, v) : ""));
  let series: echarts.SeriesOption[] = [];
  const anomalies = insights.filter((i) => i.type === "anomaly");

  const mkSeries = (name: string, data: any[], kind: "bar" | "line", extra: any = {}): echarts.SeriesOption => ({
    name, type: kind, data, smooth: kind === "line" ? 0.25 : undefined, showSymbol: kind === "line" ? data.length < 40 : undefined,
    areaStyle: type === "area" ? { opacity: 0.18 } : undefined, stack: stacked ? "s" : undefined, barMaxWidth: 42,
    emphasis: { focus: "series" }, ...extra,
  } as any);

  if (dims.length >= 2) {
    const sDim = dims[1];
    const m = meas[0];
    const seriesVals = Array.from(new Set(rows.map((r) => r[idx(sDim)])));
    const lookup = new Map(rows.map((r) => [`${r[idx(xDim)]}|${r[idx(sDim)]}`, r[idx(m)]]));
    series = seriesVals.slice(0, 25).map((sv) =>
      mkSeries(label(sDim, sv), categories.map((c) => lookup.get(`${c}|${sv}`) ?? null), isBar ? "bar" : "line", { _raw: sv }));
  } else {
    const secondAxis = meas.length === 2 && (type === "combo" || (() => {
      const a = Math.max(...rows.map((r) => Math.abs(r[idx(meas[0])] || 0)));
      const b = Math.max(...rows.map((r) => Math.abs(r[idx(meas[1])] || 0)));
      return a && b && (a / b > 8 || b / a > 8 || meas[0].format !== meas[1].format);
    })());
    meas.forEach((m, k) => {
      const kind = type === "combo" ? (k === 0 ? "bar" : "line") : isBar ? "bar" : "line";
      const data = rows.map((r) => r[idx(m)]);
      const extra: any = { yAxisIndex: secondAxis && k === 1 ? 1 : 0 };
      if (k === 0 && anomalies.length && kind === "line") {
        extra.markPoint = { symbolSize: 34, itemStyle: { color: "#e11d48" }, label: { fontSize: 9, formatter: "!" },
          data: anomalies.map((a) => ({ coord: [catLabels[categories.indexOf(a.x)] ?? label(xDim, a.x), a.value], value: a.value })) };
      }
      series.push(mkSeries(m.label, data, kind, extra));
      const prev = prevCols.find((p) => p.compare_of === m.name);
      if (prev) {
        series.push(mkSeries(prev.label, rows.map((r) => r[idx(prev)]), kind, {
          yAxisIndex: extra.yAxisIndex, lineStyle: { type: "dashed", width: 1.5 }, itemStyle: { opacity: 0.45 }, stack: undefined, areaStyle: undefined,
        }));
      }
    });
    if (secondAxis) {
      const valAxes: any[] = [0, 1].map((k) => ({ type: "value", name: meas[k].label, nameTextStyle: { fontSize: 10, align: k ? "right" : "left" },
        axisLabel: { formatter: (v: number) => fmtNumber(v, meas[k].format), fontSize: 10 }, splitLine: { show: k === 0, lineStyle: { color: "#eef2f7" } } }));
      return {
        ...base, xAxis: { type: "category", data: catLabels, axisLabel: { fontSize: 10, hideOverlap: true } }, yAxis: valAxes, series,
        tooltip: { trigger: "axis", confine: true, valueFormatter: (v: any) => fmtNumber(v, undefined, false) },
      };
    }
  }
  const fmt0 = meas[0]?.format;
  const catAxis: any = { type: "category", data: catLabels, axisLabel: { fontSize: 10, hideOverlap: true, interval: horizontal ? 0 : "auto", width: horizontal ? 140 : undefined, overflow: "truncate" }, axisTick: { alignWithLabel: true } };
  const valAxis: any = { type: "value", axisLabel: { fontSize: 10, formatter: (v: number) => fmtNumber(v, fmt0) }, splitLine: { lineStyle: { color: "#eef2f7" } } };
  if (horizontal) {
    catAxis.inverse = true;
  }
  return {
    ...base,
    tooltip: { trigger: "axis", confine: true, axisPointer: { type: isBar ? "shadow" : "line" }, valueFormatter: (v: any) => fmtNumber(v, fmt0, false) },
    legend: { ...(base.legend as object), show: series.length > 1 },
    grid: { ...(base.grid as object), top: series.length > 1 ? 34 : 12 },
    xAxis: horizontal ? valAxis : catAxis,
    yAxis: horizontal ? catAxis : valAxis,
    dataZoom: !horizontal && categories.length > 40 ? [{ type: "inside" }, { type: "slider", height: 14, bottom: 0 }] : undefined,
    series,
  };
}

export function EChart({ option, onClick, onReady, height = "100%" }: { option: echarts.EChartsOption; onClick?: (p: any) => void; onReady?: (c: echarts.ECharts) => void; height?: string | number }) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  const clickRef = useRef(onClick);
  clickRef.current = onClick;
  useEffect(() => {
    if (!ref.current) return;
    const c = echarts.init(ref.current, undefined, { renderer: "canvas" });
    inst.current = c;
    c.on("click", (p) => clickRef.current?.(p));
    onReady?.(c);
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      c.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    inst.current?.setOption(option, true);
  }, [option]);
  return <div ref={ref} style={{ width: "100%", height }} />;
}

/** Colour of a period-over-period change: green when it moves the way the metric wants (a falling return rate is good). */
function changeTone(v: number | null, base?: { higher_is_better?: boolean }): string {
  if (v === null || v === undefined || v === 0) return "";
  const better = base?.higher_is_better === false ? v < 0 : v > 0;
  return better ? "text-emerald-600" : "text-red-600";
}

export function KpiCard({ res }: { res: QueryResult }) {
  const cols = res.columns;
  const meas = cols.filter((c) => c.role === "measure" && !c.compare_of);
  const row = res.rows[0] || [];
  if (!meas.length) return <div className="text-sm text-slate-400">No measure</div>;
  const m = meas[0];
  const v = row[cols.indexOf(m)];
  const chIdx = cols.findIndex((c) => c.name === `${m.name}__change_pct`);
  const prevIdx = cols.findIndex((c) => c.name === `${m.name}__prev`);
  const ch = chIdx >= 0 ? row[chIdx] : null;
  const good = ch === null ? null : m.higher_is_better === false ? ch <= 0 : ch >= 0;   // e.g. a rising return rate is bad
  const up = ch !== null && ch >= 0;
  return (
    <div className="flex h-full flex-col justify-center">
      <div className="text-3xl font-semibold tracking-tight text-slate-900">{fmtNumber(v, m.format)}</div>
      {ch !== null && ch !== undefined && (
        <div className={cx("mt-1 flex items-center gap-1 text-xs font-medium", good ? "text-emerald-600" : "text-red-600")}>
          {up ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
          {fmtNumber(Math.abs(ch), "percent")} <span className="font-normal text-slate-400">vs {fmtNumber(row[prevIdx], m.format)} previous</span>
        </div>
      )}
      {meas.slice(1, 3).map((x) => (
        <div key={x.name} className="mt-1 text-xs text-slate-500">{x.label}: <b className="text-slate-700">{fmtNumber(row[cols.indexOf(x)], x.format)}</b></div>
      ))}
      {res.rows.length === 0 && <div className="text-xs text-slate-400">No data</div>}
    </div>
  );
}

export function DataTable({ res, onCellClick, maxHeight }: { res: QueryResult; onCellClick?: (p: PointClick) => void; maxHeight?: number | string }) {
  const [sort, setSort] = useState<{ i: number; desc: boolean } | null>(null);
  const rows = useMemo(() => {
    if (!sort) return res.rows;
    return [...res.rows].sort((a, b) => {
      const x = a[sort.i], y = b[sort.i];
      if (x === y) return 0;
      if (x === null) return 1;
      if (y === null) return -1;
      return (x < y ? -1 : 1) * (sort.desc ? -1 : 1);
    });
  }, [res.rows, sort]);
  return (
    <div className="h-full overflow-auto" style={{ maxHeight }}>
      <table className="min-w-full text-xs">
        <thead className="sticky top-0 z-10 bg-slate-50">
          <tr>
            {res.columns.map((c, i) => (
              <th key={c.name} onClick={() => setSort(sort?.i === i ? { i, desc: !sort.desc } : { i, desc: c.role === "measure" })}
                className={cx("cursor-pointer select-none whitespace-nowrap border-b border-slate-200 px-2.5 py-1.5 font-semibold text-slate-600", c.role === "measure" ? "text-right" : "text-left")}>
                <span className="inline-flex items-center gap-0.5">{c.label}{sort?.i === i && (sort.desc ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />)}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri} className="odd:bg-white even:bg-slate-50/60 hover:bg-brand-50/50">
              {res.columns.map((c, ci) => (
                <td key={c.name} onClick={() => c.role === "dimension" && onCellClick?.({ column: c, value: r[ci] })}
                  className={cx("whitespace-nowrap border-b border-slate-100 px-2.5 py-1", c.role === "measure" ? "text-right tabular-nums" : "", c.role === "dimension" && onCellClick ? "cursor-pointer hover:text-brand-700" : "",
                    c.format === "percent" && c.name.endsWith("__change_pct") ? changeTone(r[ci], res.columns.find((x) => x.name === c.compare_of)) : "")}>
                  {c.type === "date" ? fmtDateLabel(r[ci], c.grain) : fmtCell(r[ci], c.role === "measure" ? "decimal" : c.type, c.format)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {res.truncated && <div className="p-2 text-center text-xs text-amber-600">Showing the first {res.row_count} rows</div>}
    </div>
  );
}

export function PivotTable({ res }: { res: QueryResult }) {
  const cols = res.columns;
  const dims = cols.filter((c) => c.role === "dimension");
  const m = cols.find((c) => c.role === "measure" && !c.compare_of);
  if (dims.length < 2 || !m) return <DataTable res={res} />;
  const [rd, cd] = dims;
  const ri = cols.indexOf(rd), ci = cols.indexOf(cd), mi = cols.indexOf(m);
  const rKeys = Array.from(new Set(res.rows.map((r) => r[ri])));
  const cKeys = Array.from(new Set(res.rows.map((r) => r[ci])));
  const cell = new Map(res.rows.map((r) => [`${r[ri]}|${r[ci]}`, r[mi]]));
  const additive = m.additive !== false;
  const rowTot = (rk: any) => cKeys.reduce((s, ck) => s + (cell.get(`${rk}|${ck}`) || 0), 0);
  const colTot = (ck: any) => rKeys.reduce((s, rk) => s + (cell.get(`${rk}|${ck}`) || 0), 0);
  return (
    <div className="h-full overflow-auto">
      <table className="min-w-full text-xs">
        <thead className="sticky top-0 bg-slate-50">
          <tr>
            <th className="border-b border-slate-200 px-2.5 py-1.5 text-left font-semibold text-slate-600">{rd.label} \ {cd.label}</th>
            {cKeys.map((ck) => <th key={String(ck)} className="border-b border-slate-200 px-2.5 py-1.5 text-right font-semibold text-slate-600">{label(cd, ck)}</th>)}
            {additive && <th className="border-b border-slate-200 bg-slate-100 px-2.5 py-1.5 text-right font-semibold text-slate-700">Total</th>}
          </tr>
        </thead>
        <tbody>
          {rKeys.map((rk) => (
            <tr key={String(rk)} className="hover:bg-brand-50/50">
              <td className="whitespace-nowrap border-b border-slate-100 px-2.5 py-1 font-medium text-slate-700">{label(rd, rk)}</td>
              {cKeys.map((ck) => <td key={String(ck)} className="border-b border-slate-100 px-2.5 py-1 text-right tabular-nums">{fmtNumber(cell.get(`${rk}|${ck}`), m.format)}</td>)}
              {additive && <td className="border-b border-slate-100 bg-slate-50 px-2.5 py-1 text-right font-medium tabular-nums">{fmtNumber(rowTot(rk), m.format)}</td>}
            </tr>
          ))}
          {additive && (
            <tr className="bg-slate-100 font-semibold">
              <td className="px-2.5 py-1">Total</td>
              {cKeys.map((ck) => <td key={String(ck)} className="px-2.5 py-1 text-right tabular-nums">{fmtNumber(colTot(ck), m.format)}</td>)}
              <td className="px-2.5 py-1 text-right tabular-nums">{fmtNumber(rKeys.reduce((s, rk) => s + rowTot(rk), 0), m.format)}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** Renders any result as the requested visualization. */
export function ChartView({ type, res, onPoint, onReady, height = "100%" }:
  { type: string; res: QueryResult; onPoint?: (p: PointClick) => void; onReady?: (c: echarts.ECharts) => void; height?: string | number }) {
  const option = useMemo(() => buildOption(type, res, res.insights), [type, res]);
  if (!res.rows.length) return <div className="flex h-full items-center justify-center text-sm text-slate-400">No data for the current filters</div>;
  if (type === "kpi") return <KpiCard res={res} />;
  if (type === "table") return <DataTable res={res} onCellClick={onPoint} />;
  if (type === "pivot") return <PivotTable res={res} />;
  if (!option) return <DataTable res={res} onCellClick={onPoint} />;
  const dims = res.columns.filter((c) => c.role === "dimension");
  const handle = (p: any) => {
    if (!onPoint || !dims.length) return;
    if (p.componentType !== "series") return;
    let value: any;
    if (type === "pie" || type === "donut") value = p.data?.raw;
    else if (type === "heatmap" || type === "scatter") return;
    else {
      const xs = Array.from(new Set(res.rows.map((r) => r[res.columns.indexOf(dims[0])])));
      value = xs[p.dataIndex];
    }
    const seriesValue = dims[1] ? (option.series as any[])[p.seriesIndex]?._raw : undefined;
    onPoint({ column: dims[0], value, seriesValue, seriesColumn: dims[1] });
  };
  return <EChart option={option} onClick={handle} onReady={onReady} height={height} />;
}
