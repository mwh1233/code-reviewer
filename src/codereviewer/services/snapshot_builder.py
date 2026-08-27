"""Build provider-neutral review snapshots."""

from __future__ import annotations

import hashlib
import json

from codereviewer.domain.models import ReviewRequest, ReviewSnapshot


def build_input_hash(request: ReviewRequest) -> str:
    """Build a stable input hash for the current normalized request."""

    payload = json.dumps(request.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_review_id(
    request: ReviewRequest,
    *,
    review_id_prefix: str = "review",
    input_hash: str | None = None,
) -> str:
    """Build a stable review id for one normalized request instance."""

    resolved_input_hash = input_hash or build_input_hash(request)
    return f"{review_id_prefix}-{resolved_input_hash[:8]}"


def build_snapshot(
    request: ReviewRequest,
    *,
    review_id_prefix: str = "review",
    review_id: str | None = None,
    input_hash: str | None = None,
) -> ReviewSnapshot:
    """Construct a provider-neutral snapshot shell from a normalized request."""

    if not request.repo:
        raise ValueError("repo must be available before building a snapshot.")

    resolved_input_hash = input_hash or build_input_hash(request)
    resolved_review_id = review_id or build_review_id(
        request,
        review_id_prefix=review_id_prefix,
        input_hash=resolved_input_hash,
    )

    return ReviewSnapshot(
        review_id=resolved_review_id,
        provider=request.provider,
        source_kind=request.source_kind,
        repo=request.repo,
        review_url=request.review_url,
        change_number=request.change_number,
        input_hash=resolved_input_hash,
        base_ref=request.base_branch,
        head_ref=request.head_branch,
    )
