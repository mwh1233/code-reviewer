"""Pipeline entrypoints for the stage-driven review runner."""

from __future__ import annotations

from pathlib import Path

from codereviewer.config import AppConfig
from codereviewer.domain.models import PipelineResult, ReviewRequest
from codereviewer.services.review_runner import ReviewRunner


def run_pipeline(
    request: ReviewRequest,
    config: AppConfig,
) -> PipelineResult:
    """Run the stage-driven review pipeline."""

    return ReviewRunner(config).run(request)


def resume_pipeline(
    review_id: str,
    config: AppConfig,
) -> PipelineResult:
    """Resume a stage-driven review pipeline from a saved checkpoint."""

    return ReviewRunner(config).resume(review_id)


def ensure_artifact_root(path: Path) -> Path:
    """Create the artifact root if needed and return it."""

    path.mkdir(parents=True, exist_ok=True)
    return path
