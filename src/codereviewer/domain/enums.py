"""Domain enums used by the application."""

from enum import StrEnum


class ReviewStage(StrEnum):
    """Stable pipeline stages for the review lifecycle."""

    INPUT_VALIDATED = "input_validated"
    SNAPSHOT_CREATED = "snapshot_created"
    ANALYSIS_PREPARED = "analysis_prepared"
    DETERMINISTIC_CHECKS_DONE = "deterministic_checks_done"
    FINDINGS_GENERATED = "findings_generated"
    FINDINGS_VERIFIED = "findings_verified"
    OUTPUTS_PREPARED = "outputs_prepared"
    PUBLISH_ATTEMPTED = "publish_attempted"
    COMPLETED = "completed"
    FAILED = "failed"


class ProviderKind(StrEnum):
    """Supported SCM providers."""

    GITHUB = "github"
    GITLAB = "gitlab"


class ReviewSourceKind(StrEnum):
    """Supported review request source types."""

    REVIEW_URL = "review_url"
    BRANCH_COMPARE = "branch_compare"
    CHANGE_NUMBER = "change_number"


class Severity(StrEnum):
    """Severity levels for review findings."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Confidence(StrEnum):
    """Confidence levels for review findings."""

    HIGH = "high"
    REFERENCE = "reference"


class FindingSource(StrEnum):
    """Origin of a review finding."""

    RULE = "rule"
    LLM = "llm"
    HYBRID = "hybrid"
