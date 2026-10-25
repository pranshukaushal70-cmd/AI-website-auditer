import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type Audit, type EngineReport, type Finding } from "./api";
import { FindingsExplorer, filterFindings } from "./components/FindingsExplorer";
import { App } from "./App";
import { ProgressStepper } from "./components/ProgressStepper";
import { ExecutionNotice, SeverityPanel } from "./components/ReportSummary";
import { consentLabel, formatDuration, safeHref } from "./lib/format";
import { precheckAuditUrl } from "./lib/url";
import { latestPerHost } from "./pages/Dashboard";
import { History } from "./pages/History";
import { NewAudit } from "./pages/NewAudit";

const finding = (over: Partial<Finding>): Finding => ({
  id: 1, audit_id: "a", finding_code: "F-001", fingerprint: "technical:x", title: "Missing viewport", category: "technical",
  severity: "medium", confidence: 0.95, proactive: false, affected_pages: ["https://e.example/pricing"], evidence: "No viewport on 1 page.",
  suggested_action: { summary: "Add viewport", how_to_fix: "<meta name=viewport>" },
  priority: { model: "priority-v1", score: 38, rank: 1, factors: [{ name: "severity", value: 0.4, input: "medium", explanation: "x" }] },
  ...over,
});

describe("precheckAuditUrl", () => {
  it.each([
    ["example.com", "https://example.com/"],
    ["http://example.com/a#frag", "http://example.com/a"],
  ])("accepts %s", (input, out) => expect(precheckAuditUrl(input)).toEqual({ ok: true, url: out }));
  it.each(["", "ftp://x.com", "javascript:alert(1)", "http://user:pw@x.com", "http://localhost", "intranet", "a b.com"])(
    "rejects %s", (input) => expect(precheckAuditUrl(input).ok).toBe(false));
});

describe("formatting", () => {
  it("formats durations", () => {
    expect(formatDuration("2026-10-23T10:00:00Z", "2026-10-23T10:01:05Z")).toBe("1m 05s");
    expect(formatDuration(null, null)).toBe("—");
  });
  it("only links http(s)", () => {
    expect(safeHref("javascript:alert(1)")).toBeUndefined();
    expect(safeHref("https://e.example/")).toBe("https://e.example/");
  });
});

describe("filterFindings", () => {
  const items = [finding({ id: 1 }), finding({ id: 2, category: "trust", severity: "high", title: "Fact contradiction" }),
    finding({ id: 3, proactive: true, priority: null, title: "Add anchors" })];
  it("filters by category, severity, search, and suggestions", () => {
    const base = { query: "", category: "" as const, severity: "" as const, showProactive: true };
    expect(filterFindings(items, base)).toHaveLength(3);
    expect(filterFindings(items, { ...base, category: "trust" }).map((f) => f.id)).toEqual([2]);
    expect(filterFindings(items, { ...base, severity: "medium" }).map((f) => f.id)).toEqual([1]);
    expect(filterFindings(items, { ...base, showProactive: false })).toHaveLength(2);
    expect(filterFindings(items, { ...base, query: "pricing" })).toHaveLength(3);
    expect(filterFindings(items, { ...base, query: "contradiction" }).map((f) => f.id)).toEqual([2]);
  });
});

describe("FindingsExplorer", () => {
  it("expands a finding to show evidence, fix, and the score breakdown", async () => {
    render(<FindingsExplorer findings={[finding({}), finding({ id: 2, title: "Other", severity: "high" })]} />);
    const button = screen.getByRole("button", { name: /Missing viewport/ });
    expect(button).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("No viewport on 1 page.")).toBeInTheDocument();
    expect(screen.getByText(/Why it ranks #1/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "high");
    expect(screen.queryByRole("button", { name: /Missing viewport/ })).not.toBeInTheDocument();
    expect(screen.getByText("Showing 1 of 2")).toBeInTheDocument();
  });
});

describe("ProgressStepper", () => {
  it("shows each stage's state", () => {
    render(<ProgressStepper stages={{ technical: "completed", trust: "running", engagement: "pending", compose: "pending" }} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(within(items[0]!).getByText(/Done/)).toBeInTheDocument();
    expect(items[1]).toHaveAttribute("data-state", "running");
    expect(screen.getByText("1 of 4 stages complete.")).toBeInTheDocument();
  });
});

describe("latestPerHost", () => {
  const a = (id: string, host: string, created: string, status: Audit["status"], score: number): Audit => ({
    id, url: `https://${host}/`, host, status, max_pages: 4, created_at: created, started_at: null, finished_at: null, progress: {},
    error: null, readiness_score: score, readiness_band: null, total_findings: 0, critical_count: 0, high_count: 0, medium_count: 0,
    proactive_count: 0, pages_checked: 1, partial: false, engine_version: null, report_version: status === "failed" ? null : 1,
  });
  it("keeps only the newest run with a report for each host", () => {
    const out = latestPerHost([a("1", "x.com", "2026-01-01", "completed", 50), a("2", "x.com", "2026-02-01", "partial", 70),
      a("3", "x.com", "2026-03-01", "failed", 0), a("4", "y.com", "2026-01-05", "completed", 40)]);
    expect(out.map((o) => o.id)).toEqual(["4", "2"]);
  });
});

describe("api client", () => {
  afterEach(() => vi.restoreAllMocks());
  it("turns the error envelope into an ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      error: { code: "non_public_address", message: "Blocked", request_id: "req-123456" } }), { status: 422 }));
    const err = await api.createAudit("http://10.0.0.1", 2).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 422, code: "non_public_address", message: "Blocked", requestId: "req-123456" });
  });
  it("reports network failures clearly", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api.config()).rejects.toMatchObject({ code: "network_error" });
  });
});

