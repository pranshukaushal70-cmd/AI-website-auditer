import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApiError, type AuditStatus, type Severity } from "../api";
import { STATUS_LABEL } from "../lib/format";

/** Horizontal bar drawn in SVG so the page needs no inline styles (strict CSP). */
export function Bar({ value, max = 100, tone, label }: { value: number; max?: number; tone?: Severity; label: string }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <svg className="meter" viewBox="0 0 100 8" preserveAspectRatio="none" role="img" aria-label={label}>
      <rect className="track" width="100" height="8" rx="4" />
      {pct > 0 && <rect className={`fill ${tone ?? ""}`} width={Math.max(pct, 2)} height="8" rx="4" />}
    </svg>
  );
}

const STATUS_TONE: Record<AuditStatus, string> = {
  queued: "badge-neutral",
  running: "badge-info",
  completed: "badge-ok",
  partial: "badge-medium",
  failed: "badge-critical",
  timed_out: "badge-critical",
  cancelled: "badge-neutral",
  interrupted: "badge-high",
};

export function StatusBadge({ status }: { status: AuditStatus }) {
  return <span className={`badge ${STATUS_TONE[status]}`}>{STATUS_LABEL[status]}</span>;
}

export function SeverityBadge({ severity, proactive }: { severity: Severity; proactive?: boolean }) {
  if (proactive) return <span className="badge badge-proactive">Suggestion</span>;
  return <span className={`badge badge-${severity}`}>{severity[0]!.toUpperCase() + severity.slice(1)}</span>;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span role="status" className="row muted">
      <span className="spinner" aria-hidden="true" /> {label}…
    </span>
  );
}

export function ErrorPanel({ error, title = "Something went wrong" }: { error: unknown; title?: string }) {
  const err = error instanceof ApiError ? error : null;
  return (
    <div className="notice notice-error" role="alert">
      <h3>{title}</h3>
      <p className="break">{err?.message ?? (error instanceof Error ? error.message : String(error))}</p>
      {err?.requestId && <p className="small muted">Request ID: <code>{err.requestId}</code></p>}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty panel">
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function NewAuditLink({ label = "Run an audit" }: { label?: string }) {
  return (
    <Link className="btn btn-primary" to="/audits/new">
      {label}
    </Link>
  );
}
