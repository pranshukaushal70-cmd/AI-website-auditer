import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, hasReport, type Audit } from "../api";
import { Bar, EmptyState, ErrorPanel, NewAuditLink, Spinner, StatusBadge } from "../components/ui";
import { formatDateTime } from "../lib/format";

/** Latest completed/partial run per host, computed from the stored audit list. */
export function latestPerHost(audits: Audit[]): Audit[] {
  const seen = new Map<string, Audit>();
  for (const a of audits) {
    if (!hasReport(a)) continue;
    const prev = seen.get(a.host);
    if (!prev || a.created_at > prev.created_at) seen.set(a.host, a);
  }
  return [...seen.values()].sort((a, b) => (a.readiness_score ?? 0) - (b.readiness_score ?? 0));
}

export function Dashboard() {
  const [audits, setAudits] = useState<Audit[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.listAudits({ limit: 100 }).then((r) => { setAudits(r.items); setTotal(r.total); }).catch(setError);
  }, []);

  if (error) return <ErrorPanel error={error} title="Could not load the dashboard" />;
  if (!audits) return <Spinner label="Loading dashboard" />;
  if (audits.length === 0) {
    return <EmptyState title="No audits yet" action={<NewAuditLink label="Run the first audit" />}>
      The dashboard summarises stored audits. Nothing is shown until a real audit has run.
    </EmptyState>;
  }

  const latest = latestPerHost(audits);
  const withReport = audits.filter(hasReport);
  const failedish = audits.filter((a) => ["failed", "timed_out", "interrupted"].includes(a.status)).length;
  const partial = audits.filter((a) => a.status === "partial").length;
  const sev = latest.reduce((acc, a) => ({ critical: acc.critical + (a.critical_count ?? 0), high: acc.high + (a.high_count ?? 0),
    medium: acc.medium + (a.medium_count ?? 0) }), { critical: 0, high: 0, medium: 0 });
  const sevMax = Math.max(1, sev.critical, sev.high, sev.medium);

  return (
    <div className="stack">
      <div className="row"><h1>Dashboard</h1><span className="spacer" /><NewAuditLink /></div>
      <p className="small muted">
        Computed from the {audits.length} most recent stored audits{total > audits.length ? ` (of ${total})` : ""}.
      </p>
      <div className="grid grid-4">
        <Stat label="Audits stored" value={total} />
        <Stat label="With a report" value={withReport.length} />
        <Stat label="Partial" value={partial} />
        <Stat label="Failed / timed out / interrupted" value={failedish} />
      </div>
      <div className="grid grid-2">
        <section className="panel">
          <div className="eyebrow">Open defects · latest run per site</div>
          <h2>{sev.critical + sev.high + sev.medium} across {latest.length} site{latest.length === 1 ? "" : "s"}</h2>
          <div className="sev-bars">
            {(["critical", "high", "medium"] as const).map((s) => (
              <div className="sev-bar" key={s}>
                <span>{s[0]!.toUpperCase() + s.slice(1)}</span>
                <Bar value={sev[s]} max={sevMax} tone={s} label={`${sev[s]} ${s}`} />
                <span className="num mono">{sev[s]}</span>
              </div>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="eyebrow">Readiness index · latest run per site, lowest first</div>
          {latest.length === 0 ? <p className="muted">No completed audits yet.</p> : latest.slice(0, 6).map((a) => (
            <div className="dimension" key={a.id}>
              <Link to={`/audits/${a.id}`} className="break">{a.host}</Link>
              <Bar value={a.readiness_score ?? 0} label={`${a.host}: ${a.readiness_score}`} />
              <span className="num mono">{a.readiness_score?.toFixed(0) ?? "—"}</span>
            </div>
          ))}
        </section>
      </div>
      <section className="panel">
        <div className="panel-title"><h2>Recent audits</h2><Link to="/history">Full history →</Link></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Site</th><th>Status</th><th>Started</th><th className="num">Readiness</th><th className="num">Defects</th></tr></thead>
            <tbody>
              {audits.slice(0, 8).map((a) => (
                <tr key={a.id}>
                  <td className="break"><Link to={`/audits/${a.id}`}>{a.url}</Link></td>
                  <td><StatusBadge status={a.status} /></td>
                  <td>{formatDateTime(a.created_at)}</td>
                  <td className="num mono">{a.readiness_score?.toFixed(1) ?? "—"}</td>
                  <td className="num mono">{a.total_findings ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div className="panel"><div className="eyebrow">{label}</div><div className="score-value">{value}</div></div>;
}