it("renders inside a router without crashing", () => {
  render(<MemoryRouter><ProgressStepper /></MemoryRouter>);
  expect(screen.getAllByText(/Waiting/)).toHaveLength(4);
});

describe("external corroboration consent (security phase 4)", () => {
  afterEach(() => vi.restoreAllMocks());

  const config = (available: boolean) => ({
    max_pages_cap: 6, default_max_pages: 4, allowed_ports: [80, 443], max_concurrent_jobs: 2, max_queued_jobs: 10,
    runtime_limit_seconds: 240, rendering_enabled: false, priority_model: "priority-v1", engine_version: "marketplace-1.4.0",
    external_corroboration_available: available,
  });

  function mockApi(available = true) {
    const bodies: unknown[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/config")) return new Response(JSON.stringify(config(available)), { status: 200 });
      bodies.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify({ id: "a".repeat(32) }), { status: 202 });
    });
    return bodies;
  }

  async function submit(tick: boolean) {
    const bodies = mockApi();
    render(<MemoryRouter><NewAudit /></MemoryRouter>);
    const box = await screen.findByRole("checkbox", { name: /Wikipedia and Wikidata/ });
    expect(box).not.toBeChecked();
    if (tick) await userEvent.click(box);
    await userEvent.type(screen.getByLabelText("Website address"), "example.com");
    await userEvent.click(screen.getByRole("button", { name: "Start audit" }));
    await vi.waitFor(() => expect(bodies).toHaveLength(1));
    return bodies[0] as { url: string; external_corroboration: boolean };
  }

  it("is off by default and sends an explicit false", async () => {
    const body = await submit(false);
    expect(body).toMatchObject({ url: "https://example.com/", external_corroboration: false });
  });

  it("sends true only when the user ticks the box", async () => {
    expect((await submit(true)).external_corroboration).toBe(true);
  });

  it("explains exactly what is sent externally", async () => {
    mockApi();
    render(<MemoryRouter><NewAudit /></MemoryRouter>);
    const box = await screen.findByRole("checkbox", { name: /Wikipedia and Wikidata/ });
    expect(box).toHaveAccessibleDescription(/brand name detected on the site is sent to the public Wikipedia and Wikidata/);
    expect(box).toHaveAccessibleDescription(/No page content, address, or contact detail is sent/);
  });

  it("is disabled when the server has external lookups switched off", async () => {
    mockApi(false);
    render(<MemoryRouter><NewAudit /></MemoryRouter>);
    await vi.waitFor(() => expect(screen.getByRole("checkbox", { name: /Wikipedia and Wikidata/ })).toBeDisabled());
    expect(screen.getByText(/switched off on this server/)).toBeInTheDocument();
  });

  it("labels the recorded choice, including legacy audits", () => {
    expect(consentLabel(true)).toBe("Opted in");
    expect(consentLabel(false)).toBe("Not requested");
    expect(consentLabel(null)).toBe("Not recorded (predates consent)");
    expect(consentLabel(undefined)).toBe("Not recorded (predates consent)");
  });

  it("api.createAudit defaults to no consent", async () => {
    const bodies = mockApi();
    await api.createAudit("https://example.com/", 2);
    expect(bodies[0]).toMatchObject({ external_corroboration: false });
  });
});

