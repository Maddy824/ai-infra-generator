"""Tests for LLM backend request/response handling (no network)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ai_infra.config.settings import settings
from ai_infra.planner.planner import Planner


class _Recorder:
    """Stand-in for ``httpx.post`` that records the call and returns *body*."""

    def __init__(self, body: Any = None, status: int = 200, exc: Exception | None = None):
        self.body = body
        self.status = status
        self.exc = exc
        self.calls: list[dict] = []

    def __call__(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"url": url, **kwargs})
        if self.exc:
            raise self.exc
        return httpx.Response(self.status, json=self.body, request=httpx.Request("POST", url))


@pytest.fixture()
def planner(tmp_path) -> Planner:
    return Planner(tmp_path)


class TestCleanJsonExtraction:
    def test_extracts_fenced_block_after_prose(self):
        raw = 'Here is the plan:\n```json\n{"project_name": "x"}\n```\nLet me know!'
        assert Planner._clean_json(raw) == '{"project_name": "x"}'

    def test_extracts_bare_object_surrounded_by_prose(self):
        raw = 'Sure! {"project_name": "x", "a": {"b": 1}} Hope that helps.'
        assert Planner._clean_json(raw) == '{"project_name": "x", "a": {"b": 1}}'


class TestClaudeBackend:
    def test_joins_text_blocks_and_skips_thinking(self, planner, monkeypatch):
        rec = _Recorder({
            "stop_reason": "end_turn",
            "content": [
                {"type": "thinking", "thinking": ""},
                {"type": "text", "text": '{"project_name": "x"}'},
            ],
        })
        monkeypatch.setattr(httpx, "post", rec)
        monkeypatch.setattr(settings, "CLAUDE_API_KEY", "test-key")

        assert planner._call_claude("sys", "user") == '{"project_name": "x"}'
        sent = rec.calls[0]["json"]
        assert sent["model"] == settings.CLAUDE_MODEL
        assert sent["max_tokens"] == settings.LLM_MAX_TOKENS

    def test_refusal_raises(self, planner, monkeypatch):
        rec = _Recorder({
            "stop_reason": "refusal",
            "stop_details": {"type": "refusal", "category": "cyber"},
            "content": [],
        })
        monkeypatch.setattr(httpx, "post", rec)
        monkeypatch.setattr(settings, "CLAUDE_API_KEY", "test-key")

        with pytest.raises(RuntimeError, match="declined"):
            planner._call_claude("sys", "user")

    def test_fallbacks_can_be_disabled(self, planner, monkeypatch):
        rec = _Recorder({"stop_reason": "end_turn", "content": [{"type": "text", "text": "{}"}]})
        monkeypatch.setattr(httpx, "post", rec)
        monkeypatch.setattr(settings, "CLAUDE_API_KEY", "test-key")
        monkeypatch.setattr(settings, "CLAUDE_FALLBACKS", False)

        planner._call_claude("sys", "user")

        assert "fallbacks" not in rec.calls[0]["json"]
        assert "anthropic-beta" not in rec.calls[0]["headers"]

    def test_missing_key_raises(self, planner, monkeypatch):
        monkeypatch.setattr(settings, "CLAUDE_API_KEY", None)
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            planner._call_claude("sys", "user")


class TestGeminiBackend:
    def test_api_key_sent_as_header_not_in_url(self, planner, monkeypatch):
        rec = _Recorder({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
        monkeypatch.setattr(httpx, "post", rec)
        monkeypatch.setattr(settings, "GEMINI_API_KEY", "secret-key")

        assert planner._call_gemini("sys", "user") == "{}"
        assert "secret-key" not in rec.calls[0]["url"]
        assert rec.calls[0]["headers"]["x-goog-api-key"] == "secret-key"

    def test_unexpected_shape_raises_runtime_error(self, planner, monkeypatch):
        monkeypatch.setattr(httpx, "post", _Recorder({"candidates": []}))
        monkeypatch.setattr(settings, "GEMINI_API_KEY", "secret-key")

        with pytest.raises(RuntimeError, match="Unexpected Gemini response"):
            planner._call_gemini("sys", "user")


class TestOllamaBackend:
    def test_requests_json_format(self, planner, monkeypatch):
        rec = _Recorder({"response": "{}"})
        monkeypatch.setattr(httpx, "post", rec)

        assert planner._call_ollama("sys", "user") == "{}"
        assert rec.calls[0]["json"]["format"] == "json"


class TestTransportErrors:
    def test_http_error_becomes_runtime_error(self, planner, monkeypatch):
        monkeypatch.setattr(httpx, "post", _Recorder({"error": "boom"}, status=500))
        with pytest.raises(RuntimeError, match="HTTP 500"):
            planner._call_ollama("sys", "user")

    def test_connect_error_becomes_runtime_error(self, planner, monkeypatch):
        monkeypatch.setattr(httpx, "post", _Recorder(exc=httpx.ConnectError("refused")))
        with pytest.raises(RuntimeError, match="Is Ollama running"):
            planner._call_ollama("sys", "user")

    def test_timeout_becomes_runtime_error(self, planner, monkeypatch):
        monkeypatch.setattr(httpx, "post", _Recorder(exc=httpx.ReadTimeout("slow")))
        with pytest.raises(RuntimeError, match="timed out"):
            planner._call_ollama("sys", "user")
