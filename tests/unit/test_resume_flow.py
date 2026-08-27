"""Resume flow tests for stage-driven pipeline recovery."""

import json

import pytest

from codereviewer.app.pipeline import resume_pipeline
from codereviewer.config import build_app_config
from codereviewer.domain.enums import ProviderKind, ReviewSourceKind, ReviewStage
from codereviewer.domain.models import (
    ReviewCheckpoint,
    ReviewRequest,
    ReviewSnapshot,
    ReviewTrace,
    ToolCall,
    ToolChatRequest,
    ToolChatResponse,
)
from codereviewer.services import review_runner


def test_resume_pipeline_rejects_missing_checkpoint(tmp_path):
    config = build_app_config(artifact_root=tmp_path / "artifacts")

    with pytest.raises(ValueError, match="checkpoint for review_id=missing-review was not found"):
        resume_pipeline("missing-review", config)


def test_resume_pipeline_completes_remaining_stages(tmp_path, monkeypatch):
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    review_root = config.artifact_root / "reviews" / "review-resume123"
    review_root.mkdir(parents=True, exist_ok=True)

    request = ReviewRequest(
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        review_url="https://github.com/owner/repo/pull/123",
        repo="owner/repo",
        change_number=123,
    )
    snapshot = ReviewSnapshot(
        review_id="review-resume123",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url=request.review_url,
        change_number=123,
        input_hash="d" * 64,
        base_ref="main",
        head_ref="feature/test",
        base_sha="base123",
        head_sha="head456",
        changed_files=["src/example.py"],
        diff_text=(
            "diff --git a/src/example.py b/src/example.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/example.py\n"
            "+++ b/src/example.py\n"
            "@@ -1,1 +1,2 @@\n"
            " old_line\n"
            "+console.log(value)\n"
        ),
    )
    checkpoint = ReviewCheckpoint(
        review_id="review-resume123",
        provider=ProviderKind.GITHUB,
        repo="owner/repo",
        input_hash=snapshot.input_hash,
        base_sha=snapshot.base_sha,
        head_sha=snapshot.head_sha,
        completed_stages=[
            ReviewStage.INPUT_VALIDATED,
            ReviewStage.SNAPSHOT_CREATED,
        ],
        current_stage=ReviewStage.SNAPSHOT_CREATED,
        next_stage=ReviewStage.ANALYSIS_PREPARED,
        trace_id="trace-resume123",
        request=request,
        snapshot=snapshot,
    )
    trace = ReviewTrace(
        trace_id="trace-resume123",
        review_id="review-resume123",
        events=[],
    )

    (review_root / "checkpoint.json").write_text(
        json.dumps(checkpoint.model_dump(mode="json"), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    (review_root / "trace.json").write_text(
        json.dumps(trace.model_dump(mode="json"), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    class _DummyLLMProvider:
        def estimate_prompt_tokens(self, text: str, *, budget_mode: str = "normal") -> int:
            return 100

        def estimate_cost(
            self,
            input_tokens: int,
            output_tokens: int,
            *,
            budget_mode: str = "normal",
        ) -> float:
            return 0.03

        def chat_with_tools(
            self,
            request: ToolChatRequest,
            *,
            budget_mode: str = "normal",
        ) -> ToolChatResponse:
            return ToolChatResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-comment",
                        name="code_comment",
                        arguments=(
                            '{"file":"src/example.py","line":2,"summary":"LLM follow-up",'
                            '"severity":"low","category":"bug",'
                            '"explanation":"This line may be leftover debug logic.",'
                            '"suggested_fix":"Consider removing it."}'
                        ),
                    ),
                    ToolCall(
                        id="call-done",
                        name="task_done",
                        arguments='{"reason":"resume complete"}',
                    ),
                ],
                input_tokens=100,
                output_tokens=25,
                estimated_cost=0.03,
            )

    class _DummySCMProvider:
        def get_file_content(self, repo: str, path: str, ref: str) -> str:
            return "console.log(value)\n"

        def get_current_head_sha(self, snapshot: ReviewSnapshot) -> str:
            return snapshot.head_sha or "unknown"

        def publish_review_comment(self, payload) -> str:
            return "comment-123"

    monkeypatch.setattr(
        review_runner,
        "build_llm_provider",
        lambda config: _DummyLLMProvider(),
    )
    monkeypatch.setattr(
        review_runner,
        "build_scm_provider",
        lambda provider, config: _DummySCMProvider(),
    )

    result = resume_pipeline("review-resume123", config)
    saved_checkpoint = ReviewCheckpoint.model_validate_json(
        (review_root / "checkpoint.json").read_text(encoding="utf-8")
    )
    saved_trace = ReviewTrace.model_validate_json(
        (review_root / "trace.json").read_text(encoding="utf-8")
    )

    assert result.stage == ReviewStage.COMPLETED
    assert result.message == "Review resumed and completed remaining pipeline stages."
    assert (review_root / "report.md").exists()
    assert (review_root / "findings.json").exists()
    assert saved_checkpoint.terminal_status == ReviewStage.COMPLETED
    assert saved_checkpoint.current_stage == ReviewStage.COMPLETED
    assert saved_checkpoint.completed_stages[-1] == ReviewStage.COMPLETED
    assert ReviewStage.FINDINGS_VERIFIED in saved_checkpoint.completed_stages
    assert ReviewStage.PUBLISH_ATTEMPTED in saved_checkpoint.completed_stages
    assert len(saved_checkpoint.findings) == 2
    assert saved_checkpoint.findings[0].file == "src/example.py"
    assert all(finding.location_valid is True for finding in saved_checkpoint.findings)
    assert saved_checkpoint.budget.token_used == 125
    assert saved_checkpoint.budget.cost_used == 0.03
    assert saved_trace.events[-1].stage == ReviewStage.COMPLETED
    assert any(
        "Findings verified and aggregated" in event.message
        for event in saved_trace.events
    )
    assert any(
        "Prepared local output artifacts" in event.message
        for event in saved_trace.events
    )
    assert any(
        "Publish skipped: publish disabled by configuration." in event.message
        for event in saved_trace.events
    )


def test_resume_pipeline_skips_llm_when_budget_is_already_stopped(tmp_path, monkeypatch):
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    review_root = config.artifact_root / "reviews" / "review-budgetstop123"
    review_root.mkdir(parents=True, exist_ok=True)

    request = ReviewRequest(
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        review_url="https://github.com/owner/repo/pull/123",
        repo="owner/repo",
        change_number=123,
    )
    snapshot = ReviewSnapshot(
        review_id="review-budgetstop123",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url=request.review_url,
        change_number=123,
        input_hash="e" * 64,
        base_ref="main",
        head_ref="feature/test",
        base_sha="base123",
        head_sha="head456",
        changed_files=["src/example.py"],
        diff_text=(
            "diff --git a/src/example.py b/src/example.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/example.py\n"
            "+++ b/src/example.py\n"
            "@@ -1,1 +1,2 @@\n"
            " old_line\n"
            "+console.log(value)\n"
        ),
    )
    checkpoint = ReviewCheckpoint(
        review_id="review-budgetstop123",
        provider=ProviderKind.GITHUB,
        repo="owner/repo",
        input_hash=snapshot.input_hash,
        base_sha=snapshot.base_sha,
        head_sha=snapshot.head_sha,
        completed_stages=[
            ReviewStage.INPUT_VALIDATED,
            ReviewStage.SNAPSHOT_CREATED,
            ReviewStage.ANALYSIS_PREPARED,
            ReviewStage.DETERMINISTIC_CHECKS_DONE,
        ],
        current_stage=ReviewStage.DETERMINISTIC_CHECKS_DONE,
        next_stage=ReviewStage.FINDINGS_GENERATED,
        trace_id="trace-budgetstop123",
        request=request,
        snapshot=snapshot,
        budget={
            "token_limit": 100,
            "token_used": 100,
            "cost_limit": 1.0,
            "cost_used": 0.0,
            "stop_reason": "token budget exceeded before LLM call.",
            "degrade_level": "stopped",
            "last_decision": "token budget exceeded before LLM call.",
            "last_projected_ratio": 1.0,
            "last_actual_ratio": 1.0,
        },
    )
    trace = ReviewTrace(
        trace_id="trace-budgetstop123",
        review_id="review-budgetstop123",
        events=[],
    )

    (review_root / "checkpoint.json").write_text(
        json.dumps(checkpoint.model_dump(mode="json"), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    (review_root / "trace.json").write_text(
        json.dumps(trace.model_dump(mode="json"), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    class _DummyLLMProvider:
        def __init__(self) -> None:
            self.calls = 0

        def estimate_prompt_tokens(self, text: str, *, budget_mode: str = "normal") -> int:
            return 100

        def estimate_cost(
            self,
            input_tokens: int,
            output_tokens: int,
            *,
            budget_mode: str = "normal",
        ) -> float:
            return 0.03

        def chat_with_tools(
            self,
            request: ToolChatRequest,
            *,
            budget_mode: str = "normal",
        ) -> ToolChatResponse:
            self.calls += 1
            return ToolChatResponse(
                content=None,
                tool_calls=[],
                input_tokens=100,
                output_tokens=25,
                estimated_cost=0.03,
            )

    class _DummySCMProvider:
        def get_file_content(self, repo: str, path: str, ref: str) -> str:
            return "console.log(value)\n"

        def get_current_head_sha(self, snapshot: ReviewSnapshot) -> str:
            return snapshot.head_sha or "unknown"

        def publish_review_comment(self, payload) -> str:
            return "comment-123"

    llm_provider = _DummyLLMProvider()
    monkeypatch.setattr(
        review_runner,
        "build_llm_provider",
        lambda config: llm_provider,
    )
    monkeypatch.setattr(
        review_runner,
        "build_scm_provider",
        lambda provider, config: _DummySCMProvider(),
    )

    result = resume_pipeline("review-budgetstop123", config)
    saved_checkpoint = ReviewCheckpoint.model_validate_json(
        (review_root / "checkpoint.json").read_text(encoding="utf-8")
    )
    saved_trace = ReviewTrace.model_validate_json(
        (review_root / "trace.json").read_text(encoding="utf-8")
    )

    assert result.stage == ReviewStage.COMPLETED
    assert llm_provider.calls == 1
    assert saved_checkpoint.budget.stop_reason == "token budget exceeded after LLM call."
    assert any(
        "LLM review skipped due to budget policy: token budget exceeded after LLM call."
        in event.message
        for event in saved_trace.events
    )
