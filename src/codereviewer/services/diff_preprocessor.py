"""Helpers for parsing unified diffs into deterministic rule input."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from codereviewer.domain.models import ReviewSnapshot


_DIFF_HEADER_PATTERN = re.compile(r"^diff --git a/(.*?) b/(.*?)$")
_HUNK_HEADER_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<new_start>\d+)(?:,\d+)? @@")


class AddedDiffLine(BaseModel):
    """One added line extracted from a unified diff hunk."""

    line_number: int | None = None
    content: str


class PreparedFileDiff(BaseModel):
    """One changed file extracted from the review diff."""

    path: str
    diff_text: str
    is_binary: bool = False
    added_lines: list[AddedDiffLine] = Field(default_factory=list)


class PreparedDiffAnalysis(BaseModel):
    """Prepared deterministic analysis input for one review snapshot."""

    files: list[PreparedFileDiff] = Field(default_factory=list)

    @property
    def binary_files(self) -> list[str]:
        return [file.path for file in self.files if file.is_binary]

    @property
    def text_files(self) -> list[PreparedFileDiff]:
        return [file for file in self.files if not file.is_binary]


def prepare_diff_analysis(snapshot: ReviewSnapshot) -> PreparedDiffAnalysis:
    """Parse one immutable review diff into file-level sections."""

    return PreparedDiffAnalysis(files=_parse_file_diffs(snapshot.diff_text))


def get_file_diff(snapshot: ReviewSnapshot, file_path: str) -> PreparedFileDiff | None:
    """Return one prepared file diff for the requested changed path."""

    analysis = prepare_diff_analysis(snapshot)
    for file_diff in analysis.files:
        if file_diff.path == file_path:
            return file_diff
    return None


def extract_added_lines(diff_text: str) -> list[AddedDiffLine]:
    """Extract added lines from one file diff payload."""

    files = _parse_file_diffs(diff_text)
    if not files:
        return []
    return files[0].added_lines


def _parse_file_diffs(diff_text: str) -> list[PreparedFileDiff]:
    """Parse raw unified diff text into file-level sections."""

    files: list[PreparedFileDiff] = []
    current_path: str | None = None
    current_lines: list[str] = []
    current_is_binary = False
    current_added_lines: list[AddedDiffLine] = []
    new_line_number: int | None = None

    def finalize_current_file() -> None:
        nonlocal current_path, current_lines, current_is_binary, current_added_lines
        if current_path is None:
            return
        files.append(
            PreparedFileDiff(
                path=current_path,
                diff_text="\n".join(current_lines) + "\n",
                is_binary=current_is_binary,
                added_lines=list(current_added_lines),
            )
        )
        current_path = None
        current_lines = []
        current_is_binary = False
        current_added_lines = []

    for line in diff_text.splitlines():
        diff_header = _DIFF_HEADER_PATTERN.match(line)
        if diff_header is not None:
            finalize_current_file()
            current_path = _display_path(diff_header.group(1), diff_header.group(2))
            current_lines = [line]
            current_is_binary = False
            current_added_lines = []
            new_line_number = None
            continue

        if current_path is None:
            continue

        current_lines.append(line)
        if line.startswith("Binary files ") or line == "GIT binary patch":
            current_is_binary = True
            continue

        hunk_header = _HUNK_HEADER_PATTERN.match(line)
        if hunk_header is not None:
            new_line_number = int(hunk_header.group("new_start")) - 1
            continue

        if new_line_number is None or line.startswith("\\"):
            continue

        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            new_line_number += 1
            current_added_lines.append(
                AddedDiffLine(
                    line_number=new_line_number,
                    content=line[1:],
                )
            )
            continue
        if line.startswith(" "):
            new_line_number += 1

    finalize_current_file()
    return files


def _display_path(old_path: str, new_path: str) -> str:
    if new_path == "/dev/null":
        return old_path
    return new_path
