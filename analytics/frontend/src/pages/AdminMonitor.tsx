import { useState } from "react";
import { ChevronDown, ChevronRight, ThumbsDown } from "lucide-react";
import { api } from "../api/client";
import { Badge, Card, inputCls, Spinner, useAsync } from "../components/ui";

interface Monitor {
  days: number; since: string;
  cost: {
    total_inr: number; calls: number;
    by_day: { day: string; cost_inr: number; calls: number }[];
    by_user: { user: string; cost_inr: number; calls: number; questions: number; rate_limited: number }[];
    by_purpose: { purpose: string; cost_inr: number; calls: number }[];
    by_model: { model: string; cost_inr: number; calls: number }[];
  };
  answers: { count: number; median_seconds: number | null; p95_seconds: number | null; with_number_warnings: number;
    thumbs_up: number; thumbs_down: number; capped: boolean;
    by_engine: { engine: string; count: number; median_seconds: number | null; p95_seconds: number | null }[] };
  tools: { tool: string; calls: number; errors: number; last_error: string | null; last_error_at: string | null }[];
  jobs: { by_status: Record<string, number>; oldest_waiting_seconds: number;
    recent_failures: { id: number; kind: string; attempts: number; error: string; at: string }[] };
}
interface Down { message_id: number; conversation_id: number; workspace_id: number; user: string; scope: string; at: string;
  question: string; answer: string; note: string; model: string; seconds: number | null; warnings: string[];
  steps: { n: number; tool: string; label: string; ok: boolean; error: string | null; input: any; row_count: number | null }[] }
interface EvalRun { id: number; set_name: string; live: boolean; total: number; passed: number; pass_rate: number | null;
  numbers_checked: number; numbers_correct: number; invented: number; cost_inr: number; median_seconds: number | null;
  failures: { id: string; problems: string[] }[]; git_commit: string; note: string; created_at: string }

