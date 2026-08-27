"""File-backed stores for checkpoints and traces."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from codereviewer.domain.models import ReviewCheckpoint, ReviewTrace, TraceArtifactRef


class FileCheckpointStore:
    """Persist checkpoints under the review artifact directory."""

    def __init__(self, artifact_root: Path) -> None:
        self._artifact_root = artifact_root

    def save(self, review_id: str, checkpoint: ReviewCheckpoint) -> Path:
        path = self._review_root(review_id) / "checkpoint.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(checkpoint.model_dump(mode="json"), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, review_id: str) -> ReviewCheckpoint | None:
        path = self._review_root(review_id) / "checkpoint.json"
        if not path.exists():
            return None
        return ReviewCheckpoint.model_validate_json(path.read_text(encoding="utf-8"))

    def _review_root(self, review_id: str) -> Path:
        return self._artifact_root / "reviews" / review_id


class FileTraceStore:
    """Persist traces under the review artifact directory."""

    def __init__(self, artifact_root: Path) -> None:
        self._artifact_root = artifact_root

    def save(self, review_id: str, trace: ReviewTrace) -> Path:
        path = self._review_root(review_id) / "trace.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(trace.model_dump(mode="json"), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, review_id: str) -> ReviewTrace | None:
        path = self._review_root(review_id) / "trace.json"
        if not path.exists():
            return None
        return ReviewTrace.model_validate_json(path.read_text(encoding="utf-8"))

    def save_artifact(
        self,
        review_id: str,
        *,
        artifact_type: str,
        content: str,
    ) -> TraceArtifactRef:
        artifacts_root = self._review_root(review_id) / "trace_artifacts"
        artifacts_root.mkdir(parents=True, exist_ok=True)
        artifact_id = f"{artifact_type}-{uuid4().hex[:8]}"
        path = artifacts_root / f"{artifact_id}.txt"
        path.write_text(content, encoding="utf-8")
        return TraceArtifactRef(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            storage_ref=f"trace_artifacts/{path.name}",
            redacted=True,
        )

    def _review_root(self, review_id: str) -> Path:
        return self._artifact_root / "reviews" / review_id
