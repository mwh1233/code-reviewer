"""CLI tests for the M2 slice."""

from __future__ import annotations

import json

import pytest

from codereviewer.app import cli
from codereviewer.domain.enums import ProviderKind, ReviewSourceKind, ReviewStage
from codereviewer.domain.errors import ProviderResolutionError
from codereviewer.domain.models import PipelineResult, ReviewRequest, ReviewSnapshot


def test_cli_runs_and_emits_snapshot_payload(tmp_path, monkeypatch, capsys):
    snapshot = ReviewSnapshot(
        review_id="review-test1234",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/123",
        change_number=123,
        input_hash="a" * 64,
        base_ref="main",
        head_ref="feature/test",
        base_sha="base123",
        head_sha="head456",
        changed_files=["src/app.py"],
        diff_text="diff --git a/src/app.py b/src/app.py\n",
    )
    result = PipelineResult(
        review_id=snapshot.review_id,
        stage=ReviewStage.COMPLETED,
        message="ok",
        artifact_root=tmp_path / "artifacts" / "reviews" / snapshot.review_id,
        placeholder_file=tmp_path
        / "artifacts"
        / "reviews"
        / snapshot.review_id
        / "placeholder.txt",
        request=ReviewRequest(
            provider=ProviderKind.GITHUB,
            source_kind=ReviewSourceKind.REVIEW_URL,
            review_url="https://github.com/owner/repo/pull/123",
            repo="owner/repo",
            change_number=123,
        ),
        snapshot=snapshot,
    )

    monkeypatch.setattr(cli, "run_pipeline", lambda request, config: result)

    exit_code = cli.main(
        [
            "--review-url",
            "https://github.com/owner/repo/pull/123",
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["stage"] == "completed"
    assert payload["snapshot"]["base_sha"] == "base123"
    assert payload["snapshot"]["head_sha"] == "head456"


def test_cli_passes_publish_flag_to_config(tmp_path, monkeypatch, capsys):
    snapshot = ReviewSnapshot(
        review_id="review-test1234",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/123",
        change_number=123,
        input_hash="a" * 64,
        base_ref="main",
        head_ref="feature/test",
        base_sha="base123",
        head_sha="head456",
        changed_files=["src/app.py"],
        diff_text="diff --git a/src/app.py b/src/app.py\n",
    )
    result = PipelineResult(
        review_id=snapshot.review_id,
        stage=ReviewStage.COMPLETED,
        message="ok",
        artifact_root=tmp_path / "artifacts" / "reviews" / snapshot.review_id,
        placeholder_file=tmp_path
        / "artifacts"
        / "reviews"
        / snapshot.review_id
        / "placeholder.txt",
        request=ReviewRequest(
            provider=ProviderKind.GITHUB,
            source_kind=ReviewSourceKind.REVIEW_URL,
            review_url="https://github.com/owner/repo/pull/123",
            repo="owner/repo",
            change_number=123,
        ),
        snapshot=snapshot,
    )

    def assert_publish_enabled(request, config):
        assert config.publish.enabled is True
        return result

    monkeypatch.setattr(cli, "run_pipeline", assert_publish_enabled)

    exit_code = cli.main(
        [
            "--review-url",
            "https://github.com/owner/repo/pull/123",
            "--publish",
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["review_id"] == "review-test1234"


def test_cli_exits_cleanly_for_provider_error(tmp_path, monkeypatch):
    def raise_error(request, config):
        raise ProviderResolutionError("provider resolution failed")

    monkeypatch.setattr(cli, "run_pipeline", raise_error)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(
            [
                "--review-url",
                "https://gitlab.com/group/project/-/merge_requests/1",
                "--artifact-root",
                str(tmp_path / "artifacts"),
            ]
        )

    assert exc_info.value.code == 2
