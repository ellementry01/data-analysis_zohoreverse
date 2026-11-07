import { useState } from "react";
import { Brain, Check, Pencil, Undo2, X } from "lucide-react";
import { api } from "../api/client";
import { cx, inputCls, useToast } from "./ui";

/** A memory as the API returns it (backend routers/memory.py). */
export interface MemoryItem {
  id: number; layer: "personal" | "shared" | "decision"; kind: string; scope: string; scope_label: string;
  text: string; rationale: string; status: "proposed" | "active" | "rejected" | "retired" | "needs_review";
  review_reason: string; origin: "explicit" | "inferred" | "manual"; visibility: "private" | "shared";
  share_status: "none" | "pending" | "approved" | "rejected"; mine: boolean; owner: string | null; can_edit: boolean;
  source: { conversation_id: number | null; dashboard_key: string | null; excerpt: string };
  created_at: string; approved_at: string | null; last_used_at: string | null; use_count: number;
}
/** The short form an answer carries (memories_saved / memories_used). */
export interface MemoryBrief { id: number; text: string; kind: string; layer: string; scope: string; status: string; rationale?: string }

export const KIND_LABEL: Record<string, string> = {
  preference: "Preference", fact: "Fact", decision: "Decision", caveat: "Caveat", open_question: "Open question",
};

/** Under an answer: what it saved (with undo) and which memories shaped it. */
export function MemoryChips({ wsId, saved = [], used = [] }: { wsId: number; saved?: MemoryBrief[]; used?: MemoryBrief[] }) {
  const toast = useToast();
  const [undone, setUndone] = useState<number[]>([]);
  if (!saved.length && !used.length) return null;
  const undo = async (id: number) => {
    try {
      await api.del(`/workspaces/${wsId}/memory/${id}`);
      setUndone((u) => [...u, id]);
    } catch (e: any) {
      toast("error", e.message);
    }
  };
  return (
    <div className="mt-2 flex flex-col gap-1">
      {saved.map((s) => (
        <div key={`s${s.id}`} className={cx("flex items-start gap-1.5 rounded-md px-2 py-1 text-[11px]",
          undone.includes(s.id) ? "bg-slate-100 text-slate-400 line-through" : s.status === "active" ? "bg-emerald-50 text-emerald-800" : "bg-violet-50 text-violet-800")}>
          <Brain className="mt-0.5 h-3 w-3 shrink-0" />
          <span className="min-w-0 flex-1">
            <b className="font-medium">{undone.includes(s.id) ? "Removed" : s.status === "active" ? "Saved to memory" : "Suggested for memory"}:</b> {s.text}
            {s.status !== "active" && !undone.includes(s.id) && <span className="text-violet-600"> (approve it above or on the Memory page)</span>}
          </span>
          {!undone.includes(s.id) && (
            <button onClick={() => undo(s.id)} className="inline-flex shrink-0 items-center gap-0.5 font-medium hover:underline" aria-label="Undo saving this memory">
              <Undo2 className="h-3 w-3" /> Undo
            </button>
          )}
        </div>
      ))}
      {used.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 text-[11px] text-slate-500">
          <Brain className="h-3 w-3" /> Remembered:
          {used.map((u) => <span key={`u${u.id}`} title={u.text} className="max-w-[16rem] truncate rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">#{u.id} {u.text}</span>)}
        </div>
      )}
    </div>
  );
}

/** A "Remember this?" suggestion: accept, edit then accept, or reject. */
export function ProposalCard({ wsId, item, onDone }: { wsId: number; item: MemoryItem; onDone: () => void }) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(item.text);
  const [busy, setBusy] = useState(false);
  const act = async (action: "accept" | "reject") => {
    setBusy(true);
    try {
      if (action === "accept" && text.trim() !== item.text) await api.patch(`/workspaces/${wsId}/memory/${item.id}`, { text: text.trim() });
      await api.post(`/workspaces/${wsId}/memory/${item.id}/${action}`);
      onDone();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="rounded-lg border border-violet-200 bg-violet-50/60 px-2.5 py-2 text-xs text-slate-700">
      <div className="mb-1 flex items-center gap-1 font-medium text-violet-800">
        <Brain className="h-3.5 w-3.5" /> Remember this? <span className="font-normal text-violet-600">· {KIND_LABEL[item.kind] || item.kind} · {item.scope_label}</span>
      </div>
      {editing
        ? <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={500} rows={2} className={cx(inputCls, "text-xs")} />
        : <div className="text-slate-800">{text}</div>}
      {item.source.excerpt && !editing && <div className="mt-0.5 truncate text-[10px] text-slate-400" title={item.source.excerpt}>From: “{item.source.excerpt}”</div>}
      <div className="mt-1.5 flex items-center gap-2">
        <button disabled={busy || text.trim().length < 3} onClick={() => act("accept")}
          className="inline-flex items-center gap-1 rounded bg-violet-600 px-2 py-0.5 font-medium text-white hover:bg-violet-700 disabled:opacity-50"><Check className="h-3 w-3" /> Remember</button>
        {!editing && <button disabled={busy} onClick={() => setEditing(true)} className="inline-flex items-center gap-1 text-violet-700 hover:underline"><Pencil className="h-3 w-3" /> Edit</button>}
        <button disabled={busy} onClick={() => act("reject")} className="ml-auto inline-flex items-center gap-1 text-slate-500 hover:text-red-600"><X className="h-3 w-3" /> No</button>
      </div>
    </div>
  );
}
