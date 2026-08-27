"""Store interfaces for checkpoints and traces."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from codereviewer.domain.models import ReviewCheckpoint, ReviewTrace, TraceArtifactRef


class CheckpointStore(Protocol):
    """Persistence interface for review checkpoints."""

    def save(self, review_id: str, checkpoint: ReviewCheckpoint) -> Path:
        """Persist a checkpoint and return its file path."""

    def load(self, review_id: str) -> ReviewCheckpoint | None:
        """Load a checkpoint if it exists."""


class TraceStore(Protocol):
    """Persistence interface for review traces."""

    def save(self, review_id: str, trace: ReviewTrace) -> Path:
        """Persist a trace and return its file path."""

    def load(self, review_id: str) -> ReviewTrace | None:
        """Load a trace if it exists."""

    def save_artifact(
        self,
        review_id: str,
        *,
        artifact_type: str,
        content: str,
    ) -> TraceArtifactRef:
        """Persist one redacted trace artifact and return its reference."""
