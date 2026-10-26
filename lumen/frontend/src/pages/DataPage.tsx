import { useState } from "react";
import { Link } from "react-router-dom";
import { Database, FileSpreadsheet, FileUp, Search, Server, TerminalSquare } from "lucide-react";
import { api, Dataset } from "../api/client";
import { Badge, Button, Empty, ErrorBox, inputCls, PageHeader, Spinner, useAsync } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

const KIND_ICON = { file: FileSpreadsheet, connector: Server, query_table: TerminalSquare } as const;

export default function DataPage() {
  const { ws, base, canEdit } = useWs();
  const q = useAsync(() => api.get<Dataset[]>(`/workspaces/${ws.id}/datasets`), [ws.id]);
  const [search, setSearch] = useState("");
  const list = (q.data || []).filter((d) => !search || d.name.toLowerCase().includes(search.toLowerCase()) || d.columns.some((c) => c.display_name.toLowerCase().includes(search.toLowerCase())));
  return (
    <div>
      <PageHeader title="Datasets" subtitle="Imported files, synced database tables and SQL query tables in this workspace."
        actions={canEdit && <Link to={`${base}/import`}><Button variant="primary"><FileUp className="h-4 w-4" /> Import data</Button></Link>} />
      <ErrorBox error={q.error} />
      <div className="relative mb-3 max-w-sm">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
        <input className={inputCls + " pl-8"} placeholder="Search datasets and columns" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      {q.loading ? <Spinner /> : !q.data?.length ? (
        <Empty icon={<Database className="h-8 w-8" />} title="No data yet" action={canEdit && <Link to={`${base}/import`}><Button variant="primary">Import a file</Button></Link>}>
          Upload Excel or CSV files, or connect a PostgreSQL database.
        </Empty>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-card">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold text-slate-500">
              <tr><th className="px-4 py-2">Name</th><th className="px-4 py-2">Source</th><th className="px-4 py-2 text-right">Rows</th><th className="px-4 py-2 text-right">Columns</th><th className="px-4 py-2">Quality</th><th className="px-4 py-2">Refreshed</th></tr>
            </thead>
            <tbody>
              {list.map((d) => {
                const Icon = KIND_ICON[d.kind];
                return (
                  <tr key={d.id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-2.5">
                      <Link to={`${base}/data/${d.id}`} className="flex items-center gap-2 font-medium text-slate-800 hover:text-brand-700">
                        <Icon className="h-4 w-4 text-slate-400" /> {d.name}
                      </Link>
                      <div className="ml-6 text-[11px] text-slate-400">{d.slug}</div>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-slate-500">
                      {d.kind === "file" ? `${d.source_info.filename}${d.source_info.sheet ? ` · ${d.source_info.sheet}` : ""}` : d.kind === "connector" ? `${d.source_info.connector_name}: ${d.source_info.source_table}` : "SQL query table"}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{d.row_count.toLocaleString("en-IN")}</td>
                    <td className="px-4 py-2.5 text-right">{d.column_count}</td>
                    <td className="px-4 py-2.5">{d.warning_count ? <Badge tone="amber">{d.warning_count} warnings</Badge> : <Badge tone="green">OK</Badge>}</td>
                    <td className="px-4 py-2.5 text-xs text-slate-500">{timeAgo(d.last_refreshed_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
