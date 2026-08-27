"""CLI entrypoint for the stage-driven review pipeline."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from codereviewer.app.pipeline import ensure_artifact_root, resume_pipeline, run_pipeline
from codereviewer.config import build_app_config
from codereviewer.domain.errors import CodeReviewerError
from codereviewer.services.input_resolver import (
    ResolvedReviewInput,
    resolve_review_request,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""

    parser = argparse.ArgumentParser(description="Run the Code Review Agent skeleton.")
    parser.add_argument(
        "--review-url",
        help="GitHub PR URL or GitLab MR URL.",
    )
    parser.add_argument(
        "--provider",
        choices=("github", "gitlab"),
        help="Provider used for branch compare input.",
    )
    parser.add_argument(
        "--repo",
        help="Repository identifier such as owner/name or group/project.",
    )
    parser.add_argument(
        "--base-branch",
        help="Base branch name for branch compare input.",
    )
    parser.add_argument(
        "--head-branch",
        help="Head branch name for branch compare input.",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("artifacts"),
        help="Directory used to store local artifacts.",
    )
    parser.add_argument(
        "--resume-review-id",
        help="Resume an existing review from its checkpoint.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish provider comments after local outputs are prepared.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)

    config = build_app_config(
        artifact_root=args.artifact_root,
        publish_enabled=args.publish,
    )
    ensure_artifact_root(config.artifact_root)
    try:
        if args.resume_review_id:
            if any(
                [
                    args.review_url,
                    args.provider,
                    args.repo,
                    args.base_branch,
                    args.head_branch,
                ]
            ):
                raise ValueError(
                    "resume_review_id cannot be combined with new review input arguments."
                )
            result = resume_pipeline(args.resume_review_id, config)
            print(json.dumps(result.model_dump(mode="json"), ensure_ascii=True))
            return 0

        request = resolve_review_request(
            ResolvedReviewInput(
                review_url=args.review_url,
                provider=args.provider,
                repo=args.repo,
                base_branch=args.base_branch,
                head_branch=args.head_branch,
            )
        )
        result = run_pipeline(request, config)
    except (CodeReviewerError, ValueError) as exc:
        parser.exit(status=2, message=f"{exc}\n")

    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
