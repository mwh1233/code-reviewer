"""Domain models for the review pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from codereviewer.domain.enums import (
    Confidence,
    FindingSource,
    ProviderKind,
    ReviewSourceKind,
    ReviewStage,
    Severity,
)


class ReviewRequest(BaseModel):
    """Normalized review request."""

    provider: ProviderKind
    source_kind: ReviewSourceKind
    review_url: str | None = None
    repo: str | None = None
    change_number: int | None = None
    base_branch: str | None = None
    head_branch: str | None = None
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ReviewSnapshot(BaseModel):
    """Provider-neutral immutable review snapshot."""

    review_id: str
    provider: ProviderKind
    source_kind: ReviewSourceKind
    repo: str
    review_url: str | None = None
    change_number: int | None = None
    input_hash: str
    base_ref: str | None = None
    head_ref: str | None = None
    base_sha: str | None = None
    head_sha: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    diff_text: str = ""
    review_title: str | None = None
    author_login: str | None = None
    web_url: str | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class EvidenceRef(BaseModel):
    """Evidence attached to one finding."""

    source_type: str
    source_id: str
    file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    excerpt: str | None = None
    verified: bool = True


class Finding(BaseModel):
    """Structured review finding produced by tools or rules."""

    id: str
    summary: str
    severity: Severity
    confidence: Confidence
    file: str | None = None
    line: int | None = None
    explanation: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    suggested_fix: str | None = None
    category: str | None = None
    source_type: FindingSource = FindingSource.RULE
    location_valid: bool = True


class CommentPayload(BaseModel):
    """Provider-neutral publish payload for one review comment."""

    provider: ProviderKind
    repo: str
    change_number: int
    head_sha: str
    body: str


class PublishResult(BaseModel):
    """Structured result returned by one publish attempt."""

    published: bool
    reason: str | None = None
    provider_comment_id: str | None = None
    published_head_sha: str | None = None


class ToolSpec(BaseModel):
    """Metadata declared by one review tool."""

    name: str
    description: str
    input_schema: dict[str, object] = Field(default_factory=dict)
    output_schema: dict[str, object] = Field(default_factory=dict)
    execution_policy: str
    max_output_chars: int
    failure_behavior: str


class ToolResult(BaseModel):
    """Structured result returned by one review tool."""

    tool_name: str
    payload: dict[str, object] = Field(default_factory=dict)
    truncated: bool = False
    error: str | None = None


class ToolExecutionContext(BaseModel):
    """Runtime-only context injected into declarative tool functions."""

    snapshot: ReviewSnapshot
    provider: Any | None = None


class ToolCall(BaseModel):
    """One tool call emitted or consumed by the LLM function-calling protocol."""

    id: str
    name: str
    arguments: str


class ToolChatMessage(BaseModel):
    """One chat message in the tool-use conversation."""

    role: str
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None


class ToolChatRequest(BaseModel):
    """Structured request for one tool-enabled LLM chat completion."""

    messages: list[ToolChatMessage] = Field(default_factory=list)
    tools: list[dict[str, object]] = Field(default_factory=list)
    tool_choice: str = "auto"
    max_tokens: int | None = None
    temperature: float = 0.0


class ToolChatResponse(BaseModel):
    """Structured response returned by a tool-enabled LLM chat completion."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    finish_reason: str = "stop"


class RuleSpec(BaseModel):
    """Metadata declared by one deterministic rule."""

    name: str
    description: str
    input_scope: str
    default_confidence: Confidence
    failure_behavior: str


class PipelineResult(BaseModel):
    """Result returned by the pipeline skeleton."""

    review_id: str
    stage: ReviewStage
    message: str
    artifact_root: Path
    placeholder_file: Path
    request: ReviewRequest
    snapshot: ReviewSnapshot
    checkpoint_file: Path | None = None
    trace_file: Path | None = None


class BudgetSnapshot(BaseModel):
    """Minimal persisted budget placeholder for later milestones."""

    token_limit: int | None = None
    token_used: int = 0
    cost_limit: float | None = None
    cost_used: float = 0.0
    stop_reason: str | None = None
    degrade_level: str = "normal"
    last_decision: str | None = None
    last_projected_ratio: float = 0.0
    last_actual_ratio: float = 0.0


class BudgetDecision(BaseModel):
    """Budget policy decision taken before an LLM call."""

    should_call_llm: bool
    degrade_level: str
    reason: str
    projected_ratio: float
    prompt_max_chars: int


class LLMReviewResult(BaseModel):
    """Normalized result returned by an LLM review call."""

    raw_content: str
    findings: list[Finding] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0


class TraceEvent(BaseModel):
    """Structured event recorded in the review trace."""

    stage: ReviewStage
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, object] = Field(default_factory=dict)


class TraceArtifactRef(BaseModel):
    """Reference to one persisted redacted trace artifact."""

    artifact_type: str
    artifact_id: str
    storage_ref: str
    redacted: bool = True


class ReviewTrace(BaseModel):
    """Persisted trace for a review execution."""

    trace_id: str
    review_id: str
    events: list[TraceEvent] = Field(default_factory=list)
    artifact_refs: list[TraceArtifactRef] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReviewCheckpoint(BaseModel):
    """Persisted checkpoint at a stable pipeline boundary."""

    review_id: str
    provider: ProviderKind
    repo: str
    input_hash: str
    base_sha: str | None = None
    head_sha: str | None = None
    completed_stages: list[ReviewStage] = Field(default_factory=list)
    current_stage: ReviewStage
    next_stage: ReviewStage | None = None
    trace_id: str
    findings: list[Finding] = Field(default_factory=list)
    budget: BudgetSnapshot = Field(default_factory=BudgetSnapshot)
    terminal_status: ReviewStage | None = None
    error_message: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request: ReviewRequest
    snapshot: ReviewSnapshot | None = None
