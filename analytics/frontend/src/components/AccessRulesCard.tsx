import { useState } from "react";
import { Lock, Trash2 } from "lucide-react";
import { api, Dashboard } from "../api/client";
import { Button, Card, inputCls, useAsync, useToast } from "./ui";

interface Rule { id: number; target_type: "dashboard" | "domain" | "dataset"; target: string; principal_type: "role" | "user"; principal: string; created_by: string }

const DOMAINS = ["executive", "sales", "stock", "operations", "purchasing", "returns", "quick_commerce", "marketing", "finance", "customer", "product", "design", "data"];

/** Who may see which dashboards, domains and datasets. Without rules, every member sees everything. */
export function AccessRulesCard({ wsId, datasets }: { wsId: number; datasets: { slug: string; name: string }[] }) {
  const toast = useToast();
  const rules = useAsync(() => api.get<Rule[]>(`/workspaces/${wsId}/access-rules`), [wsId]);
  const dashboards = useAsync(() => api.get<Dashboard[]>(`/workspaces/${wsId}/dashboards`), [wsId]);
  const [form, setForm] = useState({ target_type: "dashboard", target: "", principal_type: "role", principal: "editor" });
  const targets = form.target_type === "dashboard" ? (dashboards.data || []).map((d) => ({ value: d.key, label: `${d.name} (${d.key})` }))
    : form.target_type === "domain" ? DOMAINS.map((d) => ({ value: d, label: d }))
      : datasets.map((d) => ({ value: d.slug, label: `${d.name} (${d.slug})` }));
  const add = async () => {
    try {
      await api.post(`/workspaces/${wsId}/access-rules`, form);
      setForm({ ...form, target: "" });
      rules.reload();
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  const remove = async (r: Rule) => {
    await api.del(`/workspaces/${wsId}/access-rules/${r.id}`);
    rules.reload();
  };
  const describe = (r: Rule) => (r.principal_type === "role" ? `${r.principal}s and above` : r.principal);
  return (
    <Card title={<span className="flex items-center gap-1.5"><Lock className="h-4 w-4" /> Access rules</span>}>
      <p className="mb-3 text-xs text-slate-500">Without rules every member sees everything in this workspace. Once a dashboard, a domain of dashboards or a dataset has rules, only the people they name (and workspace admins) see it, and the assistant sees no more than the person asking.</p>
      {(rules.data || []).length === 0 && <div className="mb-3 text-sm text-slate-400">No rules: every member sees everything.</div>}
      {(rules.data || []).map((r) => (
        <div key={r.id} className="flex items-center gap-3 border-b border-slate-100 py-1.5 text-sm last:border-0">
          <span className="flex-1"><b className="font-medium">{r.target_type}</b> {r.target} → visible to {describe(r)}</span>
          <button onClick={() => remove(r)} aria-label="Remove rule" className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
        </div>
      ))}
      <div className="mt-3 grid gap-2 sm:grid-cols-[8rem_1fr_7rem_1fr_auto]">
        <select className={inputCls} value={form.target_type} onChange={(e) => setForm({ ...form, target_type: e.target.value, target: "" })} aria-label="Restrict a">
          <option value="dashboard">Dashboard</option><option value="domain">Domain</option><option value="dataset">Dataset</option>
        </select>
        <select className={inputCls} value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })} aria-label="Which one">
          <option value="">Choose…</option>{targets.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <select className={inputCls} value={form.principal_type} onChange={(e) => setForm({ ...form, principal_type: e.target.value, principal: e.target.value === "role" ? "editor" : "" })} aria-label="Visible to">
          <option value="role">Role</option><option value="user">Person</option>
        </select>
        {form.principal_type === "role" ? (
          <select className={inputCls} value={form.principal} onChange={(e) => setForm({ ...form, principal: e.target.value })} aria-label="Minimum role">
            <option value="viewer">Viewers and above</option><option value="editor">Editors and above</option><option value="admin">Admins only</option>
          </select>
        ) : <input className={inputCls} placeholder="name@company.com" value={form.principal} onChange={(e) => setForm({ ...form, principal: e.target.value })} />}
        <Button onClick={add} disabled={!form.target || !form.principal}>Add</Button>
      </div>
    </Card>
  );
}
