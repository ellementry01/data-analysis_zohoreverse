import { useState } from "react";
import { AlertTriangle, Brain, Check, Pencil, Plus, RotateCcw, Search, Share2, Trash2, UserRound, Users, X } from "lucide-react";
import { api, Dashboard } from "../api/client";
import { KIND_LABEL, MemoryItem, ProposalCard } from "../components/MemoryNotes";
import { Badge, Button, Card, cx, Empty, ErrorBox, inputCls, Label, PageHeader, Select, Spinner, Tabs, useAsync, useToast } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

interface Profile { text: string; version: number; edited_by_user: boolean; updated_at: string | null; sources: number[]; rewrite_queued: boolean }
interface Stats { counts: Record<string, number>; inferred_decided: number; acceptance_rate: number | null; share_queue: number | null }

const KINDS = Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }));

/** What the dashboard assistants remember: your preferences, facts and decisions, team facts, and what was learned. */
export default function MemoryPage() {
  const { ws } = useWs();
  const root = `/workspaces/${ws.id}/memory`;
  const [tab, setTab] = useState("active");
  const [q, setQ] = useState("");
  const [layer, setLayer] = useState("");
  const [scope, setScope] = useState("");
  const isAdmin = ws.role === "admin";
  const list = useAsync(() => api.get<MemoryItem[]>(`${root}?status=${tab === "queue" ? "active" : tab}`), [root, tab]);
  const proposals = useAsync(() => api.get<MemoryItem[]>(`${root}/proposals`), [root]);
  const queue = useAsync(() => (isAdmin ? api.get<MemoryItem[]>(`${root}/share-queue`) : Promise.resolve([] as MemoryItem[])), [root, isAdmin]);
  const stats = useAsync(() => api.get<Stats>(`${root}/stats`), [root]);
  const dashes = useAsync(() => api.get<Dashboard[]>(`/workspaces/${ws.id}/dashboards`), [ws.id]);
  const [adding, setAdding] = useState(false);

  const reloadAll = () => { list.reload(); proposals.reload(); queue.reload(); stats.reload(); };
  const scopes = [{ value: "global", label: "All dashboards" },
    ...(dashes.data || []).map((d) => ({ value: `dashboard:${d.key}`, label: d.name, group: "One dashboard" })),
    ...Array.from(new Set((dashes.data || []).map((d) => d.domain).filter(Boolean))).map((dm) => ({ value: `domain:${dm}`, label: `All ${dm} dashboards`, group: "A domain" }))];

  if (list.error && String(list.error).includes("switched off")) {
    return <div><PageHeader title="Memory" /><Empty icon={<Brain className="h-6 w-6" />} title="Memory is switched off">An administrator turns it on with ASSISTANT_MEMORY.</Empty></div>;
  }

  const shown = (tab === "proposed" ? proposals.data : list.data || [])?.filter((x) =>
    (!layer || (layer === "mine" ? x.mine && x.layer === "personal" : x.layer === layer))
    && (!scope || x.scope === scope)
    && (!q.trim() || `${x.text} ${x.rationale} ${x.source.excerpt}`.toLowerCase().includes(q.trim().toLowerCase()))) || [];
  const c = stats.data?.counts || {};
  const tabs = [
    { id: "active", label: <>Remembered <Count n={c.active} /></> },
    { id: "proposed", label: <>Suggestions <Count n={(proposals.data || []).length} tone="violet" /></> },
    { id: "needs_review", label: <>Needs review <Count n={c.needs_review} tone="amber" /></> },
    { id: "retired", label: <>Retired <Count n={c.retired} /></> },
    ...(isAdmin ? [{ id: "queue", label: <>Team facts to approve <Count n={(queue.data || []).length} tone="amber" /></> }] : []),
  ];

  return (
    <div>
      <PageHeader title="Memory" subtitle="What the dashboard assistants remember about how you work. Anything they learn waits for your OK; only you see your own memories."
        actions={<Button variant="primary" onClick={() => setAdding(!adding)}><Plus className="h-4 w-4" /> Add a memory</Button>} />

      {stats.data && (
        <div className="mb-4 flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
          <span><b className="text-slate-800">{c.active || 0}</b> remembered</span>
          <span><b className="text-slate-800">{(proposals.data || []).length}</b> suggestions waiting</span>
          {stats.data.acceptance_rate !== null && (
            <span title="Of the suggestions learned from your conversations that you decided on, the share you accepted">
              <b className="text-slate-800">{Math.round(stats.data.acceptance_rate * 100)}%</b> of learned suggestions accepted ({stats.data.inferred_decided} decided)
            </span>
          )}
        </div>
      )}

      {adding && <AddMemory root={root} scopes={scopes} onDone={() => { setAdding(false); reloadAll(); }} />}

      <div className="grid gap-5 xl:grid-cols-[1fr_340px]">
        <div className="min-w-0">
          <Tabs tabs={tabs} value={tab} onChange={setTab} />
          {tab !== "queue" && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <div className="relative min-w-[12rem] flex-1">
                <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-slate-400" />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search memories" className={cx(inputCls, "pl-8")} />
              </div>
              <Select className="w-44" value={layer} onChange={setLayer} placeholder="Everything"
                options={[{ value: "mine", label: "My preferences & facts" }, { value: "decision", label: "Decisions" }, { value: "shared", label: "Team facts" }]} />
              <Select className="w-52" value={scope} onChange={setScope} placeholder="Any dashboard" options={scopes} />
            </div>
          )}

          <div className="mt-3 flex flex-col gap-2">
            {(list.loading || proposals.loading) && <Spinner />}
            {list.error && <ErrorBox error={list.error} />}
            {tab === "queue" && (queue.data || []).map((x) => <QueueItem key={x.id} root={root} x={x} onDone={reloadAll} />)}
            {tab === "queue" && !queue.loading && (queue.data || []).length === 0 && <Empty title="Nothing to approve">Team facts suggested by members appear here.</Empty>}
            {tab === "proposed" && shown.map((x) => <ProposalCard key={x.id} wsId={ws.id} item={x} onDone={reloadAll} />)}
            {tab !== "queue" && tab !== "proposed" && shown.map((x) => <MemoryRow key={x.id} root={root} x={x} scopes={scopes} onChange={reloadAll} />)}
            {tab !== "queue" && !list.loading && !proposals.loading && shown.length === 0 && (
              <Empty icon={<Brain className="h-6 w-6" />} title={tab === "proposed" ? "No suggestions waiting" : "Nothing here yet"}>
                {tab === "active" ? "Tell a dashboard assistant “remember …”, or add one here. Things it learns from your conversations show up as suggestions first."
                  : tab === "proposed" ? "After a conversation goes quiet for half an hour, the assistant may suggest up to three things to remember."
                    : tab === "needs_review" ? "A memory lands here when a metric it relies on changes; it isn't used until you keep or retire it."
                      : "Retired memories are kept here and can be restored."}
              </Empty>
            )}
          </div>
        </div>
        <ProfileCard root={root} />
      </div>
    </div>
  );
}

