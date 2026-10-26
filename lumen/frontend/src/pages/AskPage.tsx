import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { Bot, Info, LayoutDashboard, MessageSquarePlus, PencilRuler, Send, Trash2, User } from "lucide-react";
import { api, QueryResult } from "../api/client";
import { ResultPanel } from "../components/ResultPanel";
import { Badge, cx, Spinner, useAsync, useToast } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

interface Answer extends Partial<QueryResult> {
  type: "answer" | "clarify" | "dashboard" | "help" | "error";
  text: string; title?: string; chart_type?: string; spec?: any; assumptions?: string[]; suggestions?: string[];
  engine?: string; dashboard_id?: number; conversation_id?: number; message_id?: number;
  model?: string; model_label?: string; routing?: string[]; escalated?: boolean;
}
interface Msg { id?: number; role: "user" | "assistant"; content: string; payload?: Answer }

export default function AskPage() {
  const { ws, base } = useWs();
  const { convId } = useParams();
  const nav = useNavigate();
  const loc = useLocation() as { state?: { question?: string } };
  const toast = useToast();
  const convs = useAsync(() => api.get<{ id: number; title: string; updated_at: string; message_count: number }[]>(`/workspaces/${ws.id}/conversations`), [ws.id]);
  const me = useAsync(() => api.get<{ llm: { enabled: boolean; model: string | null; provider?: string | null; simple_model?: string; complex_model?: string } }>("/me"), []);
  const sugg = useAsync(() => api.get<string[]>(`/workspaces/${ws.id}/assistant/suggestions`), [ws.id]);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [engine, setEngine] = useState("auto");
  const [conv, setConv] = useState<number | null>(convId ? Number(convId) : null);
  const endRef = useRef<HTMLDivElement>(null);
  const asked = useRef(false);

  useEffect(() => {
    if (!convId) {
      setMsgs([]);
      setConv(null);
      return;
    }
    api.get<{ messages: Msg[] }>(`/workspaces/${ws.id}/conversations/${convId}`).then((c) => {
      setMsgs(c.messages);
      setConv(Number(convId));
    }).catch((e) => toast("error", e.message));
  }, [convId, ws.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, busy]);

  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", content: question }]);
    setBusy(true);
    try {
      const a = await api.post<Answer>(`/workspaces/${ws.id}/assistant/ask`, { question, conversation_id: conv, engine });
      setMsgs((m) => [...m, { role: "assistant", content: a.text, payload: a }]);
      if (!conv && a.conversation_id) {
        setConv(a.conversation_id);
        nav(`${base}/ask/${a.conversation_id}`, { replace: true });
      }
      convs.reload();
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "assistant", content: e.message, payload: { type: "error", text: e.message } }]);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (loc.state?.question && !asked.current) {
      asked.current = true;
      ask(loc.state.question);
      window.history.replaceState({}, "");
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const delConv = async (id: number) => {
    await api.del(`/workspaces/${ws.id}/conversations/${id}`);
    convs.reload();
    if (id === conv) nav(`${base}/ask`);
  };

  return (
    <div className="-my-5 -mx-6 flex h-[calc(100vh)]">
      <div className="no-print hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
        <button onClick={() => nav(`${base}/ask`)} className="m-3 flex items-center justify-center gap-1.5 rounded-md border border-slate-300 py-1.5 text-sm hover:bg-slate-50">
          <MessageSquarePlus className="h-4 w-4" /> New conversation
        </button>
        <div className="flex-1 overflow-y-auto px-2 pb-3">
          {(convs.data || []).map((c) => (
            <div key={c.id} className={cx("group flex items-center gap-1 rounded-md px-2 py-1.5 text-sm", c.id === conv ? "bg-brand-50 text-brand-800" : "hover:bg-slate-50")}>
              <Link to={`${base}/ask/${c.id}`} className="min-w-0 flex-1">
                <div className="truncate">{c.title}</div>
                <div className="text-[10px] text-slate-400">{timeAgo(c.updated_at)}</div>
              </Link>
              <button onClick={() => delConv(c.id)} className="hidden text-slate-400 hover:text-red-600 group-hover:block"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          ))}
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="mx-auto max-w-4xl">
            {msgs.length === 0 && (
              <div className="py-10 text-center">
                <Bot className="mx-auto mb-3 h-10 w-10 text-brand-500" />
                <h2 className="text-lg font-semibold text-slate-800">Ask anything about {ws.name}</h2>
                <p className="mx-auto mt-1 max-w-lg text-sm text-slate-500">Answers are computed from your data with governed metric definitions. Every answer shows the SQL that produced it. Follow-up questions keep the context.</p>
                <div className="mt-5 flex flex-wrap justify-center gap-2">
                  {[...(sugg.data || []), "Create a dashboard showing monthly sales, returns and inventory"].slice(0, 7).map((s) => (
                    <button key={s} onClick={() => ask(s)} className="rounded-full border border-slate-200 bg-white px-3 py-1 text-sm text-slate-700 shadow-sm hover:border-brand-300 hover:text-brand-700">{s}</button>
                  ))}
                </div>
              </div>
            )}
            {msgs.map((m, i) => <Message key={i} m={m} onAsk={ask} />)}
            {busy && <div className="flex items-center gap-2 py-3 text-sm text-slate-500"><Bot className="h-5 w-5 text-brand-500" /> <Spinner label="Analysing…" /></div>}
            <div ref={endRef} />
          </div>
        </div>
        <div className="no-print border-t border-slate-200 bg-white px-6 py-3">
          <form onSubmit={(e) => { e.preventDefault(); ask(input); }} className="mx-auto flex max-w-4xl items-center gap-2">
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder={conv ? "Ask a follow-up… (e.g. “only Amazon”, “by category”, “as a pie”)" : "Ask a question about your data…"}
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2.5 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500" />
            <select value={engine} onChange={(e) => setEngine(e.target.value)} className="rounded-md border border-slate-300 px-2 py-2 text-xs" title="Answer engine">
              <option value="auto">Auto</option>
              <option value="semantic">Semantic engine</option>
              <option value="llm" disabled={!me.data?.llm.enabled}>{me.data?.llm.provider === "anthropic" ? "Claude (auto-routed)" : `LLM ${me.data?.llm.enabled ? `(${me.data.llm.model})` : "(not configured)"}`}</option>
            </select>
            <button disabled={busy || !input.trim()} className="rounded-lg bg-brand-600 p-2.5 text-white hover:bg-brand-700 disabled:opacity-50" aria-label="Send"><Send className="h-4 w-4" /></button>
          </form>
          <div className="mx-auto mt-1 max-w-4xl text-[11px] text-slate-400">
            {me.data?.llm.provider === "anthropic" ? `Claude: ${me.data.llm.simple_model} for everyday questions, ${me.data.llm.complex_model} for complex ones. Answers use your metric definitions; any SQL is validated and run read-only.` : me.data?.llm.enabled ? `LLM: ${me.data.llm.model} — used as a fallback in Auto mode; all generated SQL is validated and run read-only.` : "Offline semantic engine (no LLM configured). Add synonyms and metrics in the Semantic layer to teach it your vocabulary."}
          </div>
        </div>
      </div>
    </div>
  );
}

