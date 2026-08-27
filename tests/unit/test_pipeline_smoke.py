"""Pipeline tests for the stage-driven runner."""

import json

import pytest

from codereviewer.app.pipeline import resume_pipeline, run_pipeline
from codereviewer.config import build_app_config
from codereviewer.domain.enums import FindingSource, ProviderKind, ReviewSourceKind, ReviewStage
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
from codereviewer.services.snapshot_builder import build_review_id


class _DummyGitHubProvider:
    def __init__(self) -> None:
        self.published_comment_bodies: list[str] = []

    def resolve_snapshot_target(self, request: ReviewRequest) -> ReviewSnapshot:
        return ReviewSnapshot(
            review_id="review-provider123",
            provider=request.provider,
            source_kind=request.source_kind,
            repo=request.repo or "owner/repo",
            review_url=request.review_url,
            change_number=request.change_number,
            input_hash="b" * 64,
            base_ref=request.base_branch or "main",
            head_ref=request.head_branch or "feature/test",
            base_sha="base123",
            head_sha="head456",
            changed_files=["src/example.py", ".env"],
            diff_text=(
                "diff --git a/src/example.py b/src/example.py\n"
                "index 1111111..2222222 100644\n"
                "--- a/src/example.py\n"
                "+++ b/src/example.py\n"
                "@@ -1,1 +1,2 @@\n"
                " old_line\n"
                "+console.log(value)\n"
                "diff --git a/.env b/.env\n"
                "new file mode 100644\n"
                "index 0000000..3333333\n"
                "--- /dev/null\n"
                "+++ b/.env\n"
                "@@ -0,0 +1 @@\n"
                "+API_KEY=test\n"
            ),
        )

    def get_file_content(self, repo: str, path: str, ref: str) -> str:
        return {
            "src/example.py": "console.log(value)\n",
            ".env": "API_KEY=test\n",
        }[path]

    def get_current_head_sha(self, snapshot: ReviewSnapshot) -> str:
        return snapshot.head_sha or "unknown"

    def publish_review_comment(self, payload) -> str:
        self.published_comment_bodies.append(payload.body)
        return "comment-123"


class _DummyLLMProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[ToolChatRequest] = []
        self.budget_modes: list[str] = []

    def estimate_prompt_tokens(self, text: str, *, budget_mode: str = "normal") -> int:
        return 120

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        budget_mode: str = "normal",
    ) -> float:
        return 0.05

    def chat_with_tools(
        self,
        request: ToolChatRequest,
        *,
        budget_mode: str = "normal",
    ) -> ToolChatResponse:
        self.calls += 1
        self.requests.append(request)
        self.budget_modes.append(budget_mode)
        return ToolChatResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-comment",
                    name="code_comment",
                    arguments=json.dumps(self._comment_payload(), ensure_ascii=True),
                ),
                ToolCall(
                    id="call-done",
                    name="task_done",
                    arguments='{"reason":"review complete"}',
                ),
            ],
            input_tokens=120,
            output_tokens=30,
            estimated_cost=0.05,
        )

    def _comment_payload(self) -> dict[str, object]:
        return {
            "file": "src/example.py",
            "line": 2,
            "summary": "LLM spotted issue",
            "severity": "medium",
            "category": "bug",
            "explanation": "This may be noisy debug logic.",
            "suggested_fix": "Remove the statement if not needed.",
        }


class _DuplicateFindingLLMProvider(_DummyLLMProvider):
    def _comment_payload(self) -> dict[str, object]:
        return {
            "file": "src/example.py",
            "line": 2,
            "summary": "Debug statement added in the changed code.",
            "severity": "low",
            "category": "bug",
            "explanation": "This duplicates the deterministic debug finding.",
            "suggested_fix": "Remove the debug statement.",
        }


