"""PDF rendering of a stored audit (reportlab, built-in Helvetica fonts only)."""

from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import readiness as readiness_v2
from .prioritization import MODEL_VERSION

SEVERITY_COLOURS = {"critical": colors.HexColor("#b42318"), "high": colors.HexColor("#c4560a"), "medium": colors.HexColor("#8a6d00")}
INK, MUTED, RULE = colors.HexColor("#1b1f24"), colors.HexColor("#5b6470"), colors.HexColor("#d5d9de")


def consent_label(choice: bool | None) -> str:
    """Per-audit consent as recorded in the database (None: the audit predates consent recording)."""
    if choice is None:
        return "Not recorded (predates consent)"
    return "opted in" if choice else "not requested (user did not opt in)"


def _t(value, limit: int = 1200) -> str:
    """Escape for reportlab markup and drop characters Helvetica cannot encode."""
    text = str(value if value is not None else "")
    if len(text) > limit:
        text = text[:limit] + " …[truncated]"
    text = text.replace("·", "|").replace("…", "...").replace("—", "-").replace("–", "-").replace("→", "->").replace("↔", "<->")
    text = text.encode("latin-1", "replace").decode("latin-1")
    return escape(text).replace("\n", "<br/>")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=18, textColor=INK, alignment=0, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, textColor=INK, spaceBefore=10, spaceAfter=4),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=10.5, textColor=INK, spaceBefore=6, spaceAfter=2),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=9, leading=12, textColor=INK),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Helvetica", fontSize=8, leading=10.5, textColor=MUTED),
        "mono": ParagraphStyle("mono", parent=base["BodyText"], fontName="Courier", fontSize=7.5, leading=9.5, textColor=INK),
    }


