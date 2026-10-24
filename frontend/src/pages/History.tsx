import { useEffect, useId, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, hasReport, type Audit, type AuditStatus } from "../api";
import { EmptyState, ErrorPanel, NewAuditLink, Spinner, StatusBadge } from "../components/ui";
import { consentLabel, formatDateTime, STATUS_LABEL } from "../lib/format";

const PAGE = 20;

export function History() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<AuditStatus | "">("");
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ items: Audit[]; total: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const qId = useId();
  const sId = useId();

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(query), 250);
    return () => window.clearTimeout(t);
  }, [query]);

  useEffect(() => {
    setData(null);
    api.listAudits({ status: status || undefined, q: debounced || undefined, limit: PAGE, offset })
      .then((r) => { setData(r); setError(null); })
      .catch(setError);
  }, [status, debounced, offset]);

  function toggle(id: string) {
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id].slice(-2)));
  }

  function compare() {
    const chosen = (data?.items ?? []).filter((a) => selected.includes(a.id)).sort((a, b) => a.created_at.localeCompare(b.created_at));
    if (chosen.length === 2) navigate(`/compare?base=${chosen[0]!.id}&target=${chosen[1]!.id}`);
  }

  return (
    <div className="stack">
      <div className="row"><h1>Audit history</h1><span className="spacer" /><NewAuditLink /></div>
      <div className="panel">
        <div className="filters">
          <div className="field">
            <label htmlFor={qId}>Search URL or host</label>
            <input id={qId} className="input" type="search" value={query} onChange={(e) => { setQuery(e.target.value); setOffset(0); }} />
          </div>
          <div className="field">
            <label htmlFor={sId}>Status</label>
            <select id={sId} className="input" value={status} onChange={(e) => { setStatus(e.target.value as AuditStatus | ""); setOffset(0); }}>
              <option value="">Any status</option>
              {(Object.keys(STATUS_LABEL) as AuditStatus[]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
            </select>
          </div>
          <div />
          <button className="btn" onClick={compare} disabled={selected.length !== 2}>Compare selected ({selected.length}/2)</button>
        </div>
        {error !== null ? <ErrorPanel error={error} title="Could not load history" /> : !data ? <Spinner /> : data.items.length === 0 ? (
          <EmptyState title="No audits match">{query || status ? "Try clearing the filters." : "Run an audit to start the history."}</EmptyState>
        ) : (
          <>
            <div className="table-wrap">
              {/* Explicit roles keep table semantics for assistive technology when the mobile card layout changes display. */}
              <table className="history-table" role="table">
                <caption className="sr-only">Stored audits, newest first. Select two completed audits to compare.</caption>
                <thead role="rowgroup"><tr role="row"><th role="columnheader"><span className="sr-only">Select</span></th><th role="columnheader">Site</th>
                  <th role="columnheader">Status</th><th role="columnheader">Started</th><th role="columnheader" className="num">Pages</th>
                  <th role="columnheader" className="num">Readiness</th><th role="columnheader" className="num">Crit / High / Med</th>
                  <th role="columnheader">External lookups</th></tr></thead>
                <tbody role="rowgroup">
                  {data.items.map((a) => (
                    <tr key={a.id} role="row">
                      <td role="cell" className="select-cell">
                        <input type="checkbox" aria-label={`Select audit of ${a.url} from ${formatDateTime(a.created_at)}`}
                          disabled={!hasReport(a)} checked={selected.includes(a.id)} onChange={() => toggle(a.id)} />
                      </td>
                      <td role="cell" className="break site-cell" data-label="Site"><Link to={`/audits/${a.id}`}>{a.url}</Link></td>
                      <td role="cell" data-label="Status"><StatusBadge status={a.status} /></td>
                      <td role="cell" data-label="Started" title={a.created_at}>{formatDateTime(a.created_at)}</td>
                      <td role="cell" className="num mono" data-label="Pages">{a.pages_checked ?? "—"}</td>
                      <td role="cell" className="num mono" data-label="Readiness">{a.readiness_score?.toFixed(1) ?? "—"}</td>
                      <td role="cell" className="num mono" data-label="Crit / High / Med">{hasReport(a) ? `${a.critical_count} / ${a.high_count} / ${a.medium_count}` : "—"}</td>
                      <td role="cell" data-label="External lookups">{consentLabel(a.external_corroboration)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row section">
              <span className="muted small">{offset + 1}–{offset + data.items.length} of {data.total}</span>
              <span className="spacer" />
              <button className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
              <button className="btn btn-sm" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Next</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
