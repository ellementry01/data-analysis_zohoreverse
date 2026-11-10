import { Fragment, ReactNode, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BellRing, Check, FileText, MessageSquareText, RefreshCw, Search, X } from "lucide-react";
import { api } from "../api/client";
import { Badge, Button, Card, cx, Empty, ErrorBox, inputCls, PageHeader, Spinner, Tabs, useAsync, useToast } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

type Domain = "stock" | "operations" | "executive";

interface Decision { decision: "acknowledged" | "dismissed"; note: string; decided_by: string; decided_at: string; memory_id: number | null }
interface Alert {
  alert_id: number; alert_code: string; rule_name: string; agent: string; severity: "CRITICAL" | "WARNING" | "INFO";
  status: "OPEN" | "RESOLVED"; sku_code: string | null; product_name: string | null; location_name: string | null;
  document_ref: string | null; metric_value: number | null; threshold_value: number | null; message: string;
  details: Record<string, unknown>; raised_date: string | null; handled_by: string | null; handled_at: string | null;
  decision: Decision | null;
}
interface Rule {
  alert_code: string; rule_name: string; description: string; agent: string; threshold: string; is_active: boolean;
  current_settings: string | null; open: number; critical: number; warning: number; undecided: number;
}
interface Run { run_id: number; agent: string; data_as_of_date: string; status: string; finished_at: string | null; notes: string | null }
interface Briefing { id: number; as_of: string | null; text: string; written_by: string; cost_inr: number | null; created_by: string; created_at: string }
interface Summary { available: boolean; rules: Rule[]; runs: Run[]; open: number; critical?: number; undecided?: number; as_of?: string | null; briefing: Briefing | null }

const AGENT_OF: Record<Domain, string | null> = { stock: "STOCK", operations: "OPERATIONS", executive: null };
const SEV_TONE: Record<string, "red" | "amber" | "slate"> = { CRITICAL: "red", WARNING: "amber", INFO: "slate" };
const SEV_LABEL: Record<string, string> = { CRITICAL: "Critical", WARNING: "Warning", INFO: "Info" };

/** Alerts from the stock and operations rules (run in the warehouse after each data build), decisions on them and the
 * executive briefing. For workspace admins (Phase 7). */
