"""Publish final review findings through provider adapters."""

from __future__ import annotations

from codereviewer.domain.enums import ReviewSourceKind
from codereviewer.domain.errors import PublishError
from codereviewer.domain.interfaces.scm import SCMProvider
from codereviewer.domain.models import CommentPayload, Finding, PublishResult, ReviewSnapshot
from codereviewer.reporters.comment import render_review_comment
from codereviewer.services.security import sanitize_findings


class PublishController:
    """Apply publish policy, head SHA checks, and provider comment publishing."""

    def __init__(self, *, publish_enabled: bool) -> None:
        self._publish_enabled = publish_enabled

    def publish(
        self,
        *,
        provider: SCMProvider,
        review_id: str,
        snapshot: ReviewSnapshot,
        findings: list[Finding],
    ) -> PublishResult:
        if not self._publish_enabled:
            return PublishResult(
                published=False,
                reason="publish disabled by configuration.",
            )

        if snapshot.source_kind != ReviewSourceKind.REVIEW_URL:
            return PublishResult(
                published=False,
                reason="provider comment publishing only supports review_url inputs.",
            )

        if snapshot.change_number is None:
            raise PublishError("cannot publish without a provider change number.")
        if snapshot.head_sha is None:
            raise PublishError("cannot publish without snapshot head_sha.")

        current_head_sha = provider.get_current_head_sha(snapshot)
        if current_head_sha != snapshot.head_sha:
            raise PublishError(
                "refused to publish because head SHA changed from "
                f"{snapshot.head_sha} to {current_head_sha}."
            )

        safe_findings = sanitize_findings(findings)
        comment_id = provider.publish_review_comment(
            CommentPayload(
                provider=snapshot.provider,
                repo=snapshot.repo,
                change_number=snapshot.change_number,
                head_sha=current_head_sha,
                body=render_review_comment(
                    review_id=review_id,
                    snapshot=snapshot,
                    findings=safe_findings,
                ),
            )
        )
        return PublishResult(
            published=True,
            provider_comment_id=comment_id,
            published_head_sha=current_head_sha,
        )
