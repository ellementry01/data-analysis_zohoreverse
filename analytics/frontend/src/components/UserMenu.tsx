import { Link } from "react-router-dom";
import { LogOut, Shield } from "lucide-react";
import { api } from "../api/client";
import { cx, useAsync } from "./ui";

export interface Me { email: string; name?: string; auth_mode?: "dev" | "google"; is_platform_admin?: boolean }

export function useMe() {
  return useAsync(() => api.get<Me>("/me"), []);
}

/** Who is signed in, a way out, and (for platform admins) the administration page. */
export function UserMenu({ compact = false }: { compact?: boolean }) {
  const me = useMe();
  if (!me.data) return null;
  const signOut = async () => {
    try { await api.post("/auth/logout"); } catch { /* already signed out */ }
    window.location.href = "/api/auth/login";
  };
  return (
    <div className={cx("text-xs text-slate-500", compact ? "border-t border-slate-100 px-4 py-2.5" : "flex items-center gap-3")}>
      <div className={cx("min-w-0", compact && "mb-1")}>
        <div className="truncate font-medium text-slate-700" title={me.data.email}>{me.data.name || me.data.email}</div>
        {me.data.name && <div className="truncate text-[11px] text-slate-400">{me.data.email}</div>}
      </div>
      <div className="flex items-center gap-3">
        {me.data.is_platform_admin && (
          <Link to="/admin" className="inline-flex items-center gap-1 text-brand-600 hover:underline"><Shield className="h-3.5 w-3.5" /> Administration</Link>
        )}
        {me.data.auth_mode === "google" && (
          <button onClick={signOut} className="inline-flex items-center gap-1 hover:text-slate-800"><LogOut className="h-3.5 w-3.5" /> Sign out</button>
        )}
      </div>
    </div>
  );
}
