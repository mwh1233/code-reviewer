"""Trace orchestration helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from codereviewer.domain.enums import ReviewStage
from codereviewer.domain.interfaces.store import TraceStore
from codereviewer.domain.models import ReviewTrace, TraceArtifactRef, TraceEvent
from codereviewer.services.security import redact_text


class TraceManager:
    """Create and persist review trace events."""

    def __init__(self, store: TraceStore) -> None:
        self._store = store

    def create(self, review_id: str) -> ReviewTrace:
        trace = ReviewTrace(
            trace_id=f"trace-{uuid4().hex[:10]}",
            review_id=review_id,
        )
        self._store.save(review_id, trace)
        return trace

    def append_event(
        self,
        *,
        review_id: str,
        trace: ReviewTrace,
        stage: ReviewStage,
        message: str,
        details: dict[str, object] | None = None,
    ) -> ReviewTrace:
        trace.events.append(
            TraceEvent(
                stage=stage,
                message=redact_text(message),
                timestamp=datetime.now(timezone.utc),
                details=_redact_details(details or {}),
            )
        )
        trace.updated_at = datetime.now(timezone.utc)
        self._store.save(review_id, trace)
        return trace

    def write_artifact(
        self,
        *,
        review_id: str,
        trace: ReviewTrace,
        artifact_type: str,
        content: str,
    ) -> TraceArtifactRef:
        artifact_ref = self._store.save_artifact(
            review_id,
            artifact_type=artifact_type,
            content=redact_text(content),
        )
        trace.artifact_refs.append(artifact_ref)
        trace.updated_at = datetime.now(timezone.utc)
        self._store.save(review_id, trace)
        return artifact_ref

    def load(self, review_id: str) -> ReviewTrace | None:
        return self._store.load(review_id)


def _redact_details(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            str(key): _redact_details(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_details(item) for item in value]
    return value
