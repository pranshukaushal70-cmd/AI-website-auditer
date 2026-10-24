import { useId, useMemo, useState } from "react";
import type { Category, Finding, Severity } from "../api";
import { CATEGORY_LABEL, hostPath, safeHref } from "../lib/format";
import { Bar, SeverityBadge } from "./ui";

export function filterFindings(
  findings: Finding[],
  opts: { query: string; category: Category | ""; severity: Severity | ""; showProactive: boolean },
): Finding[] {
  const q = opts.query.trim().toLowerCase();
  return findings.filter((f) => {
    if (!opts.showProactive && f.proactive) return false;
    if (opts.category && f.category !== opts.category) return false;
    if (opts.severity && (f.proactive || f.severity !== opts.severity)) return false;
    if (!q) return true;
    return (
      f.title.toLowerCase().includes(q) ||
      f.evidence.toLowerCase().includes(q) ||
      f.affected_pages.some((p) => p.toLowerCase().includes(q))
    );
  });
}

export function FindingsExplorer({ findings }: { findings: Finding[] }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<Category | "">("");
  const [severity, setSeverity] = useState<Severity | "">("");
  const [showProactive, setShowProactive] = useState(true);
  const ids = { q: useId(), c: useId(), s: useId() };
  const visible = useMemo(
    () => filterFindings(findings, { query, category, severity, showProactive }),
    [findings, query, category, severity, showProactive],
  );

  return (
    <section aria-labelledby="findings-heading">
      <div className="panel-title">
        <h2 id="findings-heading">Prioritised findings</h2>
        <span className="muted small" aria-live="polite">
          Showing {visible.length} of {findings.length}
        </span>
      </div>
      <div className="filters">
        <div className="field">
          <label htmlFor={ids.q}>Search</label>
          <input id={ids.q} className="input" type="search" placeholder="Title, evidence, or page URL"
            value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor={ids.c}>Category</label>
          <select id={ids.c} className="input" value={category} onChange={(e) => setCategory(e.target.value as Category | "")}>
            <option value="">All categories</option>
            {(Object.keys(CATEGORY_LABEL) as Category[]).map((c) => (
              <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={ids.s}>Severity</label>
          <select id={ids.s} className="input" value={severity} onChange={(e) => setSeverity(e.target.value as Severity | "")}>
            <option value="">All severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
          </select>
        </div>
        <label className="toggle">
          <input type="checkbox" checked={showProactive} onChange={(e) => setShowProactive(e.target.checked)} />
          Show suggestions
        </label>
      </div>
      {visible.length === 0 ? (
        <p className="empty">No findings match these filters.</p>
      ) : (
        <div>{visible.map((f) => <FindingCard key={f.id} finding={f} />)}</div>
      )}
    </section>
  );
}

function FindingCard({ finding: f }: { finding: Finding }) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const action = f.suggested_action;
  return (
    <article className="finding">
      <button className="finding-summary" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen((o) => !o)}>
        <span className="rank">
          {f.priority ? `#${f.priority.rank}` : "—"}
          <small>{f.priority ? `${f.priority.score.toFixed(1)} pts` : "not ranked"}</small>
        </span>
        <span>
          <span className="finding-title">{f.title}</span>
          <span className="finding-sub">
            <span>{CATEGORY_LABEL[f.category]}</span>
            <span>Confidence {Math.round(f.confidence * 100)}%</span>
            <span>{f.affected_pages.length} page{f.affected_pages.length === 1 ? "" : "s"}</span>
            <span className="mono">{f.finding_code}</span>
          </span>
        </span>
        <SeverityBadge severity={f.severity} proactive={f.proactive} />
      </button>
      {open && (
        <div className="finding-body" id={bodyId}>
          {f.proactive && (
            <p className="small muted">
              This is a proactive suggestion, not a detected defect. It does not affect the readiness index or the ranking.
            </p>
          )}
          <div>
            <h4>Evidence (rule output)</h4>
            <div className="evidence">{f.evidence}</div>
          </div>
          <div>
            <h4>Affected pages</h4>
            <ul className="small break">
              {f.affected_pages.map((p) => (
                <li key={p}>
                  {safeHref(p) ? <a href={safeHref(p)} target="_blank" rel="noopener noreferrer nofollow">{hostPath(p)}</a> : p}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4>Recommended fix</h4>
            <p>{action.summary}</p>
            {action.how_to_fix && action.how_to_fix !== action.summary && <pre className="fix">{action.how_to_fix}</pre>}
          </div>
          {f.priority && (
            <div>
              <h4>Why it ranks #{f.priority.rank} ({f.priority.model})</h4>
              <p className="small muted">
                Score = 100 × severity × confidence × reach × evidence × effort = <strong>{f.priority.score.toFixed(1)}</strong>.
                Each factor is between 0 and 1; a lower factor lowers the priority proportionally.
              </p>
              {f.priority.factors.map((factor) => (
                <div className="factor" key={factor.name} title={factor.explanation}>
                  <span>{factor.name}</span>
                  <span className="mono">{factor.value.toFixed(2)}</span>
                  <Bar value={factor.value} max={1} label={`${factor.name} ${factor.value.toFixed(2)}: ${factor.explanation}`} />
                </div>
              ))}
              <ul className="small muted">
                {f.priority.factors.map((factor) => (
                  <li key={factor.name}><strong>{factor.name}</strong> ({String(factor.input)}): {factor.explanation}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