function Count({ n, tone = "slate" }: { n?: number; tone?: "slate" | "violet" | "amber" }) {
  if (!n) return null;
  return <span className={cx("ml-1 rounded-full px-1.5 text-[10px]", tone === "violet" ? "bg-violet-100 text-violet-700" : tone === "amber" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600")}>{n}</span>;
}

function AddMemory({ root, scopes, onDone }: { root: string; scopes: { value: string; label: string; group?: string }[]; onDone: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ text: "", kind: "preference", scope: "global", rationale: "", share_with_team: false });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.post(root, f);
      toast("success", "Saved to memory");
      onDone();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="mb-4" title="Add a memory">
      <div className="grid gap-3 md:grid-cols-[1fr_180px_220px]">
        <div><Label>What should the assistants remember?</Label>
          <input autoFocus value={f.text} maxLength={500} onChange={(e) => setF({ ...f, text: e.target.value })} className={inputCls}
            placeholder="e.g. Compare with the same period last year, not the previous period" /></div>
        <div><Label>Kind</Label><Select value={f.kind} onChange={(kind) => setF({ ...f, kind })} options={KINDS} /></div>
        <div><Label>Where it applies</Label><Select value={f.scope} onChange={(scope) => setF({ ...f, scope })} options={scopes} /></div>
      </div>
      {f.kind === "decision" && (
        <div className="mt-3"><Label hint="kept with the decision, with today's date">Why</Label>
          <input value={f.rationale} maxLength={500} onChange={(e) => setF({ ...f, rationale: e.target.value })} className={inputCls} /></div>
      )}
      {(f.kind === "fact" || f.kind === "caveat") && (
        <label className="mt-3 flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={f.share_with_team} onChange={(e) => setF({ ...f, share_with_team: e.target.checked })} />
          Suggest it as a team fact (a workspace admin approves it; until then only you have it)
        </label>
      )}
      <div className="mt-3 flex gap-2">
        <Button variant="primary" loading={busy} disabled={f.text.trim().length < 3} onClick={save}><Check className="h-4 w-4" /> Save</Button>
        <Button variant="ghost" onClick={onDone}>Cancel</Button>
      </div>
    </Card>
  );
}

