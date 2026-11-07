import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { Bot, MessageSquarePlus, Send, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { Answer, ChatMessage, Msg } from "../components/ChatMessage";
import { cx, Spinner, useAsync, useToast } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

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
      setMsgs((m) => [...m, { id: a.message_id, role: "assistant", content: a.text, payload: a }]);
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

  const rate = async (i: number, m: Msg, feedback: "up" | "down" | null) => {
    if (!conv || !m.id) return;
    try {
      await api.post(`/workspaces/${ws.id}/conversations/${conv}/messages/${m.id}/feedback`, { feedback });
      setMsgs((all) => all.map((x, k) => (k === i ? { ...x, feedback } : x)));
    } catch (e: any) {
      toast("error", e.message);
    }
  };

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
            {msgs.map((m, i) => <ChatMessage key={i} m={m} onAsk={ask} wsId={ws.id} base={base} onFeedback={(f) => rate(i, m, f)} />)}
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
