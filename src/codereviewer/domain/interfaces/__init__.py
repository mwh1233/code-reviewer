"""Stable domain interfaces."""

from codereviewer.domain.interfaces.llm import LLMProvider
from codereviewer.domain.interfaces.scm import SCMProvider
from codereviewer.domain.interfaces.tool import ReviewRule, ReviewTool, ToolExecutor

__all__ = ["LLMProvider", "SCMProvider", "ReviewRule", "ReviewTool", "ToolExecutor"]
