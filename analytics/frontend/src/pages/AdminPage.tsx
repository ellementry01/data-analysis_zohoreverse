import { useState } from "react";
import { Link } from "react-router-dom";
import { Activity, ArrowLeft, Copy, KeyRound, ScrollText, Users } from "lucide-react";
import { api } from "../api/client";
import { useMe } from "../components/UserMenu";
import { Badge, Button, Card, ErrorBox, inputCls, Label, Spinner, Tabs, useAsync, useToast } from "../components/ui";
import { timeAgo } from "../lib/format";
import MonitorTab from "./AdminMonitor";

interface AdminUser { email: string; name: string; active: boolean; is_platform_admin: boolean; last_login_at: string | null; workspaces: Record<string, string> }
interface Token { id: number; name: string; user_email: string; created_at: string; last_used_at: string | null; expires_at: string | null; revoked: boolean; token?: string }
interface AuditEvent { id: number; at: string; user_email: string; action: string; target: string; detail: any; ip: string }

/** Platform administration: who can sign in, tokens for scripts, the audit log and monitoring of the assistants. */
export default function AdminPage() {
  const me = useMe();
  const [tab, setTab] = useState("users");
  if (me.error) return <div className="p-8"><ErrorBox error={me.error} /></div>;
  if (!me.data) return <Spinner />;
  if (!me.data.is_platform_admin) return <div className="p-8 text-sm text-slate-600">Only platform administrators can open this page. <Link className="text-brand-600" to="/">Back</Link></div>;
  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <div className="mb-4 flex items-center gap-2">
        <Link to="/" className="text-slate-400 hover:text-slate-700" aria-label="Back"><ArrowLeft className="h-4 w-4" /></Link>
        <h1 className="text-xl font-semibold text-slate-900">Administration</h1>
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "users", label: <span className="inline-flex items-center gap-1"><Users className="h-3.5 w-3.5" /> Users</span> },
        { id: "tokens", label: <span className="inline-flex items-center gap-1"><KeyRound className="h-3.5 w-3.5" /> API tokens</span> },
        { id: "audit", label: <span className="inline-flex items-center gap-1"><ScrollText className="h-3.5 w-3.5" /> Audit log</span> },
        { id: "monitor", label: <span className="inline-flex items-center gap-1"><Activity className="h-3.5 w-3.5" /> Monitoring</span> },
      ]} />
      <div className="mt-4">
        {tab === "users" && <UsersTab self={me.data.email} />}
        {tab === "tokens" && <TokensTab />}
        {tab === "audit" && <AuditTab />}
        {tab === "monitor" && <MonitorTab />}
      </div>
    </div>
  );
}