const rs = (n: number) => `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const secs = (n: number | null) => (n == null ? "–" : `${n.toLocaleString("en-IN")} s`);

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold text-slate-900">{value}</div>
      {hint && <div className="text-[11px] text-slate-400">{hint}</div>}
    </div>
  );
}

/** Phase 8 monitoring: what the assistants cost, how fast and how well they answer, and the evaluation history. */
export default function MonitorTab() {
  const [days, setDays] = useState(14);
  const mon = useAsync(() => api.get<Monitor>(`/admin/monitor?days=${days}`), [days]);
  const down = useAsync(() => api.get<Down[]>("/admin/monitor/thumbs-down?days=90"), []);
  const evals = useAsync(() => api.get<EvalRun[]>("/admin/eval-runs?limit=300"), []);
  const d = mon.data;
  const maxDay = Math.max(0.01, ...(d?.cost.by_day || []).map((x) => x.cost_inr));
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm text-slate-600">
        Last
        <select className={inputCls + " !w-28"} value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period">
          {[7, 14, 30, 90].map((n) => <option key={n} value={n}>{n} days</option>)}
        </select>
        {d && <span className="text-xs text-slate-400">since {d.since} (India time)</span>}
      </div>
      {mon.loading && <Spinner />}
      {d && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="AI cost" value={rs(d.cost.total_inr)} hint={`${d.cost.calls} Claude calls`} />
            <Stat label="Answers" value={d.answers.count.toLocaleString("en-IN")} hint={`${d.answers.thumbs_up} 👍 · ${d.answers.thumbs_down} 👎`} />
            <Stat label="Answer time" value={secs(d.answers.median_seconds)} hint={`median · slowest 5%: ${secs(d.answers.p95_seconds)}`} />
            <Stat label="Background queue" value={`${d.jobs.by_status.queued || 0} waiting`}
              hint={d.jobs.oldest_waiting_seconds ? `oldest ${Math.round(d.jobs.oldest_waiting_seconds / 60)} min` : `${d.jobs.by_status.failed || 0} failed in all`} />
          </div>

          <Card title="AI cost per day">
            <div className="flex h-32 items-end gap-1" role="img" aria-label="AI cost per day">
              {d.cost.by_day.map((x) => (
                <div key={x.day} className="group relative flex-1" title={`${x.day}: ${rs(x.cost_inr)}, ${x.calls} calls`}>
                  <div className="rounded-t bg-brand-500/80" style={{ height: `${Math.max(x.cost_inr ? 3 : 0, (x.cost_inr / maxDay) * 120)}px` }} />
                </div>
              ))}
            </div>
            <div className="mt-1 flex justify-between text-[11px] text-slate-400"><span>{d.cost.by_day[0]?.day}</span><span>{d.cost.by_day[d.cost.by_day.length - 1]?.day}</span></div>
          </Card>

          <div className="grid gap-4 md:grid-cols-2">
            <Card title="Per person">
              <table className="w-full text-xs">
                <thead className="text-left text-slate-500"><tr><th className="py-1">Person</th><th className="text-right">Questions</th><th className="text-right">Claude calls</th><th className="text-right">Cost</th><th className="text-right" title="Questions refused by the per-person limit">Limited</th></tr></thead>
                <tbody>
                  {d.cost.by_user.map((u) => (
                    <tr key={u.user} className="border-t border-slate-100"><td className="max-w-[12rem] truncate py-1" title={u.user}>{u.user}</td>
                      <td className="text-right">{u.questions}</td><td className="text-right">{u.calls}</td><td className="text-right">{rs(u.cost_inr)}</td>
                      <td className="text-right">{u.rate_limited ? <Badge tone="amber">{u.rate_limited}</Badge> : "–"}</td></tr>
                  ))}
                  {d.cost.by_user.length === 0 && <tr><td colSpan={5} className="py-2 text-slate-400">No questions in this period.</td></tr>}
                </tbody>
              </table>
            </Card>
            <Card title="By purpose and model">
              <table className="w-full text-xs">
                <tbody>
                  {d.cost.by_purpose.map((p) => <tr key={p.purpose} className="border-t border-slate-100 first:border-0"><td className="py-1">{p.purpose}</td><td className="text-right">{p.calls} calls</td><td className="text-right">{rs(p.cost_inr)}</td></tr>)}
                  {d.cost.by_model.map((p) => <tr key={p.model} className="border-t border-slate-100"><td className="py-1 text-slate-500">{p.model}</td><td className="text-right text-slate-500">{p.calls} calls</td><td className="text-right text-slate-500">{rs(p.cost_inr)}</td></tr>)}
                </tbody>
              </table>
              <div className="mt-3 text-xs text-slate-500">Answer time by engine:</div>
              <table className="w-full text-xs">
                <tbody>{d.answers.by_engine.map((e) => <tr key={e.engine} className="border-t border-slate-100"><td className="py-1">{e.engine}</td><td className="text-right">{e.count} answers</td><td className="text-right">median {secs(e.median_seconds)}</td><td className="text-right">slowest 5% {secs(e.p95_seconds)}</td></tr>)}</tbody>
              </table>
              {d.answers.with_number_warnings > 0 && <div className="mt-2 text-xs text-amber-700">{d.answers.with_number_warnings} answers carried a "numbers could not be traced" warning.</div>}
            </Card>
          </div>

          <Card title="Assistant tools">
            <table className="w-full text-xs">
              <thead className="text-left text-slate-500"><tr><th className="py-1">Tool</th><th className="text-right">Calls</th><th className="text-right">Errors</th><th className="pl-3">Latest error</th></tr></thead>
              <tbody>
                {d.tools.map((t) => (
                  <tr key={t.tool} className="border-t border-slate-100 align-top"><td className="py-1 font-mono">{t.tool}</td><td className="text-right">{t.calls}</td>
                    <td className="text-right">{t.errors ? <span className="text-red-600">{t.errors} ({Math.round((100 * t.errors) / t.calls)}%)</span> : 0}</td>
                    <td className="pl-3 text-slate-500">{t.last_error ? `${t.last_error_at?.slice(0, 10)}: ${t.last_error}` : ""}</td></tr>
                ))}
                {d.tools.length === 0 && <tr><td colSpan={4} className="py-2 text-slate-400">No tool calls in this period.</td></tr>}
              </tbody>
            </table>
            {d.jobs.recent_failures.length > 0 && (
              <div className="mt-3 text-xs"><div className="mb-1 text-slate-500">Background jobs that failed:</div>
                {d.jobs.recent_failures.map((j) => <div key={j.id} className="text-red-700">#{j.id} {j.kind} ({j.attempts} tries, {j.at.slice(0, 10)}): {j.error}</div>)}</div>
            )}
          </Card>
        </>
      )}

      <Card title="Answers marked wrong (last 90 days)">
        {down.loading && <Spinner />}
        {(down.data || []).length === 0 && !down.loading && <div className="text-sm text-slate-400">No thumbs-down answers.</div>}
        {(down.data || []).map((x) => <DownRow key={x.message_id} x={x} />)}
      </Card>

      <Card title="Evaluation runs">
        <p className="mb-2 text-xs text-slate-500">Each run of an evaluation set (<code className="rounded bg-slate-100 px-1">python -m evals run</code>). Live runs use Claude; the release gate (<code className="rounded bg-slate-100 px-1">python -m evals gate</code>) checks the latest live run of each set against its pass mark.</p>
        {evals.loading && <Spinner />}
        <table className="w-full text-xs">
          <thead className="text-left text-slate-500"><tr><th className="py-1">When</th><th>Set</th><th></th><th className="text-right">Passed</th><th className="text-right">Numbers right</th><th className="text-right">Invented</th><th className="text-right">Cost</th><th className="pl-3">Note</th></tr></thead>
          <tbody>
            {(evals.data || []).map((r) => (
              <tr key={r.id} className="border-t border-slate-100 align-top">
                <td className="py-1 whitespace-nowrap">{r.created_at.slice(0, 10)}</td><td className="font-mono">{r.set_name}</td>
                <td>{r.live ? <Badge tone="violet">live</Badge> : <Badge>offline</Badge>}</td>
                <td className="text-right">{r.passed}/{r.total}</td>
                <td className="text-right">{r.numbers_checked ? `${r.numbers_correct}/${r.numbers_checked}` : "–"}</td>
                <td className="text-right">{r.invented ? <span className="text-red-600">{r.invented}</span> : 0}</td>
                <td className="text-right">{r.cost_inr ? rs(r.cost_inr) : "–"}</td>
                <td className="pl-3 text-slate-500" title={r.failures.map((f) => `${f.id}: ${f.problems.join("; ")}`).join("\n")}>{r.note}{r.failures.length ? ` (${r.failures.length} failed)` : ""}</td>
              </tr>
            ))}
            {!evals.loading && (evals.data || []).length === 0 && <tr><td colSpan={8} className="py-2 text-slate-400">No runs recorded yet.</td></tr>}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function DownRow({ x }: { x: Down }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-slate-100 py-2 text-sm last:border-0">
      <button className="flex w-full items-start gap-2 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" /> : <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />}
        <ThumbsDown className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
        <span className="min-w-0 flex-1"><span className="font-medium text-slate-800">{x.question || "(no question)"}</span>
          <span className="block text-xs text-slate-500">{x.user} · {x.scope} · {x.at.slice(0, 16).replace("T", " ")} · {x.model}{x.seconds != null ? ` · ${x.seconds} s` : ""}{x.note ? ` · “${x.note}”` : ""}</span></span>
      </button>
      {open && (
        <div className="ml-12 mt-2 space-y-2 text-xs">
          <div className="whitespace-pre-wrap rounded bg-slate-50 p-2 text-slate-700">{x.answer}</div>
          {x.warnings.map((w, i) => <div key={i} className="text-amber-700">{w}</div>)}
          {x.steps.length > 0 && (
            <ol className="space-y-1">
              {x.steps.map((s) => (
                <li key={s.n}><span className={s.ok ? "text-slate-700" : "text-red-600"}>{s.n}. {s.label || s.tool}</span>
                  {s.row_count != null && <span className="text-slate-400"> · {s.row_count} rows</span>}
                  {s.error && <span className="text-red-600"> · {s.error}</span>}
                  <code className="mt-0.5 block break-all text-[11px] text-slate-400">{s.tool}({JSON.stringify(s.input)})</code></li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}
