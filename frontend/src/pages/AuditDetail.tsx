import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, hasReport, isActive, type Audit, type EngineReport, type Finding } from "../api";
import { FindingsExplorer } from "../components/FindingsExplorer";
import { ProgressStepper } from "../components/ProgressStepper";
import { ExecutionNotice, ReadinessPanel, SeverityPanel } from "../components/ReportSummary";
import { ErrorPanel, NewAuditLink, Spinner, StatusBadge } from "../components/ui";
import { consentLabel, formatDateTime, formatDuration } from "../lib/format";

const FAILURE_COPY: Record<string, string> = {
  failed: "The audit engine did not produce a valid report.",
  timed_out: "The audit hit the hard runtime limit and was stopped. Slow or unresponsive sites can cause this.",
  cancelled: "This audit was cancelled before it finished. No results were stored.",
  interrupted: "The server stopped while this audit was running, so it could not finish.",
};

export function AuditDetail() {
  const { id = "" } = useParams();
  const [audit, setAudit] = useState<Audit | null>(null);
  const [report, setReport] = useState<EngineReport | null>(null);
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [previous, setPrevious] = useState<Audit | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [cancelling, setCancelling] = useState(false);
  const [, setTick] = useState(0);

  const load = useCallback(async () => {
    try {
      const a = await api.getAudit(id);
      setAudit(a);
      setError(null);
      if (hasReport(a)) {
        const [r, f, hist] = await Promise.all([api.report(id), api.findings(id), api.listAudits({ host: a.host, limit: 20 })]);
        setReport(r.report);
        setFindings(f.items);
        setPrevious(hist.items.find((x) => x.id !== a.id && hasReport(x) && x.created_at <= a.created_at) ?? null);
      }
      return a;
    } catch (err) {
      setError(err);
      return null;
    }
  }, [id]);

  useEffect(() => {
    let timer: number | undefined;
    let stopped = false;
    const poll = async () => {
      const a = await load();
      if (!stopped && a && isActive(a.status)) timer = window.setTimeout(poll, 1500);
    };
    poll();
    const clock = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      window.clearInterval(clock);
    };
  }, [load]);

  async function cancel() {
    setCancelling(true);
    try {
      setAudit(await api.cancelAudit(id));
    } catch (err) {
      setError(err);
    } finally {
      setCancelling(false);
    }
  }

  if (error && !audit) return <ErrorPanel error={error} title="Could not load this audit" />;
  if (!audit) return <Spinner label="Loading audit" />;

  return (
    <div className="stack">
      <header className="audit-head">
        <div>
          <div className="eyebrow">Audit · <span className="mono">{audit.id.slice(0, 8)}</span></div>
          <h1 className="break">{audit.url}</h1>
          <div className="meta">
            <StatusBadge status={audit.status} />
            <span title={audit.created_at}>Started {formatDateTime(audit.started_at ?? audit.created_at)}</span>
            <span>Duration {formatDuration(audit.started_at, audit.finished_at)}</span>
            <span>Budget {audit.max_pages} pages</span>
            <span>External lookups: {consentLabel(audit.external_corroboration)}</span>
            {audit.engine_version && <span className="mono">{audit.engine_version}</span>}
          </div>
        </div>
        <div className="row">
          {isActive(audit.status) && (
            <button className="btn btn-danger" onClick={cancel} disabled={cancelling}>{cancelling ? "Cancelling…" : "Cancel audit"}</button>
          )}
          {hasReport(audit) && (
            <>
              <a className="btn" href={api.exportUrl(audit.id, "json")} download>Export JSON</a>
              <a className="btn" href={api.exportUrl(audit.id, "pdf")} download>Export PDF</a>
              {previous && <Link className="btn" to={`/compare?base=${previous.id}&target=${audit.id}`}>Compare with previous run</Link>}
            </>
          )}
        </div>
      </header>

      {error !== null && <ErrorPanel error={error} title="Refreshing failed" />}

      {isActive(audit.status) && (
        <section className="panel" aria-labelledby="progress-heading">
          <div className="panel-title">
            <h2 id="progress-heading">{audit.status === "queued" ? "Waiting for a free worker" : "Audit in progress"}</h2>
            <Spinner label="Updating" />
          </div>
          <ProgressStepper stages={audit.progress.stages} />
          <p className="small muted section">Requests to the site are spaced out deliberately, so a six-page audit usually takes 20–90 seconds.</p>
        </section>
      )}

      {FAILURE_COPY[audit.status] && (
        <section className="notice notice-error" role="alert">
          <h3>{FAILURE_COPY[audit.status]}</h3>
          {audit.error && <p className="small mono break">{audit.error}</p>}
          <div className="row"><NewAuditLink label="Start a new audit" /></div>
        </section>
      )}

      {hasReport(audit) && report && findings && (
        <>
          <ExecutionNotice report={report} />
          <div className="grid grid-2">
            <ReadinessPanel report={report} />
            <SeverityPanel audit={audit} report={report} />
          </div>
          {(report.scope.audited_urls?.length ?? 0) > 0 && (
            <details className="panel small">
              <summary>Audited pages ({report.scope.audited_urls!.length})</summary>
              <ul className="break">{report.scope.audited_urls!.map((u) => <li key={u}>{u}</li>)}</ul>
            </details>
          )}
          <div className="panel"><FindingsExplorer findings={findings} /></div>
        </>
      )}
    </div>
  );
}
