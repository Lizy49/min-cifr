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
