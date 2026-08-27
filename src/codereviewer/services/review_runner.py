"""Stage-driven review runner for M4."""

from __future__ import annotations

from pathlib import Path

from codereviewer.adapters.storage.file_store import FileCheckpointStore, FileTraceStore
from codereviewer.config import AppConfig
from codereviewer.domain.enums import ReviewStage
from codereviewer.domain.errors import CodeReviewerError
from codereviewer.domain.models import (
    BudgetSnapshot,
    Finding,
    PipelineResult,
    ReviewRequest,
    ReviewSnapshot,
    ReviewTrace,
)
from codereviewer.reporters.json_output import write_findings_json
from codereviewer.reporters.markdown import write_markdown_report
from codereviewer.services.agent_runtime import AgentRuntime
from codereviewer.services.budget_manager import BudgetManager
from codereviewer.services.checkpoint_manager import CheckpointManager
from codereviewer.services.comment_locator import CommentLocator
from codereviewer.services.diff_preprocessor import prepare_diff_analysis
from codereviewer.services.evidence_validator import EvidenceValidator
from codereviewer.services.finding_aggregator import FindingAggregator
from codereviewer.services.llm_provider_factory import build_llm_provider
from codereviewer.services.publish_controller import PublishController
from codereviewer.services.rule_engine import build_builtin_rule_engine
from codereviewer.services.scm_provider_factory import build_scm_provider
from codereviewer.services.security import sanitize_findings
from codereviewer.services.snapshot_builder import build_input_hash, build_review_id
from codereviewer.services.tool_engine import ToolEngine
from codereviewer.services.trace_manager import TraceManager
from codereviewer.tools.builtin import build_builtin_tool_registry


_PLACEHOLDER_STAGE_FLOW: dict[ReviewStage, tuple[ReviewStage, str]] = {}


