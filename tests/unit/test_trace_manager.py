"""Unit tests for trace persistence."""

from codereviewer.adapters.storage.file_store import FileTraceStore
from codereviewer.config import build_app_config
from codereviewer.domain.enums import ReviewStage
from codereviewer.services.trace_manager import TraceManager


def test_trace_manager_creates_and_appends_events(tmp_path):
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    manager = TraceManager(FileTraceStore(config.artifact_root))

    trace = manager.create("review-abc12345")
    updated = manager.append_event(
        review_id="review-abc12345",
        trace=trace,
        stage=ReviewStage.INPUT_VALIDATED,
        message="validated",
    )

    loaded = manager.load("review-abc12345")

    assert loaded is not None
    assert loaded.trace_id == trace.trace_id
    assert updated.events[-1].message == "validated"
    assert loaded.events[-1].stage == ReviewStage.INPUT_VALIDATED
    assert loaded.events[-1].details == {}


def test_trace_manager_persists_structured_event_details(tmp_path):
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    manager = TraceManager(FileTraceStore(config.artifact_root))

    trace = manager.create("review-toolchat123")
    manager.append_event(
        review_id="review-toolchat123",
        trace=trace,
        stage=ReviewStage.FINDINGS_GENERATED,
        message="tool chat summary",
        details={
            "tool_name": "read_file",
            "finish_reason": "tool_calls",
            "tool_call_count": 1,
        },
    )

    loaded = manager.load("review-toolchat123")

    assert loaded is not None
    assert loaded.events[-1].details == {
        "tool_name": "read_file",
        "finish_reason": "tool_calls",
        "tool_call_count": 1,
    }


def test_trace_manager_persists_redacted_artifact_refs(tmp_path):
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    manager = TraceManager(FileTraceStore(config.artifact_root))

    trace = manager.create("review-artifact123")
    artifact = manager.write_artifact(
        review_id="review-artifact123",
        trace=trace,
        artifact_type="llm_prompt",
        content='token="github_pat_1234567890abcdefghijklmnopqrstuvwxyz"',
    )
    loaded = manager.load("review-artifact123")

    assert loaded is not None
    assert loaded.artifact_refs[-1].artifact_id == artifact.artifact_id
    artifact_path = config.artifact_root / "reviews" / "review-artifact123" / artifact.storage_ref
    assert artifact_path.exists()
    assert "[REDACTED_SECRET]" in artifact_path.read_text(encoding="utf-8")
    assert "github_pat_1234567890abcdefghijklmnopqrstuvwxyz" not in artifact_path.read_text(
        encoding="utf-8"
    )
