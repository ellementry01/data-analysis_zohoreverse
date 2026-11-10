import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { BellRing, Bot, Brain, Globe2, MessageSquarePlus, Send, Trash2, X } from "lucide-react";
import { api } from "../api/client";
import { Answer, ChatMessage, Msg, Step, StepList } from "../components/ChatMessage";
import { MemoryItem, ProposalCard } from "../components/MemoryNotes";
import { cx, Spinner, useAsync, useToast } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

export default function AskPage() {
  const { ws, base } = useWs();
  const { convId } = useParams();
  const nav = useNavigate();
  const loc = useLocation() as { state?: { question?: string; domain?: Domain } };
  const toast = useToast();
  const convs = useAsync(() => api.get<{ id: number; title: string; updated_at: string; message_count: number; scope_type?: string }[]>(`/workspaces/${ws.id}/conversations`), [ws.id]);
  const me = useAsync(() => api.get<{ llm: { enabled: boolean; model: string | null; provider?: string | null; simple_model?: string; complex_model?: string };
    features?: { global_assistant?: boolean; agent_loop?: boolean; memory?: boolean; scheduled_agents?: boolean } }>("/me"), []);
  // Phase 6: the global assistant (admins only until company sign-in is on), with live steps and memory
  const global = !!me.data?.features?.global_assistant && !!me.data?.features?.agent_loop && !!me.data?.llm.enabled && ws.role === "admin";
  const memoryOn = global && !!me.data?.features?.memory;
  const proposals = useAsync(() => (memoryOn ? api.get<MemoryItem[]>(`/workspaces/${ws.id}/memory/proposals`) : Promise.resolve([] as MemoryItem[])), [ws.id, memoryOn]);
  const [live, setLive] = useState<Step[]>([]);
  const sugg = useAsync(() => api.get<string[]>(`/workspaces/${ws.id}/assistant/suggestions`), [ws.id]);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [engine, setEngine] = useState("auto");
  const [conv, setConv] = useState<number | null>(convId ? Number(convId) : null);
  // Phase 7: a domain assistant (Stock / Operations / Executive), opened from the Alerts page
  const [domain, setDomain] = useState<Domain | null>(loc.state?.domain || null);
  const domainOn = !!me.data?.features?.scheduled_agents && !!me.data?.features?.agent_loop && !!me.data?.llm.enabled && ws.role === "admin";
  const activeDomain = domainOn ? domain : null;
  const endRef = useRef<HTMLDivElement>(null);
  const asked = useRef(false);

  useEffect(() => {
    if (!convId) {
      setMsgs([]);
      setConv(null);
      if (!loc.state?.domain) setDomain(null);
      return;
    }
    api.get<{ messages: Msg[]; scope_type?: string }>(`/workspaces/${ws.id}/conversations/${convId}`).then((c) => {
      setMsgs(c.messages);
      setConv(Number(convId));
      const d = (c.scope_type || "").startsWith("domain:") ? (c.scope_type!.split(":")[1] as Domain) : null;
      setDomain(d);
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
    const done = (a: Answer) => {
      setMsgs((m) => [...m, { id: a.message_id, role: "assistant", content: a.text, payload: a }]);
      if (!conv && a.conversation_id) {
        setConv(a.conversation_id);
        nav(`${base}/ask/${a.conversation_id}`, { replace: true });
      }
      convs.reload();
      if (a.memories_saved?.some((x) => x.status === "proposed")) proposals.reload();
    };
    try {
      if ((global || activeDomain) && engine !== "semantic") {
        setLive([]);
        let answered = false;
        let failure: string | null = null;
        await api.stream(`/workspaces/${ws.id}/assistant/ask/stream`, { question, conversation_id: conv, engine, domain: activeDomain }, (e) => {
          if (e.type === "step") setLive((s) => [...s, { n: e.n, tool: e.tool, label: e.label }]);
          else if (e.type === "step_done") setLive((s) => s.map((x) => (x.n === e.n ? { ...x, ok: e.ok, label: e.label, row_count: e.rows } : x)));
          else if (e.type === "checking") setLive((s) => [...s, { n: 99, tool: "check", label: e.label }]);
          else if (e.type === "answer") { answered = true; done(e.answer); }
          else if (e.type === "error") failure = e.detail;
        });
        if (failure) throw new Error(failure);
        if (!answered) throw new Error("The answer was interrupted; please ask again.");
      } else {
        done(await api.post<Answer>(`/workspaces/${ws.id}/assistant/ask`, { question, conversation_id: conv, engine, domain: activeDomain }));
      }
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "assistant", content: e.message, payload: { type: "error", text: e.message } }]);
    } finally {
      setBusy(false);
      setLive([]);
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
                <div className="truncate">{(c.scope_type || "").startsWith("domain:") && <BellRing className="mr-1 inline h-3 w-3 text-amber-600" />}{c.title}</div>
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
            {activeDomain && (
              <div className="mb-3 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <BellRing className="h-4 w-4 shrink-0" />
                <span className="flex-1"><b>{DOMAIN_LABEL[activeDomain]}</b>: explains the alerts from the {activeDomain === "executive" ? "stock and operations" : activeDomain} rules and digs into the dashboards behind them. It never decides an alert; you do, on the <Link to={`${base}/alerts`} className="underline">Alerts page</Link>.</span>
                {!conv && <button onClick={() => setDomain(null)} title="Ask the general assistant instead" className="text-amber-700 hover:text-amber-900"><X className="h-4 w-4" /></button>}
              </div>
            )}
            {msgs.length === 0 && (
              <div className="py-10 text-center">
                <Bot className="mx-auto mb-3 h-10 w-10 text-brand-500" />
                <h2 className="text-lg font-semibold text-slate-800">Ask anything about {ws.name}</h2>
                <p className="mx-auto mt-1 max-w-lg text-sm text-slate-500">{global
                  ? "This assistant knows every dashboard you can see, their known data issues and what you've asked it to remember. Ask across dashboards; each number says where it comes from."
                  : "Answers are computed from your data with governed metric definitions. Every answer shows the SQL that produced it. Follow-up questions keep the context."}</p>
                {global && (
                  <div className="mt-4 flex flex-wrap justify-center gap-2">
                    {["What stands out across all dashboards right now?", "What did I decide about partner stock?", "Compare what Stock and Fulfilment show for Bagru"].map((s) => (
                      <button key={s} onClick={() => ask(s)} className="inline-flex items-center gap-1 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-sm text-brand-800 hover:bg-brand-100"><Globe2 className="h-3.5 w-3.5" />{s}</button>
                    ))}
                  </div>
                )}
                <div className="mt-5 flex flex-wrap justify-center gap-2">
                  {[...(sugg.data || []), "Create a dashboard showing monthly sales, returns and inventory"].slice(0, 7).map((s) => (
                    <button key={s} onClick={() => ask(s)} className="rounded-full border border-slate-200 bg-white px-3 py-1 text-sm text-slate-700 shadow-sm hover:border-brand-300 hover:text-brand-700">{s}</button>
                  ))}
                </div>
              </div>
            )}
            {memoryOn && (proposals.data || []).length > 0 && (
              <div className="mb-4 grid gap-2 md:grid-cols-2">
                {(proposals.data || []).slice(0, 2).map((p) => <ProposalCard key={p.id} wsId={ws.id} item={p} onDone={proposals.reload} />)}
                {(proposals.data || []).length > 2 && <Link to={`${base}/memory`} className="inline-flex items-center gap-1 text-xs text-violet-700 hover:underline"><Brain className="h-3 w-3" /> {(proposals.data || []).length - 2} more suggestions on the Memory page</Link>}
              </div>
            )}
            {msgs.map((m, i) => <ChatMessage key={i} m={m} onAsk={ask} wsId={ws.id} base={base} onFeedback={(f) => rate(i, m, f)} />)}
            {busy && (
              <div className="py-3 text-sm text-slate-500">
                <div className="flex items-center gap-2"><Bot className="h-5 w-5 text-brand-500" /> <Spinner label={live.length ? "Working it out…" : "Analysing…"} /></div>
                {live.length > 0 && <div className="ml-7"><StepList steps={live} live /></div>}
              </div>
            )}
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
            {global ? "Global assistant: knows every dashboard you can see, their data issues and your memories; reads only, and only what you may see. " : ""}
            {me.data?.llm.provider === "anthropic" ? `Claude: ${me.data.llm.simple_model} for everyday questions, ${me.data.llm.complex_model} for complex ones. Answers use your metric definitions; any SQL is validated and run read-only.` : me.data?.llm.enabled ? `LLM: ${me.data.llm.model} — used as a fallback in Auto mode; all generated SQL is validated and run read-only.` : "Offline semantic engine (no LLM configured). Add synonyms and metrics in the Semantic layer to teach it your vocabulary."}
          </div>
        </div>
      </div>
    </div>
  );
}

type Domain = "stock" | "operations" | "executive";
const DOMAIN_LABEL: Record<Domain, string> = { stock: "Stock assistant", operations: "Operations assistant", executive: "Executive assistant" };