function MemoryRow({ root, x, scopes, onChange }: { root: string; x: MemoryItem; scopes: { value: string; label: string; group?: string }[]; onChange: () => void }) {
  const toast = useToast();
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState({ text: x.text, rationale: x.rationale, kind: x.kind, scope: x.scope });
  const call = async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      if (ok) toast("success", ok);
      setEdit(false);
      onChange();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const act = (a: string, ok?: string) => call(() => api.post(`${root}/${x.id}/${a}`), ok);
  const shareLabel = x.layer === "decision" ? (x.visibility === "shared" ? "Make private" : "Share with the team")
    : x.share_status === "pending" ? "Withdraw team suggestion" : "Suggest as team fact";
  const canShare = x.mine && (x.layer === "decision" || (x.layer === "personal" && (x.kind === "fact" || x.kind === "caveat")));
  const sharing = x.layer === "decision" ? x.visibility === "shared" : x.share_status === "pending";
  return (
    <div className={cx("rounded-lg border bg-white px-3 py-2.5 shadow-sm", x.status === "needs_review" ? "border-amber-200" : "border-slate-200")}>
      <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
        <Badge tone={x.layer === "decision" ? "violet" : x.layer === "shared" ? "green" : "blue"}>{KIND_LABEL[x.kind] || x.kind}</Badge>
        <span className="text-slate-500">{x.scope_label}</span>
        {x.layer === "shared" && <span className="inline-flex items-center gap-0.5 text-emerald-700"><Users className="h-3 w-3" /> team fact</span>}
        {x.layer === "decision" && x.visibility === "shared" && <span className="inline-flex items-center gap-0.5 text-violet-700"><Users className="h-3 w-3" /> shared</span>}
        {x.share_status === "pending" && <span className="text-amber-700">waiting for an admin</span>}
        {x.share_status === "rejected" && x.mine && <span className="text-slate-400">team suggestion declined</span>}
        {x.owner && <span className="inline-flex items-center gap-0.5 text-slate-500"><UserRound className="h-3 w-3" /> {x.owner}</span>}
        <span className="ml-auto text-slate-400">
          {x.origin === "inferred" ? "learned" : x.origin === "explicit" ? "you asked" : "added"} {timeAgo(x.approved_at || x.created_at)}
          {x.use_count > 0 && <> · used {x.use_count}× (last {timeAgo(x.last_used_at)})</>}
        </span>
      </div>
      {edit ? (
        <div className="mt-2 grid gap-2">
          <input value={f.text} maxLength={500} onChange={(e) => setF({ ...f, text: e.target.value })} className={inputCls} />
          <div className="grid gap-2 md:grid-cols-2">
            {x.layer !== "shared" && <Select value={f.kind} onChange={(kind) => setF({ ...f, kind })} options={KINDS} />}
            <Select value={f.scope} onChange={(scope) => setF({ ...f, scope })} options={scopes} />
          </div>
          {(f.kind === "decision" || f.rationale) && <input value={f.rationale} maxLength={500} placeholder="Why" onChange={(e) => setF({ ...f, rationale: e.target.value })} className={inputCls} />}
          <div className="flex gap-2">
            <Button size="sm" variant="primary" disabled={f.text.trim().length < 3} onClick={() => call(() => api.patch(`${root}/${x.id}`, f), "Saved")}><Check className="h-3.5 w-3.5" /> Save</Button>
            <Button size="sm" variant="ghost" onClick={() => setEdit(false)}><X className="h-3.5 w-3.5" /> Cancel</Button>
          </div>
        </div>
      ) : (
        <>
          <div className="mt-1 text-sm text-slate-800">{x.text}</div>
          {x.rationale && <div className="mt-0.5 text-xs text-slate-500">Why: {x.rationale}</div>}
          {x.status === "needs_review" && (
            <div className="mt-1.5 flex items-center gap-1 rounded bg-amber-50 px-2 py-1 text-xs text-amber-800"><AlertTriangle className="h-3.5 w-3.5 shrink-0" /> {x.review_reason} Not used until you keep or retire it.</div>
          )}
          {x.source.excerpt && <div className="mt-1 truncate text-[11px] text-slate-400" title={x.source.excerpt}>From{x.source.dashboard_key ? ` the ${x.source.dashboard_key} chat` : ""}: “{x.source.excerpt}”</div>}
        </>
      )}
      {!edit && (
        <div className="mt-1.5 flex flex-wrap gap-3 text-xs">
          {x.status === "needs_review" && x.can_edit && <button onClick={() => act("keep", "Kept")} className="inline-flex items-center gap-1 font-medium text-amber-800 hover:underline"><Check className="h-3 w-3" /> Still true: keep it</button>}
          {x.can_edit && x.status !== "retired" && <button onClick={() => setEdit(true)} className="inline-flex items-center gap-1 text-slate-600 hover:text-brand-700"><Pencil className="h-3 w-3" /> Edit</button>}
          {canShare && x.status === "active" && <button onClick={() => act(sharing ? "unshare" : "share")} className="inline-flex items-center gap-1 text-slate-600 hover:text-brand-700"><Share2 className="h-3 w-3" /> {shareLabel}</button>}
          {x.can_edit && (x.status === "active" || x.status === "needs_review") && <button onClick={() => act("retire")} className="text-slate-600 hover:text-brand-700">Retire</button>}
          {x.can_edit && x.status === "retired" && <button onClick={() => act("restore")} className="inline-flex items-center gap-1 text-slate-600 hover:text-brand-700"><RotateCcw className="h-3 w-3" /> Restore</button>}
          {x.can_edit && <button onClick={() => { if (confirm("Delete this memory for good?")) call(() => api.del(`${root}/${x.id}`)); }} className="ml-auto inline-flex items-center gap-1 text-slate-400 hover:text-red-600"><Trash2 className="h-3 w-3" /> Delete</button>}
        </div>
      )}
    </div>
  );
}

