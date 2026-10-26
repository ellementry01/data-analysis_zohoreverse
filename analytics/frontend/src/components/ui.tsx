import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, X } from "lucide-react";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type BtnVariant = "primary" | "secondary" | "ghost" | "danger";
export function Button({ variant = "secondary", size = "md", className, loading, children, ...rest }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: "sm" | "md"; loading?: boolean }) {
  const base = "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap";
  const sizes = { sm: "px-2.5 py-1 text-xs", md: "px-3.5 py-2 text-sm" };
  const variants: Record<BtnVariant, string> = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm",
    secondary: "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 shadow-sm",
    ghost: "text-slate-600 hover:bg-slate-100",
    danger: "bg-white text-red-600 border border-red-200 hover:bg-red-50",
  };
  return (
    <button className={cx(base, sizes[size], variants[variant], className)} disabled={loading || rest.disabled} {...rest}>
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  );
}

export function Card({ className, children, title, actions, bodyClass }: { className?: string; children: ReactNode; title?: ReactNode; actions?: ReactNode; bodyClass?: string }) {
  return (
    <div className={cx("rounded-lg border border-slate-200 bg-white shadow-card", className)}>
      {(title || actions) && (
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-2.5">
          <div className="text-sm font-semibold text-slate-800">{title}</div>
          <div className="flex items-center gap-2">{actions}</div>
        </div>
      )}
      <div className={cx("p-4", bodyClass)}>{children}</div>
    </div>
  );
}

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "blue" | "green" | "amber" | "red" | "violet" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700", blue: "bg-brand-50 text-brand-700", green: "bg-emerald-50 text-emerald-700",
    amber: "bg-amber-50 text-amber-700", red: "bg-red-50 text-red-700", violet: "bg-violet-50 text-violet-700",
  };
  return <span className={cx("inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium", tones[tone])}>{children}</span>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-slate-500">
      <Loader2 className="h-4 w-4 animate-spin" /> {label || "Loading…"}
    </div>
  );
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
      {icon && <div className="mb-3 text-slate-400">{icon}</div>}
      <div className="text-sm font-semibold text-slate-800">{title}</div>
      {children && <div className="mt-1 max-w-md text-sm text-slate-500">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: any }) {
  if (!error) return null;
  return (
    <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span className="break-words">{String(error?.message || error)}</span>
    </div>
  );
}

export function Modal({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 pt-16" onMouseDown={onClose}>
      <div className={cx("w-full rounded-lg bg-white shadow-xl", wide ? "max-w-4xl" : "max-w-lg")} onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <div className="font-semibold text-slate-800">{title}</div>
          <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-slate-200 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: { id: string; label: ReactNode }[]; value: string; onChange: (id: string) => void }) {
  return (
    <div className="flex gap-1 border-b border-slate-200">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={cx("-mb-px border-b-2 px-3 py-2 text-sm font-medium", value === t.id ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-700")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export const inputCls = "w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-800 shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:bg-slate-50";

export function Label({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="mb-1 block text-xs font-medium text-slate-600">
      {children} {hint && <span className="font-normal text-slate-400">{hint}</span>}
    </label>
  );
}

export function Select({ value, onChange, options, className, placeholder, disabled }:
  { value: string; onChange: (v: string) => void; options: { value: string; label: string; group?: string }[]; className?: string; placeholder?: string; disabled?: boolean }) {
  const groups = Array.from(new Set(options.map((o) => o.group || "")));
  return (
    <select className={cx(inputCls, className)} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {groups.map((g) =>
        g ? (
          <optgroup key={g} label={g}>
            {options.filter((o) => o.group === g).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </optgroup>
        ) : (
          options.filter((o) => !o.group).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)
        ),
      )}
    </select>
  );
}

// ---------------------------------------------------------------------------------------------- toasts
type Toast = { id: number; tone: "success" | "error" | "info"; text: string };
const ToastCtx = createContext<(tone: Toast["tone"], text: string) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((tone: Toast["tone"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, tone, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="no-print fixed bottom-4 right-4 z-[60] flex w-96 flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className={cx("flex items-start gap-2 rounded-md border px-3 py-2 text-sm shadow-lg",
            t.tone === "error" ? "border-red-200 bg-red-50 text-red-800" : t.tone === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-white text-slate-700")}>
            {t.tone === "error" ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> : t.tone === "success" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <Info className="mt-0.5 h-4 w-4 shrink-0" />}
            <span className="break-words">{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

// ---------------------------------------------------------------------------------------------- data hook
export function useAsync<T>(fn: () => Promise<T>, deps: any[]) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fn()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1), setData };
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
