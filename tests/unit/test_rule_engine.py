"""Unit tests for deterministic M5 rule evaluation."""

from __future__ import annotations

from codereviewer.domain.enums import ProviderKind, ReviewSourceKind
from codereviewer.domain.models import ReviewSnapshot
from codereviewer.services.rule_engine import build_builtin_rule_engine
from codereviewer.services.tool_engine import ToolEngine
from codereviewer.tools.builtin import build_builtin_tool_registry


def test_rule_engine_emits_findings_with_evidence():
    snapshot = ReviewSnapshot(
        review_id="review-rules123",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/1",
        change_number=1,
        input_hash="c" * 64,
        base_ref="main",
        head_ref="feature/test",
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

    findings = build_builtin_rule_engine().evaluate(
        snapshot=snapshot,
        tool_executor=ToolEngine(build_builtin_tool_registry()),
    )

    assert len(findings) == 2
    assert all(finding.evidence for finding in findings)
    assert {finding.file for finding in findings} == {"src/example.py", ".env"}


def test_rule_engine_returns_no_findings_when_rules_do_not_match():
    snapshot = ReviewSnapshot(
        review_id="review-rules456",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/2",
        change_number=2,
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
            "+return value\n"
        ),
    )

    findings = build_builtin_rule_engine().evaluate(
        snapshot=snapshot,
        tool_executor=ToolEngine(build_builtin_tool_registry()),
    )

    assert findings == []


def test_rule_engine_covers_five_built_in_rules():
    snapshot = ReviewSnapshot(
        review_id="review-rules789",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/3",
        change_number=3,
        input_hash="e" * 64,
        base_ref="main",
        head_ref="feature/test",
        base_sha="base123",
        head_sha="head456",
        changed_files=[
            ".env",
            "web/app.js",
            "web/debug.js",
            "scripts/debug.py",
            "src/secrets.txt",
        ],
        diff_text=(
            "diff --git a/.env b/.env\n"
            "@@ -0,0 +1 @@\n"
            "+API_KEY=test\n"
            "diff --git a/web/app.js b/web/app.js\n"
            "@@ -1,0 +1 @@\n"
            "+console.log(value)\n"
            "diff --git a/web/debug.js b/web/debug.js\n"
            "@@ -1,0 +1 @@\n"
            "+debugger;\n"
            "diff --git a/scripts/debug.py b/scripts/debug.py\n"
            "@@ -1,0 +1 @@\n"
            "+pdb.set_trace()\n"
            "diff --git a/src/secrets.txt b/src/secrets.txt\n"
            "@@ -1,0 +1 @@\n"
            "+token=github_pat_1234567890abcdefghijklmnopqrstuvwxyz\n"
        ),
    )

    findings = build_builtin_rule_engine().evaluate(
        snapshot=snapshot,
        tool_executor=ToolEngine(build_builtin_tool_registry()),
    )

    assert len(findings) == 5
    assert {
        finding.summary for finding in findings
    } == {
        "Sensitive-looking file appears in the change set.",
        "Debug statement added in the changed code.",
        "Token-like secret value added in the changed code.",
    }


def test_rule_engine_does_not_flag_python_print_calls_as_debug_statements():
    snapshot = ReviewSnapshot(
        review_id="review-rulesprint123",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/4",
        change_number=4,
        input_hash="f" * 64,
        base_ref="main",
        head_ref="feature/test",
        base_sha="base123",
        head_sha="head456",
        changed_files=["src/cli.py"],
        diff_text=(
            "diff --git a/src/cli.py b/src/cli.py\n"
            "@@ -1,0 +1 @@\n"
            "+print('ok')\n"
        ),
    )

    findings = build_builtin_rule_engine().evaluate(
        snapshot=snapshot,
        tool_executor=ToolEngine(build_builtin_tool_registry()),
    )

    assert findings == []
