import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type CompareItem, type CompareResult } from "../api";
import { ErrorPanel, SeverityBadge, Spinner } from "../components/ui";
import { CATEGORY_LABEL, formatDateTime } from "../lib/format";

const GROUPS: { key: "new" | "resolved" | "persistent" | "inconclusive"; title: string; blurb: string }[] = [
  { key: "new", title: "Newly detected", blurb: "Present only in the later run." },
  { key: "resolved", title: "Resolved", blurb: "Present only in the earlier run, and the category was evaluated in the later run." },
  { key: "persistent", title: "Persistent", blurb: "Present in both runs." },
  { key: "inconclusive", title: "Inconclusive", blurb: "Present in one run, but the category could not be evaluated in the other." },
];

export function Compare() {
  const [params] = useSearchParams();
  const base = params.get("base") ?? "";
  const target = params.get("target") ?? "";
  const [data, setData] = useState<CompareResult | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!base || !target) return;
    api.compare(base, target).then(setData).catch(setError);
  }, [base, target]);

  if (!base || !target) return <ErrorPanel error="Choose two audits to compare from the History page." title="Nothing to compare" />;
  if (error) return <ErrorPanel error={error} title="Could not compare these audits" />;
  if (!data) return <Spinner label="Comparing runs" />;

  return (
    <div className="stack">
      <h1>Run comparison</h1>
      <div className="grid grid-3">
        <RunCard label="Earlier run (base)" run={data.base} />
        <RunCard label="Later run (target)" run={data.target} />
        <div className="panel">
          <div className="eyebrow">Readiness change</div>
          <div className="score-value">{data.readiness_delta === null ? "—" : `${data.readiness_delta > 0 ? "+" : ""}${data.readiness_delta.toFixed(1)}`}</div>
          <p className="small muted">{data.counts.resolved} resolved · {data.counts.new} new · {data.counts.persistent} persistent · {data.counts.inconclusive} inconclusive</p>
        </div>
      </div>
      {data.caveats.length > 0 && (
        <div className="notice"><h3>Read this comparison with care</h3><ul className="small">{data.caveats.map((c) => <li key={c}>{c}</li>)}</ul></div>
      )}
      <div className="compare-cols">
        {GROUPS.map((g) => (
          <section className="panel" key={g.key} aria-labelledby={`cmp-${g.key}`}>
            <h2 id={`cmp-${g.key}`}>{g.title} <span className="muted">({data[g.key].length})</span></h2>
            <p className="small muted">{g.blurb}</p>
            {data[g.key].length === 0 ? <p className="small muted">None.</p> : (
              <ul className="compare-list">{data[g.key].map((i) => <CompareRow key={i.fingerprint} item={i} />)}</ul>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}

function RunCard({ label, run }: { label: string; run: CompareResult["base"] }) {
  return (
    <div className="panel">
      <div className="eyebrow">{label}</div>
      <Link className="break" to={`/audits/${run.id}`}>{run.url}</Link>
      <p className="small muted">{formatDateTime(run.created_at)} · readiness <span className="mono">{run.readiness_score?.toFixed(1) ?? "—"}</span></p>
    </div>
  );
}

function CompareRow({ item }: { item: CompareItem }) {
  return (
    <li>
      <div className="row"><strong>{item.title}</strong><span className="spacer" /><SeverityBadge severity={item.severity} /></div>
      <div className="small muted">
        {CATEGORY_LABEL[item.category]}
        {item.severity_changed && item.previous_severity && ` · was ${item.previous_severity}`}
        {item.reason && ` · ${item.reason}`}
      </div>
    </li>
  );
}