describe("history table on narrow screens", () => {
  afterEach(() => vi.restoreAllMocks());

  it("labels every data cell with its column so rows can render as cards, and keeps table roles", async () => {
    const audit = (id: string, url: string, consent: boolean | null, status: Audit["status"]): Audit => ({
      id, url, host: new URL(url).host, status, max_pages: 4, created_at: "2026-10-25T10:00:00Z", started_at: null,
      finished_at: null, progress: {}, error: null, readiness_score: status === "failed" ? null : 91.5, readiness_band: null,
      total_findings: 0, critical_count: 0, high_count: 0, medium_count: 0, proactive_count: 0, pages_checked: 1,
      partial: false, engine_version: null, report_version: status === "failed" ? null : 1, external_corroboration: consent,
    });
    const items = [audit("1", "https://a.example/", true, "completed"), audit("2", "https://b.example/long/path?x=1", null, "failed")];
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ items, total: 2, limit: 20, offset: 0 }), { status: 200 }));
    render(<MemoryRouter><History /></MemoryRouter>);
    const table = await screen.findByRole("table");
    expect(table).toHaveClass("history-table");
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Select", "Site", "Status", "Started", "Pages", "Readiness", "Crit / High / Med", "External lookups"]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      const cells = within(row).getAllByRole("cell");
      expect(cells).toHaveLength(8);
      expect(cells[0]).toHaveClass("select-cell");
      expect(cells.slice(1).map((c) => c.getAttribute("data-label"))).toEqual(headers.slice(1));
    }
    expect(within(rows[1]!).getByRole("checkbox")).toBeDisabled();
    expect(within(rows[1]!).getByText("Not recorded (predates consent)")).toBeInTheDocument();
  });
});

describe("scope notes (security phase 6)", () => {
  const report = (execution: Partial<EngineReport["execution"]>, scope: Partial<EngineReport["scope"]> = {}): EngineReport => ({
    site: "https://e.example/", audited_at: "2026-10-25T10:00:00Z",
    summary: { total_findings: 0, critical: 0, high: 0, medium: 0, proactive_suggestions_count: 0 },
    scope: { pages_checked: 2, robots_checked: true, sitemap_checked: true, sitemap_found: false, render_check: false,
             external_sources_checked: 0, ...scope },
    execution: { partial: false, ...execution },
  });

  it("shows nothing for a complete audit without notes", () => {
    const { container } = render(<ExecutionNotice report={report({})} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists truncated pages and skipped off-site sitemaps as information, not as missing evidence", () => {
    render(<ExecutionNotice report={report({ truncated_pages: ["https://e.example/huge"] },
      { sitemaps_skipped_offsite: ["https://cdn.other.example/sitemap.xml"] })} />);
    expect(screen.getByRole("heading", { name: "Audit scope notes" })).toBeInTheDocument();
    expect(screen.getByText(/only the first 2 MB was analysed: https:\/\/e\.example\/huge/)).toBeInTheDocument();
    expect(screen.getByText(/on another host were not fetched .*https:\/\/cdn\.other\.example\/sitemap\.xml/)).toBeInTheDocument();
    expect(screen.queryByText(/not counted as passes/)).not.toBeInTheDocument();
  });

  it("keeps the partial-audit warning when evidence is missing", () => {
    render(<ExecutionNotice report={report({ partial: true, truncated_pages: ["https://e.example/huge"] })} />);
    expect(screen.getByRole("heading", { name: /Partial audit/ })).toBeInTheDocument();
    expect(screen.getByText(/not counted as passes/)).toBeInTheDocument();
    expect(screen.getByText(/only the first 2 MB was analysed/)).toBeInTheDocument();
  });

  it("says when declared sitemaps on another host were not fetched", () => {
    const audit = { max_pages: 6 } as Audit;
    const { rerender } = render(<SeverityPanel audit={audit} report={report({}, { sitemaps_skipped_offsite: ["https://cdn.x/s.xml", "https://y/s.xml"] })} />);
    expect(screen.getByText("Checked, none found on this site · 2 on another host not fetched")).toBeInTheDocument();
    rerender(<SeverityPanel audit={audit} report={report({}, { sitemap_found: true })} />);
    expect(screen.getByText("Found")).toBeInTheDocument();
  });
});

it("states in the footer that the platform is local-only with no authentication (security phase 6)", () => {
  render(<MemoryRouter initialEntries={["/no-such-page"]}><App /></MemoryRouter>);
  const note = screen.getByRole("note");
  expect(within(screen.getByRole("contentinfo")).getByRole("note")).toBe(note);
  expect(note).toHaveTextContent(
    "Local-only · no authentication: any user or program on this computer can start audits and read every stored audit.");
});
