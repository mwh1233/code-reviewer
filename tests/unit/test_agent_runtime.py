"""Unit tests for the single-agent tool-use runtime."""

from __future__ import annotations

from codereviewer.domain.enums import ProviderKind, ReviewSourceKind
from codereviewer.domain.models import (
    BudgetSnapshot,
    ReviewSnapshot,
    ToolCall,
    ToolChatRequest,
    ToolChatResponse,
)
from codereviewer.services.agent_runtime import AgentRuntime, AgentRuntimeConfig
from codereviewer.services.budget_manager import BudgetManager
from codereviewer.services.trace_manager import TraceManager
from codereviewer.adapters.storage.file_store import FileTraceStore
from codereviewer.config import build_app_config
from codereviewer.tools.builtin import build_builtin_tool_registry


class _StubSCMProvider:
    def get_file_content(self, repo: str, path: str, ref: str) -> str:
        return "def demo():\n    console.log(value)\n"


class _ScriptedLLMProvider:
    def __init__(self, scripted_responses: list[ToolChatResponse], *, estimated_tokens: int = 100) -> None:
        self._scripted_responses = scripted_responses
        self._estimated_tokens = estimated_tokens
        self.requests: list[ToolChatRequest] = []
        self.budget_modes: list[str] = []

    def estimate_prompt_tokens(self, text: str, *, budget_mode: str = "normal") -> int:
        return self._estimated_tokens

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        budget_mode: str = "normal",
    ) -> float:
        return 0.02

    def review(
        self,
        prompt: str,
        *,
        budget_mode: str = "normal",
    ):  # pragma: no cover - compatibility stub only
        raise AssertionError("review() should not be used by AgentRuntime tests.")

    def chat_with_tools(
        self,
        request: ToolChatRequest,
        *,
        budget_mode: str = "normal",
    ) -> ToolChatResponse:
        self.requests.append(request)
        self.budget_modes.append(budget_mode)
        return self._scripted_responses.pop(0)


def _build_snapshot() -> ReviewSnapshot:
    return ReviewSnapshot(
        review_id="review-agent123",
        provider=ProviderKind.GITHUB,
        source_kind=ReviewSourceKind.REVIEW_URL,
        repo="owner/repo",
        review_url="https://github.com/owner/repo/pull/1",
        change_number=1,
        input_hash="a" * 64,
        base_ref="main",
        head_ref="feature/test",
        base_sha="base123",
        head_sha="head456",
        changed_files=["src/example.py"],
        diff_text=(
            "diff --git a/src/example.py b/src/example.py\n"
            "@@ -1,1 +1,2 @@\n"
            " old_line\n"
            "+console.log(value)\n"
        ),
    )


def test_agent_runtime_uses_analysis_tools_before_submitting_comment(tmp_path):
    provider = _ScriptedLLMProvider(
        [
            ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-read-file",
                        name="read_file",
                        arguments='{"file_path":"src/example.py"}',
                    )
                ],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="tool_calls",
            ),
            ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-comment",
                        name="code_comment",
                        arguments=(
                            '{"file":"src/example.py","line":2,"summary":"Debug statement should be removed",'
                            '"severity":"medium","category":"bug",'
                            '"explanation":"The added console.log call looks like leftover debug logic.",'
                            '"suggested_fix":"Remove the statement."}'
                        ),
                    )
                ],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="tool_calls",
            ),
            ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-done",
                        name="task_done",
                        arguments='{"reason":"review complete"}',
                    )
                ],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="tool_calls",
            ),
        ]
    )
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    trace_manager = TraceManager(FileTraceStore(config.artifact_root))
    runtime = AgentRuntime(
        llm_provider=provider,
        tool_registry=build_builtin_tool_registry(),
        trace_manager=trace_manager,
        budget_manager=BudgetManager(BudgetSnapshot(token_limit=1000, cost_limit=1.0)),
    )
    trace = trace_manager.create("review-agent123")

    result = runtime.run(
        snapshot=_build_snapshot(),
        existing_findings=[],
        trace=trace,
        review_id="review-agent123",
        provider=_StubSCMProvider(),
    )

    assert result.stop_reason == "task_done"
    assert result.comments_submitted == 1
    assert result.tool_calls_total == 3
    assert len(result.findings) == 1
    assert result.findings[0].summary == "Debug statement should be removed"
    assert result.findings[0].category == "bug"
    assert result.findings[0].evidence[0].source_id == "call-comment"
    assert provider.requests[0].tools[0]["name"] == "code_comment"
    assert "category" in provider.requests[0].tools[0]["parameters"]["required"]
    assert any(tool["name"] == "read_file" for tool in provider.requests[0].tools)


