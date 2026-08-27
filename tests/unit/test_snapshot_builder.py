"""Unit tests for snapshot skeleton construction."""

from codereviewer.domain.enums import ProviderKind, ReviewSourceKind
from codereviewer.domain.models import ReviewRequest
from codereviewer.services.snapshot_builder import build_input_hash, build_review_id, build_snapshot


def test_build_snapshot_from_branch_compare_request():
    request = ReviewRequest(
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.BRANCH_COMPARE,
        repo="owner/repo",
        base_branch="main",
        head_branch="feature/x",
    )

    snapshot = build_snapshot(request)

    assert snapshot.review_id.startswith("review-")
    assert snapshot.provider == ProviderKind.GITHUB
    assert snapshot.repo == "owner/repo"
    assert snapshot.base_ref == "main"
    assert snapshot.head_ref == "feature/x"
    assert snapshot.base_sha is None
    assert snapshot.head_sha is None
    assert snapshot.changed_files == []
    assert snapshot.diff_text == ""
    assert len(snapshot.input_hash) == 64


def test_build_review_id_matches_snapshot_review_id():
    request = ReviewRequest(
        provider=ProviderKind.GITLAB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        review_url="https://gitlab.com/group/project/-/merge_requests/1",
        repo="group/project",
        change_number=1,
    )

    input_hash = build_input_hash(request)
    review_id = build_review_id(request, input_hash=input_hash)
    snapshot = build_snapshot(request, review_id=review_id, input_hash=input_hash)

    assert snapshot.review_id == review_id
    assert snapshot.input_hash == input_hash