class _SecretEchoLLMProvider(_DummyLLMProvider):
    def _comment_payload(self) -> dict[str, object]:
        return {
            "file": "src/example.py",
            "line": 2,
            "summary": "Leaked github_pat_1234567890abcdefghijklmnopqrstuvwxyz",
            "severity": "high",
            "category": "security",
            "explanation": "Found sk-12345678901234567890 in generated review output.",
            "suggested_fix": "Rotate glpat-GBs_x7v8sYcNNdfMIO1qAmM6MQpvOjEKdTpvdHRsOA8.01.170s8o4n0 immediately.",
        }


class _SecretSnapshotGitHubProvider(_DummyGitHubProvider):
    def resolve_snapshot_target(self, request: ReviewRequest) -> ReviewSnapshot:
        return ReviewSnapshot(
            review_id="review-secret123",
            provider=request.provider,
            source_kind=request.source_kind,
            repo=request.repo or "owner/repo",
            review_url=request.review_url,
            change_number=request.change_number,
            input_hash="f" * 64,
            base_ref=request.base_branch or "main",
            head_ref=request.head_branch or "feature/test",
            base_sha="base123",
            head_sha="head456",
            changed_files=["src/example.py", ".env"],
            diff_text=(
                "diff --git a/src/example.py b/src/example.py\n"
                "index 1111111..2222222 100644\n"
                "--- a/src/example.py\n"
                "+++ b/src/example.py\n"
                "@@ -1,1 +1,2 @@\n"
                " old_line\n"
                '+token = "github_pat_1234567890abcdefghijklmnopqrstuvwxyz"\n'
                "diff --git a/.env b/.env\n"
                "new file mode 100644\n"
                "index 0000000..3333333\n"
                "--- /dev/null\n"
                "+++ b/.env\n"
                "@@ -0,0 +1 @@\n"
                "+LLM_API_KEY=sk-12345678901234567890\n"
            ),
        )

    def get_file_content(self, repo: str, path: str, ref: str) -> str:
        return {
            "src/example.py": 'token = "github_pat_1234567890abcdefghijklmnopqrstuvwxyz"\n',
            ".env": "LLM_API_KEY=sk-12345678901234567890\n",
        }[path]


def test_run_pipeline_creates_checkpoint_and_trace(tmp_path, monkeypatch):
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    llm_provider = _DummyLLMProvider()
    scm_provider = _DummyGitHubProvider()
    monkeypatch.setattr(
        review_runner,
        "build_scm_provider",
        lambda provider, config: scm_provider,
    )
    monkeypatch.setattr(
        review_runner,
        "build_llm_provider",
        lambda config: llm_provider,
    )

    result = run_pipeline(
        request := ReviewRequest(
            provider=ProviderKind.GITHUB,
            source_kind=ReviewSourceKind.BRANCH_COMPARE,
            repo="owner/repo",
            base_branch="main",
            head_branch="feature/test",
        ),
        config,
    )

    assert result.stage == ReviewStage.COMPLETED
    assert result.artifact_root.exists()
    assert result.placeholder_file.exists()
    assert result.checkpoint_file is not None and result.checkpoint_file.exists()
    assert result.trace_file is not None and result.trace_file.exists()
    assert (result.artifact_root / "report.md").exists()
    assert (result.artifact_root / "findings.json").exists()
    assert result.review_id == build_review_id(request)
    assert result.snapshot.review_id == result.review_id

    checkpoint = ReviewCheckpoint.model_validate_json(
        result.checkpoint_file.read_text(encoding="utf-8")
    )
    trace = ReviewTrace.model_validate_json(result.trace_file.read_text(encoding="utf-8"))

    assert checkpoint.current_stage == ReviewStage.COMPLETED
    assert checkpoint.terminal_status == ReviewStage.COMPLETED
    assert checkpoint.completed_stages[-1] == ReviewStage.COMPLETED
    assert ReviewStage.DETERMINISTIC_CHECKS_DONE in checkpoint.completed_stages
    assert ReviewStage.FINDINGS_GENERATED in checkpoint.completed_stages
    assert ReviewStage.FINDINGS_VERIFIED in checkpoint.completed_stages
    assert ReviewStage.PUBLISH_ATTEMPTED in checkpoint.completed_stages
    assert ReviewStage.SNAPSHOT_CREATED in checkpoint.completed_stages
    assert len(checkpoint.findings) == 3
    assert {finding.file for finding in checkpoint.findings} == {"src/example.py", ".env"}
    env_finding = next(finding for finding in checkpoint.findings if finding.file == ".env")
    assert env_finding.location_valid is False
    assert env_finding.confidence.value == "reference"
    assert any(
        evidence.source_type == "location_check_failed"
        for evidence in env_finding.evidence
    )
    assert any(
        finding.file == "src/example.py" and finding.location_valid is True
        for finding in checkpoint.findings
    )
    assert checkpoint.budget.token_used == 150
    assert checkpoint.budget.cost_used == 0.05
    assert llm_provider.calls == 1
    assert trace.events[-1].stage == ReviewStage.COMPLETED
    assert any("Tool read_diff completed." in event.message for event in trace.events)
    assert any("LLM findings generated" in event.message for event in trace.events)
    assert any("Findings verified and aggregated" in event.message for event in trace.events)
    assert any("Prepared local output artifacts" in event.message for event in trace.events)
    assert any("Publish skipped: publish disabled by configuration." in event.message for event in trace.events)
    assert sorted(path.name for path in (config.artifact_root / "reviews").iterdir()) == [
        result.review_id
    ]


