import { useEffect, useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type PublicConfig } from "../api";
import { ErrorPanel } from "../components/ui";
import { precheckAuditUrl } from "../lib/url";

export function NewAudit() {
  const navigate = useNavigate();
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [url, setUrl] = useState("");
  const [maxPages, setMaxPages] = useState(4);
  const [externalCorroboration, setExternalCorroboration] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const urlId = useId();
  const pagesId = useId();
  const errId = useId();
  const consentId = useId();
  const consentHelpId = useId();

  useEffect(() => {
    api.config().then((c) => {
      setConfig(c);
      setMaxPages(c.default_max_pages);
    }).catch(setSubmitError);
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    const check = precheckAuditUrl(url);
    if (!check.ok) {
      setFieldError(check.message);
      return;
    }
    setFieldError(null);
    setBusy(true);
    try {
      const audit = await api.createAudit(check.url, maxPages, externalCorroboration);
      navigate(`/audits/${audit.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422 && err.code !== "validation_error") setFieldError(err.message);
      else setSubmitError(err);
    } finally {
      setBusy(false);
    }
  }

  const cap = config?.max_pages_cap ?? 6;
  return (
    <div className="grid grid-2">
      <form className="panel" onSubmit={onSubmit} noValidate aria-labelledby="new-heading">
        <h1 id="new-heading">Run an audit</h1>
        <p className="muted">Audit only sites you own or have permission to test. The crawl is read-only and bounded.</p>
        <div className="field">
          <label htmlFor={urlId}>Website address</label>
          <input id={urlId} className="input" type="text" inputMode="url" autoComplete="url" placeholder="example.com"
            value={url} onChange={(e) => setUrl(e.target.value)} aria-invalid={fieldError ? "true" : "false"}
            aria-describedby={fieldError ? errId : undefined} required />
          {fieldError && <div id={errId} className="field-error" role="alert">{fieldError}</div>}
        </div>
        <div className="field section">
          <label htmlFor={pagesId}>Representative pages: <span className="mono">{maxPages}</span></label>
          <input id={pagesId} type="range" min={1} max={cap} value={maxPages} onChange={(e) => setMaxPages(Number(e.target.value))} />
          <span className="hint">The homepage plus up to {cap - 1} more pages chosen from the sitemap and internal links. More pages take longer.</span>
        </div>
        <fieldset className="field section consent">
          <legend>External corroboration (optional)</legend>
          <label className="toggle" htmlFor={consentId}>
            <input id={consentId} type="checkbox" checked={externalCorroboration}
              disabled={config?.external_corroboration_available === false}
              onChange={(e) => setExternalCorroboration(e.target.checked)} aria-describedby={consentHelpId} />
            Compare the site with Wikipedia and Wikidata
          </label>
          <span id={consentHelpId} className="hint">
            Off by default. If you tick this, the brand name detected on the site is sent to the public Wikipedia and Wikidata
            search APIs to compare facts such as location. No page content, address, or contact detail is sent. Your choice is
            recorded with the audit and shown in its history and exports.
            {config?.external_corroboration_available === false && " External lookups are switched off on this server, so this option is unavailable."}
          </span>
        </fieldset>
        <div className="row section">
          <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "Starting…" : "Start audit"}</button>
        </div>
        {submitError !== null && <div className="section"><ErrorPanel error={submitError} title="Could not start the audit" /></div>}
      </form>
      <aside className="panel small" aria-label="Audit limits">
        <h2>Safety limits in force</h2>
        <ul className="check-list">
          <li>Only http and https on ports {config?.allowed_ports.join(", ") ?? "80, 443"}.</li>
          <li>Hostnames resolving to private, loopback, link-local, or reserved addresses are refused; every redirect is re-checked.</li>
          <li>robots.txt is honoured before every page fetch, with at least 0.5 s between requests to the site.</li>
          <li>Responses are capped at 2 MB; the whole audit stops after {config ? Math.round(config.runtime_limit_seconds) : 240} s.</li>
          <li>At most {config?.max_concurrent_jobs ?? 2} audits run at once, and one per site at a time.</li>
          <li>JavaScript rendering is {config?.rendering_enabled ? "enabled" : "disabled"} in this deployment.</li>
        </ul>
      </aside>
    </div>
  );
}