def test_agent_runtime_enters_grace_round_with_control_tools_only(tmp_path):
    provider = _ScriptedLLMProvider(
        [
            ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-comment",
                        name="code_comment",
                        arguments=(
                            '{"file":"src/example.py","line":2,"summary":"One more issue",'
                            '"severity":"low","category":"maintainability",'
                            '"explanation":"First pass found an issue.",'
                            '"suggested_fix":"Apply the follow-up fix."}'
                        ),
                    )
                ],
                input_tokens=100,
                output_tokens=60,
                estimated_cost=0.02,
                finish_reason="tool_calls",
            ),
            ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-done",
                        name="task_done",
                        arguments='{"reason":"budget exhausted"}',
                    )
                ],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="tool_calls",
            ),
        ]
    )
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    trace_manager = TraceManager(FileTraceStore(config.artifact_root))
    trace = trace_manager.create("review-agent-grace123")
    runtime = AgentRuntime(
        llm_provider=provider,
        tool_registry=build_builtin_tool_registry(),
        trace_manager=trace_manager,
        budget_manager=BudgetManager(BudgetSnapshot(token_limit=150, cost_limit=1.0)),
    )

    result = runtime.run(
        snapshot=_build_snapshot(),
        existing_findings=[],
        trace=trace,
        review_id="review-agent-grace123",
        provider=_StubSCMProvider(),
    )

    assert result.stop_reason == "task_done"
    assert result.comments_submitted == 1
    assert len(provider.requests) == 2
    assert [tool["name"] for tool in provider.requests[1].tools] == [
        "code_comment",
        "task_done",
    ]


def test_agent_runtime_switches_to_lower_budget_mode_after_threshold(tmp_path):
    provider = _ScriptedLLMProvider(
        [
            ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-read-file",
                        name="read_file",
                        arguments='{"file_path":"src/example.py"}',
                    )
                ],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="tool_calls",
            ),
            ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-done",
                        name="task_done",
                        arguments='{"reason":"review complete"}',
                    )
                ],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="tool_calls",
            ),
        ]
    )
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    trace_manager = TraceManager(FileTraceStore(config.artifact_root))
    trace = trace_manager.create("review-agent-budgetmode123")
    runtime = AgentRuntime(
        llm_provider=provider,
        tool_registry=build_builtin_tool_registry(),
        trace_manager=trace_manager,
        budget_manager=BudgetManager(BudgetSnapshot(token_limit=300, cost_limit=1.0)),
    )

    result = runtime.run(
        snapshot=_build_snapshot(),
        existing_findings=[],
        trace=trace,
        review_id="review-agent-budgetmode123",
        provider=_StubSCMProvider(),
    )

    assert result.stop_reason == "task_done"
    assert provider.budget_modes == ["normal", "degraded"]


def test_agent_runtime_stops_after_consecutive_empty_rounds(tmp_path):
    provider = _ScriptedLLMProvider(
        [
            ToolChatResponse(
                content="No issues yet.",
                tool_calls=[],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="stop",
            ),
            ToolChatResponse(
                content="Still nothing to report.",
                tool_calls=[],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="stop",
            ),
            ToolChatResponse(
                content="No additional findings.",
                tool_calls=[],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="stop",
            ),
        ]
    )
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    trace_manager = TraceManager(FileTraceStore(config.artifact_root))
    trace = trace_manager.create("review-agent-empty123")
    runtime = AgentRuntime(
        llm_provider=provider,
        tool_registry=build_builtin_tool_registry(),
        trace_manager=trace_manager,
        budget_manager=BudgetManager(BudgetSnapshot(token_limit=1000, cost_limit=1.0)),
    )

    result = runtime.run(
        snapshot=_build_snapshot(),
        existing_findings=[],
        trace=trace,
        review_id="review-agent-empty123",
        provider=_StubSCMProvider(),
    )

    assert result.stop_reason == "empty_rounds"
    assert result.comments_submitted == 0
    assert result.tool_calls_total == 0
    assert result.findings == []
    assert len(provider.requests) == 3