function Message({ m, onAsk }: { m: Msg; onAsk: (q: string) => void }) {
  const { ws, base } = useWs();
  const nav = useNavigate();
  const [chart, setChart] = useState(m.payload?.chart_type || "table");
  if (m.role === "user") {
    return (
      <div className="mb-4 flex justify-end">
        <div className="flex max-w-[80%] items-start gap-2 rounded-2xl rounded-tr-sm bg-brand-600 px-4 py-2 text-sm text-white"><span>{m.content}</span><User className="mt-0.5 h-4 w-4 shrink-0 opacity-70" /></div>
      </div>
    );
  }
  const p = m.payload || ({ type: "answer", text: m.content } as Answer);
  const hasData = p.type === "answer" && p.columns && p.rows;
  return (
    <div className="mb-6 flex gap-3">
      <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-100"><Bot className="h-4 w-4 text-brand-700" /></div>
      <div className="min-w-0 flex-1">
        <div className={cx("rounded-2xl rounded-tl-sm border px-4 py-3 text-sm", p.type === "error" ? "border-red-200 bg-red-50 text-red-800" : p.type === "clarify" ? "border-amber-200 bg-amber-50 text-slate-800" : "border-slate-200 bg-white text-slate-800")}>
          {p.title && hasData && <div className="mb-1 font-semibold text-slate-900">{p.title}</div>}
          <div className="leading-relaxed">{m.content}</div>
          {p.assumptions && p.assumptions.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">{p.assumptions.map((a, i) => <span key={i} className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600"><Info className="h-3 w-3" />{a}</span>)}</div>
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
            <ResultPanel res={p as QueryResult} chartType={chart} onChartType={setChart} spec={p.spec} title={p.title || "AI answer"} wsId={ws.id} height={320} />
            <div className="mt-2 flex items-center gap-3 text-[11px] text-slate-400">
              <Badge tone={p.engine === "claude" || p.engine === "llm" ? "violet" : "blue"}>{p.engine === "claude" ? `${p.model_label}${p.escalated ? " (escalated)" : ""}` : p.engine === "llm" ? "LLM-generated SQL" : "offline semantic engine"}</Badge>
              {p.engine === "claude" && p.routing && p.routing.length > 0 && <span title={p.routing.join(" · ")}>{p.spec ? "governed metrics" : "validated SQL"} · {p.routing[p.routing.length - 1]}</span>}
              {p.spec && <button onClick={() => nav(`${base}/reports/new`, { state: { spec: p.spec, chart, title: p.title } })} className="inline-flex items-center gap-1 text-brand-600 hover:underline"><PencilRuler className="h-3 w-3" /> Open in report builder</button>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
