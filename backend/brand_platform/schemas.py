"""Request and response models for the public API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AuditStatus = Literal["queued", "running", "completed", "partial", "failed", "timed_out", "cancelled", "interrupted"]


class CreateAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048, description="Public http(s) URL or bare domain to audit.")
    max_pages: int | None = Field(default=None, ge=1, le=6, description="Representative page budget (engine hard cap: 6).")
    external_corroboration: bool = Field(
        default=False, strict=True,  # only a JSON true opts in; "yes", "1" or 1 are rejected, never coerced to consent
        description="Opt in to sending the detected brand name to the Wikipedia and Wikidata search APIs "
                    "to compare public facts. Off unless explicitly set to true.")


class Audit(BaseModel):
    id: str
    url: str
    host: str
    status: AuditStatus
    max_pages: int
    created_at: str
    started_at: str | None
    finished_at: str | None
    progress: dict[str, Any]
    error: str | None
    readiness_score: float | None
    readiness_band: str | None
    total_findings: int | None
    critical_count: int | None
    high_count: int | None
    medium_count: int | None
    proactive_count: int | None
    pages_checked: int | None
    partial: bool | None
    engine_version: str | None
    report_version: int | None
    external_corroboration: bool | None = None  # None: audit predates consent recording ("not recorded")


class AuditList(BaseModel):
    items: list[Audit]
    total: int
    limit: int
    offset: int


class Finding(BaseModel):
    id: int
    audit_id: str
    finding_code: str
    fingerprint: str
    title: str
    category: str
    severity: str
    confidence: float
    proactive: bool
    affected_pages: list[str]
    evidence: str
    suggested_action: dict[str, Any]
    priority: dict[str, Any] | None


class FindingList(BaseModel):
    items: list[Finding]
    total: int


class PublicConfig(BaseModel):
    max_pages_cap: int
    default_max_pages: int
    allowed_ports: list[int]
    max_concurrent_jobs: int
    max_queued_jobs: int
    runtime_limit_seconds: float
    rendering_enabled: bool
    priority_model: str
    engine_version: str
    external_corroboration_available: bool  # False when the operator's offline switch disables external lookups
    retention_days: int | None = None  # None: audits are kept indefinitely (retention disabled, the default)
