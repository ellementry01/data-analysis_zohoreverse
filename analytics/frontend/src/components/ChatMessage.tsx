import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bot, Info, LayoutDashboard, PencilRuler, ThumbsDown, ThumbsUp, User } from "lucide-react";
import { QueryResult } from "../api/client";
import { ResultPanel } from "./ResultPanel";
import { Badge, cx } from "./ui";

export interface Answer extends Partial<QueryResult> {
  type: "answer" | "clarify" | "dashboard" | "help" | "error";
  text: string; title?: string; chart_type?: string; spec?: any; assumptions?: string[]; suggestions?: string[];
  engine?: string; dashboard_id?: number; conversation_id?: number; message_id?: number;
  model?: string; model_label?: string; routing?: string[]; escalated?: boolean;
}
export interface Msg { id?: number; role: "user" | "assistant"; content: string; payload?: Answer; feedback?: "up" | "down" | null }

/** One chat message: the user's question, or an answer with its chart, assumptions and where it came from. */
export function ChatMessage({ m, onAsk, wsId, base, compact = false, onFeedback }:
  { m: Msg; onAsk: (q: string) => void; wsId: number; base: string; compact?: boolean; onFeedback?: (f: "up" | "down" | null) => void }) {
  const nav = useNavigate();
  const [chart, setChart] = useState(m.payload?.chart_type || "table");
  if (m.role === "user") {
    return (
      <div className="mb-4 flex justify-end">
        <div className={cx("flex items-start gap-2 rounded-2xl rounded-tr-sm bg-brand-600 px-4 py-2 text-sm text-white", compact ? "max-w-[90%]" : "max-w-[80%]")}>
          <span>{m.content}</span><User className="mt-0.5 h-4 w-4 shrink-0 opacity-70" />
        </div>
      </div>
    );
  }
  const p = m.payload || ({ type: "answer", text: m.content } as Answer);
  const hasData = p.type === "answer" && p.columns && p.rows;
  return (
    <div className={cx("flex gap-3", compact ? "mb-4" : "mb-6")}>
      {!compact && <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-100"><Bot className="h-4 w-4 text-brand-700" /></div>}
      <div className="min-w-0 flex-1">
        <div className={cx("rounded-2xl rounded-tl-sm border px-4 py-3 text-sm", p.type === "error" ? "border-red-200 bg-red-50 text-red-800" : p.type === "clarify" ? "border-amber-200 bg-amber-50 text-slate-800" : "border-slate-200 bg-white text-slate-800")}>
          {p.title && hasData && <div className="mb-1 font-semibold text-slate-900">{p.title}</div>}
          <div className="leading-relaxed">{m.content}</div>
          {p.assumptions && p.assumptions.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">{p.assumptions.map((a, i) => <span key={i} className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600"><Info className="h-3 w-3 shrink-0" />{a}</span>)}</div>
          )}
          {p.type === "dashboard" && p.dashboard_id && (
            <Link to={`${base}/dashboards/${p.dashboard_id}`} className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-700"><LayoutDashboard className="h-3.5 w-3.5" /> Open dashboard</Link>
          )}
          {p.suggestions && p.suggestions.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">{p.suggestions.map((s) => <button key={s} onClick={() => onAsk(s)} className="rounded-full border border-brand-200 bg-white px-2.5 py-0.5 text-xs text-brand-700 hover:bg-brand-50">{s}</button>)}</div>
          )}
        </div>
        {hasData && (
          <div className="mt-2 rounded-xl border border-slate-200 bg-white p-3 shadow-card">
            <ResultPanel res={p as QueryResult} chartType={chart} onChartType={setChart} spec={p.spec} title={p.title || "AI answer"} wsId={wsId} height={compact ? 240 : 320} />
          </div>
        )}
        <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
          {p.engine && <Badge tone={p.engine === "claude" || p.engine === "llm" ? "violet" : "blue"}>{p.engine === "claude" ? `${p.model_label}${p.escalated ? " (escalated)" : ""}` : p.engine === "llm" ? "LLM-generated SQL" : "offline semantic engine"}</Badge>}
          {p.engine === "claude" && p.routing && p.routing.length > 0 && hasData && <span title={p.routing.join(" · ")}>{p.spec ? "governed metrics" : "validated SQL"}</span>}
          {hasData && p.spec && <button onClick={() => nav(`${base}/reports/new`, { state: { spec: p.spec, chart, title: p.title } })} className="inline-flex items-center gap-1 text-brand-600 hover:underline"><PencilRuler className="h-3 w-3" /> Open in report builder</button>}
          {onFeedback && m.id && (
            <span className="ml-auto inline-flex items-center gap-1">
              <button aria-label="Good answer" title="Good answer" onClick={() => onFeedback(m.feedback === "up" ? null : "up")}
                className={cx("rounded p-0.5 hover:bg-slate-100", m.feedback === "up" ? "text-green-600" : "hover:text-slate-700")}><ThumbsUp className="h-3.5 w-3.5" /></button>
              <button aria-label="Bad answer" title="Bad answer" onClick={() => onFeedback(m.feedback === "down" ? null : "down")}
                className={cx("rounded p-0.5 hover:bg-slate-100", m.feedback === "down" ? "text-red-600" : "hover:text-slate-700")}><ThumbsDown className="h-3.5 w-3.5" /></button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