def test_agent_runtime_injects_previous_round_findings_into_second_round(tmp_path):
    provider = _ScriptedLLMProvider(
        [
            ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-comment-round1",
                        name="code_comment",
                        arguments=(
                            '{"file":"src/example.py","line":2,"summary":"Debug statement should be removed",'
                            '"severity":"medium","category":"bug",'
                            '"explanation":"The added console.log call looks like leftover debug logic.",'
                            '"suggested_fix":"Remove the statement."}'
                        ),
                    )
                ],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="tool_calls",
            ),
            ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-done-round2",
                        name="task_done",
                        arguments='{"reason":"review complete"}',
                    )
                ],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="tool_calls",
            ),
        ]
    )
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    trace_manager = TraceManager(FileTraceStore(config.artifact_root))
    trace = trace_manager.create("review-agent-rounds123")
    runtime = AgentRuntime(
        llm_provider=provider,
        tool_registry=build_builtin_tool_registry(),
        trace_manager=trace_manager,
        budget_manager=BudgetManager(BudgetSnapshot(token_limit=1000, cost_limit=1.0)),
        config=AgentRuntimeConfig(max_rounds=2, max_tool_rounds=1),
    )

    result = runtime.run(
        snapshot=_build_snapshot(),
        existing_findings=[],
        trace=trace,
        review_id="review-agent-rounds123",
        provider=_StubSCMProvider(),
    )

    assert result.stop_reason == "task_done"
    assert result.rounds_executed == 2
    assert len(provider.requests) == 2
    second_round_user_message = next(
        message.content
        for message in provider.requests[1].messages
        if message.role == "user"
    )
    assert second_round_user_message is not None
    assert "变更摘要" in second_round_user_message
    assert "规则引擎已发现问题" not in second_round_user_message
    assert "Diff 内容" in second_round_user_message
    assert "审查指令" in second_round_user_message
    assert "上一轮已确认问题" in second_round_user_message
    assert "[src/example.py:2] Debug statement should be removed" in second_round_user_message


def test_agent_runtime_builds_detailed_system_prompt_and_rule_engine_context(tmp_path):
    provider = _ScriptedLLMProvider(
        [
            ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-done",
                        name="task_done",
                        arguments='{"reason":"nothing else to report"}',
                    )
                ],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="tool_calls",
            ),
        ]
    )
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    trace_manager = TraceManager(FileTraceStore(config.artifact_root))
    trace = trace_manager.create("review-agent-prompt123")
    runtime = AgentRuntime(
        llm_provider=provider,
        tool_registry=build_builtin_tool_registry(),
        trace_manager=trace_manager,
        budget_manager=BudgetManager(BudgetSnapshot(token_limit=1000, cost_limit=1.0)),
    )

    result = runtime.run(
        snapshot=_build_snapshot(),
        existing_findings=[],
        trace=trace,
        review_id="review-agent-prompt123",
        provider=_StubSCMProvider(),
    )

    assert result.stop_reason == "task_done"
    system_message = provider.requests[0].messages[0].content
    user_message = provider.requests[0].messages[1].content
    assert system_message is not None
    assert "审查原则" in system_message
    assert "严重程度定义" in system_message
    assert "问题分类" in system_message
    assert "工具使用指南" in system_message
    assert "输出约束" in system_message
    assert "禁止事项" in system_message
    assert "优先使用中文表述" in system_message
    assert user_message is not None
    assert "变更摘要" in user_message
    assert "变更文件数：1" in user_message
    assert "新增行数：1" in user_message
    assert "删除行数：0" in user_message
    assert "- src/example.py（修改）：+1 / -0" in user_message
    assert "Diff 内容" in user_message
    assert "审查指令" in user_message
    assert "优先使用中文表述" in user_message


def test_agent_runtime_rejects_code_comment_for_unchanged_file(tmp_path):
    provider = _ScriptedLLMProvider(
        [
            ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-invalid-comment",
                        name="code_comment",
                        arguments=(
                            '{"file":"src/other.py","line":2,"summary":"Wrong file",'
                            '"severity":"medium","category":"bug",'
                            '"explanation":"This file is not part of the change.",'
                            '"suggested_fix":"Review the actual changed file."}'
                        ),
                    )
                ],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="tool_calls",
            ),
            ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-done",
                        name="task_done",
                        arguments='{"reason":"invalid comment rejected"}',
                    )
                ],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="tool_calls",
            ),
        ]
    )
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    trace_manager = TraceManager(FileTraceStore(config.artifact_root))
    runtime = AgentRuntime(
        llm_provider=provider,
        tool_registry=build_builtin_tool_registry(),
        trace_manager=trace_manager,
        budget_manager=BudgetManager(BudgetSnapshot(token_limit=1000, cost_limit=1.0)),
    )
    trace = trace_manager.create("review-agent-invalidfile123")

    result = runtime.run(
        snapshot=_build_snapshot(),
        existing_findings=[],
        trace=trace,
        review_id="review-agent-invalidfile123",
        provider=_StubSCMProvider(),
    )

    assert result.stop_reason == "task_done"
    assert result.comments_submitted == 0
    tool_messages = [
        message.content
        for message in provider.requests[1].messages
        if message.role == "tool"
    ]
    assert tool_messages
    assert "is not in the changed files list" in tool_messages[0]


