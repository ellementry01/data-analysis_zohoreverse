// Thin typed wrapper around the Ellementry REST API.
export const USER_KEY = "ellementry.user";

export function currentUser(): string {
  try {
    return localStorage.getItem(USER_KEY) || "owner@local";
  } catch {
    return "owner@local";
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = { "X-User-Email": currentUser() };
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d: any) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ") : res.statusText;
    throw new ApiError(res.status, msg || `HTTP ${res.status}`);
  }
  return data as T;
}

export const api = {
  get: <T,>(p: string) => request<T>("GET", p),
  post: <T,>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  put: <T,>(p: string, b?: unknown) => request<T>("PUT", p, b ?? {}),
  patch: <T,>(p: string, b?: unknown) => request<T>("PATCH", p, b ?? {}),
  del: <T,>(p: string) => request<T>("DELETE", p),
  upload: <T,>(p: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<T>("POST", p, fd, true);
  },
  async download(path: string, body: unknown, filename: string) {
    const res = await fetch(`/api${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "X-User-Email": currentUser(), "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) throw new ApiError(res.status, (await res.text()) || "Download failed");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};

// ---------------------------------------------------------------------------------------------- types
export type DataType = "text" | "integer" | "decimal" | "date" | "datetime" | "boolean";

export interface Workspace {
  id: number; name: string; description: string; role: string | null; created_at: string;
  dataset_count?: number; dashboard_count?: number; members?: { user_email: string; role: string }[];
}
export interface Column {
  id: number; name: string; display_name: string; data_type: DataType; position: number; is_derived: boolean;
  expression: string | null; description: string; hidden: boolean; source_name: string | null;
}
export interface QualityWarning { level: string; code: string; column?: string; message: string; count?: number; variants?: Record<string, string[]> }
export interface Dataset {
  id: number; name: string; slug: string; kind: "file" | "connector" | "query_table"; description: string; row_count: number;
  default_date_column: string | null; created_at: string; updated_at: string; last_refreshed_at: string | null;
  source_info: any; column_count: number; warning_count: number; columns: Column[]; query_sql: string | null;
  quality: { warnings?: QualityWarning[]; row_count?: number; checked_at?: string };
  transforms: { id: number; kind: string; params: any; position: number; created_at: string; last_result: string }[];
}
export interface Field { ref: string; name: string; label: string; type: DataType; derived: boolean; role: "measure" | "dimension" }
export interface ModelDataset {
  id: number; slug: string; name: string; kind: string; row_count: number; default_date_column: string | null;
  label_column: string | null; lookups: string[]; fields: Field[];
}
export interface Metric {
  id: number; name: string; label: string; description: string; kind: "simple" | "composite"; dataset_id: number | null;
  expression: string; filters: FilterRule[]; time_column: string | null; semi_additive: boolean; synonyms: string[];
  format: "number" | "currency" | "percent"; higher_is_better: boolean;
}
export interface FilterRule { column: string; op: string; value: any }
export interface Model { datasets: ModelDataset[]; metrics: Metric[]; date_presets: string[]; relationships: { from: string; to: string }[] }

export interface Dimension { field: string; grain?: string | null; alias?: string | null; label?: string | null }
export interface Measure { metric?: string | null; field?: string | null; agg?: string; alias?: string | null; label?: string | null }
export interface SpecFilter { field: string; op: string; value: any }
export interface QuerySpec {
  dimensions: Dimension[]; measures: Measure[]; filters: SpecFilter[]; time_range?: any; time_field?: string | null;
  compare?: "previous_period" | "previous_year" | null; sort: { field: string; dir: "asc" | "desc" }[]; limit?: number | null; apply_rules?: boolean;
}
export interface ResultColumn {
  name: string; label: string; role: "dimension" | "measure"; type: string; format?: string; grain?: string | null;
  additive?: boolean; compare_of?: string; higher_is_better?: boolean;
}
export interface Insight { type: string; text: string; x?: string; value?: number; expected?: number }
export interface QueryResult {
  columns: ResultColumn[]; rows: any[][]; row_count: number; truncated: boolean; duration_ms: number; sql: string;
  warnings: string[]; date_range: [string, string] | null; suggested_chart: string; insights: Insight[];
  comparison?: { mode: string; previous_range: string; current_range: string; summary?: string };
  applied_spec?: QuerySpec;
}
export interface Report { id: number; name: string; description: string; chart_type: string; spec: QuerySpec; options: any; updated_at: string }
export interface DashFilter { id: string; type: "date_range" | "values"; label: string; field: string; value: any }
export interface Widget { id: number; title: string; chart_type: string; spec: QuerySpec; options: any; layout: { x: number; y: number; w: number; h: number }; report_id: number | null }
export interface Dashboard { id: number; name: string; description: string; filters: DashFilter[]; is_template: boolean; widgets: Widget[]; widget_count: number; updated_at: string }
export interface Relationship { id: number; from_dataset_id: number; from_column: string; to_dataset_id: number; to_column: string; cardinality: string }

export const emptySpec = (): QuerySpec => ({ dimensions: [], measures: [], filters: [], sort: [], time_range: null, compare: null, limit: null, apply_rules: true });
