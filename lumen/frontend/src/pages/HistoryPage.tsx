import { useState } from "react";
import { api } from "../api/client";
import { Badge, Card, cx, ErrorBox, PageHeader, Select, Spinner, useAsync } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

interface H { id: number; user: string; source: string; sql: string; status: string; error: string; duration_ms: number; row_count: number; created_at: string }

export default function HistoryPage() {
  const { ws } = useWs();
  const [source, setSource] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const q = useAsync(() => api.get<H[]>(`/workspaces/${ws.id}/history?limit=300${source ? `&source=${source}` : ""}`), [ws.id, source]);
  return (
    <div>
      <PageHeader title="Query history" subtitle="Every query executed in this workspace — by charts, dashboards, the SQL console and the AI assistant (including rejected ones)."
        actions={<Select className="!w-44" value={source} onChange={setSource} placeholder="All sources" options={["chart", "dashboard", "sql", "ai"].map((s) => ({ value: s, label: s }))} />} />
      <ErrorBox error={q.error} />
      {q.loading ? <Spinner /> : (
        <Card bodyClass="p-0">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-3 py-2">When</th><th className="px-3 py-2">Source</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">SQL</th><th className="px-3 py-2 text-right">Rows</th><th className="px-3 py-2 text-right">ms</th><th className="px-3 py-2">User</th></tr></thead>
            <tbody>
              {(q.data || []).map((h) => (
                <tr key={h.id} className="cursor-pointer border-t border-slate-100 align-top hover:bg-slate-50" onClick={() => setOpen(open === h.id ? null : h.id)}>
                  <td className="whitespace-nowrap px-3 py-1.5 text-xs text-slate-500">{timeAgo(h.created_at)}</td>
                  <td className="px-3 py-1.5"><Badge tone={h.source === "ai" ? "violet" : "slate"}>{h.source}</Badge></td>
                  <td className="px-3 py-1.5"><Badge tone={h.status === "ok" ? "green" : h.status === "rejected" ? "amber" : "red"}>{h.status}</Badge></td>
                  <td className="max-w-[640px] px-3 py-1.5">
                    <div className={cx("font-mono text-[11px] text-slate-700", open === h.id ? "whitespace-pre-wrap break-all" : "truncate")}>{h.sql}</div>
                    {h.error && <div className="text-xs text-red-600">{h.error}</div>}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{h.row_count}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{Math.round(h.duration_ms)}</td>
                  <td className="px-3 py-1.5 text-xs text-slate-500">{h.user}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
