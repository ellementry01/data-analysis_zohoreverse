import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, Trash2, UserCog, Users } from "lucide-react";
import { api, currentUser, USER_KEY, Workspace } from "../api/client";
import { Badge, Button, Card, inputCls, Label, PageHeader, Select, useAsync, useToast } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useWs } from "./WorkspaceLayout";

export default function SettingsPage() {
  const { ws, model } = useWs();
  const toast = useToast();
  const nav = useNavigate();
  const full = useAsync(() => api.get<Workspace>(`/workspaces/${ws.id}`), [ws.id]);
  const me = useAsync(() => api.get<{ email: string; llm: { enabled: boolean; model: string | null; base_url_host: string | null; provider?: string | null; simple_model?: string; complex_model?: string } }>("/me"), []);
  const schedules = useAsync(() => api.get<any[]>(`/workspaces/${ws.id}/schedules`), [ws.id]);
  const [name, setName] = useState(ws.name);
  const [desc, setDesc] = useState(ws.description);
  const [member, setMember] = useState({ user_email: "", role: "viewer" });
  const [user, setUser] = useState(currentUser());
  const isAdmin = ws.role === "admin";

  const saveWs = async () => {
    try {
      await api.patch(`/workspaces/${ws.id}`, { name, description: desc });
      toast("success", "Saved");
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const upsert = async (body: { user_email: string; role: string }) => {
    try {
      await api.put(`/workspaces/${ws.id}/members`, body);
      full.reload();
      setMember({ user_email: "", role: "viewer" });
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const remove = async (email: string) => {
    try {
      await api.del(`/workspaces/${ws.id}/members/${encodeURIComponent(email)}`);
      full.reload();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const switchUser = () => {
    try { localStorage.setItem(USER_KEY, user.trim().toLowerCase()); } catch { /* storage unavailable */ }
    nav("/");
    window.location.reload();
  };

  return (
    <div>
      <PageHeader title="Settings" />
      <div className="grid max-w-4xl gap-4">
        <Card title="Workspace">
          <div className="grid gap-3">
            <div><Label>Name</Label><input className={inputCls} value={name} disabled={!isAdmin} onChange={(e) => setName(e.target.value)} /></div>
            <div><Label>Description</Label><textarea className={inputCls} rows={2} value={desc} disabled={!isAdmin} onChange={(e) => setDesc(e.target.value)} /></div>
            {isAdmin && <div><Button variant="primary" onClick={saveWs}>Save</Button></div>}
          </div>
        </Card>
        <Card title={<span className="flex items-center gap-1.5"><Users className="h-4 w-4" /> Members & roles</span>}>
          <p className="mb-3 text-xs text-slate-500"><b>Admin</b>: everything incl. members · <b>Editor</b>: import, model, metrics, reports, dashboards · <b>Viewer</b>: view, filter, drill, ask AI.</p>
          {(full.data?.members || []).map((m) => (
            <div key={m.user_email} className="flex items-center gap-3 border-b border-slate-100 py-2 text-sm last:border-0">
              <span className="flex-1">{m.user_email}</span>
              {isAdmin ? <Select className="!w-32" value={m.role} onChange={(v) => upsert({ user_email: m.user_email, role: v })} options={["admin", "editor", "viewer"].map((r) => ({ value: r, label: r }))} /> : <Badge>{m.role}</Badge>}
              {isAdmin && <button onClick={() => remove(m.user_email)} className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>}
            </div>
          ))}
          {isAdmin && (
            <div className="mt-3 flex gap-2">
              <input className={inputCls} placeholder="colleague@company.com" value={member.user_email} onChange={(e) => setMember({ ...member, user_email: e.target.value })} />
              <Select className="!w-32" value={member.role} onChange={(v) => setMember({ ...member, role: v })} options={["admin", "editor", "viewer"].map((r) => ({ value: r, label: r }))} />
              <Button onClick={() => upsert(member)} disabled={!member.user_email.includes("@")}>Add</Button>
            </div>
          )}
        </Card>
        <Card title={<span className="flex items-center gap-1.5"><UserCog className="h-4 w-4" /> Local user</span>}>
          <p className="mb-2 text-xs text-slate-500">This local-first build identifies users by email (no passwords). Switch user to try roles; you only see workspaces you are a member of.</p>
          <div className="flex gap-2"><input className={inputCls} value={user} onChange={(e) => setUser(e.target.value)} /><Button onClick={switchUser}>Switch</Button></div>
        </Card>
        <Card title={<span className="flex items-center gap-1.5"><Bot className="h-4 w-4" /> AI assistant</span>}>
          {me.data?.llm.provider === "anthropic" ? (
            <div className="text-sm">Anthropic Claude connected. Everyday questions go to <b>{me.data.llm.simple_model}</b>; genuinely complex ones (opposing trends, "why", cohorts, share-of-total, many metrics) go to <b>{me.data.llm.complex_model}</b>, which is also used once if a cheaper plan fails validation. Opus and Fable are never used. Answers use your metric definitions where possible, and any SQL passes the validator and runs read-only. If the API is unreachable, the offline engine answers.</div>
          ) : me.data?.llm.enabled ? (
            <div className="text-sm">LLM connected: <b>{me.data.llm.model}</b> at {me.data.llm.base_url_host}. In <i>Auto</i> mode the semantic engine answers first and the LLM is used when it cannot; every LLM query passes the SQL validator and runs read-only.</div>
          ) : (
            <div className="text-sm text-slate-600">No LLM configured — the built-in semantic engine answers questions offline using your metrics, glossary and data values. To enable Claude, set <code className="rounded bg-slate-100 px-1">ANTHROPIC_API_KEY</code> in <code className="rounded bg-slate-100 px-1">.env</code> (Docker) or <code className="rounded bg-slate-100 px-1">backend/.env</code> and restart. Alternatively, for an OpenAI-compatible model (Ollama, LM Studio…), set <code className="rounded bg-slate-100 px-1">LLM_BASE_URL</code>, <code className="rounded bg-slate-100 px-1">LLM_API_KEY</code> and <code className="rounded bg-slate-100 px-1">LLM_MODEL</code> in <code className="rounded bg-slate-100 px-1">backend/.env</code> and restart.</div>
          )}
          <div className="mt-2 text-xs text-slate-400">{model.metrics.length} metrics define the vocabulary the assistant understands.</div>
        </Card>
        <Card title="Scheduled syncs">
          {(schedules.data || []).map((s) => (
            <div key={s.id} className="flex items-center gap-3 border-b border-slate-100 py-1.5 text-sm last:border-0">
              <span className="flex-1">{model.datasets.find((d) => d.id === s.dataset_id)?.name}</span>
              <span className="text-xs text-slate-500">every {s.interval_minutes} min · last {timeAgo(s.last_run_at)}</span>
              <Badge tone={s.last_status?.startsWith("ok") ? "green" : s.last_status ? "red" : "slate"}>{s.last_status || "pending"}</Badge>
            </div>
          ))}
          {!schedules.data?.length && <div className="text-sm text-slate-400">No schedules. Set one on a database-connected dataset.</div>}
        </Card>
      </div>
    </div>
  );
}
