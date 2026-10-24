/** Typed client for the platform API. All data shown in the UI comes from these calls. */

export type AuditStatus =
  | "queued" | "running" | "completed" | "partial" | "failed" | "timed_out" | "cancelled" | "interrupted";

export type StageState = "pending" | "running" | "completed" | "failed" | "timed_out";

export interface Audit {
  id: string;
  url: string;
  host: string;
  status: AuditStatus;
  max_pages: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress: { stages?: Record<string, StageState>; current?: string | null };
  error: string | null;
  readiness_score: number | null;
  readiness_band: string | null;
  total_findings: number | null;
  critical_count: number | null;
  high_count: number | null;
  medium_count: number | null;
  proactive_count: number | null;
  pages_checked: number | null;
  partial: boolean | null;
  engine_version: string | null;
  report_version: number | null;
  /** Per-audit consent for Wikipedia/Wikidata lookups; null for audits created before consent was recorded. */
  external_corroboration?: boolean | null;
}

export type Severity = "critical" | "high" | "medium";
export type Category = "technical" | "trust" | "engagement";

export interface PriorityFactor {
  name: string;
  value: number;
  input: string | number;
  explanation: string;
}

export interface Finding {
  id: number;
  audit_id: string;
  finding_code: string;
  fingerprint: string;
  title: string;
  category: Category;
  severity: Severity;
  confidence: number;
  proactive: boolean;
  affected_pages: string[];
  evidence: string;
  suggested_action: { summary?: string; priority?: string; how_to_fix?: string; proactive?: boolean };
  priority: { model: string; score: number; rank: number; factors: PriorityFactor[] } | null;
}

export interface UnavailableCheck {
  category: Category;
  check: string;
  evidence: string;
}

export interface EngineReport {
  site: string;
  audited_at: string;
  summary: { total_findings: number; critical: number; high: number; medium: number; proactive_suggestions_count: number };
  scope: {
    pages_checked: number;
    robots_checked: boolean;
    sitemap_checked: boolean;
    sitemap_found?: boolean;
    render_check: boolean;
    render_status?: string;
    external_sources_checked: number;
    audited_urls?: string[];
    external_corroboration?: "skipped_by_user" | "unavailable" | "performed" | "not_run";
  };
  execution: {
    partial: boolean;
    missing_categories?: string[];
    unavailable_categories?: string[];
    unavailable_checks?: UnavailableCheck[];
    skipped_checks?: UnavailableCheck[];
    failed_pages?: string[];
    errors?: string[];
    runtime_seconds?: number;
    note?: string;
  };
  readiness?: { score: number; band: string; dimensions: Record<Category, number>; method: string };
}

export interface CompareItem {
  fingerprint: string;
  title: string;
  category: Category;
  severity: Severity;
  confidence: number;
  affected_pages: string[];
  priority_score: number | null;
  previous_severity?: Severity;
  severity_changed?: boolean;
  reason?: string;
  side?: "base" | "target";
}

export interface CompareResult {
  base: Pick<Audit, "id" | "url" | "status" | "created_at" | "readiness_score">;
  target: Pick<Audit, "id" | "url" | "status" | "created_at" | "readiness_score">;
  readiness_delta: number | null;
  counts: Record<"persistent" | "new" | "resolved" | "inconclusive", number>;
  caveats: string[];
  persistent: CompareItem[];
  new: CompareItem[];
  resolved: CompareItem[];
  inconclusive: CompareItem[];
}

export interface PublicConfig {
  max_pages_cap: number;
  default_max_pages: number;
  allowed_ports: number[];
  max_concurrent_jobs: number;
  max_queued_jobs: number;
  runtime_limit_seconds: number;
  rendering_enabled: boolean;
  priority_model: string;
  engine_version: string;
  external_corroboration_available: boolean;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId?: string,
    public details?: { field: string; message: string }[],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(BASE + path, {
      ...init,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "network_error", "The API could not be reached. Check that the backend is running.");
  }
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!response.ok) {
    const err = (body as { error?: { code?: string; message?: string; request_id?: string; details?: never } } | null)?.error;
    throw new ApiError(
      response.status,
      err?.code ?? "http_error",
      err?.message ?? `Request failed with status ${response.status}.`,
      err?.request_id ?? response.headers.get("X-Request-ID") ?? undefined,
      err?.details,
    );
  }
  return body as T;
}

export const api = {
  config: () => request<PublicConfig>("/config"),
  createAudit: (url: string, maxPages: number, externalCorroboration = false) =>
    request<Audit>("/audits", {
      method: "POST",
      body: JSON.stringify({ url, max_pages: maxPages, external_corroboration: externalCorroboration }),
    }),
  listAudits: (params: { status?: string; q?: string; host?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    });
    return request<{ items: Audit[]; total: number; limit: number; offset: number }>(`/audits?${qs}`);
  },
  getAudit: (id: string) => request<Audit>(`/audits/${encodeURIComponent(id)}`),
  cancelAudit: (id: string) => request<Audit>(`/audits/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  findings: (id: string) => request<{ items: Finding[]; total: number }>(`/audits/${encodeURIComponent(id)}/findings`),
  report: (id: string) => request<{ audit: Audit; report: EngineReport }>(`/audits/${encodeURIComponent(id)}/report`),
  compare: (base: string, target: string) =>
    request<CompareResult>(`/compare?base=${encodeURIComponent(base)}&target=${encodeURIComponent(target)}`),
  exportUrl: (id: string, format: "json" | "pdf") => `${BASE}/audits/${encodeURIComponent(id)}/report.${format}`,
};

export const ACTIVE_STATUSES: AuditStatus[] = ["queued", "running"];
export const isActive = (s: AuditStatus) => ACTIVE_STATUSES.includes(s);
export const hasReport = (a: Audit) => a.report_version !== null && (a.status === "completed" || a.status === "partial");
