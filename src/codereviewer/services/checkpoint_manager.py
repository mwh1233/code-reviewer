"""Checkpoint orchestration helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from codereviewer.domain.enums import ReviewStage
from codereviewer.domain.interfaces.store import CheckpointStore
from codereviewer.domain.models import (
    BudgetSnapshot,
    Finding,
    ReviewCheckpoint,
    ReviewRequest,
    ReviewSnapshot,
)
from codereviewer.services.security import redact_text, sanitize_findings, sanitize_snapshot


class CheckpointManager:
    """Create and persist stage-boundary checkpoints."""

    def __init__(self, store: CheckpointStore) -> None:
        self._store = store

    def save_stage(
        self,
        *,
        review_id: str,
        input_hash: str,
        request: ReviewRequest,
        snapshot: ReviewSnapshot | None,
        trace_id: str,
        completed_stages: list[ReviewStage],
        current_stage: ReviewStage,
        next_stage: ReviewStage | None,
        findings: list[Finding] | None = None,
        error_message: str | None = None,
        terminal_status: ReviewStage | None = None,
        budget: BudgetSnapshot | None = None,
    ) -> ReviewCheckpoint:
        sanitized_snapshot = sanitize_snapshot(snapshot) if snapshot is not None else None
        sanitized_findings = sanitize_findings(list(findings or []))
        checkpoint = ReviewCheckpoint(
            review_id=review_id,
            provider=request.provider,
            repo=request.repo or "",
            input_hash=input_hash,
            base_sha=sanitized_snapshot.base_sha if sanitized_snapshot is not None else None,
            head_sha=sanitized_snapshot.head_sha if sanitized_snapshot is not None else None,
            completed_stages=list(completed_stages),
            current_stage=current_stage,
            next_stage=next_stage,
            trace_id=trace_id,
            findings=sanitized_findings,
            budget=budget or BudgetSnapshot(),
            terminal_status=terminal_status,
            error_message=redact_text(error_message) if error_message is not None else None,
            updated_at=datetime.now(timezone.utc),
            request=request,
            snapshot=sanitized_snapshot,
        )
        self._store.save(review_id, checkpoint)
        return checkpoint

    def load(self, review_id: str) -> ReviewCheckpoint | None:
        return self._store.load(review_id)