class ReviewRunner:
    """Execute reviews as a sequence of stable stages."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._checkpoint_manager = CheckpointManager(
            FileCheckpointStore(config.artifact_root)
        )
        self._trace_manager = TraceManager(FileTraceStore(config.artifact_root))

    def run(self, request: ReviewRequest) -> PipelineResult:
        input_hash = build_input_hash(request)
        review_id = build_review_id(request, input_hash=input_hash)
        provider = build_scm_provider(request.provider, self._config)
        trace = self._trace_manager.create(review_id)
        completed_stages: list[ReviewStage] = []
        findings: list[Finding] = []
        budget = BudgetSnapshot(
            token_limit=self._config.llm.max_total_tokens,
            cost_limit=self._config.llm.max_total_cost,
        )

        self._record_stage_completion(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            trace=trace,
            completed_stages=completed_stages,
            current_stage=ReviewStage.INPUT_VALIDATED,
            next_stage=ReviewStage.SNAPSHOT_CREATED,
            message="Review input validated.",
            findings=findings,
            budget=budget,
        )

        snapshot = provider.resolve_snapshot_target(request)
        snapshot.review_id = review_id
        snapshot.input_hash = input_hash
        self._record_stage_completion(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            current_stage=ReviewStage.SNAPSHOT_CREATED,
            next_stage=ReviewStage.ANALYSIS_PREPARED,
            message="Immutable review snapshot created.",
            findings=findings,
            budget=budget,
        )

        findings = self._run_analysis_prepared(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            findings=findings,
            budget=budget,
        )
        findings = self._run_deterministic_checks(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            provider=provider,
            findings=findings,
            budget=budget,
        )
        findings, budget = self._run_llm_findings_generated(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            provider=provider,
            findings=findings,
            budget=budget,
        )
        findings = self._run_findings_verified(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            findings=findings,
            budget=budget,
        )
        self._run_outputs_prepared(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            findings=findings,
            budget=budget,
        )
        self._run_publish_attempted(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            provider=provider,
            findings=findings,
            budget=budget,
        )
        self._record_stage_completion(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            current_stage=ReviewStage.COMPLETED,
            next_stage=None,
            message="Review pipeline completed.",
            terminal_status=ReviewStage.COMPLETED,
            findings=findings,
            budget=budget,
        )
        review_root = self._config.artifact_root / "reviews" / review_id
        review_root.mkdir(parents=True, exist_ok=True)
        placeholder_file = self._write_placeholder(review_root, request, snapshot)
        checkpoint_file = review_root / "checkpoint.json"
        trace_file = review_root / "trace.json"

        return PipelineResult(
            review_id=review_id,
            stage=ReviewStage.COMPLETED,
            message="Stage-driven review pipeline completed successfully.",
            artifact_root=review_root,
            placeholder_file=placeholder_file,
            request=request,
            snapshot=snapshot,
            checkpoint_file=checkpoint_file if checkpoint_file.exists() else None,
            trace_file=trace_file if trace_file.exists() else None,
        )

    def resume(self, review_id: str) -> PipelineResult:
        checkpoint = self._checkpoint_manager.load(review_id)
        if checkpoint is None:
            raise ValueError(f"checkpoint for review_id={review_id} was not found.")
        if checkpoint.snapshot is None:
            raise ValueError(
                f"checkpoint for review_id={review_id} does not contain a snapshot."
            )

        trace = self._trace_manager.load(review_id)
        if trace is None:
            raise ValueError(f"trace for review_id={review_id} was not found.")

        self._trace_manager.append_event(
            review_id=review_id,
            trace=trace,
            stage=checkpoint.current_stage,
            message="Review resumed from checkpoint.",
        )
        provider = build_scm_provider(checkpoint.request.provider, self._config)
        completed_stages = list(checkpoint.completed_stages)
        findings = list(checkpoint.findings)
        budget = checkpoint.budget
        if (
            checkpoint.current_stage not in completed_stages
            and checkpoint.current_stage not in {ReviewStage.COMPLETED, ReviewStage.FAILED}
        ):
            completed_stages.append(checkpoint.current_stage)

        stage = checkpoint.terminal_status or checkpoint.current_stage
        message = "Review resumed from checkpoint."
        if checkpoint.terminal_status is None and checkpoint.next_stage is not None:
            if checkpoint.next_stage == ReviewStage.ANALYSIS_PREPARED:
                findings = self._run_analysis_prepared(
                    review_id=review_id,
                    input_hash=checkpoint.input_hash,
                    request=checkpoint.request,
                    snapshot=checkpoint.snapshot,
                    trace=trace,
                    completed_stages=completed_stages,
                    findings=findings,
                    budget=budget,
                )
                checkpoint.next_stage = ReviewStage.DETERMINISTIC_CHECKS_DONE

            if checkpoint.next_stage == ReviewStage.DETERMINISTIC_CHECKS_DONE:
                findings = self._run_deterministic_checks(
                    review_id=review_id,
                    input_hash=checkpoint.input_hash,
                    request=checkpoint.request,
                    snapshot=checkpoint.snapshot,
                    trace=trace,
                    completed_stages=completed_stages,
                    provider=provider,
                    findings=findings,
                    budget=budget,
                )
                checkpoint.next_stage = ReviewStage.FINDINGS_GENERATED

            if checkpoint.next_stage == ReviewStage.FINDINGS_GENERATED:
                findings, budget = self._run_llm_findings_generated(
                    review_id=review_id,
                    input_hash=checkpoint.input_hash,
                    request=checkpoint.request,
                    snapshot=checkpoint.snapshot,
                    trace=trace,
                    completed_stages=completed_stages,
                    provider=provider,
                    findings=findings,
                    budget=budget,
                )
                checkpoint.next_stage = ReviewStage.FINDINGS_VERIFIED

            if checkpoint.next_stage == ReviewStage.FINDINGS_VERIFIED:
                findings = self._run_findings_verified(
                    review_id=review_id,
                    input_hash=checkpoint.input_hash,
                    request=checkpoint.request,
                    snapshot=checkpoint.snapshot,
                    trace=trace,
                    completed_stages=completed_stages,
                    findings=findings,
                    budget=budget,
                )
                checkpoint.next_stage = ReviewStage.OUTPUTS_PREPARED

            if checkpoint.next_stage == ReviewStage.OUTPUTS_PREPARED:
                self._run_outputs_prepared(
                    review_id=review_id,
                    input_hash=checkpoint.input_hash,
                    request=checkpoint.request,
                    snapshot=checkpoint.snapshot,
                    trace=trace,
                    completed_stages=completed_stages,
                    findings=findings,
                    budget=budget,
                )
                checkpoint.next_stage = ReviewStage.PUBLISH_ATTEMPTED

            if checkpoint.next_stage == ReviewStage.PUBLISH_ATTEMPTED:
                self._run_publish_attempted(
                    review_id=review_id,
                    input_hash=checkpoint.input_hash,
                    request=checkpoint.request,
                    snapshot=checkpoint.snapshot,
                    trace=trace,
                    completed_stages=completed_stages,
                    provider=provider,
                    findings=findings,
                    budget=budget,
                )
                checkpoint.next_stage = ReviewStage.COMPLETED

            if checkpoint.next_stage == ReviewStage.COMPLETED:
                self._record_stage_completion(
                    review_id=review_id,
                    input_hash=checkpoint.input_hash,
                    request=checkpoint.request,
                    snapshot=checkpoint.snapshot,
                    trace=trace,
                    completed_stages=completed_stages,
                    current_stage=ReviewStage.COMPLETED,
                    next_stage=None,
                    message="Review pipeline completed after resume.",
                    terminal_status=ReviewStage.COMPLETED,
                    findings=findings,
                    budget=budget,
                )
                stage = ReviewStage.COMPLETED
                message = "Review resumed and completed remaining pipeline stages."

        checkpoint_file = self._config.artifact_root / "reviews" / review_id / "checkpoint.json"
        trace_file = self._config.artifact_root / "reviews" / review_id / "trace.json"
        review_root = self._config.artifact_root / "reviews" / review_id
        placeholder_file = self._write_placeholder(
            review_root,
            checkpoint.request,
            checkpoint.snapshot,
            resumed=True,
        )

        return PipelineResult(
            review_id=review_id,
            stage=stage,
            message=message,
            artifact_root=review_root,
            placeholder_file=placeholder_file,
            request=checkpoint.request,
            snapshot=checkpoint.snapshot,
            checkpoint_file=checkpoint_file if checkpoint_file.exists() else None,
            trace_file=trace_file if trace_file.exists() else None,
        )

    def _advance_placeholder_stages(
        self,
        *,
        review_id: str,
        input_hash: str,
        request: ReviewRequest,
        snapshot: ReviewSnapshot,
        trace: ReviewTrace,
        completed_stages: list[ReviewStage],
        start_stage: ReviewStage,
        findings: list[Finding],
        budget: BudgetSnapshot,
    ) -> None:
        current_stage = start_stage
        while current_stage in _PLACEHOLDER_STAGE_FLOW:
            next_stage, message = _PLACEHOLDER_STAGE_FLOW[current_stage]
            self._record_stage_completion(
                review_id=review_id,
                input_hash=input_hash,
                request=request,
                snapshot=snapshot,
                trace=trace,
                completed_stages=completed_stages,
                current_stage=current_stage,
                next_stage=next_stage if next_stage != ReviewStage.COMPLETED else None,
                message=message,
                findings=findings,
                budget=budget,
            )
            current_stage = next_stage

    def _record_stage_completion(
        self,
        *,
        review_id: str,
        input_hash: str,
        request: ReviewRequest,
        trace: ReviewTrace,
        completed_stages: list[ReviewStage],
        current_stage: ReviewStage,
        next_stage: ReviewStage | None,
        message: str,
        snapshot: ReviewSnapshot | None = None,
        terminal_status: ReviewStage | None = None,
        findings: list[Finding] | None = None,
        budget: BudgetSnapshot | None = None,
        error_message: str | None = None,
    ) -> None:
        if current_stage not in completed_stages:
            completed_stages.append(current_stage)
        self._trace_manager.append_event(
            review_id=review_id,
            trace=trace,
            stage=current_stage,
            message=message,
        )
        self._checkpoint_manager.save_stage(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace_id=trace.trace_id,
            completed_stages=completed_stages,
            current_stage=current_stage,
            next_stage=next_stage,
            terminal_status=terminal_status,
            findings=findings,
            budget=budget,
            error_message=error_message,
        )

    def _run_analysis_prepared(
        self,
        *,
        review_id: str,
        input_hash: str,
        request: ReviewRequest,
        snapshot: ReviewSnapshot,
        trace: ReviewTrace,
        completed_stages: list[ReviewStage],
        findings: list[Finding],
        budget: BudgetSnapshot,
    ) -> list[Finding]:
        analysis = prepare_diff_analysis(snapshot)
        message = (
            "Prepared deterministic diff analysis for "
            f"{len(analysis.files)} files "
            f"({len(analysis.text_files)} text, {len(analysis.binary_files)} binary)."
        )
        self._record_stage_completion(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            current_stage=ReviewStage.ANALYSIS_PREPARED,
            next_stage=ReviewStage.DETERMINISTIC_CHECKS_DONE,
            message=message,
            findings=findings,
            budget=budget,
        )
        return findings

    def _run_deterministic_checks(
        self,
        *,
        review_id: str,
        input_hash: str,
        request: ReviewRequest,
        snapshot: ReviewSnapshot,
        trace: ReviewTrace,
        completed_stages: list[ReviewStage],
        provider,
        findings: list[Finding],
        budget: BudgetSnapshot,
    ) -> list[Finding]:
        tool_engine = ToolEngine(
            build_builtin_tool_registry(),
            trace_manager=self._trace_manager,
            trace=trace,
            review_id=review_id,
        )
        rule_engine = build_builtin_rule_engine()
        deterministic_findings = rule_engine.evaluate(
            snapshot=snapshot,
            tool_executor=tool_engine,
            provider=provider,
        )
        message = (
            "Deterministic checks completed with "
            f"{len(deterministic_findings)} candidate findings."
        )
        self._record_stage_completion(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            current_stage=ReviewStage.DETERMINISTIC_CHECKS_DONE,
            next_stage=ReviewStage.FINDINGS_GENERATED,
            message=message,
            findings=deterministic_findings,
            budget=budget,
        )
        return deterministic_findings

    def _run_llm_findings_generated(
        self,
        *,
        review_id: str,
        input_hash: str,
        request: ReviewRequest,
        snapshot: ReviewSnapshot,
        trace: ReviewTrace,
        completed_stages: list[ReviewStage],
        provider,
        findings: list[Finding],
        budget: BudgetSnapshot,
    ) -> tuple[list[Finding], BudgetSnapshot]:
        llm_provider = build_llm_provider(self._config)
        budget_manager = BudgetManager(budget)

        try:
            runtime = AgentRuntime(
                llm_provider=llm_provider,
                tool_registry=build_builtin_tool_registry(),
                trace_manager=self._trace_manager,
                budget_manager=budget_manager,
            )
            result = runtime.run(
                snapshot=snapshot,
                existing_findings=findings,
                trace=trace,
                review_id=review_id,
                provider=provider,
            )
        except CodeReviewerError as exc:
            self._record_failed_stage(
                review_id=review_id,
                input_hash=input_hash,
                request=request,
                snapshot=snapshot,
                trace=trace,
                completed_stages=completed_stages,
                message=f"LLM review failed during findings_generated: {exc}",
                findings=findings,
                budget=budget,
                error_message=str(exc),
            )
            raise
        except Exception as exc:
            self._record_failed_stage(
                review_id=review_id,
                input_hash=input_hash,
                request=request,
                snapshot=snapshot,
                trace=trace,
                completed_stages=completed_stages,
                message=f"LLM review failed during findings_generated: {exc}",
                findings=findings,
                budget=budget,
                error_message=str(exc),
            )
            raise
        budget = result.budget_snapshot
        llm_findings = findings + result.findings
        if not result.findings and result.stop_reason == "budget_exhausted":
            self._record_stage_completion(
                review_id=review_id,
                input_hash=input_hash,
                request=request,
                snapshot=snapshot,
                trace=trace,
                completed_stages=completed_stages,
                current_stage=ReviewStage.FINDINGS_GENERATED,
                next_stage=ReviewStage.FINDINGS_VERIFIED,
                message=f"LLM review skipped due to budget policy: {budget.stop_reason}",
                findings=findings,
                budget=budget,
            )
            return findings, budget
        budget_suffix = ""
        if budget.stop_reason:
            budget_suffix = f" Budget stop recorded: {budget.stop_reason}"
        self._record_stage_completion(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            current_stage=ReviewStage.FINDINGS_GENERATED,
            next_stage=ReviewStage.FINDINGS_VERIFIED,
            message=(
                "LLM findings generated with "
                f"{len(result.findings)} additional candidate findings via AgentRuntime. "
                f"Budget level={budget.degrade_level}. "
                f"stop_reason={result.stop_reason}."
                f"{budget_suffix}"
            ),
            findings=llm_findings,
            budget=budget,
        )
        return llm_findings, budget

    def _run_findings_verified(
        self,
        *,
        review_id: str,
        input_hash: str,
        request: ReviewRequest,
        snapshot: ReviewSnapshot,
        trace: ReviewTrace,
        completed_stages: list[ReviewStage],
        findings: list[Finding],
        budget: BudgetSnapshot,
    ) -> list[Finding]:
        locator = CommentLocator(snapshot)
        validator = EvidenceValidator()
        aggregator = FindingAggregator()

        try:
            located_findings = locator.validate(findings)
            validated_findings = validator.validate(located_findings)
            final_findings = aggregator.aggregate(validated_findings)
        except Exception as exc:
            self._record_failed_stage(
                review_id=review_id,
                input_hash=input_hash,
                request=request,
                snapshot=snapshot,
                trace=trace,
                completed_stages=completed_stages,
                message=f"Finding verification failed during findings_verified: {exc}",
                findings=findings,
                budget=budget,
                error_message=str(exc),
            )
            raise

        invalid_location_count = sum(
            1 for finding in validated_findings if not finding.location_valid
        )
        self._record_stage_completion(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            current_stage=ReviewStage.FINDINGS_VERIFIED,
            next_stage=ReviewStage.OUTPUTS_PREPARED,
            message=(
                "Findings verified and aggregated into "
                f"{len(final_findings)} final findings. "
                f"Invalid locations downgraded: {invalid_location_count}."
            ),
            findings=final_findings,
            budget=budget,
        )
        return final_findings

    def _run_outputs_prepared(
        self,
        *,
        review_id: str,
        input_hash: str,
        request: ReviewRequest,
        snapshot: ReviewSnapshot,
        trace: ReviewTrace,
        completed_stages: list[ReviewStage],
        findings: list[Finding],
        budget: BudgetSnapshot,
    ) -> None:
        review_root = self._config.artifact_root / "reviews" / review_id
        safe_findings = sanitize_findings(findings)

        try:
            write_findings_json(review_root, safe_findings)
            write_markdown_report(
                review_root,
                review_id=review_id,
                request=request,
                snapshot=snapshot,
                findings=safe_findings,
                budget=budget,
                trace_id=trace.trace_id,
            )
        except Exception as exc:
            self._record_failed_stage(
                review_id=review_id,
                input_hash=input_hash,
                request=request,
                snapshot=snapshot,
                trace=trace,
                completed_stages=completed_stages,
                message=f"Output preparation failed during outputs_prepared: {exc}",
                findings=findings,
                budget=budget,
                error_message=str(exc),
            )
            raise

        self._record_stage_completion(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            current_stage=ReviewStage.OUTPUTS_PREPARED,
            next_stage=ReviewStage.PUBLISH_ATTEMPTED,
            message=(
                "Prepared local output artifacts: "
                "report.md and findings.json."
            ),
            findings=findings,
            budget=budget,
        )

    def _run_publish_attempted(
        self,
        *,
        review_id: str,
        input_hash: str,
        request: ReviewRequest,
        snapshot: ReviewSnapshot,
        trace: ReviewTrace,
        completed_stages: list[ReviewStage],
        provider,
        findings: list[Finding],
        budget: BudgetSnapshot,
    ) -> None:
        controller = PublishController(
            publish_enabled=self._config.publish.enabled,
        )

        try:
            publish_result = controller.publish(
                provider=provider,
                review_id=review_id,
                snapshot=snapshot,
                findings=findings,
            )
        except Exception as exc:
            self._record_failed_stage(
                review_id=review_id,
                input_hash=input_hash,
                request=request,
                snapshot=snapshot,
                trace=trace,
                completed_stages=completed_stages,
                message=f"Publish failed during publish_attempted: {exc}",
                findings=findings,
                budget=budget,
                error_message=str(exc),
            )
            raise

        if publish_result.published:
            message = (
                "Published provider review comment with "
                f"comment_id={publish_result.provider_comment_id} "
                f"at head_sha={publish_result.published_head_sha}."
            )
        else:
            message = f"Publish skipped: {publish_result.reason}"

        self._record_stage_completion(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            current_stage=ReviewStage.PUBLISH_ATTEMPTED,
            next_stage=ReviewStage.COMPLETED,
            message=message,
            findings=findings,
            budget=budget,
        )

    def _record_failed_stage(
        self,
        *,
        review_id: str,
        input_hash: str,
        request: ReviewRequest,
        snapshot: ReviewSnapshot | None,
        trace: ReviewTrace,
        completed_stages: list[ReviewStage],
        message: str,
        findings: list[Finding],
        budget: BudgetSnapshot,
        error_message: str,
    ) -> None:
        self._record_stage_completion(
            review_id=review_id,
            input_hash=input_hash,
            request=request,
            snapshot=snapshot,
            trace=trace,
            completed_stages=completed_stages,
            current_stage=ReviewStage.FAILED,
            next_stage=None,
            message=message,
            terminal_status=ReviewStage.FAILED,
            findings=findings,
            budget=budget,
            error_message=error_message,
        )

    @staticmethod
    def _write_placeholder(
        review_root: Path,
        request: ReviewRequest,
        snapshot: ReviewSnapshot,
        *,
        resumed: bool = False,
    ) -> Path:
        review_root.mkdir(parents=True, exist_ok=True)
        placeholder_file = review_root / "placeholder.txt"
        prefix = "Resumed review pipeline.\n" if resumed else "Review pipeline completed.\n"
        placeholder_file.write_text(
            prefix
            + f"provider={request.provider.value}\n"
            + f"source_kind={request.source_kind.value}\n"
            + f"repo={request.repo}\n"
            + f"base_sha={snapshot.base_sha}\n"
            + f"head_sha={snapshot.head_sha}\n"
            + f"changed_files={len(snapshot.changed_files)}\n"
            + f"input_hash={snapshot.input_hash}\n",
            encoding="utf-8",
        )
        return placeholder_file
