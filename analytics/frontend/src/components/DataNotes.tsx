import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Bell, ChevronDown, ChevronRight, Lightbulb, MessageSquareText, TrendingDown, TrendingUp } from "lucide-react";
import { api } from "../api/client";
import { timeAgo } from "../lib/format";
import { cx } from "./ui";

/** Phase 5 (backend routers/data_issues.py). */
export interface IssueBrief {
  code: string; title: string; status: string; severity: "high" | "medium" | "low"; note: string; what_is_needed: string;
  affects: { dashboards?: string[]; metrics?: string[]; datasets?: string[] }; widget_ids: number[]; whole_dashboard: boolean;
}
export interface WorthItem {
  id: string; kind: "vs_last_year" | "unusual" | "record" | "gap" | "stale"; widget_id: number | null; widget: string | null;
  metric: string | null; tone: "good" | "bad" | "neutral"; text: string; question: string; values: Record<string, any>;
}
export interface Insights { issues: IssueBrief[]; worth_a_look: { items: WorthItem[]; computed_at: string | null; status: "ready" | "updating" } }

const SEV: Record<string, string> = { high: "bg-red-100 text-red-800", medium: "bg-amber-100 text-amber-800", low: "bg-slate-100 text-slate-600" };

/** A small note on a tile whose number is affected by a known data issue. */
export function TileIssueBadge({ issues }: { issues: IssueBrief[] }) {
  if (!issues.length) return null;
  const tip = issues.map((i) => `${i.code}: ${i.note}`).join("\n");
  return (
    <span title={`Known data issue${issues.length > 1 ? "s" : ""} - see the note above the dashboard\n${tip}`}
      aria-label={`Known data issue: ${tip}`}
      className="inline-flex shrink-0 items-center gap-0.5 rounded bg-amber-50 px-1 text-[10px] font-medium text-amber-800">
      <AlertTriangle className="h-3 w-3" /> {issues.map((i) => i.code).join(", ")}
    </span>
  );
}

/** "Known data issues" above a dashboard, most severe first; collapsed to one line by default. */
export function IssueStrip({ issues, widgetTitles }: { issues: IssueBrief[]; widgetTitles: Record<number, string> }) {
  const [open, setOpen] = useState(false);
  if (!issues.length) return null;
  const high = issues.filter((i) => i.severity === "high").length;
  return (
    <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50/60 text-xs text-slate-700">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left" aria-expanded={open}>
        <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-700" />
        <span className="font-medium text-amber-900">Known data issues on this dashboard: {issues.length}</span>
        {high > 0 && <span className="text-amber-800">({high} high)</span>}
        <span className="min-w-0 flex-1 truncate text-slate-500">{!open && issues.slice(0, 3).map((i) => `${i.code} ${i.note}`).join(" · ")}</span>
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
      </button>
      {open && (
        <ul className="divide-y divide-amber-100 border-t border-amber-200 px-3">
          {issues.map((i) => (
            <li key={i.code} className="py-1.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className={cx("rounded px-1 text-[10px] font-semibold", SEV[i.severity])}>{i.code}</span>
                <span className="font-medium text-slate-800">{i.note}</span>
                {i.status === "awaiting" && <span className="text-[10px] text-slate-500">(awaiting confirmation)</span>}
              </div>
              <div className="mt-0.5 text-[11px] text-slate-500">
                Affects: {i.widget_ids.length ? i.widget_ids.map((w) => widgetTitles[w]).filter(Boolean).join(", ") : "the dashboard as a whole"}
                {i.what_is_needed && <> · <span title={i.what_is_needed}>{i.what_is_needed.slice(0, 160)}{i.what_is_needed.length > 160 ? "…" : ""}</span></>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** What deserves attention on this dashboard, computed from its own numbers (no AI). */
export function WorthALook({ data, onAsk }: { data: Insights["worth_a_look"]; onAsk?: (question: string) => void }) {
  if (!data.items.length) return null;
  return (
    <div className="mb-3 rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-card">
      <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-slate-700">
        <Lightbulb className="h-3.5 w-3.5 text-brand-600" /> Worth a look
        <span className="font-normal text-slate-400">· worked out from this dashboard's numbers{data.computed_at ? `, ${timeAgo(data.computed_at)}` : ""}{data.status === "updating" ? " (updating)" : ""}</span>
      </div>
      <ul className="flex flex-col gap-1">
        {data.items.map((it) => (
          <li key={it.id} className="flex items-start gap-2 text-sm text-slate-700">
            <span className={cx("mt-0.5 shrink-0", it.tone === "bad" ? "text-red-600" : it.tone === "good" ? "text-emerald-600" : "text-slate-400")}>
              {it.tone === "good" ? <TrendingUp className="h-4 w-4" /> : it.tone === "bad" ? <TrendingDown className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
            </span>
            <span className="min-w-0 flex-1">{it.text}</span>
            {onAsk && (
              <button onClick={() => onAsk(it.question)} className="inline-flex shrink-0 items-center gap-1 text-xs text-brand-600 hover:underline" title={it.question}>
                <MessageSquareText className="h-3 w-3" /> Ask why
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

interface Note { id: number; kind: string; title: string; body: string; issue_code: string | null; created_at: string; read: boolean }

/** The owner's notifications (workspace admins): data issues opened, solved or reopened. */
export function NotificationsBell({ wsId }: { wsId: number }) {
  const [data, setData] = useState<{ unread: number; items: Note[] } | null>(null);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const load = () => { api.get<{ unread: number; items: Note[] }>(`/workspaces/${wsId}/notifications`).then(setData).catch(() => setData(null)); };
  useEffect(() => { load(); const t = setInterval(load, 120000); return () => { clearInterval(t); }; }, [wsId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => { document.removeEventListener("mousedown", close); };
  }, []);
  if (!data) return null;
  const readAll = async () => { await api.post(`/workspaces/${wsId}/notifications/read`, {}); load(); };
  return (
    <div ref={box} className="relative">
      <button onClick={() => setOpen(!open)} aria-label={`Notifications, ${data.unread} unread`} title="Data notifications"
        className="relative rounded p-1 text-slate-500 hover:bg-slate-100">
        <Bell className="h-4 w-4" />
        {data.unread > 0 && <span className="absolute -right-0.5 -top-0.5 rounded-full bg-red-600 px-1 text-[9px] font-semibold text-white">{data.unread > 9 ? "9+" : data.unread}</span>}
      </button>
      {open && (
        <div className="absolute bottom-8 left-0 z-50 w-80 rounded-lg border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center border-b border-slate-100 px-3 py-2 text-xs font-semibold text-slate-700">
            Data notifications
            {data.unread > 0 && <button onClick={readAll} className="ml-auto font-normal text-brand-600 hover:underline">Mark all read</button>}
          </div>
          <ul className="max-h-80 overflow-y-auto">
            {data.items.length === 0 && <li className="px-3 py-3 text-xs text-slate-400">Nothing yet.</li>}
            {data.items.map((n) => (
              <li key={n.id} className={cx("border-b border-slate-50 px-3 py-2 text-xs", !n.read && "bg-brand-50/50")}>
                <div className="font-medium text-slate-800">{n.title}</div>
                {n.body && <div className="mt-0.5 line-clamp-2 text-slate-500">{n.body}</div>}
                <div className="mt-0.5 text-[10px] text-slate-400">{timeAgo(n.created_at)}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