function QueueItem({ root, x, onDone }: { root: string; x: MemoryItem; onDone: () => void }) {
  const toast = useToast();
  const act = async (a: "approve_share" | "reject_share") => {
    try {
      await api.post(`${root}/${x.id}/${a}`);
      toast("success", a === "approve_share" ? "Approved: every member's assistant now knows it" : "Declined");
      onDone();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  return (
    <div className="rounded-lg border border-amber-200 bg-white px-3 py-2.5 shadow-sm">
      <div className="text-[11px] text-slate-500">{KIND_LABEL[x.kind]} · {x.scope_label} · suggested by {x.owner}</div>
      <div className="mt-1 text-sm text-slate-800">{x.text}</div>
      <div className="mt-1.5 flex gap-2">
        <Button size="sm" variant="primary" onClick={() => act("approve_share")}><Check className="h-3.5 w-3.5" /> Approve for everyone</Button>
        <Button size="sm" variant="ghost" onClick={() => act("reject_share")}>Decline</Button>
      </div>
    </div>
  );
}

function ProfileCard({ root }: { root: string }) {
  const toast = useToast();
  const p = useAsync(() => api.get<Profile>(`${root}/profile`), [root]);
  const [edit, setEdit] = useState(false);
  const [text, setText] = useState("");
  const save = async () => {
    try {
      await api.put(`${root}/profile`, { text });
      setEdit(false);
      p.reload();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const rewrite = async () => {
    try {
      await api.post(`${root}/profile/rewrite`);
      toast("info", "Queued: the profile is rewritten from your memories in the background (one small AI call).");
      p.reload();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  return (
    <Card title="How you work (your profile)" className="h-fit">
      <p className="mb-2 text-xs text-slate-500">The assistants read this before answering you. It is rewritten from your memories every week (and after every 10 you approve); your own edits are kept.</p>
      {p.loading && <Spinner />}
      {p.data && (edit ? (
        <>
          <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={1600} rows={8} className={cx(inputCls, "text-sm")} />
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="primary" onClick={save}>Save</Button>
            <Button size="sm" variant="ghost" onClick={() => setEdit(false)}>Cancel</Button>
          </div>
        </>
      ) : (
        <>
          <div className="whitespace-pre-wrap text-sm text-slate-800">{p.data.text || <span className="text-slate-400">No profile yet: it is written once you have a few memories.</span>}</div>
          <div className="mt-2 text-[11px] text-slate-400">
            {p.data.updated_at && <>Version {p.data.version}, {timeAgo(p.data.updated_at)}{p.data.edited_by_user ? " · includes your edits" : ""}</>}
            {p.data.rewrite_queued && <div className="text-violet-600">A rewrite is queued.</div>}
          </div>
          <div className="mt-2 flex gap-2">
            <Button size="sm" onClick={() => { setText(p.data!.text); setEdit(true); }}><Pencil className="h-3.5 w-3.5" /> Edit</Button>
            <Button size="sm" variant="ghost" disabled={p.data.rewrite_queued} onClick={rewrite}><RotateCcw className="h-3.5 w-3.5" /> Rewrite from memories</Button>
          </div>
        </>
      ))}
    </Card>
  );
}
