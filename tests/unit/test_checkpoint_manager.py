"""Unit tests for checkpoint persistence."""

from codereviewer.adapters.storage.file_store import FileCheckpointStore
from codereviewer.config import build_app_config
from codereviewer.domain.enums import Confidence, FindingSource, ProviderKind, ReviewSourceKind, ReviewStage, Severity
from codereviewer.domain.models import EvidenceRef, Finding, ReviewRequest, ReviewSnapshot
from codereviewer.services.checkpoint_manager import CheckpointManager


def test_checkpoint_manager_saves_and_loads_checkpoint(tmp_path):
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    manager = CheckpointManager(FileCheckpointStore(config.artifact_root))
    request = ReviewRequest(
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        review_url="https://github.com/owner/repo/pull/1",
        repo="owner/repo",
        change_number=1,
    )
    snapshot = ReviewSnapshot(
        review_id="review-abc12345",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url=request.review_url,
        change_number=1,
        input_hash="a" * 64,
        base_ref="main",
        head_ref="feature",
        base_sha="base123",
        head_sha="head456",
    )

    manager.save_stage(
        review_id=snapshot.review_id,
        input_hash=snapshot.input_hash,
        request=request,
        snapshot=snapshot,
        trace_id="trace-abc12345",
        completed_stages=[ReviewStage.INPUT_VALIDATED],
        current_stage=ReviewStage.SNAPSHOT_CREATED,
        next_stage=ReviewStage.ANALYSIS_PREPARED,
        findings=[
            Finding(
                id="finding-1",
                summary="debug statement",
                severity=Severity.LOW,
                confidence=Confidence.HIGH,
                file="src/app.py",
                line=3,
                explanation="debug code was added",
                evidence=[
                    EvidenceRef(
                        source_type="diff",
                        source_id="read_diff",
                        file="src/app.py",
                        line_start=3,
                        line_end=3,
                        excerpt="console.log(value)",
                    )
                ],
                source_type=FindingSource.RULE,
            )
        ],
    )

    loaded = manager.load(snapshot.review_id)

    assert loaded is not None
    assert loaded.current_stage == ReviewStage.SNAPSHOT_CREATED
    assert loaded.snapshot is not None
    assert loaded.snapshot.head_sha == "head456"
    assert loaded.findings[0].file == "src/app.py"