function UsersTab({ self }: { self: string }) {
  const toast = useToast();
  const users = useAsync(() => api.get<AdminUser[]>("/admin/users"), []);
  const patch = async (u: AdminUser, body: Partial<AdminUser>) => {
    if (body.active === false && !confirm(`Switch off ${u.email}? Their sessions and tokens stop working at once.`)) return;
    try {
      await api.patch(`/admin/users/${encodeURIComponent(u.email)}`, body);
      users.reload();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  return (
    <Card title="People who have signed in">
      <p className="mb-3 text-xs text-slate-500">Anyone with a company Google account can sign in; what they see depends on their workspace membership and access rules. Switching someone off ends their access immediately.</p>
      {users.loading && <Spinner />}
      {(users.data || []).length === 0 && !users.loading && <div className="text-sm text-slate-400">Nobody has signed in with Google yet.</div>}
      {(users.data || []).map((u) => (
        <div key={u.email} className="flex flex-wrap items-center gap-3 border-b border-slate-100 py-2 text-sm last:border-0">
          <div className="min-w-0 flex-1">
            <div className="font-medium text-slate-800">{u.name || u.email}</div>
            <div className="text-xs text-slate-500">{u.email} · last sign-in {timeAgo(u.last_login_at)} · {Object.entries(u.workspaces).map(([w, r]) => `${w}: ${r}`).join(", ") || "no workspaces"}</div>
          </div>
          {u.is_platform_admin && <Badge tone="violet">admin</Badge>}
          <Badge tone={u.active ? "green" : "red"}>{u.active ? "active" : "switched off"}</Badge>
          {u.email !== self && (
            <>
              <Button size="sm" onClick={() => patch(u, { is_platform_admin: !u.is_platform_admin })}>{u.is_platform_admin ? "Remove admin" : "Make admin"}</Button>
              <Button size="sm" variant={u.active ? "danger" : "secondary"} onClick={() => patch(u, { active: !u.active })}>{u.active ? "Switch off" : "Switch on"}</Button>
            </>
          )}
        </div>
      ))}
    </Card>
  );
}

function TokensTab() {
  const toast = useToast();
  const tokens = useAsync(() => api.get<Token[]>("/admin/tokens"), []);
  const [name, setName] = useState("");
  const [days, setDays] = useState(90);
  const [fresh, setFresh] = useState<string | null>(null);
  const create = async () => {
    try {
      const t = await api.post<Token>("/admin/tokens", { name, days });
      setFresh(t.token || null);
      setName("");
      tokens.reload();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const revoke = async (t: Token) => {
    if (!confirm(`Revoke "${t.name}"? Scripts using it stop working.`)) return;
    await api.del(`/admin/tokens/${t.id}`);
    tokens.reload();
  };
  return (
    <Card title="API tokens for scripts">
      <p className="mb-3 text-xs text-slate-500">Scripts (dashboard builds, evaluations) send a token as <code className="rounded bg-slate-100 px-1">Authorization: Bearer …</code> and act as you. Put it in the <code className="rounded bg-slate-100 px-1">ELLEMENTRY_API_TOKEN</code> environment variable where the script runs; never paste it into chat or commit it.</p>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <div className="flex-1"><Label>Name</Label><input className={inputCls} placeholder="e.g. dashboard builds" value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div><Label>Valid for (days)</Label><input type="number" min={1} max={365} className={inputCls + " !w-28"} value={days} onChange={(e) => setDays(Number(e.target.value))} /></div>
        <Button variant="primary" disabled={!name.trim()} onClick={create}>Create token</Button>
      </div>
      {fresh && (
        <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          Copy this token now; it will not be shown again.
          <div className="mt-1 flex items-center gap-2"><code className="min-w-0 flex-1 break-all rounded bg-white px-2 py-1">{fresh}</code>
            <button onClick={() => navigator.clipboard.writeText(fresh)} aria-label="Copy token" className="text-amber-800"><Copy className="h-4 w-4" /></button></div>
        </div>
      )}
      {(tokens.data || []).map((t) => (
        <div key={t.id} className="flex items-center gap-3 border-b border-slate-100 py-2 text-sm last:border-0">
          <div className="min-w-0 flex-1"><div>{t.name}</div><div className="text-xs text-slate-500">{t.user_email} · created {timeAgo(t.created_at)} · last used {timeAgo(t.last_used_at)}{t.expires_at ? ` · expires ${t.expires_at.slice(0, 10)}` : ""}</div></div>
          {t.revoked ? <Badge tone="red">revoked</Badge> : <Button size="sm" variant="danger" onClick={() => revoke(t)}>Revoke</Button>}
        </div>
      ))}
    </Card>
  );
}

const ACTIONS = ["", "sign_in", "sign_in_failed", "sign_out", "assistant_ask", "rate_limited", "briefing", "alert_decision", "memory_saved", "access_rule_added", "access_rule_removed", "member_set", "member_removed", "user_updated", "token_created", "token_revoked"];

function AuditTab() {
  const [action, setAction] = useState("");
  const [who, setWho] = useState("");
  const log = useAsync(() => api.get<AuditEvent[]>(`/admin/audit?limit=300${action ? `&action=${action}` : ""}${who.includes("@") ? `&who=${encodeURIComponent(who)}` : ""}`), [action, who]);
  return (
    <Card title="Audit log">
      <div className="mb-3 flex flex-wrap gap-2">
        <select className={inputCls + " !w-56"} value={action} onChange={(e) => setAction(e.target.value)} aria-label="Filter by action">
          {ACTIONS.map((a) => <option key={a} value={a}>{a ? a.replace(/_/g, " ") : "All actions"}</option>)}
        </select>
        <input className={inputCls + " !w-64"} placeholder="Filter by email" value={who} onChange={(e) => setWho(e.target.value)} />
      </div>
      {log.loading && <Spinner />}
      <div className="max-h-[60vh] overflow-y-auto">
        {(log.data || []).map((e) => (
          <div key={e.id} className="grid grid-cols-[9rem_12rem_1fr] gap-2 border-b border-slate-100 py-1.5 text-xs last:border-0">
            <span className="text-slate-500" title={e.at}>{e.at.replace("T", " ").slice(0, 19)}</span>
            <span className="truncate text-slate-700" title={e.user_email}>{e.user_email}</span>
            <span className="text-slate-700"><b className="font-medium">{e.action.replace(/_/g, " ")}</b>{e.target ? ` · ${e.target}` : ""}{e.detail && Object.keys(e.detail).length ? <span className="text-slate-400"> {JSON.stringify(e.detail)}</span> : null}</span>
          </div>
        ))}
        {!log.loading && (log.data || []).length === 0 && <div className="text-sm text-slate-400">No events.</div>}
      </div>
    </Card>
  );
}
