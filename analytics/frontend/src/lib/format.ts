/** Escape text before interpolating it into an ECharts tooltip, which renders its formatter output as HTML. */
export function escapeHtml(v: any): string {
  if (v === null || v === undefined) return "";
  return String(v).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string));
}

export function fmtNumber(v: any, format?: string, compact = true): string {
  if (v === null || v === undefined || v === "") return "–";
  const n = typeof v === "number" ? v : Number(v);
  if (Number.isNaN(n)) return String(v);
  if (format === "percent") return `${(n * 100).toFixed(Math.abs(n) < 0.1 ? 2 : 1)}%`;
  const a = Math.abs(n);
  let s: string;
  if (compact && a >= 1e7) s = `${(n / 1e7).toFixed(2)} Cr`;
  else if (compact && a >= 1e5) s = `${(n / 1e5).toFixed(2)} L`;
  else if (a >= 100 || Number.isInteger(n)) s = n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  else s = n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return format === "currency" ? `₹${s}` : s;
}

export function fmtCell(v: any, type?: string, format?: string): string {
  if (v === null || v === undefined) return "";
  if (type === "decimal" || type === "integer" || typeof v === "number") return fmtNumber(v, format, false);
  if (type === "boolean") return v ? "Yes" : "No";
  return String(v);
}

export function fmtDateLabel(v: any, grain?: string | null): string {
  if (v === null || v === undefined) return "(blank)";
  const s = String(v);
  if (!/^\d{4}-\d{2}-\d{2}/.test(s)) return s;
  const d = new Date(s.slice(0, 10) + "T00:00:00");
  if (grain === "month") return d.toLocaleDateString("en-IN", { month: "short", year: "numeric" });
  if (grain === "quarter") return `Q${Math.floor(d.getMonth() / 3) + 1} ${d.getFullYear()}`;
  if (grain === "year") return String(d.getFullYear());
  if (grain === "week") return `Wk of ${d.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}`;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export const PRESET_LABELS: Record<string, string> = {
  today: "Today", yesterday: "Yesterday", last_7_days: "Last 7 days", last_30_days: "Last 30 days", last_90_days: "Last 90 days",
  this_week: "This week", last_week: "Last week", this_month: "This month", last_month: "Last month", this_quarter: "This quarter",
  last_quarter: "Last quarter", this_year: "This year", last_year: "Last year", last_3_months: "Last 3 months",
  last_6_months: "Last 6 months", last_12_months: "Last 12 months", year_to_date: "Year to date", all_time: "All time",
};

export function describeRange(r: any): string {
  if (!r) return "All time";
  if (typeof r === "string") return PRESET_LABELS[r] || r;
  if (r.preset) return PRESET_LABELS[r.preset] || r.preset;
  if (r.last) return `Last ${r.last} ${r.unit}`;
  if (r.from || r.to) return `${r.from || "…"} → ${r.to || "…"}`;
  return "Custom";
}

export function timeAgo(iso?: string | null): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export const TYPE_ICON: Record<string, string> = { text: "Aa", integer: "#", decimal: "#.#", date: "📅", datetime: "⏱", boolean: "✓" };