export default function AlertsPage() {
  const { ws, base } = useWs();
  const nav = useNavigate();
  const [tab, setTab] = useState<Domain>("executive");
  const [status, setStatus] = useState("OPEN");
  const [q, setQ] = useState("");
  const [rule, setRule] = useState("");
  const [undecidedOnly, setUndecidedOnly] = useState(false);
  const summary = useAsync(() => api.get<Summary>(`/workspaces/${ws.id}/agents/summary`), [ws.id]);
  const list = useAsync(() => api.get<Alert[]>(`/workspaces/${ws.id}/agents/alerts?status=${status}${tab === "executive" ? "" : `&domain=${tab}`}`), [ws.id, tab, status]);

  if (summary.error && String(summary.error).includes("switched off")) {
    return <div><PageHeader title="Alerts" /><Empty title="Alerts are switched off">An administrator turns them on with ASSISTANT_SCHEDULED.</Empty></div>;
  }
  if (summary.error) return <div><PageHeader title="Alerts" /><ErrorBox error={summary.error} /></div>;
  if (summary.loading || !summary.data) return <Spinner />;
  const s = summary.data;
  if (!s.available) {
    return <div><PageHeader title="Alerts" /><Empty icon={<BellRing className="h-6 w-6" />} title="No alerts yet">
      The warehouse writes alerts after each build (<code>python dw.py agents run all</code>); import its views with scripts/configure_warehouse_workspace.py.</Empty></div>;
  }
  const agent = AGENT_OF[tab];
  const rules = s.rules.filter((r) => !agent || r.agent === agent);
  const shown = (list.data || []).filter((a) => (!rule || a.alert_code === rule) && (!undecidedOnly || !a.decision)
    && (!q.trim() || `${a.message} ${a.sku_code || ""} ${a.document_ref || ""}`.toLowerCase().includes(q.trim().toLowerCase())));
  const explain = (question: string) => nav(`${base}/ask`, { state: { question, domain: tab } });
  const reload = () => { summary.reload(); list.reload(); };

  return (
    <div>
      <PageHeader title="Alerts"
        subtitle={<>Raised by fixed rules in the data warehouse after each data build{s.as_of ? <>, on data up to <b>{s.as_of}</b></> : null}. Acknowledge or dismiss each one; your decisions are remembered by the assistants.</>}
        actions={<Button onClick={() => explain(tab === "executive" ? "What needs my attention first among the open alerts?" : `Which ${tab} alerts matter most, and why?`)}>
          <MessageSquareText className="h-4 w-4" /> Ask the {tab === "executive" ? "executive" : tab} assistant</Button>} />
      <Tabs tabs={[{ id: "executive", label: "Everything" }, { id: "stock", label: "Stock" }, { id: "operations", label: "Operations" }]}
        value={tab} onChange={(t) => { setTab(t as Domain); setRule(""); }} />

      {tab === "executive" && <BriefingCard wsId={ws.id} briefing={s.briefing} onDone={reload} />}

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {rules.map((r) => (
          <button key={r.alert_code} onClick={() => setRule(rule === r.alert_code ? "" : r.alert_code)}
            className={cx("rounded-lg border bg-white p-3 text-left shadow-sm hover:border-brand-300", rule === r.alert_code ? "border-brand-400 ring-1 ring-brand-300" : "border-slate-200")}>
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-slate-400">{r.alert_code}</span>
              <span className="font-medium text-slate-800">{r.rule_name}</span>
              {!r.is_active && <Badge>Off</Badge>}
            </div>
            <div className="mt-1 text-2xl font-semibold text-slate-900">{r.open}<span className="ml-1 text-sm font-normal text-slate-500">open</span></div>
            <div className="mt-0.5 text-xs text-slate-500">{r.critical > 0 && <span className="text-red-700">{r.critical} critical · </span>}{r.undecided} not decided</div>
            <div className="mt-1.5 text-xs text-slate-500">{r.description}.{r.current_settings && <> Threshold: <code className="text-[11px]">{r.current_settings}</code></>}</div>
          </button>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[12rem] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search product, SKU, location or PO" className={cx(inputCls, "pl-8")} />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-md border border-slate-300 px-2 py-1.5 text-sm">
          <option value="OPEN">Open</option><option value="RESOLVED">Resolved</option><option value="ALL">All</option>
        </select>
        <label className="flex items-center gap-1.5 text-sm text-slate-600"><input type="checkbox" checked={undecidedOnly} onChange={(e) => setUndecidedOnly(e.target.checked)} /> Not decided only</label>
        <span className="text-xs text-slate-500">{shown.length} shown</span>
      </div>

      <div className="mt-3 flex flex-col gap-2">
        {list.loading && <Spinner />}
        {list.error && <ErrorBox error={list.error} />}
        {!list.loading && shown.length === 0 && <Empty icon={<BellRing className="h-6 w-6" />} title="Nothing here">No alerts match.</Empty>}
        {shown.slice(0, 300).map((a) => <AlertRow key={a.alert_id} wsId={ws.id} a={a} onExplain={explain} onChange={reload} />)}
        {shown.length > 300 && <div className="text-center text-xs text-slate-500">Showing the first 300; search or pick a rule to narrow the list.</div>}
      </div>

      <RunsLine runs={s.runs} />
    </div>
  );
}

function AlertRow({ wsId, a, onExplain, onChange }: { wsId: number; a: Alert; onExplain: (q: string) => void; onChange: () => void }) {
  const toast = useToast();
  const [deciding, setDeciding] = useState<null | "acknowledged" | "dismissed">(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!deciding) return;
    setBusy(true);
    try {
      await api.post(`/workspaces/${wsId}/agents/alerts/${a.alert_id}/decision`, { decision: deciding, note });
      toast("success", deciding === "acknowledged" ? "Acknowledged" : "Dismissed");
      setDeciding(null);
      setNote("");
      onChange();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={cx("rounded-lg border bg-white px-3 py-2.5 shadow-sm", a.decision ? "border-slate-200 opacity-80" : "border-slate-200")}>
      <div className="flex flex-wrap items-start gap-2">
        <Badge tone={SEV_TONE[a.severity]}>{SEV_LABEL[a.severity] || a.severity}</Badge>
        <span className="text-xs text-slate-400">#{a.alert_id} · {a.rule_name}</span>
        {a.status === "RESOLVED" && <Badge tone="green">Resolved{a.handled_at ? ` ${String(a.handled_at).slice(0, 10)}` : ""}</Badge>}
        {a.decision && <Badge tone={a.decision.decision === "acknowledged" ? "blue" : "slate"}>
          {a.decision.decision === "acknowledged" ? "Acknowledged" : "Dismissed"} by {a.decision.decided_by} {timeAgo(a.decision.decided_at)}</Badge>}
        <span className="ml-auto text-xs text-slate-400">{a.raised_date ? `raised ${a.raised_date}` : ""}</span>
      </div>
      <div className="mt-1 text-sm text-slate-800">{a.message}</div>
      {a.decision?.note && <div className="mt-1 text-xs text-slate-600">Note: {a.decision.note}</div>}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => onExplain(`Explain alert #${a.alert_id}: why was it raised, and what should I check?`)}>
          <MessageSquareText className="h-3.5 w-3.5" /> Explain</Button>
        {a.status === "OPEN" && !deciding && <>
          <Button size="sm" onClick={() => setDeciding("acknowledged")}><Check className="h-3.5 w-3.5" /> Acknowledge</Button>
          <Button size="sm" onClick={() => setDeciding("dismissed")}><X className="h-3.5 w-3.5" /> Dismiss</Button>
        </>}
      </div>
      {deciding && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input autoFocus value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000}
            placeholder={deciding === "acknowledged" ? "What will be done (optional), e.g. PO raised in the ERP" : "Why it can be ignored (optional), e.g. supplier confirmed dispatch"}
            className={cx(inputCls, "min-w-[16rem] flex-1")} onKeyDown={(e) => { if (e.key === "Enter") save(); }} />
          <Button size="sm" variant="primary" loading={busy} onClick={save}>{deciding === "acknowledged" ? "Acknowledge" : "Dismiss"}</Button>
          <Button size="sm" onClick={() => { setDeciding(null); setNote(""); }}>Cancel</Button>
        </div>
      )}
    </div>
  );
}

