import { useEffect, useRef, useState } from "react";
import { Bot, History, MessageSquarePlus, Send, Target, Trash2, X } from "lucide-react";
import { api, DashFilter, Dashboard, Widget } from "../api/client";
import { timeAgo } from "../lib/format";
import { Answer, ChatMessage, Msg, Step, StepList } from "./ChatMessage";
import { cx, Spinner, useAsync, useToast } from "./ui";

export interface DrillState { [widgetId: number]: { field: string; value: any }[] }

interface Thread { id: number; title: string; updated_at: string; message_count: number }

const STARTERS = ["What does this dashboard show?", "What stands out on this dashboard?", "Which caveats should I keep in mind here?"];

/** The dashboard's own assistant: it already knows the dashboard and what is on screen, so questions need no context. */
export function AssistantPanel({ wsId, base, dash, filters, drill, focus, onClearFocus, onClose, streaming = false }:
  { wsId: number; base: string; dash: Dashboard; filters: DashFilter[]; drill: DrillState; focus: Widget | null;
    onClearFocus: () => void; onClose: () => void; streaming?: boolean }) {
  const toast = useToast();
  const root = `/workspaces/${wsId}/dashboards/key/${encodeURIComponent(dash.key)}/assistant`;
  const threads = useAsync(() => api.get<Thread[]>(`${root}/conversations`), [root]);
  const [conv, setConv] = useState<number | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [showThreads, setShowThreads] = useState(false);
  const [live, setLive] = useState<Step[]>([]);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy, live.length]);
  useEffect(() => { if (focus) inputRef.current?.focus(); }, [focus?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const open = async (id: number) => {
    try {
      const c = await api.get<{ messages: Msg[] }>(`/workspaces/${wsId}/conversations/${id}`);
      setMsgs(c.messages);
      setConv(id);
      setShowThreads(false);
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const fresh = () => { setConv(null); setMsgs([]); setShowThreads(false); };
  const remove = async (id: number) => {
    await api.del(`/workspaces/${wsId}/conversations/${id}`);
    threads.reload();
    if (id === conv) fresh();
  };

  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", content: focus ? `About “${focus.title}”: ${question}` : question }]);
    setBusy(true);
    const screen_state = {
      filters: filters.filter((f) => f.id !== "__drill").map((f) => ({ id: f.id, value: f.value })),
      drill: Object.fromEntries(Object.entries(drill).filter(([, s]) => s.length > 0)),
      focus_widget_id: focus?.id ?? null,
    };
    const done = (a: Answer) => {
      setMsgs((m) => [...m, { id: a.message_id, role: "assistant", content: a.text, payload: a }]);
      if (a.conversation_id && a.conversation_id !== conv) setConv(a.conversation_id);
      threads.reload();
    };
    try {
      if (streaming) {
        // multi-step answers: show each step as it happens
        setLive([]);
        let answered = false;
        let failure: string | null = null;
        await api.stream(`${root}/ask/stream`, { question, conversation_id: conv, screen_state }, (e) => {
          if (e.type === "step") setLive((s) => [...s, { n: e.n, tool: e.tool, label: e.label }]);
          else if (e.type === "step_done") setLive((s) => s.map((x) => (x.n === e.n ? { ...x, ok: e.ok, label: e.label, row_count: e.rows } : x)));
          else if (e.type === "checking") setLive((s) => [...s, { n: 99, tool: "check", label: e.label }]);
          else if (e.type === "answer") { answered = true; done(e.answer); }
          else if (e.type === "error") failure = e.detail;
        });
        if (failure) throw new Error(failure);
        if (!answered) throw new Error("The answer was interrupted; please ask again.");
      } else {
        done(await api.post<Answer>(`${root}/ask`, { question, conversation_id: conv, screen_state }));
      }
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "assistant", content: e.message, payload: { type: "error", text: e.message } }]);
    } finally {
      setBusy(false);
      setLive([]);
    }
  };

  const rate = async (i: number, m: Msg, feedback: "up" | "down" | null) => {
    if (!conv || !m.id) return;
    try {
      await api.post(`/workspaces/${wsId}/conversations/${conv}/messages/${m.id}/feedback`, { feedback });
      setMsgs((all) => all.map((x, k) => (k === i ? { ...x, feedback } : x)));
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  return (
    <aside className="no-print fixed inset-0 z-40 flex flex-col bg-slate-50 lg:sticky lg:inset-auto lg:top-0 lg:z-auto lg:h-[calc(100vh-2.5rem)] lg:w-[420px] lg:shrink-0 lg:rounded-lg lg:border lg:border-slate-200 lg:shadow-card"
      aria-label={`Assistant for ${dash.name}`}>
      <div className="flex items-center gap-2 border-b border-slate-200 bg-white px-3 py-2 lg:rounded-t-lg">
        <Bot className="h-4 w-4 text-brand-600" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-slate-800">Ask about {dash.name}</div>
          <div className="text-[11px] text-slate-400">Knows this dashboard and what you're looking at</div>
        </div>
        <button onClick={() => setShowThreads(!showThreads)} title="Past conversations" aria-label="Past conversations"
          className={cx("rounded p-1 hover:bg-slate-100", showThreads ? "text-brand-600" : "text-slate-500")}><History className="h-4 w-4" /></button>
        <button onClick={fresh} title="New conversation" aria-label="New conversation" className="rounded p-1 text-slate-500 hover:bg-slate-100"><MessageSquarePlus className="h-4 w-4" /></button>
        <button onClick={onClose} title="Close" aria-label="Close assistant" className="rounded p-1 text-slate-500 hover:bg-slate-100"><X className="h-4 w-4" /></button>
      </div>

      {showThreads && (
        <div className="max-h-64 overflow-y-auto border-b border-slate-200 bg-white px-2 py-2">
          {threads.loading && <div className="px-2 text-xs text-slate-400">Loading…</div>}
          {!threads.loading && (threads.data || []).length === 0 && <div className="px-2 text-xs text-slate-400">No past conversations on this dashboard yet.</div>}
          {(threads.data || []).map((t) => (
            <div key={t.id} className={cx("group flex items-center gap-1 rounded-md px-2 py-1.5 text-sm", t.id === conv ? "bg-brand-50 text-brand-800" : "hover:bg-slate-50")}>
              <button onClick={() => open(t.id)} className="min-w-0 flex-1 text-left">
                <div className="truncate">{t.title}</div>
                <div className="text-[10px] text-slate-400">{timeAgo(t.updated_at)} · {t.message_count} messages</div>
              </button>
              <button onClick={() => remove(t.id)} aria-label="Delete conversation" className="hidden text-slate-400 hover:text-red-600 group-hover:block"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          ))}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {msgs.length === 0 && !busy && (
          <div className="py-6 text-center">
            <p className="mx-auto max-w-xs text-sm text-slate-500">Ask anything about this dashboard. Answers use its metric definitions and the filters you have set, and show the query behind them.</p>
            <div className="mt-4 flex flex-col items-center gap-2">
              {STARTERS.map((s) => (
                <button key={s} onClick={() => ask(s)} className="rounded-full border border-slate-200 bg-white px-3 py-1 text-sm text-slate-700 shadow-sm hover:border-brand-300 hover:text-brand-700">{s}</button>
              ))}
            </div>
          </div>
        )}
        {msgs.map((m, i) => <ChatMessage key={i} m={m} onAsk={ask} wsId={wsId} base={base} compact onFeedback={(f) => rate(i, m, f)} />)}
        {busy && (
          <div className="py-2 text-sm text-slate-500">
            <Spinner label={live.length ? "Working it out…" : "Looking at the dashboard…"} />
            {live.length > 0 && <StepList steps={live} live />}
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="border-t border-slate-200 bg-white px-3 py-2 lg:rounded-b-lg">
        {focus && (
          <div className="mb-1.5 flex items-center gap-1.5 rounded bg-brand-50 px-2 py-1 text-xs text-brand-800">
            <Target className="h-3.5 w-3.5 shrink-0" /><span className="min-w-0 flex-1 truncate">Asking about “{focus.title}”</span>
            <button onClick={onClearFocus} aria-label="Stop asking about this widget" className="text-brand-600 hover:text-brand-800"><X className="h-3.5 w-3.5" /></button>
          </div>
        )}
        <form onSubmit={(e) => { e.preventDefault(); ask(input); }} className="flex items-center gap-2">
          <input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)} maxLength={2000}
            placeholder={focus ? "What would you like to know about it?" : conv ? "Ask a follow-up…" : "Ask about this dashboard…"}
            className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500" />
          <button disabled={busy || !input.trim()} className="rounded-lg bg-brand-600 p-2 text-white hover:bg-brand-700 disabled:opacity-50" aria-label="Send"><Send className="h-4 w-4" /></button>
        </form>
      </div>
    </aside>
  );
}
