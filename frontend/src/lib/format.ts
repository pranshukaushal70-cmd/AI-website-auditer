import type { AuditStatus, Category, Severity } from "../api";

/** Timestamps are stored as UTC ISO-8601; render them in the viewer's local time zone. */
export function formatDateTime(iso: string | null | undefined, locale?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(d);
}

export function formatDuration(startIso: string | null, endIso: string | null, now = Date.now()): string {
  if (!startIso) return "—";
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : now;
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
}

export const STATUS_LABEL: Record<AuditStatus, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  partial: "Partial",
  failed: "Failed",
  timed_out: "Timed out",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
};

export const CATEGORY_LABEL: Record<Category, string> = {
  technical: "Technical discoverability",
  trust: "Trust & freshness",
  engagement: "Engagement & answerability",
};

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium"];

/** The recorded per-audit consent for Wikipedia/Wikidata lookups. */
export function consentLabel(choice: boolean | null | undefined): string {
  if (choice === null || choice === undefined) return "Not recorded (predates consent)";
  return choice ? "Opted in" : "Not requested";
}

export const BAND_LABEL: Record<string, string> = {
  excellent: "Excellent",
  strong: "Strong",
  needs_attention: "Needs attention",
  at_risk: "At risk",
};

export const STAGE_LABEL: Record<string, string> = {
  technical: "Crawl & technical checks",
  trust: "Trust & freshness",
  engagement: "Engagement",
  compose: "Compose report",
};

export const CHECK_LABEL: Record<string, string> = {
  crawler_block: "Page fetch",
  js_render_gap: "JavaScript render comparison",
  rendered_mobile: "Rendered mobile layout",
  rendered_experience: "Rendered above-the-fold layout",
  structured_data: "Structured data",
  viewport_check: "Viewport meta",
  faq_schema_check: "FAQ schema parity",
  locked_content: "Images & canvas text",
  copyright: "Copyright freshness",
  multi_signal_freshness: "Multi-signal freshness",
  eeat_check: "Authorship & contact transparency",
  corroboration_check: "External corroboration",
  ambiguity_check: "Entity ambiguity",
  entity_confidence: "Entity confidence",
  h1_audit: "Heading hierarchy",
  readability: "Readability",
  navigation_cta: "Navigation & CTAs",
  answerability: "Answerability",
  deep_link_context: "Deep-link context",
  clutter: "Text-to-code ratio",
};

export function hostPath(url: string): string {
  try {
    const u = new URL(url);
    return u.host + (u.pathname === "/" ? "" : u.pathname);
  } catch {
    return url;
  }
}

/** Only http(s) URLs from audit data become links; anything else renders as plain text. */
export function safeHref(url: string): string | undefined {
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : undefined;
  } catch {
    return undefined;
  }
}
