"""Tests for publish policy and provider comment publishing."""

import pytest

from codereviewer.domain.enums import Confidence, FindingSource, ProviderKind, ReviewSourceKind, Severity
from codereviewer.domain.errors import PublishError
from codereviewer.domain.models import Finding, ReviewSnapshot
from codereviewer.services.publish_controller import PublishController


class _DummyProvider:
    def __init__(self, *, current_head_sha: str = "head456", comment_id: str = "123") -> None:
        self.current_head_sha = current_head_sha
        self.comment_id = comment_id
        self.published_bodies: list[str] = []

    def get_current_head_sha(self, snapshot: ReviewSnapshot) -> str:
        return self.current_head_sha

    def publish_review_comment(self, payload) -> str:
        self.published_bodies.append(payload.body)
        return self.comment_id


def _build_snapshot(source_kind: ReviewSourceKind = ReviewSourceKind.REVIEW_URL) -> ReviewSnapshot:
    return ReviewSnapshot(
        review_id="review-test123",
        provider=ProviderKind.GITHUB,
        source_kind=source_kind,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/123",
        change_number=123,
        input_hash="a" * 64,
        head_sha="head456",
    )


def _build_findings() -> list[Finding]:
    return [
        Finding(
            id="finding-1",
            summary="Potential bug",
            severity=Severity.MEDIUM,
            confidence=Confidence.REFERENCE,
            file="src/app.py",
            line=10,
            explanation="Something looks suspicious.",
            suggested_fix="Check the branch condition.",
            source_type=FindingSource.LLM,
        )
    ]


def test_publish_controller_skips_when_disabled():
    controller = PublishController(publish_enabled=False)

    result = controller.publish(
        provider=_DummyProvider(),
        review_id="review-test123",
        snapshot=_build_snapshot(),
        findings=_build_findings(),
    )

    assert result.published is False
    assert result.reason == "publish disabled by configuration."


def test_publish_controller_rejects_head_sha_mismatch():
    controller = PublishController(publish_enabled=True)

    with pytest.raises(PublishError, match="head SHA changed"):
        controller.publish(
            provider=_DummyProvider(current_head_sha="new-head789"),
            review_id="review-test123",
            snapshot=_build_snapshot(),
            findings=_build_findings(),
        )


def test_publish_controller_publishes_comment_when_enabled():
    provider = _DummyProvider(comment_id="987")
    controller = PublishController(publish_enabled=True)

    result = controller.publish(
        provider=provider,
        review_id="review-test123",
        snapshot=_build_snapshot(),
        findings=_build_findings(),
    )

    assert result.published is True
    assert result.provider_comment_id == "987"
    assert result.published_head_sha == "head456"
    assert provider.published_bodies
    assert "Potential bug" in provider.published_bodies[0]


def test_publish_controller_publishes_mergeable_summary_when_no_findings():
    provider = _DummyProvider(comment_id="456")
    controller = PublishController(publish_enabled=True)

    result = controller.publish(
        provider=provider,
        review_id="review-test123",
        snapshot=_build_snapshot(),
        findings=[],
    )

    assert result.published is True
    assert result.provider_comment_id == "456"
    assert result.published_head_sha == "head456"
    assert provider.published_bodies
    assert "未发现需要阻塞合并的高置信度问题，可以合并。" in provider.published_bodies[0]
    assert "问题总数: 0" in provider.published_bodies[0]


def test_publish_controller_skips_non_review_url_inputs():
    controller = PublishController(publish_enabled=True)

    result = controller.publish(
        provider=_DummyProvider(),
        review_id="review-test123",
        snapshot=_build_snapshot(ReviewSourceKind.BRANCH_COMPARE),
        findings=_build_findings(),
    )

    assert result.published is False
    assert result.reason == "provider comment publishing only supports review_url inputs."
