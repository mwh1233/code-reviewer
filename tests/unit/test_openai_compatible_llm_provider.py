"""Unit tests for the OpenAI-compatible LLM adapter."""

from __future__ import annotations

import json

import pytest
import requests

from codereviewer.adapters.llm.openai_compatible import OpenAICompatibleLLMProvider
from codereviewer.config import LLMConfig
from codereviewer.domain.errors import LLMProviderError
from codereviewer.domain.models import ToolCall, ToolChatMessage, ToolChatRequest


class _DummyResponse:
    def __init__(
        self,
        *,
        payload: dict[str, object],
        status_code: int = 200,
    ) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)

    def json(self) -> dict[str, object]:
        return self._payload


def test_openai_compatible_provider_reviews_with_requests_post(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_post(**kwargs):
        captured.update(kwargs)
        return _DummyResponse(
            payload={
                "choices": [
                    {
                        "message": {
                            "content": '{"findings":[]}',
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 35,
                },
            }
        )

    monkeypatch.setattr(requests, "post", _fake_post)
    provider = OpenAICompatibleLLMProvider(
        LLMConfig(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            timeout_seconds=30.0,
        )
    )

    result = provider.review("return findings json only")

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["timeout"] == (10.0, 120.0)
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == "deepseek-v4-flash"
    assert result.raw_content == '{"findings":[]}'
    assert result.input_tokens == 120
    assert result.output_tokens == 35


def test_openai_compatible_provider_maps_http_errors(monkeypatch):
    def _fake_post(**kwargs):
        return _DummyResponse(payload={}, status_code=429)

    monkeypatch.setattr(requests, "post", _fake_post)
    provider = OpenAICompatibleLLMProvider(
        LLMConfig(api_key="test-key")
    )

    with pytest.raises(LLMProviderError, match="HTTP 429"):
        provider.review("prompt")


def test_openai_compatible_provider_maps_http_errors_for_tool_chat(monkeypatch):
    def _fake_post(**kwargs):
        return _DummyResponse(payload={}, status_code=400)

    monkeypatch.setattr(requests, "post", _fake_post)
    provider = OpenAICompatibleLLMProvider(
        LLMConfig(api_key="test-key")
    )

    with pytest.raises(LLMProviderError, match="HTTP 400"):
        provider.chat_with_tools(
            ToolChatRequest(
                messages=[ToolChatMessage(role="user", content="prompt")],
                tools=[],
            )
        )


def test_openai_compatible_provider_maps_read_timeouts(monkeypatch):
    def _fake_post(**kwargs):
        raise requests.ReadTimeout("read timed out")

    monkeypatch.setattr(requests, "post", _fake_post)
    provider = OpenAICompatibleLLMProvider(
        LLMConfig(api_key="test-key")
    )

    with pytest.raises(LLMProviderError, match="timed out"):
        provider.review("prompt")


def test_openai_compatible_provider_rejects_invalid_json_payload(monkeypatch):
    class _InvalidJsonResponse(_DummyResponse):
        def json(self) -> dict[str, object]:
            raise json.JSONDecodeError("bad json", doc="", pos=0)

    monkeypatch.setattr(
        requests,
        "post",
        lambda **kwargs: _InvalidJsonResponse(payload={}),
    )
    provider = OpenAICompatibleLLMProvider(
        LLMConfig(api_key="test-key")
    )

    with pytest.raises(LLMProviderError, match="invalid JSON"):
        provider.review("prompt")


def test_openai_compatible_provider_sends_tools_and_parses_tool_calls(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_post(**kwargs):
        captured.update(kwargs)
        return _DummyResponse(
            payload={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"file_path":"src/app.py"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 80,
                    "completion_tokens": 20,
                },
            }
        )

    monkeypatch.setattr(requests, "post", _fake_post)
    provider = OpenAICompatibleLLMProvider(
        LLMConfig(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            timeout_seconds=30.0,
        )
    )

    result = provider.chat_with_tools(
        ToolChatRequest(
            messages=[
                ToolChatMessage(role="system", content="system instruction"),
                ToolChatMessage(role="user", content="read the file"),
                ToolChatMessage(
                    role="assistant",
                    tool_calls=[
                        ToolCall(
                            id="call_prev",
                            name="list_changed_files",
                            arguments="{}",
                        )
                    ],
                ),
                ToolChatMessage(
                    role="tool",
                    tool_call_id="call_prev",
                    content='{"files":["src/app.py"]}',
                ),
            ],
            tools=[
                {
                    "name": "read_file",
                    "description": "Read one file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                        },
                        "required": ["file_path"],
                    },
                }
            ],
            tool_choice="auto",
            max_tokens=256,
        )
    )

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["json"]["messages"][0] == {
        "role": "system",
        "content": "system instruction",
    }
    assert captured["json"]["messages"][2]["tool_calls"][0]["function"]["name"] == "list_changed_files"
    assert captured["json"]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read one file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                    },
                    "required": ["file_path"],
                },
            },
        }
    ]
    assert captured["json"]["tool_choice"] == "auto"
    assert captured["json"]["max_tokens"] == 256
    assert result.finish_reason == "tool_calls"
    assert result.content is None
    assert result.tool_calls == [
        ToolCall(
            id="call_1",
            name="read_file",
            arguments='{"file_path":"src/app.py"}',
        )
    ]
    assert result.input_tokens == 80
    assert result.output_tokens == 20


def test_openai_compatible_provider_rejects_invalid_tool_call_arguments(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda **kwargs: _DummyResponse(
            payload={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"file_path":',
                                    },
                                }
                            ],
                        },
                    }
                ]
            }
        ),
    )
    provider = OpenAICompatibleLLMProvider(LLMConfig(api_key="test-key"))

    with pytest.raises(LLMProviderError, match="invalid JSON arguments for tool 'read_file'"):
        provider.chat_with_tools(
            ToolChatRequest(
                messages=[ToolChatMessage(role="user", content="prompt")],
                tools=[],
            )
        )


def test_openai_compatible_provider_returns_plain_text_when_no_tool_calls(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda **kwargs: _DummyResponse(
            payload={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": "No more tools needed.",
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 30,
                    "completion_tokens": 10,
                },
            }
        ),
    )
    provider = OpenAICompatibleLLMProvider(LLMConfig(api_key="test-key"))

    result = provider.chat_with_tools(
        ToolChatRequest(
            messages=[ToolChatMessage(role="user", content="prompt")],
            tools=[],
        )
    )

    assert result.content == "No more tools needed."
    assert result.tool_calls == []
    assert result.finish_reason == "stop"
    assert result.input_tokens == 30
    assert result.output_tokens == 10