def test_resume_pipeline_returns_saved_snapshot(tmp_path):
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    review_root = config.artifact_root / "reviews" / "review-existing123"
    review_root.mkdir(parents=True, exist_ok=True)

    request = ReviewRequest(
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        review_url="https://github.com/owner/repo/pull/123",
        repo="owner/repo",
        change_number=123,
    )
    snapshot = ReviewSnapshot(
        review_id="review-existing123",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/123",
        change_number=123,
        input_hash="c" * 64,
        base_ref="main",
        head_ref="feature/test",
        base_sha="base123",
        head_sha="head456",
        changed_files=["src/example.py"],
        diff_text="diff --git a/src/example.py b/src/example.py\n",
    )
    checkpoint = ReviewCheckpoint(
        review_id="review-existing123",
        provider=ProviderKind.GITHUB,
        repo="owner/repo",
        input_hash=snapshot.input_hash,
        base_sha=snapshot.base_sha,
        head_sha=snapshot.head_sha,
        completed_stages=[
            ReviewStage.INPUT_VALIDATED,
            ReviewStage.SNAPSHOT_CREATED,
            ReviewStage.ANALYSIS_PREPARED,
        ],
        current_stage=ReviewStage.COMPLETED,
        next_stage=None,
        trace_id="trace-existing123",
        terminal_status=ReviewStage.COMPLETED,
        request=request,
        snapshot=snapshot,
    )
    trace = ReviewTrace(
        trace_id="trace-existing123",
        review_id="review-existing123",
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

    result = resume_pipeline("review-existing123", config)

    assert result.review_id == "review-existing123"
    assert result.snapshot.head_sha == "head456"
    assert result.trace_file is not None and result.trace_file.exists()
    assert "Resumed review pipeline." in result.placeholder_file.read_text(encoding="utf-8")


def test_run_pipeline_skips_llm_when_budget_is_exceeded_before_call(
    tmp_path,
    monkeypatch,
):
    config = build_app_config(
        artifact_root=tmp_path / "artifacts",
        llm_max_total_tokens=100,
        llm_max_total_cost=0.01,
    )
    request = ReviewRequest(
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.BRANCH_COMPARE,
        repo="owner/repo",
        base_branch="main",
        head_branch="feature/test",
    )
    llm_provider = _DummyLLMProvider()
    monkeypatch.setattr(
        review_runner,
        "build_scm_provider",
        lambda provider, config: _DummyGitHubProvider(),
    )
    monkeypatch.setattr(
        review_runner,
        "build_llm_provider",
        lambda config: llm_provider,
    )

    result = run_pipeline(request, config)

    review_id = build_review_id(request)
    checkpoint_path = config.artifact_root / "reviews" / review_id / "checkpoint.json"
    trace_path = config.artifact_root / "reviews" / review_id / "trace.json"
    checkpoint = ReviewCheckpoint.model_validate_json(
        checkpoint_path.read_text(encoding="utf-8")
    )
    trace = ReviewTrace.model_validate_json(trace_path.read_text(encoding="utf-8"))

    assert result.stage == ReviewStage.COMPLETED
    assert checkpoint.current_stage == ReviewStage.COMPLETED
    assert checkpoint.terminal_status == ReviewStage.COMPLETED
    assert checkpoint.error_message is None
    assert checkpoint.budget.stop_reason == "token budget exceeded before LLM call."
    assert checkpoint.budget.token_used == 0
    assert checkpoint.budget.cost_used == 0.0
    assert checkpoint.budget.degrade_level == "stopped"
    assert len(checkpoint.findings) == 2
    assert {finding.file for finding in checkpoint.findings} == {"src/example.py", ".env"}
    assert ReviewStage.DETERMINISTIC_CHECKS_DONE in checkpoint.completed_stages
    assert ReviewStage.FINDINGS_GENERATED in checkpoint.completed_stages
    assert llm_provider.calls == 0
    assert any(
        "LLM review skipped due to budget policy: token budget exceeded before LLM call."
        in event.message
        for event in trace.events
    )


def test_run_pipeline_records_stop_reason_when_actual_usage_exceeds_limit(
    tmp_path,
    monkeypatch,
):
    config = build_app_config(
        artifact_root=tmp_path / "artifacts",
        llm_max_total_tokens=140,
        llm_max_total_cost=1.0,
    )
    llm_provider = _DummyLLMProvider()
    monkeypatch.setattr(
        review_runner,
        "build_scm_provider",
        lambda provider, config: _DummyGitHubProvider(),
    )
    monkeypatch.setattr(
        review_runner,
        "build_llm_provider",
        lambda config: llm_provider,
    )

    result = run_pipeline(
        request := ReviewRequest(
            provider=ProviderKind.GITHUB,
            source_kind=ReviewSourceKind.BRANCH_COMPARE,
            repo="owner/repo",
            base_branch="main",
            head_branch="feature/test",
        ),
        config,
    )
    checkpoint = ReviewCheckpoint.model_validate_json(
        result.checkpoint_file.read_text(encoding="utf-8")
    )
    trace = ReviewTrace.model_validate_json(result.trace_file.read_text(encoding="utf-8"))

    assert checkpoint.current_stage == ReviewStage.COMPLETED
    assert checkpoint.budget.token_used == 150
    assert checkpoint.budget.degrade_level == "stopped"
    assert checkpoint.budget.stop_reason == "token budget exceeded after LLM call."
    assert any(
        "Budget stop recorded: token budget exceeded after LLM call."
        in event.message
        for event in trace.events
    )


def test_run_pipeline_deduplicates_duplicate_rule_and_llm_findings(
    tmp_path,
    monkeypatch,
):
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    llm_provider = _DuplicateFindingLLMProvider()
    monkeypatch.setattr(
        review_runner,
        "build_scm_provider",
        lambda provider, config: _DummyGitHubProvider(),
    )
    monkeypatch.setattr(
        review_runner,
        "build_llm_provider",
        lambda config: llm_provider,
    )

    result = run_pipeline(
        ReviewRequest(
            provider=ProviderKind.GITHUB,
            source_kind=ReviewSourceKind.BRANCH_COMPARE,
            repo="owner/repo",
            base_branch="main",
            head_branch="feature/test",
        ),
        config,
    )
    checkpoint = ReviewCheckpoint.model_validate_json(
        result.checkpoint_file.read_text(encoding="utf-8")
    )

    assert len(checkpoint.findings) == 2
    debug_finding = next(
        finding for finding in checkpoint.findings if finding.file == "src/example.py"
    )
    assert debug_finding.source_type == FindingSource.HYBRID
    assert debug_finding.location_valid is True
    assert len(debug_finding.evidence) == 2


def test_run_pipeline_publishes_review_comment_when_enabled(tmp_path, monkeypatch):
    config = build_app_config(
        artifact_root=tmp_path / "artifacts",
        publish_enabled=True,
    )
    llm_provider = _DummyLLMProvider()
    scm_provider = _DummyGitHubProvider()
    monkeypatch.setattr(
        review_runner,
        "build_scm_provider",
        lambda provider, config: scm_provider,
    )
    monkeypatch.setattr(
        review_runner,
        "build_llm_provider",
        lambda config: llm_provider,
    )

    result = run_pipeline(
        ReviewRequest(
            provider=ProviderKind.GITHUB,
            source_kind=ReviewSourceKind.REVIEW_URL,
            review_url="https://github.com/owner/repo/pull/123",
            repo="owner/repo",
            change_number=123,
        ),
        config,
    )
    trace = ReviewTrace.model_validate_json(result.trace_file.read_text(encoding="utf-8"))

    assert scm_provider.published_comment_bodies
    assert "LLM spotted issue" in scm_provider.published_comment_bodies[0]
    assert any(
        "Published provider review comment with comment_id=comment-123" in event.message
        for event in trace.events
    )


def test_run_pipeline_redacts_secrets_from_outputs_trace_and_checkpoint(tmp_path, monkeypatch):
    config = build_app_config(
        artifact_root=tmp_path / "artifacts",
        publish_enabled=True,
    )
    llm_provider = _SecretEchoLLMProvider()
    scm_provider = _SecretSnapshotGitHubProvider()
    monkeypatch.setattr(
        review_runner,
        "build_scm_provider",
        lambda provider, config: scm_provider,
    )
    monkeypatch.setattr(
        review_runner,
        "build_llm_provider",
        lambda config: llm_provider,
    )

    result = run_pipeline(
        ReviewRequest(
            provider=ProviderKind.GITHUB,
            source_kind=ReviewSourceKind.REVIEW_URL,
            review_url="https://github.com/owner/repo/pull/123",
            repo="owner/repo",
            change_number=123,
        ),
        config,
    )
    review_root = result.artifact_root
    checkpoint_text = (review_root / "checkpoint.json").read_text(encoding="utf-8")
    trace = ReviewTrace.model_validate_json(
        (review_root / "trace.json").read_text(encoding="utf-8")
    )
    report_text = (review_root / "report.md").read_text(encoding="utf-8")
    findings_text = (review_root / "findings.json").read_text(encoding="utf-8")

    forbidden_values = [
        "github_pat_1234567890abcdefghijklmnopqrstuvwxyz",
        "sk-12345678901234567890",
        "glpat-GBs_x7v8sYcNNdfMIO1qAmM6MQpvOjEKdTpvdHRsOA8.01.170s8o4n0",
    ]
    for value in forbidden_values:
        assert value not in checkpoint_text
        assert value not in report_text
        assert value not in findings_text
        assert value not in json.dumps(trace.model_dump(mode="json"))
        assert value not in scm_provider.published_comment_bodies[0]

    assert trace.artifact_refs
    assert any(ref.artifact_type == "llm_prompt" for ref in trace.artifact_refs)
    assert any(ref.artifact_type == "llm_response" for ref in trace.artifact_refs)

    for artifact_ref in trace.artifact_refs:
        artifact_path = review_root / artifact_ref.storage_ref
        artifact_text = artifact_path.read_text(encoding="utf-8")
        for value in forbidden_values:
            assert value not in artifact_text
        assert artifact_ref.redacted is True

    prompt_artifact = next(ref for ref in trace.artifact_refs if ref.artifact_type == "llm_prompt")
    prompt_text = (review_root / prompt_artifact.storage_ref).read_text(encoding="utf-8")
    assert ".env" not in prompt_text
    assert "[REDACTED_SECRET]" in prompt_text
    assert "[REDACTED_SECRET]" in report_text
    assert "[REDACTED_SECRET]" in findings_text
    assert "[REDACTED_SECRET]" in scm_provider.published_comment_bodies[0]
