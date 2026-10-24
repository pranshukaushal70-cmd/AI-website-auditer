import { Link } from "react-router-dom";
import { NewAuditLink } from "../components/ui";

const STEPS = [
  ["Admission check", "The URL is normalised, resolved, and refused if any address is private, reserved, or on a non-standard port."],
  ["Bounded crawl", "robots.txt is read first. At most six same-domain pages are sampled, with request spacing, size and time limits."],
  ["Three rule-based audits", "Technical discoverability, trust and freshness, and engagement each emit findings with evidence and a fix."],
  ["Explainable ranking", "Defects are ranked by severity × confidence × reach × evidence × effort, with every factor shown."],
  ["Persist, compare, export", "Results are stored, compared run-to-run, and exported as JSON or PDF."],
] as const;

export function Landing() {
  return (
    <>
      <section className="hero">
        <div>
          <div className="eyebrow">Website intelligence for the AI-assistant era</div>
          <h1>Find out whether AI assistants can find, trust, and quote your site.</h1>
          <p className="lead">
            Search and chat assistants increasingly answer questions by reading websites directly. Pages that block crawlers,
            hide facts behind JavaScript, contradict their own structured data, or strand visitors who arrive on a deep link
            are less likely to be cited correctly. This platform audits a sample of your pages for those problems and tells
            you what to fix first, and why.
          </p>
          <div className="row">
            <NewAuditLink />
            <Link className="btn" to="/dashboard">View dashboard</Link>
          </div>
        </div>
        <ol className="pipeline" aria-label="How an audit works">
          {STEPS.map(([title, text], i) => (
            <li className="pipeline-step" key={title}>
              <span className="step-num" aria-hidden="true">{i + 1}</span>
              <span><strong>{title}</strong><span className="muted small">{text}</span></span>
            </li>
          ))}
        </ol>
      </section>

      <section className="section grid grid-3">
        <div className="panel">
          <div className="eyebrow">Technical</div>
          <h2>Discoverability</h2>
          <p className="small">robots.txt and AI-crawler rules, sitemaps, canonical and noindex directives, redirect chains,
            Schema.org quality by page type, visible-versus-structured fact parity, image alternatives, viewport.</p>
        </div>
        <div className="panel">
          <div className="eyebrow">Trust</div>
          <h2>Freshness & identity</h2>
          <p className="small">Multi-signal freshness (sitemap, schema, meta, in-page dates), authorship and contact transparency,
            sameAs sanity, and optional Wikipedia/Wikidata corroboration.</p>
        </div>
        <div className="panel">
          <div className="eyebrow">Engagement</div>
          <h2>Answerability</h2>
          <p className="small">Heading hierarchy, walls of text, intent-classified calls to action, navigation dead-ends,
            quote-readiness, and whether a deep-linked visitor keeps context.</p>
        </div>
      </section>

      <section className="section grid grid-2">
        <div className="panel">
          <h2>What it will not do</h2>
          <ul className="check-list small">
            <li>Log in, submit forms, or change anything on the audited site.</li>
            <li>Fetch pages that robots.txt disallows, or reach private-network addresses.</li>
            <li>Claim the sample represents the whole site: at most six pages are checked.</li>
            <li>Treat a check that could not run as a pass — partial audits are labelled.</li>
            <li>Render JavaScript in the web platform (disabled for network safety), so render gaps are not verified here.</li>
          </ul>
        </div>
        <div className="panel">
          <h2>Demo workflow</h2>
          <ol className="small">
            <li>Run an audit of a site you are permitted to test.</li>
            <li>Watch the four stages progress, then review the readiness overview and ranked findings.</li>
            <li>Open a finding to see its evidence, affected pages, fix, and score breakdown.</li>
            <li>Fix something and audit again; compare the two runs from History.</li>
            <li>Export the report as JSON or PDF.</li>
          </ol>
          <p className="small muted">The readiness index is an internal heuristic, not an Adobe score, and is not endorsed by Adobe.</p>
        </div>
      </section>
    </>
  );
}
