import type { Audit, Category, EngineReport } from "../api";
import { BAND_LABEL, CATEGORY_LABEL, CHECK_LABEL, SEVERITY_ORDER } from "../lib/format";
import { Bar } from "./ui";

export function ReadinessPanel({ report }: { report: EngineReport }) {
  const r = report.readiness;
  if (!r) return null;
  return (
    <section className="panel" aria-labelledby="readiness-heading">
      <div className="eyebrow">Internal diagnostic index</div>
      <h2 id="readiness-heading" className="sr-only">Readiness index</h2>
      <div className="score">
        <span className="score-value">{r.score.toFixed(1)}</span>
        <span className="score-scale">/ 100 · {BAND_LABEL[r.band] ?? r.band}</span>
      </div>
      <div className="stack">
        {(Object.keys(CATEGORY_LABEL) as Category[]).map((c) => (
          <div className="dimension" key={c}>
            <span>{CATEGORY_LABEL[c]}</span>
            <Bar value={r.dimensions[c] ?? 0} label={`${CATEGORY_LABEL[c]}: ${r.dimensions[c]} of 100`} />
            <span className="num mono">{(r.dimensions[c] ?? 0).toFixed(0)}</span>
          </div>
        ))}
      </div>
      <p className="small muted">
        Starts at 100 per dimension and subtracts a severity- and confidence-weighted penalty for each detected defect.
        Suggestions do not count. Not an Adobe score and not validated against search or AI-assistant outcomes.
      </p>
    </section>
  );
}

export function SeverityPanel({ audit, report }: { audit: Audit; report: EngineReport }) {
  const counts = { critical: report.summary.critical, high: report.summary.high, medium: report.summary.medium };
  const max = Math.max(1, ...Object.values(counts));
  return (
    <section className="panel" aria-labelledby="severity-heading">
      <div className="eyebrow">Detected defects</div>
      <h2 id="severity-heading">
        {report.summary.total_findings} finding{report.summary.total_findings === 1 ? "" : "s"}
        <span className="muted small"> · {report.summary.proactive_suggestions_count} suggestion(s)</span>
      </h2>
      <div className="sev-bars">
        {SEVERITY_ORDER.map((s) => (
          <div className="sev-bar" key={s}>
            <span>{s[0]!.toUpperCase() + s.slice(1)}</span>
            <Bar value={counts[s]} max={max} tone={s} label={`${counts[s]} ${s} findings`} />
            <span className="num mono">{counts[s]}</span>
          </div>
        ))}
      </div>
      <dl className="grid grid-3 small">
        <div><dt className="muted">Pages checked</dt><dd className="mono">{report.scope.pages_checked} of {audit.max_pages} budget</dd></div>
        <div><dt className="muted">robots.txt</dt><dd>{report.scope.robots_checked ? "Checked" : "Not checked"}</dd></div>
        <div><dt className="muted">Sitemap</dt><dd>{sitemapLabel(report)}</dd></div>
      </dl>
    </section>
  );
}

function sitemapLabel(report: EngineReport): string {
  const status = report.scope.sitemap_found ? "Found" : report.scope.sitemap_checked ? "Checked, none found on this site" : "Not checked";
  const skipped = report.scope.sitemaps_skipped_offsite?.length ?? 0;
  return skipped ? `${status} · ${skipped} on another host not fetched` : status;
}

/** Makes partial execution impossible to miss: unavailable checks are never presented as passes. */
export function ExecutionNotice({ report }: { report: EngineReport }) {
  const ex = report.execution;
  const unavailableCats = ex.unavailable_categories ?? [];
  const missing = ex.missing_categories ?? [];
  const checks = ex.unavailable_checks ?? [];
  const failed = ex.failed_pages ?? [];
  const truncated = ex.truncated_pages ?? [];
  const skippedSitemaps = report.scope.sitemaps_skipped_offsite ?? [];
  const missingEvidence = ex.partial || checks.length > 0 || failed.length > 0;
  if (!missingEvidence && truncated.length === 0 && skippedSitemaps.length === 0) return null;
  const heading = ex.partial ? "Partial audit — some evidence is missing" : missingEvidence ? "Some checks could not run" : "Audit scope notes";
  return (
    <section className={`notice ${ex.partial ? "" : "notice-info"}`} aria-labelledby="exec-heading">
      <h3 id="exec-heading">{heading}</h3>
      {missingEvidence && <p className="small">Checks that could not run are not counted as passes and produce no findings.</p>}
      <ul className="small">
        {[...missing, ...unavailableCats].length > 0 && (
          <li>No usable evidence for: <strong>{[...new Set([...missing, ...unavailableCats])].join(", ")}</strong>.</li>
        )}
        {checks.length > 0 && (
          <li>Unavailable checks: {checks.map((c) => `${CHECK_LABEL[c.check] ?? c.check} (${c.category})`).join("; ")}.</li>
        )}
        {failed.length > 0 && <li className="break">Pages that failed to load: {failed.join(", ")}.</li>}
        {truncated.length > 0 && (
          <li className="break">Larger than 2 MB, so only the first 2 MB was analysed: {truncated.join(", ")}.</li>
        )}
        {skippedSitemaps.length > 0 && (
          <li className="break">
            Sitemaps declared in robots.txt on another host were not fetched (only the audited site is crawled):{" "}
            {skippedSitemaps.join(", ")}.
          </li>
        )}
        {(ex.errors ?? []).slice(0, 5).map((e) => <li key={e} className="break mono">{e}</li>)}
      </ul>
    </section>
  );
}
