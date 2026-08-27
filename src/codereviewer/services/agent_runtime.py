"""Single-agent multi-round tool-use runtime for stage 5 review generation."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field

from codereviewer.domain.enums import Confidence, FindingSource, ReviewStage, Severity
from codereviewer.domain.errors import ToolExecutionError
from codereviewer.domain.interfaces.llm import LLMProvider
from codereviewer.domain.models import (
    BudgetSnapshot,
    EvidenceRef,
    Finding,
    ReviewSnapshot,
    ReviewTrace,
    ToolChatMessage,
    ToolChatRequest,
    ToolChatResponse,
    ToolExecutionContext,
)
from codereviewer.services.budget_manager import BudgetManager
from codereviewer.services.diff_preprocessor import prepare_diff_analysis
from codereviewer.services.security import build_llm_diff_excerpt
from codereviewer.services.trace_manager import TraceManager
from codereviewer.tools.registry import ToolRegistry


class AgentRuntimeConfig(BaseModel):
    """Runtime limits for the stage 5 tool-use loop."""

    max_rounds: int = 2
    max_tool_rounds: int = 15
    max_empty_rounds: int = 3
    grace_round_enabled: bool = True
    max_tool_calls_per_round: int = 3
    max_tool_output_chars: int = 3000


class AgentRuntimeResult(BaseModel):
    """Structured result returned by the agent runtime."""

    findings: list[Finding] = Field(default_factory=list)
    rounds_executed: int = 0
    tool_calls_total: int = 0
    comments_submitted: int = 0
    stop_reason: str = "completed"
    budget_snapshot: BudgetSnapshot


class AgentRuntime:
    """Drive a single-agent multi-round tool-use code review session."""

    _CONTROL_TOOL_NAMES = ("code_comment", "task_done")
    _CATEGORY_VALUES = (
        "bug",
        "security",
        "performance",
        "maintainability",
        "test",
        "style",
        "documentation",
        "other",
    )

    def __init__(
        self,
        *,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        trace_manager: TraceManager,
        budget_manager: BudgetManager,
        config: AgentRuntimeConfig | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._tool_registry = tool_registry
        self._trace_manager = trace_manager
        self._budget_manager = budget_manager
        self._config = config or AgentRuntimeConfig()

    def run(
        self,
        *,
        snapshot: ReviewSnapshot,
        existing_findings: list[Finding],
        trace: ReviewTrace,
        review_id: str,
        provider=None,
    ) -> AgentRuntimeResult:
        """Execute the full tool-use loop and return newly collected findings."""

        collected_findings: list[Finding] = []
        rounds_executed = 0
        tool_calls_total = 0
        comments_submitted = 0
        stop_reason = "max_rounds"

        for round_index in range(1, self._config.max_rounds + 1):
            rounds_executed = round_index
            round_findings: list[Finding] = []
            empty_rounds = 0
            in_grace_round = False
            grace_round_remaining = 0
            messages = self._build_round_messages(
                snapshot=snapshot,
                existing_findings=existing_findings,
                collected_findings=collected_findings,
                round_index=round_index,
            )
            self._trace_manager.append_event(
                review_id=review_id,
                trace=trace,
                stage=ReviewStage.FINDINGS_GENERATED,
                message=f"Agent runtime round {round_index} started.",
                details={
                    "round": round_index,
                    "existing_findings": len(existing_findings),
                    "collected_findings": len(collected_findings),
                },
            )

            for tool_round in range(1, self._config.max_tool_rounds + 1):
                tool_schemas = self._available_tools(include_analysis=not in_grace_round)
                budget_mode = self._budget_manager.snapshot.degrade_level
                if budget_mode == "stopped":
                    budget_mode = "essential_only"
                if not in_grace_round:
                    estimated_input_tokens = self._estimate_chat_tokens(messages, tool_schemas)
                    estimated_cost = self._llm_provider.estimate_cost(
                        estimated_input_tokens,
                        800,
                        budget_mode=budget_mode,
                    )
                    decision = self._budget_manager.plan_llm_call(
                        estimated_input_tokens=estimated_input_tokens,
                        estimated_cost=estimated_cost,
                    )
                    budget_mode = decision.degrade_level
                    selection = self._describe_llm_selection(budget_mode)
                    self._trace_manager.append_event(
                        review_id=review_id,
                        trace=trace,
                        stage=ReviewStage.FINDINGS_GENERATED,
                        message=(
                            "Agent runtime budget decision: "
                            f"level={decision.degrade_level}, "
                            f"projected_ratio={decision.projected_ratio:.3f}, "
                            f"reason={decision.reason}, "
                            f"llm_tier={selection['tier']}, "
                            f"llm_model={selection['model'] or 'unknown'}"
                        ),
                        details={
                            "round": round_index,
                            "tool_round": tool_round,
                            "degrade_level": decision.degrade_level,
                            "projected_ratio": decision.projected_ratio,
                            "in_grace_round": in_grace_round,
                            "llm_budget_mode": budget_mode,
                            "llm_model_tier": selection["tier"],
                            "llm_model": selection["model"],
                        },
                    )

                    if not decision.should_call_llm:
                        if (
                            self._config.grace_round_enabled
                            and not in_grace_round
                        ):
                            in_grace_round = True
                            grace_round_remaining = 1
                            messages.append(
                                ToolChatMessage(
                                    role="system",
                                    content=(
                                        "预算即将耗尽。不要再调用分析工具。"
                                        "请提交你已经确认的剩余 code_comment 结果，"
                                        "然后调用 task_done 结束审查。"
                                        "如果你还没有发现问题，请直接调用 task_done。"
                                    ),
                                )
                            )
                            self._trace_manager.append_event(
                                review_id=review_id,
                                trace=trace,
                                stage=ReviewStage.FINDINGS_GENERATED,
                                message="Agent runtime entered grace round.",
                                details={
                                    "round": round_index,
                                    "tool_round": tool_round,
                                    "comments_pending": len(round_findings),
                                    "trigger": "budget_exhausted",
                                },
                            )
                            continue
                        stop_reason = "budget_exhausted"
                        break
                else:
                    budget_mode = "essential_only"
                    selection = self._describe_llm_selection(budget_mode)
                    self._trace_manager.append_event(
                        review_id=review_id,
                        trace=trace,
                        stage=ReviewStage.FINDINGS_GENERATED,
                        message="Agent runtime executing grace-round finalization call.",
                        details={
                            "round": round_index,
                            "tool_round": tool_round,
                            "control_tools_only": True,
                            "llm_budget_mode": budget_mode,
                            "llm_model_tier": selection["tier"],
                            "llm_model": selection["model"],
                        },
                    )

                request = ToolChatRequest(
                    messages=messages,
                    tools=tool_schemas,
                    tool_choice="auto",
                    max_tokens=1024,
                    temperature=0.0,
                )
                self._trace_manager.write_artifact(
                    review_id=review_id,
                    trace=trace,
                    artifact_type="llm_prompt",
                    content=json.dumps(
                        request.model_dump(mode="json"),
                        ensure_ascii=True,
                        indent=2,
                    ),
                )
                response = self._llm_provider.chat_with_tools(
                    request,
                    budget_mode=budget_mode,
                )
                self._trace_manager.write_artifact(
                    review_id=review_id,
                    trace=trace,
                    artifact_type="llm_response",
                    content=json.dumps(
                        response.model_dump(mode="json"),
                        ensure_ascii=True,
                        indent=2,
                    ),
                )
                self._budget_manager.record_usage(
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    cost=response.estimated_cost,
                )
                has_visible_content = self._has_visible_content(response.content)
                if has_visible_content or response.tool_calls:
                    messages.append(
                        ToolChatMessage(
                            role="assistant",
                            content=response.content,
                            tool_calls=response.tool_calls,
                        )
                    )
                self._trace_manager.append_event(
                    review_id=review_id,
                    trace=trace,
                    stage=ReviewStage.FINDINGS_GENERATED,
                    message="Agent runtime received tool chat response.",
                    details={
                        "round": round_index,
                        "tool_round": tool_round,
                        "finish_reason": response.finish_reason,
                        "tool_call_count": len(response.tool_calls),
                        "budget_level": self._budget_manager.snapshot.degrade_level,
                        "llm_budget_mode": budget_mode,
                        "llm_model_tier": selection["tier"],
                        "llm_model": selection["model"],
                    },
                )

                if (
                    response.finish_reason == "length"
                    and not response.tool_calls
                    and not has_visible_content
                ):
                    self._trace_manager.append_event(
                        review_id=review_id,
                        trace=trace,
                        stage=ReviewStage.FINDINGS_GENERATED,
                        message=(
                            "Agent runtime detected an empty truncated LLM response."
                        ),
                        details={
                            "round": round_index,
                            "tool_round": tool_round,
                            "finish_reason": response.finish_reason,
                            "in_grace_round": in_grace_round,
                        },
                    )
                    if (
                        self._config.grace_round_enabled
                        and not in_grace_round
                    ):
                        in_grace_round = True
                        grace_round_remaining = 1
                        messages.append(
                            ToolChatMessage(
                                role="system",
                                content=(
                                    "上一轮 LLM 输出因上下文过长被截断，"
                                    "无法继续分析。这是你的最后一轮机会："
                                    "请立即提交你已经发现的问题(code_comment)，"
                                    "或调用 task_done 结束审查。"
                                    "不要再调用任何分析工具。"
                                ),
                            )
                        )
                        self._trace_manager.append_event(
                            review_id=review_id,
                            trace=trace,
                            stage=ReviewStage.FINDINGS_GENERATED,
                            message=(
                                "Agent runtime entered grace round after "
                                "response truncation."
                            ),
                            details={
                                "round": round_index,
                                "tool_round": tool_round,
                                "comments_pending": len(round_findings),
                                "trigger": "response_truncated",
                            },
                        )
                        continue
                    stop_reason = "response_truncated"
                    break

                if not response.tool_calls:
                    if in_grace_round:
                        stop_reason = "budget_exhausted"
                        break
                    empty_rounds += 1
                    if empty_rounds >= self._config.max_empty_rounds:
                        stop_reason = "empty_rounds"
                        break
                    continue

                empty_rounds = 0
                task_done_called = False
                analysis_tool_calls_in_round = 0
                max_analysis_tools = self._config.max_tool_calls_per_round
                for tool_call in response.tool_calls:
                    tool_calls_total += 1
                    is_control_tool = tool_call.name in self._CONTROL_TOOL_NAMES
                    if not is_control_tool:
                        analysis_tool_calls_in_round += 1
                    if (
                        not is_control_tool
                        and analysis_tool_calls_in_round > max_analysis_tools
                    ):
                        result_message = json.dumps(
                            {
                                "tool_name": tool_call.name,
                                "error": (
                                    f"本轮分析工具调用已达上限({max_analysis_tools})，"
                                    "本调用未执行。请先提交已发现的问题(code_comment) "
                                    "或结束审查(task_done)，下一轮可继续分析。"
                                ),
                                "skipped": True,
                            },
                            ensure_ascii=True,
                        )
                        self._trace_manager.append_event(
                            review_id=review_id,
                            trace=trace,
                            stage=ReviewStage.FINDINGS_GENERATED,
                            message=(
                                f"Agent runtime skipped tool {tool_call.name} "
                                f"(round limit {max_analysis_tools})."
                            ),
                            details={
                                "round": round_index,
                                "tool_round": tool_round,
                                "tool_call_id": tool_call.id,
                                "tool_name": tool_call.name,
                                "analysis_tool_count": analysis_tool_calls_in_round,
                            },
                        )
                    elif tool_call.name == "code_comment":
                        result_message, finding = self._handle_code_comment(
                            tool_call_id=tool_call.id,
                            arguments=tool_call.arguments,
                            snapshot=snapshot,
                        )
                        if finding is not None:
                            round_findings.append(finding)
                            collected_findings.append(finding)
                            comments_submitted += 1
                            self._trace_manager.append_event(
                                review_id=review_id,
                                trace=trace,
                                stage=ReviewStage.FINDINGS_GENERATED,
                                message="Agent runtime submitted candidate finding.",
                                details={
                                    "round": round_index,
                                    "tool_round": tool_round,
                                    "tool_call_id": tool_call.id,
                                    "file": finding.file,
                                    "line": finding.line,
                                    "summary": finding.summary,
                                    "severity": finding.severity.value,
                                },
                            )
                    elif tool_call.name == "task_done":
                        result_message = self._handle_task_done(tool_call.arguments)
                        task_done_called = True
                    else:
                        result_message = self._handle_analysis_tool(
                            tool_name=tool_call.name,
                            arguments=tool_call.arguments,
                            snapshot=snapshot,
                            provider=provider,
                            review_id=review_id,
                            trace=trace,
                            round_index=round_index,
                            tool_round=tool_round,
                            tool_call_id=tool_call.id,
                        )

                    messages.append(
                        ToolChatMessage(
                            role="tool",
                            tool_call_id=tool_call.id,
                            content=result_message,
                        )
                    )

                if task_done_called:
                    stop_reason = "task_done"
                    break
                if in_grace_round:
                    grace_round_remaining -= 1
                    if grace_round_remaining <= 0:
                        stop_reason = "budget_exhausted"
                        break

            self._trace_manager.append_event(
                review_id=review_id,
                trace=trace,
                stage=ReviewStage.FINDINGS_GENERATED,
                message=f"Agent runtime round {round_index} completed.",
                details={
                    "round": round_index,
                    "new_findings": len(round_findings),
                    "tool_calls_total": tool_calls_total,
                    "stop_reason": stop_reason,
                },
            )
            if stop_reason in {
                "task_done",
                "budget_exhausted",
                "empty_rounds",
                "response_truncated",
            }:
                break
            if not round_findings:
                stop_reason = "no_new_findings"
                break

        return AgentRuntimeResult(
            findings=collected_findings,
            rounds_executed=rounds_executed,
            tool_calls_total=tool_calls_total,
            comments_submitted=comments_submitted,
            stop_reason=stop_reason,
            budget_snapshot=self._budget_manager.snapshot,
        )

    def _build_round_messages(
        self,
        *,
        snapshot: ReviewSnapshot,
        existing_findings: list[Finding],
        collected_findings: list[Finding],
        round_index: int,
    ) -> list[ToolChatMessage]:
        diff_excerpt = build_llm_diff_excerpt(snapshot, max_chars=12000)
        diff_summary = self._build_diff_summary(snapshot)
        rule_engine_findings = self._summarize_findings(
            [finding for finding in existing_findings if self._is_llm_visible_finding(finding)]
        )
        prior_round_findings = self._summarize_findings(
            [finding for finding in collected_findings if self._is_llm_visible_finding(finding)]
        )
        user_sections = [
            "请使用可用工具审查本次变更代码。",
            "",
            "变更摘要",
            diff_summary,
        ]
        if rule_engine_findings:
            user_sections.extend(
                [
                    "",
                    "规则引擎已发现问题",
                    "确定性检查已经发现以下问题，请不要重复提交：",
                    rule_engine_findings,
                ]
            )
        if round_index > 1 and prior_round_findings:
            user_sections.extend(
                [
                    "",
                    "上一轮已确认问题",
                    "请不要重复这些问题，优先继续挖掘新的问题：",
                    prior_round_findings,
                ]
            )
        user_sections.extend(
            [
                "",
                "Diff 内容",
                diff_excerpt,
                "",
                "审查指令",
                "请使用可用工具检查变更代码。",
                "你提交的评论必须严格基于你实际读过的代码内容。",
                "所有 review 评论、summary、explanation、suggested_fix 优先使用中文表述。",
                "当你没有更多问题需要报告时，请调用 task_done。",
            ]
        )
        user_content = "\n".join(user_sections)
        return [
            ToolChatMessage(
                role="system",
                content=self._system_prompt(),
            ),
            ToolChatMessage(role="user", content=user_content),
        ]

    def _available_tools(self, *, include_analysis: bool) -> list[dict[str, object]]:
        tools = [self._code_comment_schema(), self._task_done_schema()]
        if include_analysis:
            tools.extend(self._tool_registry.get_all_schemas())
        return tools

    @staticmethod
    def _code_comment_schema() -> dict[str, object]:
        return {
            "name": "code_comment",
            "description": (
                "提交一条有代码依据的审查评论。"
                "当你在变更代码中发现一个具体问题时就调用一次。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "相对仓库根目录的变更文件路径。"},
                    "line": {"type": "integer", "description": "变更文件中的新增行号，1-based。"},
                    "summary": {"type": "string", "description": "问题摘要，优先使用中文。"},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                        "description": "问题严重程度。",
                    },
                    "category": {
                        "type": "string",
                        "enum": list(AgentRuntime._CATEGORY_VALUES),
                        "description": "问题分类。",
                    },
                    "explanation": {
                        "type": "string",
                        "description": "问题解释，必须引用具体代码，优先使用中文。",
                    },
                    "suggested_fix": {
                        "type": ["string", "null"],
                        "description": "可选修复建议，若提供应可执行，优先使用中文。",
                    },
                },
                "required": [
                    "file",
                    "line",
                    "summary",
                    "severity",
                    "category",
                    "explanation",
                ],
            },
        }

    @staticmethod
    def _task_done_schema() -> dict[str, object]:
        return {
            "name": "task_done",
            "description": "声明当前审查已经完成，没有更多问题需要提交。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "结束审查的简短原因，优先使用中文。"},
                },
                "required": ["reason"],
            },
        }

    def _handle_code_comment(
        self,
        *,
        tool_call_id: str,
        arguments: str,
        snapshot: ReviewSnapshot,
    ) -> tuple[str, Finding | None]:
        try:
            payload = self._parse_arguments(arguments)
            file = self._require_string(payload.get("file"), "file")
            if file not in snapshot.changed_files:
                raise ToolExecutionError(
                    f"File '{file}' is not in the changed files list. "
                    f"Changed files: {snapshot.changed_files}"
                )
            line = self._require_positive_int(payload.get("line"), "line")
            summary = self._require_string(payload.get("summary"), "summary")
            explanation = self._require_string(payload.get("explanation"), "explanation")
            severity = Severity(self._require_string(payload.get("severity"), "severity"))
            category = self._require_category(payload.get("category"))
            suggested_fix = self._optional_string(payload.get("suggested_fix"))
        except (ToolExecutionError, ValueError) as exc:
            return (
                json.dumps(
                    {
                        "accepted": False,
                        "error": str(exc),
                    },
                    ensure_ascii=True,
                ),
                None,
            )

        finding = Finding(
            id=self._finding_id(summary, file, line),
            summary=summary,
            severity=severity,
            confidence=Confidence.REFERENCE,
            file=file,
            line=line,
            explanation=explanation,
            evidence=[
                EvidenceRef(
                    source_type="agent_tool_call",
                    source_id=tool_call_id,
                    file=file,
                    line_start=line,
                    line_end=line,
                    excerpt=summary,
                    verified=False,
                )
            ],
            suggested_fix=suggested_fix,
            category=category,
            source_type=FindingSource.LLM,
        )
        return (
            json.dumps(
                {
                    "accepted": True,
                    "finding_id": finding.id,
                },
                ensure_ascii=True,
            ),
            finding,
        )

    def _handle_task_done(self, arguments: str) -> str:
        payload = self._parse_arguments(arguments)
        reason = self._optional_string(payload.get("reason")) or "审查完成"
        return json.dumps({"accepted": True, "reason": reason}, ensure_ascii=True)

    def _handle_analysis_tool(
        self,
        *,
        tool_name: str,
        arguments: str,
        snapshot: ReviewSnapshot,
        provider,
        review_id: str,
        trace: ReviewTrace,
        round_index: int,
        tool_round: int,
        tool_call_id: str,
    ) -> str:
        payload = self._parse_arguments(arguments)
        result = self._tool_registry.execute(
            tool_name,
            arguments=payload,
            context=ToolExecutionContext(snapshot=snapshot, provider=provider),
        )
        self._trace_manager.append_event(
            review_id=review_id,
            trace=trace,
            stage=ReviewStage.FINDINGS_GENERATED,
            message=f"Agent runtime executed tool {tool_name}.",
            details={
                "round": round_index,
                "tool_round": tool_round,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "error": result.error,
                "truncated": result.truncated,
            },
        )
        result_payload = result.payload
        result_dict = {
            "tool_name": tool_name,
            "payload": result_payload,
            "truncated": result.truncated,
            "error": result.error,
        }
        result_message = json.dumps(result_dict, ensure_ascii=True)
        max_chars = self._config.max_tool_output_chars
        if len(result_message) > max_chars and result_payload is not None:
            payload_json = json.dumps(result_payload, ensure_ascii=True)
            keep_chars = max(200, max_chars - 400)
            truncated_payload = payload_json[:keep_chars] + "\n...[truncated]"
            result_dict = {
                "tool_name": tool_name,
                "payload": truncated_payload,
                "truncated": True,
                "error": result.error,
                "original_size": len(payload_json),
            }
            result_message = json.dumps(result_dict, ensure_ascii=True)
        return result_message

    def _estimate_chat_tokens(
        self,
        messages: list[ToolChatMessage],
        tools: list[dict[str, object]],
    ) -> int:
        serialized = json.dumps(
            {
                "messages": [message.model_dump(mode="json") for message in messages],
                "tools": tools,
            },
            ensure_ascii=True,
        )
        return self._llm_provider.estimate_prompt_tokens(
            serialized,
            budget_mode="normal",
        )

    def _describe_llm_selection(self, budget_mode: str) -> dict[str, str | None]:
        tier_resolver = getattr(self._llm_provider, "resolve_model_tier", None)
        model_resolver = getattr(self._llm_provider, "resolve_model_name", None)
        tier = tier_resolver(budget_mode=budget_mode) if callable(tier_resolver) else "unknown"
        model = model_resolver(budget_mode=budget_mode) if callable(model_resolver) else None
        return {
            "tier": tier,
            "model": model,
        }

    @classmethod
    def _system_prompt(cls) -> str:
        return "\n".join(
            [
                "你是一个严谨的代码审查 Agent，专注于在变更代码中发现具体、可复现的问题。",
                "",
                "审查原则",
                "- 每个评论都必须基于你实际读过的 diff 或文件内容。",
                "- 只评论变更文件中的代码。",
                "- 优先发现正确性、安全性、并发、资源泄漏等高影响问题。",
                "- 避免只讨论风格类问题，除非已经严重影响可读性。",
                "- 不要重复提交相同问题。",
                "- 所有 review 评论、summary、explanation、suggested_fix 优先使用中文表述。",
                "",
                "严重程度定义",
                "- critical：安全漏洞、数据丢失、崩溃、核心逻辑正确性 bug、并发竞态。",
                "- high：明显 bug、性能问题、资源泄漏、错误处理缺失、边界条件未处理。",
                "- medium：代码质量问题、缺少测试、逻辑不清晰、次要性能问题。",
                "- low：命名、风格、文档、微小改进建议。",
                "",
                "问题分类",
                "- bug：功能错误或逻辑缺陷。",
                "- security：安全漏洞、注入、权限或敏感信息泄露。",
                "- performance：性能问题、低效算法或 N+1 查询。",
                "- maintainability：可维护性问题、重复代码或复杂度过高。",
                "- test：测试缺失、覆盖不足或测试质量差。",
                "- style：代码风格、命名或格式问题。",
                "- documentation：文档缺失或注释不准确。",
                "- other：其他问题。",
                "",
                "工具使用指南",
                "- 审查开始时优先调用 list_changed_files，先了解完整变更范围。",
                "- 使用 read_diff 查看某个文件的具体变更。",
                "- 需要完整上下文时调用 read_file。",
                "- 需要理解函数或类的使用方式时调用 find_references。",
                "- 每发现一个具体问题就调用一次 code_comment，可以调用多次。",
                "- 没有更多有依据的问题需要报告时调用 task_done。",
                "- 每次最多调用 2 个 read_diff 或 read_file，逐个文件审查，不要一次性批量读取。",
                "- 每审查完一个文件，如果发现问题，立即调用 code_comment 提交，不要等全部文件读完再统一提交。",
                "- 禁止在没有提交任何 code_comment 的情况下连续调用超过 3 个分析工具(read_diff/read_file/find_references)。",
                "",
                "输出约束",
                "- 每个 code_comment 都必须包含 file、line、summary、severity、category、explanation。",
                "- line 必须指向变更文件中的新增行。",
                "- explanation 必须引用具体代码，并说明为什么这是问题。",
                "- suggested_fix 可选，但如果提供必须是可执行的修复建议。",
                "",
                "禁止事项",
                "- 禁止评论你没有读过的代码。",
                "- 禁止提交没有具体代码引用的泛泛评论。",
                "- 禁止重复规则引擎已经发现的问题。",
                "- 禁止在未确认的情况下假设代码行为。",
            ]
        )

    @staticmethod
    def _summarize_findings(findings: list[Finding]) -> str:
        summaries: list[str] = []
        for finding in findings:
            location = ""
            if finding.file is not None and finding.line is not None:
                location = f"[{finding.file}:{finding.line}] "
            summaries.append(f"- {location}{finding.summary}")
        return "\n".join(summaries)

    @staticmethod
    def _build_diff_summary(snapshot: ReviewSnapshot) -> str:
        analysis = prepare_diff_analysis(snapshot)
        total_added = 0
        total_deleted = 0
        file_summaries: list[str] = []

        for file_diff in analysis.files:
            if not AgentRuntime._is_llm_visible_path(file_diff.path):
                continue
            added_count = len(file_diff.added_lines)
            deleted_count = 0
            for line in file_diff.diff_text.splitlines():
                if line.startswith("--- ") or line.startswith("+++ "):
                    continue
                if line.startswith("-"):
                    deleted_count += 1
            total_added += added_count
            total_deleted += deleted_count
            file_summaries.append(
                f"- {file_diff.path}（{AgentRuntime._infer_change_type(file_diff.diff_text)}）："
                f"+{added_count} / -{deleted_count}"
            )

        return "\n".join(
            [
                f"- 变更文件数：{len(file_summaries)}",
                f"- 新增行数：{total_added}",
                f"- 删除行数：{total_deleted}",
                "- 文件列表：",
                *file_summaries,
            ]
        )

    @staticmethod
    def _infer_change_type(diff_text: str) -> str:
        if "new file mode" in diff_text:
            return "新增"
        if "deleted file mode" in diff_text:
            return "删除"
        if "rename from " in diff_text or "rename to " in diff_text:
            return "重命名"
        return "修改"

    @staticmethod
    def _parse_arguments(arguments: str) -> dict[str, object]:
        try:
            payload = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("tool arguments must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ToolExecutionError("tool arguments must decode to a JSON object.")
        return payload

    @staticmethod
    def _require_string(value: object, field_name: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ToolExecutionError(f"tool field '{field_name}' must be a non-empty string.")

    @staticmethod
    def _require_positive_int(value: object, field_name: str) -> int:
        if isinstance(value, int) and value > 0:
            return value
        raise ToolExecutionError(f"tool field '{field_name}' must be a positive integer.")

    @staticmethod
    def _optional_string(value: object) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _has_visible_content(value: str | None) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _is_llm_visible_path(path: str | None) -> bool:
        if path is None:
            return True
        normalized_path = path.lower()
        return not (normalized_path.startswith(".env") or "/.env" in normalized_path)

    @classmethod
    def _is_llm_visible_finding(cls, finding: Finding) -> bool:
        return cls._is_llm_visible_path(finding.file)

    @classmethod
    def _require_category(cls, value: object) -> str:
        category = cls._require_string(value, "category")
        if category not in cls._CATEGORY_VALUES:
            raise ToolExecutionError(
                "tool field 'category' must be one of: "
                f"{', '.join(cls._CATEGORY_VALUES)}."
            )
        return category

    @staticmethod
    def _finding_id(summary: str, file: str | None, line: int | None) -> str:
        digest = hashlib.sha1(f"{summary}:{file}:{line}".encode("utf-8")).hexdigest()
        return f"agent-{digest[:10]}"