def test_agent_runtime_limits_grace_round_to_one_finalization_call(tmp_path):
    provider = _ScriptedLLMProvider(
        [
            ToolChatResponse(
                tool_calls=[
                    ToolCall(
                        id="call-comment",
                        name="code_comment",
                        arguments=(
                            '{"file":"src/example.py","line":2,"summary":"Budget edge",'
                            '"severity":"low","category":"other",'
                            '"explanation":"First pass found one issue.",'
                            '"suggested_fix":"Handle it before merge."}'
                        ),
                    )
                ],
                input_tokens=100,
                output_tokens=60,
                estimated_cost=0.02,
                finish_reason="tool_calls",
            ),
            ToolChatResponse(
                content="No final action.",
                tool_calls=[],
                input_tokens=100,
                output_tokens=20,
                estimated_cost=0.02,
                finish_reason="stop",
            ),
        ]
    )
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    trace_manager = TraceManager(FileTraceStore(config.artifact_root))
    trace = trace_manager.create("review-agent-gracelimit123")
    runtime = AgentRuntime(
        llm_provider=provider,
        tool_registry=build_builtin_tool_registry(),
        trace_manager=trace_manager,
        budget_manager=BudgetManager(BudgetSnapshot(token_limit=150, cost_limit=1.0)),
    )

    result = runtime.run(
        snapshot=_build_snapshot(),
        existing_findings=[],
        trace=trace,
        review_id="review-agent-gracelimit123",
        provider=_StubSCMProvider(),
    )

    assert result.stop_reason == "budget_exhausted"
    assert len(provider.requests) == 2
    assert [tool["name"] for tool in provider.requests[1].tools] == [
        "code_comment",
        "task_done",
    ]


def test_agent_runtime_enters_grace_round_after_empty_truncated_response(tmp_path):
    provider = _ScriptedLLMProvider(
        [
            ToolChatResponse(
                content="",
                tool_calls=[],
                input_tokens=100,
                output_tokens=1024,
                estimated_cost=0.02,
                finish_reason="length",
            ),
            ToolChatResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-grace-1",
                        name="task_done",
                        arguments='{"reason":"no findings"}',
                    )
                ],
                input_tokens=50,
                output_tokens=20,
                estimated_cost=0.001,
                finish_reason="stop",
            ),
        ]
    )
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    trace_manager = TraceManager(FileTraceStore(config.artifact_root))
    trace = trace_manager.create("review-agent-truncated123")
    runtime = AgentRuntime(
        llm_provider=provider,
        tool_registry=build_builtin_tool_registry(),
        trace_manager=trace_manager,
        budget_manager=BudgetManager(BudgetSnapshot(token_limit=2000, cost_limit=1.0)),
    )

    result = runtime.run(
        snapshot=_build_snapshot(),
        existing_findings=[],
        trace=trace,
        review_id="review-agent-truncated123",
        provider=_StubSCMProvider(),
    )

    assert result.stop_reason == "task_done"
    assert result.comments_submitted == 0
    assert len(provider.requests) == 2
    assert [tool["name"] for tool in provider.requests[1].tools] == [
        "code_comment",
        "task_done",
    ]


def test_agent_runtime_stops_on_truncation_when_grace_round_disabled(tmp_path):
    provider = _ScriptedLLMProvider(
        [
            ToolChatResponse(
                content="",
                tool_calls=[],
                input_tokens=100,
                output_tokens=1024,
                estimated_cost=0.02,
                finish_reason="length",
            ),
        ]
    )
    config = build_app_config(artifact_root=tmp_path / "artifacts")
    trace_manager = TraceManager(FileTraceStore(config.artifact_root))
    trace = trace_manager.create("review-agent-truncated-disabled")
    runtime = AgentRuntime(
        llm_provider=provider,
        tool_registry=build_builtin_tool_registry(),
        trace_manager=trace_manager,
        budget_manager=BudgetManager(BudgetSnapshot(token_limit=2000, cost_limit=1.0)),
        config=AgentRuntimeConfig(grace_round_enabled=False),
    )

    result = runtime.run(
        snapshot=_build_snapshot(),
        existing_findings=[],
        trace=trace,
        review_id="review-agent-truncated-disabled",
        provider=_StubSCMProvider(),
    )

    assert result.stop_reason == "response_truncated"
    assert result.comments_submitted == 0
    assert len(provider.requests) == 1