def _table(rows, widths, header=True):
    table = Table(rows, colWidths=widths, hAlign="LEFT")
    style = [("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE), ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED)]
    table.setStyle(TableStyle(style))
    return table


def _severity_chart(counts: dict) -> Drawing:
    width, bar_h, gap = 300, 12, 6
    total = max(1, max(counts.values() or [0]))
    drawing = Drawing(width + 120, 3 * (bar_h + gap))
    for i, sev in enumerate(("critical", "high", "medium")):
        y = (2 - i) * (bar_h + gap)
        n = counts.get(sev, 0)
        drawing.add(String(0, y + 2, sev.capitalize(), fontName="Helvetica", fontSize=8, fillColor=INK))
        drawing.add(Rect(60, y, width, bar_h, fillColor=colors.HexColor("#eef0f2"), strokeColor=None))
        if n:
            drawing.add(Rect(60, y, width * n / total, bar_h, fillColor=SEVERITY_COLOURS[sev], strokeColor=None))
        drawing.add(String(60 + width + 6, y + 2, str(n), fontName="Helvetica-Bold", fontSize=8, fillColor=INK))
    return drawing


def render_pdf(audit: dict, report: dict, findings: list[dict]) -> bytes:
    s = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"AI-Readiness audit - {audit['host']}", author="Brand AI-Readiness Intelligence Platform")
    scope, summary, execution = report.get("scope", {}), report.get("summary", {}), report.get("execution", {})
    readiness = report.get("readiness") or {}
    defects = [f for f in findings if not f.get("proactive")]
    proactive = [f for f in findings if f.get("proactive")]
    story = [
        Paragraph("Brand AI-Readiness Audit", s["title"]),
        Paragraph(_t(audit["url"]), s["body"]),
        Paragraph(_t(f"Audit {audit['id']} · status {audit['status']} · audited {report.get('audited_at', '')} (UTC) · engine {audit.get('engine_version')}"), s["small"]),
        Paragraph(_t(f"External corroboration (Wikipedia/Wikidata): {consent_label(audit.get('external_corroboration'))}; "
                     f"outcome: {(report.get('scope') or {}).get('external_corroboration', 'not recorded')}; "
                     f"external sources checked: {(report.get('scope') or {}).get('external_sources_checked', 0)}."), s["small"]),
        Spacer(1, 6),
        Paragraph("The readiness index is an internal heuristic diagnostic computed from the engine's own findings. "
                  "It is not an Adobe score, is not endorsed by Adobe, and has not been validated against search or AI-assistant outcomes.", s["small"]),
    ]

    story += [Paragraph("Summary", s["h2"]), _table([
        ["Readiness index", "Band", "Technical", "Trust", "Engagement"],
        [str(readiness.get("score", "n/a")), _t(readiness.get("band", "n/a")),
         *(str((readiness.get("dimensions") or {}).get(k, "n/a")) for k in ("technical", "trust", "engagement"))],
    ], [32 * mm, 32 * mm, 32 * mm, 32 * mm, 32 * mm])]
    story += [Spacer(1, 6), Paragraph(_t(f"{summary.get('total_findings', 0)} defect finding(s) and "
                                         f"{summary.get('proactive_suggestions_count', 0)} proactive suggestion(s)."), s["body"]),
              Spacer(1, 4), _severity_chart({k: summary.get(k, 0) for k in ("critical", "high", "medium")})]

    v2 = readiness_v2.compute(findings, report)
    story += [Paragraph(f"Readiness index {readiness_v2.MODEL_VERSION} (itemised)", s["h2"]), Paragraph(_t(
        f"Score {v2['score'] if v2['score'] is not None else 'n/a'} ({v2['band'] or 'n/a'}); engine index v1: "
        f"{v2['engine_v1']['score'] if v2['engine_v1']['score'] is not None else 'n/a'}. "
        f"Not assessed (no usable evidence): {', '.join(v2['coverage']['not_assessed']) or 'none'}. "
        "Penalty = base(severity: critical 30, high 18, medium 7) x confidence x reach."), s["small"])]
    rows = [["Dimension", "Finding", "Base", "Conf.", "Reach", "Penalty"]]
    for dim, d in v2["dimensions"].items():
        for p in d["penalties"]:
            rows.append([dim, Paragraph(_t(f"{p['finding_code']} {p['title']}"), s["small"]), str(p["base_penalty"]),
                         str(p["confidence"]), str(p["reach"]), str(p["penalty"])])
        rows.append([dim, Paragraph("<b>Dimension score</b>" if d["assessed"] else "<b>Not assessed</b>", s["small"]), "", "", "",
                     str(d["score"]) if d["assessed"] else "n/a"])
    story.append(_table(rows, [24 * mm, 84 * mm, 14 * mm, 14 * mm, 14 * mm, 18 * mm]))

    story += [Paragraph("Scope", s["h2"]), _table([
        ["Pages checked", "robots.txt", "Sitemap checked / found", "Rendering", "External sources"],
        [str(scope.get("pages_checked")), "yes" if scope.get("robots_checked") else "no",
         f"{'yes' if scope.get('sitemap_checked') else 'no'} / {'yes' if scope.get('sitemap_found') else 'no'}",
         _t(scope.get("render_status", "n/a")), str(scope.get("external_sources_checked"))],
    ], [30 * mm, 24 * mm, 40 * mm, 34 * mm, 32 * mm])]
    if scope.get("audited_urls"):
        story += [Spacer(1, 3), Paragraph("Audited pages: " + _t(", ".join(scope["audited_urls"]), 2000), s["small"])]

    story += [Paragraph("Methodology", s["h2"]), Paragraph(
        "A bounded, read-only crawl (robots.txt respected, same-domain, page budget capped at six) feeds three rule-based "
        "sub-audits: technical discoverability, trust and freshness, and on-page engagement. Each rule emits severity, "
        "confidence, affected pages, evidence, and a fix. Findings are ranked by the deterministic model "
        f"<b>{MODEL_VERSION}</b>: priority = 100 x severity x confidence x reach x evidence x effort, where every factor is "
        "in (0, 1] and shown per finding below. Effort levels are expert estimates, not measurements.", s["body"])]

    story.append(Paragraph("Prioritised recommendations", s["h2"]))
    if not defects:
        story.append(Paragraph("No defect findings were recorded for the checks that ran.", s["body"]))
    rows = [["#", "Finding", "Severity", "Score", "Factors (sev x conf x reach x evid x effort)"]]
    for f in defects[:15]:
        p = f.get("priority") or {}
        factors = " x ".join(f"{x['value']}" for x in p.get("factors", []))
        rows.append([str(p.get("rank", "")), Paragraph(_t(f["title"]), s["body"]), f["severity"], str(p.get("score", "")),
                     Paragraph(_t(factors), s["small"])])
    if len(rows) > 1:
        story.append(_table(rows, [8 * mm, 72 * mm, 18 * mm, 14 * mm, 62 * mm]))

    story.append(Paragraph("Finding details", s["h2"]))
    for f in defects + proactive:
        action = f.get("suggested_action") or {}
        label = "Proactive suggestion (not a defect)" if f.get("proactive") else f"{f['severity'].capitalize()} severity"
        block = [Paragraph(_t(f"{f['id']} · {f['title']}"), s["h3"]),
                 Paragraph(_t(f"{label} · category {f['category']} · confidence {f['confidence']:.2f}"), s["small"]),
                 Paragraph("<b>Affected pages:</b> " + _t(", ".join(f.get("affected_pages") or []), 600), s["small"]),
                 Paragraph("<b>Evidence:</b> " + _t(f.get("evidence")), s["body"]),
                 Paragraph("<b>Recommended action:</b> " + _t(action.get("summary")), s["body"])]
        if action.get("how_to_fix") and action.get("how_to_fix") != action.get("summary"):
            block.append(Paragraph(_t(action["how_to_fix"], 900), s["mono"]))
        story.append(KeepTogether(block))

    story.append(Paragraph("Execution notes and limitations", s["h2"]))
    notes = [f"Partial execution: {'yes' if execution.get('partial') else 'no'}."]
    if execution.get("missing_categories"):
        notes.append("Missing categories: " + ", ".join(execution["missing_categories"]) + ".")
    if execution.get("unavailable_categories"):
        notes.append("Categories with no usable evidence: " + ", ".join(execution["unavailable_categories"]) + ".")
    if execution.get("unavailable_checks"):
        notes.append("Checks that could not run: " + ", ".join(f"{c['category']}/{c['check']}" for c in execution["unavailable_checks"]) + ".")
    if execution.get("failed_pages"):
        notes.append("Pages that failed to load: " + ", ".join(execution["failed_pages"]) + ".")
    if execution.get("truncated_pages"):
        notes.append("Larger than 2 MB, so only the first 2 MB was analysed: " + ", ".join(execution["truncated_pages"]) + ".")
    if scope.get("sitemaps_skipped_offsite"):
        notes.append("Sitemaps declared in robots.txt on another host were not fetched (only the audited site is crawled): "
                     + ", ".join(scope["sitemaps_skipped_offsite"]) + ".")
    for err in (execution.get("errors") or [])[:10]:
        notes.append("Error: " + str(err))
    notes += ["Unavailable checks are not treated as passes. A sample of at most six pages cannot represent an entire site.",
              "Live websites change; re-running an audit can produce different results. Browser rendering is disabled in the "
              "web platform for SSRF safety, so client-side rendering gaps are not verified."]
    story += [Paragraph(_t(n, 1500), s["small"]) for n in notes]

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 9 * mm, "Brand AI-Readiness Intelligence Platform - internal diagnostic, not an Adobe score")
        canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
