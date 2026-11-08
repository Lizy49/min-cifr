import json
import time
import uuid

import pytest
import requests

from edu_audit import ai


class Reply:
    def __init__(self, data, code=200):
        self.data = data
        self.status_code = code

    def json(self):
        return self.data


def test_ai_disabled_keeps_rule_based_audit_available(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    result = ai.analyze([], [], [])
    assert result["enabled"] is False
    assert result["status"] == "disabled"
    assert result["suggestions"] == []


def test_gigachat_missing_key_does_not_make_network_request(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gigachat")
    monkeypatch.delenv("GIGACHAT_CREDENTIALS", raising=False)
    def fail(*args, **kwargs):
        raise AssertionError("Network must not be used without credentials")
    monkeypatch.setattr(requests.Session, "post", fail)
    assert ai.test_connection()["status"] == "not_configured"
    assert ai.analyze([], [], [])["status"] == "disabled"


def test_gigachat_token_and_suggestions_use_only_source_urls(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gigachat")
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "test-authorisation-key")
    monkeypatch.setenv("GIGACHAT_MODEL", "GigaChat")
    monkeypatch.setenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    ai._TOKENS.clear()
    calls = []

    def post(self, url, **kwargs):
        calls.append(url)
        assert kwargs.get("verify") is True
        assert kwargs.get("allow_redirects") is False
        if "oauth" in url:
            assert kwargs["headers"]["Authorization"] == "Basic test-authorisation-key"
            assert uuid.UUID(kwargs["headers"]["RqUID"]).version == 4
            return Reply({"access_token": "fake-token", "expires_at": (time.time() + 1800) * 1000})
        assert kwargs["headers"]["Authorization"] == "Bearer fake-token"
        assert kwargs["json"]["response_format"]["type"] == "json_schema"
        payload = {"suggestions": [{
            "title": "Сверить мероприятие", "reason": "Требуется подтверждение.",
            "recommendation": "Проверить новость.", "urls": [
                "https://school.example/news/1", "https://invented.example/not-real"
            ],
        }]}
        return Reply({"choices": [{"message": {"content": json.dumps(payload)}}]})

    monkeypatch.setattr(requests.Session, "post", post)
    pages = [{
        "url": "https://school.example/news/1", "title": "Новость",
        "text": "Текст", "category": "news", "details": {},
    }]
    result = ai.analyze(pages, [], [])
    assert result["status"] == "completed"
    assert result["suggestions"][0]["urls"] == ["https://school.example/news/1"]
    assert sum("oauth" in item for item in calls) == 1
    ai._TOKENS.clear()


@pytest.mark.parametrize("provider", ["other-provider", ""])
def test_unknown_ai_provider_is_disabled_safely(monkeypatch, provider):
    monkeypatch.setenv("AI_PROVIDER", provider)
    assert ai.public_state()["enabled"] is False
    assert ai.analyze([], [], [])["status"] == "disabled"



def test_gemini_missing_key_does_not_make_network_request(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    def fail(*args, **kwargs):
        raise AssertionError("Network must not be used without Gemini API key")
    monkeypatch.setattr(requests.Session, "post", fail)
    assert ai.public_state()["enabled"] is False
    assert ai.test_connection()["status"] == "not_configured"
    assert ai.analyze([], [], [])["status"] == "disabled"


def test_gemini_generate_content_uses_api_key_header_and_filters_urls(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    calls = []

    def post(self, url, **kwargs):
        calls.append((url, kwargs))
        assert kwargs["headers"]["x-goog-api-key"] == "fake-gemini-key"
        assert kwargs["allow_redirects"] is False
        assert kwargs["json"]["model"] == "deepseek-flash"
        assert kwargs["json"]["thinking"] == {"type": "disabled"}
        if len(calls) == 2:
            assert kwargs["json"]["response_format"] == {"type": "json_object"}
        if "maxOutputTokens" in kwargs["json"].get("generationConfig", {}):
            payload = {"suggestions": [{
                "title": "Сверить новость", "reason": "Есть расхождение.",
                "recommendation": "Проверить дату.", "urls": [
                    "https://school.example/news/1", "https://fake.example/no"
                ],
            }]}
            return Reply({"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]})
        return Reply({"candidates": [{"content": {"parts": [{"text": "OK"}]}}]})

    monkeypatch.setattr(requests.Session, "post", post)
    pages = [{
        "url": "https://school.example/news/1", "title": "Новость",
        "text": "Текст", "category": "news", "details": {},
    }]
    assert ai.test_connection()["status"] == "ok"
    result = ai.analyze(pages, [], [])
    assert result["status"] == "completed"
    assert result["suggestions"][0]["urls"] == ["https://school.example/news/1"]
    assert len(calls) == 2


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
def test_gemini_http_errors_are_readable(monkeypatch, status):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setattr(requests.Session, "post", lambda *a, **k: Reply({}, status))
    result = ai.test_connection()
    assert result["status"] == "failed"
    assert "Gemini" in result["message"]


def test_deepseek_connection_and_analysis_use_chat_completions(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    calls = []

    def post(self, url, **kwargs):
        calls.append((url, kwargs))
        assert url == "https://api.deepseek.com/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer test-deepseek-key"
        assert kwargs["allow_redirects"] is False
        assert kwargs["json"]["model"] == "deepseek-flash"
        assert kwargs["json"]["thinking"] == {"type": "disabled"}
        if len(calls) == 2:
            assert kwargs["json"]["response_format"] == {"type": "json_object"}
        if len(calls) == 1:
            content = "OK"
        else:
            content = json.dumps({"suggestions": [{
                "title": "Проверить публикацию",
                "reason": "Дата требует сверки.",
                "recommendation": "Сопоставить с независимым источником.",
                "urls": ["https://school.example/news/1", "https://fake.example/no"],
            }]}, ensure_ascii=False)
        return Reply({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(requests.Session, "post", post)
    assert ai.public_state()["provider"] == "deepseek"
    assert ai.test_connection()["status"] == "ok"
    result = ai.analyze([{
        "url": "https://school.example/news/1", "title": "Новость",
        "text": "Текст", "category": "news", "details": {},
    }], [], [])
    assert result["status"] == "completed"
    assert result["suggestions"][0]["urls"] == ["https://school.example/news/1"]
    assert len(calls) == 2


def test_deepseek_missing_key_does_not_make_network_request(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def fail(*args, **kwargs):
        raise AssertionError("Network must not be used without DeepSeek API key")

    monkeypatch.setattr(requests.Session, "post", fail)
    assert ai.public_state()["enabled"] is False
    assert ai.test_connection()["status"] == "not_configured"
    assert ai.analyze([], [], [])["status"] == "disabled"
