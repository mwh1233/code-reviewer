"""OpenAI-compatible LLM adapter for M6."""

from __future__ import annotations

import json

import requests
from requests import Response
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError as RequestsHTTPError
from requests.exceptions import ReadTimeout, RequestException

from codereviewer.config import LLMConfig
from codereviewer.domain.errors import LLMProviderError
from codereviewer.domain.models import (
    LLMReviewResult,
    ToolCall,
    ToolChatMessage,
    ToolChatRequest,
    ToolChatResponse,
)


class OpenAICompatibleLLMProvider:
    """Call one OpenAI-compatible chat completions endpoint."""

    _CONNECT_TIMEOUT_SECONDS = 10.0
    _MIN_READ_TIMEOUT_SECONDS = 120.0

    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    def review(self, prompt: str, *, budget_mode: str = "normal") -> LLMReviewResult:
        payload = {
            "model": self._config.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a deterministic code review assistant. "
                        "Return only JSON with a top-level 'findings' array."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        response_json = self._request_json(payload)
        choice = self._extract_first_choice(response_json)
        message = self._extract_message(choice)
        content = self._extract_required_text_content(message)
        input_tokens, output_tokens = self._extract_usage(response_json)
        estimated_cost = self._estimate_cost(input_tokens, output_tokens)
        return LLMReviewResult(
            raw_content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
        )

    def chat_with_tools(
        self,
        request: ToolChatRequest,
        *,
        budget_mode: str = "normal",
    ) -> ToolChatResponse:
        payload: dict[str, object] = {
            "model": self._config.model,
            "temperature": request.temperature,
            "messages": [self._serialize_message(message) for message in request.messages],
            "tools": [self._serialize_tool_schema(tool) for tool in request.tools],
            "tool_choice": request.tool_choice,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        response_json = self._request_json(payload)
        choice = self._extract_first_choice(response_json)
        message = self._extract_message(choice)
        content = self._extract_optional_text_content(message)
        tool_calls = self._extract_tool_calls(message)
        input_tokens, output_tokens = self._extract_usage(response_json)
        estimated_cost = self._estimate_cost(input_tokens, output_tokens)
        finish_reason = self._extract_finish_reason(choice)
        return ToolChatResponse(
            content=content,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            finish_reason=finish_reason,
        )

    def estimate_prompt_tokens(self, text: str, *, budget_mode: str = "normal") -> int:
        """Estimate prompt tokens conservatively without a tokenizer dependency."""

        return max(1, len(text) // 4)

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        budget_mode: str = "normal",
    ) -> float:
        """Expose the same simple cost estimation used after live calls."""

        return self._estimate_cost(input_tokens, output_tokens)

    def _request_json(self, payload: dict[str, object]) -> dict[str, object]:
        response = self._post_json(
            url=f"{self._config.base_url.rstrip('/')}/chat/completions",
            payload=payload,
        )

        try:
            decoded = response.json()
        except json.JSONDecodeError as exc:
            raise LLMProviderError("LLM provider returned invalid JSON.") from exc
        except ValueError as exc:
            raise LLMProviderError("LLM provider returned invalid JSON.") from exc
        if not isinstance(decoded, dict):
            raise LLMProviderError("LLM provider returned an unexpected payload.")
        return decoded

    def _post_json(self, *, url: str, payload: dict[str, object]) -> Response:
        try:
            response = requests.post(
                url=url,
                headers=self._build_headers(),
                json=payload,
                timeout=self._request_timeout(),
            )
            response.raise_for_status()
        except ReadTimeout as exc:
            raise LLMProviderError("LLM request timed out.") from exc
        except RequestsHTTPError as exc:
            status_code = (
                exc.response.status_code
                if exc.response is not None
                else "unknown"
            )
            raise LLMProviderError(
                f"LLM request failed with HTTP {status_code}."
            ) from exc
        except RequestsConnectionError as exc:
            raise LLMProviderError(f"LLM request failed: {exc}.") from exc
        except RequestException as exc:
            raise LLMProviderError(f"LLM request failed: {exc}.") from exc
        return response

    def _build_headers(self) -> dict[str, str]:
        if not self._config.api_key:
            raise LLMProviderError("LLM API key is not configured.")
        return {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "codereviewer/0.1",
        }

    def _request_timeout(self) -> tuple[float, float]:
        connect_timeout = min(
            self._config.timeout_seconds,
            self._CONNECT_TIMEOUT_SECONDS,
        )
        # Large diff reviews can take much longer than the network connect phase.
        read_timeout = max(
            self._config.timeout_seconds,
            self._MIN_READ_TIMEOUT_SECONDS,
        )
        return (connect_timeout, read_timeout)

    @staticmethod
    def _extract_first_choice(response_json: dict[str, object]) -> dict[str, object]:
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMProviderError("LLM provider response is missing choices.")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise LLMProviderError("LLM provider response contains an invalid choice.")
        return choice

    @staticmethod
    def _extract_message(choice: dict[str, object]) -> dict[str, object]:
        message = choice.get("message")
        if not isinstance(message, dict):
            raise LLMProviderError("LLM provider response is missing message content.")
        return message

    @classmethod
    def _extract_required_text_content(cls, message: dict[str, object]) -> str:
        content = cls._extract_optional_text_content(message)
        if content is None:
            raise LLMProviderError("LLM provider response did not contain text content.")
        return content

    @staticmethod
    def _extract_optional_text_content(message: dict[str, object]) -> str | None:
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
            if text_parts:
                return "".join(text_parts)
        if content is None:
            return None
        return None

    @classmethod
    def _extract_tool_calls(cls, message: dict[str, object]) -> list[ToolCall]:
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls is None:
            return []
        if not isinstance(raw_tool_calls, list):
            raise LLMProviderError("LLM provider response contains invalid tool calls.")

        tool_calls: list[ToolCall] = []
        for raw_tool_call in raw_tool_calls:
            if not isinstance(raw_tool_call, dict):
                raise LLMProviderError("LLM provider response contains invalid tool calls.")
            call_id = raw_tool_call.get("id")
            function = raw_tool_call.get("function")
            if not isinstance(call_id, str) or not isinstance(function, dict):
                raise LLMProviderError("LLM provider response contains invalid tool calls.")
            name = function.get("name")
            arguments = function.get("arguments")
            if not isinstance(name, str) or not isinstance(arguments, str):
                raise LLMProviderError("LLM provider response contains invalid tool calls.")
            try:
                parsed_arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise LLMProviderError(
                    f"LLM provider returned invalid JSON arguments for tool '{name}'."
                ) from exc
            if not isinstance(parsed_arguments, dict):
                raise LLMProviderError(
                    f"LLM provider returned non-object JSON arguments for tool '{name}'."
                )
            tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=name,
                    arguments=arguments,
                )
            )
        return tool_calls

    @staticmethod
    def _extract_finish_reason(choice: dict[str, object]) -> str:
        finish_reason = choice.get("finish_reason")
        return finish_reason if isinstance(finish_reason, str) else "stop"

    @staticmethod
    def _extract_usage(response_json: dict[str, object]) -> tuple[int, int]:
        usage = response_json.get("usage")
        return (
            OpenAICompatibleLLMProvider._usage_int(usage, "prompt_tokens"),
            OpenAICompatibleLLMProvider._usage_int(usage, "completion_tokens"),
        )

    @staticmethod
    def _usage_int(usage: object, field_name: str) -> int:
        if not isinstance(usage, dict):
            return 0
        value = usage.get(field_name)
        return int(value) if isinstance(value, (int, float)) else 0

    @staticmethod
    def _serialize_message(message: ToolChatMessage) -> dict[str, object]:
        payload: dict[str, object] = {"role": message.role}
        if message.content is not None:
            payload["content"] = message.content
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                    },
                }
                for tool_call in message.tool_calls
            ]
        if message.tool_call_id is not None:
            payload["tool_call_id"] = message.tool_call_id
        return payload

    @staticmethod
    def _serialize_tool_schema(tool: dict[str, object]) -> dict[str, object]:
        if (
            isinstance(tool.get("type"), str)
            and tool.get("type") == "function"
            and isinstance(tool.get("function"), dict)
        ):
            return tool
        return {
            "type": "function",
            "function": tool,
        }

    def _estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        # Conservative placeholder estimate for M6 without model-pricing service.
        return (input_tokens * 0.000001) + (output_tokens * 0.000003)