function BriefingCard({ wsId, briefing, onDone }: { wsId: number; briefing: Briefing | null; onDone: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const write = async () => {
    setBusy(true);
    try {
      await api.post(`/workspaces/${wsId}/agents/briefing`, {});
      onDone();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="mt-4" title={<span className="inline-flex items-center gap-1.5"><FileText className="h-4 w-4" /> Executive briefing</span>}
      actions={<Button size="sm" loading={busy} onClick={write}><RefreshCw className="h-3.5 w-3.5" /> {briefing ? "Bring up to date" : "Write the briefing"}</Button>}>
      {!briefing && <div className="text-sm text-slate-500">No briefing yet. It brings together the headline numbers, the open alerts, what stands out on the dashboards and the serious data issues; every number in it is computed by the app.</div>}
      {briefing && <>
        <BriefingText text={briefing.text} />
        <div className="mt-2 text-xs text-slate-400">
          {briefing.as_of && <>Data to {briefing.as_of} · </>}written {timeAgo(briefing.created_at)}{" "}
          {briefing.written_by === "code" ? "from the facts (no AI)" : `by ${briefing.written_by.includes("sonnet") ? "Claude Sonnet 5.5" : briefing.written_by}`}
          {briefing.cost_inr ? ` · ₹${briefing.cost_inr.toFixed(2)}` : ""}. "Bring up to date" reuses it when nothing has changed.
        </div>
      </>}
    </Card>
  );
}

/** **bold**, "- " bullets and paragraphs; nothing else is interpreted (the text is shown as text). */
function BriefingText({ text }: { text: string }) {
  const inline = (s: string): ReactNode[] => s.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : <Fragment key={i}>{p}</Fragment>);
  const blocks = text.split(/\n\s*\n/);
  return (
    <div className="space-y-2 text-sm leading-relaxed text-slate-800">
      {blocks.map((b, i) => {
        const lines = b.split("\n").filter((l) => l.trim());
        const bullets = lines.filter((l) => /^\s*[-•]\s/.test(l));
        if (bullets.length && bullets.length >= lines.length - 1) {
          const head = lines.find((l) => !/^\s*[-•]\s/.test(l));
          return <div key={i}>{head && <div>{inline(head)}</div>}<ul className="ml-5 list-disc">{bullets.map((l, k) => <li key={k}>{inline(l.replace(/^\s*[-•]\s/, ""))}</li>)}</ul></div>;
        }
        return <p key={i}>{lines.map((l, k) => <Fragment key={k}>{k > 0 && <br />}{inline(l)}</Fragment>)}</p>;
      })}
    </div>
  );
}

function RunsLine({ runs }: { runs: Run[] }) {
  if (!runs.length) return null;
  return (
    <div className="mt-6 text-xs text-slate-500">
      Latest runs: {runs.map((r, i) => <span key={r.run_id}>{i > 0 && " · "}{r.agent.toLowerCase()} run {r.run_id} {r.status === "SUCCEEDED" ? "succeeded" : <b className="text-red-700">{r.status.toLowerCase()}</b>}
        {r.finished_at ? ` ${timeAgo(r.finished_at)}` : ""} (data to {String(r.data_as_of_date).slice(0, 10)})</span>)}
    </div>
  );
}
