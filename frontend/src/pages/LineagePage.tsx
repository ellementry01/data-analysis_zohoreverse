import { useMemo } from "react";
import { api } from "../api/client";
import { EChart } from "../components/Chart";
import { Card, ErrorBox, PageHeader, Spinner, useAsync } from "../components/ui";
import { escapeHtml } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

interface Lineage { nodes: { id: string; type: string; label: string }[]; edges: { from: string; to: string; label: string }[] }
const COL: Record<string, number> = { source: 0, file: 1, connector: 1, query_table: 2, report: 3, dashboard: 3 };
const COLOR: Record<string, string> = { source: "#94a3b8", file: "#2856c4", connector: "#0ea5e9", query_table: "#8b5cf6", report: "#14b8a6", dashboard: "#f59e0b" };

export default function LineagePage() {
  const { ws } = useWs();
  const q = useAsync(() => api.get<Lineage>(`/workspaces/${ws.id}/lineage`), [ws.id]);
  const option = useMemo(() => {
    if (!q.data) return null;
    const perCol: Record<number, number> = {};
    const nodes = q.data.nodes.map((n) => {
      const c = COL[n.type] ?? 1;
      perCol[c] = (perCol[c] || 0) + 1;
      return { id: n.id, name: n.label, x: c * 300, y: perCol[c] * 56, itemStyle: { color: COLOR[n.type] }, symbolSize: 14, label: { show: true, position: "right", fontSize: 11 },
        tooltip: { formatter: `${escapeHtml(n.type.replace("_", " "))}: ${escapeHtml(n.label)}` } };
    });
    return {
      tooltip: {},
      series: [{ type: "graph", layout: "none", roam: true, data: nodes, edgeSymbol: ["none", "arrow"], edgeSymbolSize: 7,
        links: q.data.edges.map((e) => ({ source: e.from, target: e.to, label: { show: !!e.label, formatter: e.label, fontSize: 9 } })),
        lineStyle: { color: "#cbd5e1", curveness: 0.15 } }],
    } as any;
  }, [q.data]);
  return (
    <div>
      <PageHeader title="Lineage" subtitle="Where each dataset comes from and which query tables, reports and dashboards depend on it." />
      <ErrorBox error={q.error} />
      <div className="mb-2 flex gap-4 text-xs text-slate-500">
        {Object.entries(COLOR).map(([k, c]) => <span key={k}><span style={{ color: c }}>●</span> {k.replace("_", " ")}</span>)}
      </div>
      {q.loading ? <Spinner /> : option && <Card bodyClass="p-0"><div className="h-[620px]"><EChart option={option} /></div></Card>}
    </div>
  );
}
