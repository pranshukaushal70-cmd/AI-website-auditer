import { Link, NavLink, Route, Routes } from "react-router-dom";
import { AuditDetail } from "./pages/AuditDetail";
import { Compare } from "./pages/Compare";
import { Dashboard } from "./pages/Dashboard";
import { History } from "./pages/History";
import { Landing } from "./pages/Landing";
import { NewAudit } from "./pages/NewAudit";

export function App() {
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <div className="topbar-inner">
          <Link className="wordmark" to="/" aria-label="AI-Readiness Intelligence home">
            <span className="wordmark-glyph" aria-hidden="true">AR</span>
            <span className="wordmark-text">AI-Readiness Intelligence</span>
          </Link>
          <nav className="nav" aria-label="Primary">
            <NavLink to="/dashboard">Dashboard</NavLink>
            <NavLink to="/audits/new">New audit</NavLink>
            <NavLink to="/history">History</NavLink>
          </nav>
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/audits/new" element={<NewAudit />} />
          <Route path="/audits/:id" element={<AuditDetail />} />
          <Route path="/history" element={<History />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="*" element={<div className="empty panel"><h1>Page not found</h1><Link to="/">Go home</Link></div>} />
        </Routes>
      </main>
      <footer className="footer">
        <div className="footer-inner">
          <span>Brand AI-Readiness Intelligence Platform · read-only, bounded, robots-aware audits</span>
          <span>Readiness index is an internal diagnostic — not an Adobe score.</span>
          <span className="footer-warning" role="note">
            Local-only · no authentication: any user or program on this computer can start audits and read every stored audit.
          </span>
        </div>
      </footer>
    </>
  );
}
