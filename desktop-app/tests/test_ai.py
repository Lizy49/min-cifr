import json
import time
import uuid

import pytest
import requests

from edu_audit import ai
from edu_audit.exporters import export_html


class Reply:
    def __init__(self, data, code=200):
        self.data = data
        self.status_code = code

    def json(self):
        return self.data


def test_alice_reviews_required_sections_and_exports_grounded_suggestions(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_PROVIDER", "alice")
    monkeypatch.setenv("YANDEX_API_KEY", "test-key")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test-folder")
    source = "https://school.example/schedule"
    findings = [{"rule": f"section.{i}", "status": "unknown"} for i in range(28)]

    def response(text):
        return Reply({"status": "completed", "output": [
            {"type": "reasoning"},
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ]})

    def post(self, url, **kwargs):
        assert url == "https://ai.api.cloud.yandex.net/v1/responses"
        assert kwargs["headers"] == {"Authorization": "Api-Key test-key", "OpenAI-Project": "test-folder"}
        assert kwargs["allow_redirects"] is False
        payload = kwargs["json"]
        assert payload["model"] == "gpt://test-folder/aliceai-llm"
        assert payload["store"] is False
        assert "text" not in payload
        assert "max_output_tokens" in payload
        assert isinstance(payload["input"], str)
        if "instructions" not in payload:
            assert payload["input"] == "Ответь одним словом: OK."
            return response("OK")
        assert "JSON" in payload["instructions"]
        context = json.loads(payload["input"])
        assert any(page["url"] == source for page in context["site_pages"])
        assert len(context["rule_results"]) == len(findings)
        assert "Обязательный раздел: Расписание" in context["technical_specification_checklist"]["criteria"]
        suggestion = {"title": "<Сверить расписание>", "reason": "Есть разночтение.",
                      "recommendation": "Открыть страницу.", "urls": [source, "https://invented.example"]}
        return response("```json\n" + json.dumps({"suggestions": [suggestion]}) + "\n```")

    monkeypatch.setattr(requests.Session, "post", post)
    assert ai.test_connection()["status"] == "ok"
    pages = [{"url": f"https://school.example/news/{i}", "title": "Новость",
              "category": "news", "text": "Текст"} for i in range(25)]
    pages.append({"url": source, "title": "Расписание", "category": "schedule", "text": "Текст"})
    result = ai.analyze(pages, findings, [], organization_kind="school")
    assert result["status"] == "completed"
    assert result["suggestions"][0]["urls"] == [source]
    report = {"organization": {"name": "Школа", "url": "https://school.example"}, "meta": {"ai": result}}
    output = export_html(report, tmp_path / "audit.html").read_text(encoding="utf-8")
    assert "&lt;Сверить расписание&gt;" in output
    assert f'href="{source}"' in output


def test_alice_requires_folder_and_reports_rate_limit(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "alice")
    monkeypatch.setenv("YANDEX_API_KEY", "test-key")
    monkeypatch.delenv("YANDEX_FOLDER_ID", raising=False)
    assert ai.analyze([], [], [])["status"] == "disabled"
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test-folder")
    monkeypatch.setattr(requests.Session, "post", lambda *args, **kwargs: Reply({}, 429))
    result = ai.analyze([], [], [])
    assert result["status"] == "failed"
    assert "лимит" in result["message"]
    assert result["suggestions"] == []


def test_alice_explains_403_without_exposing_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "alice")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test-folder")
    monkeypatch.setenv("YANDEX_API_KEY", "test-secret")
    monkeypatch.setattr(requests.Session, "post", lambda *args, **kwargs: Reply(
        {"error": {"message": "test-secret"}}, 403
    ))
    result = ai.test_connection()
    assert result["status"] == "failed"
    assert "HTTP 403" in result["message"]
    assert "ai.assistants.editor" in result["message"]
    assert "yc.ai.foundationModels.execute" in result["message"]
    assert "test-secret" not in result["message"]


def test_alice_bad_request_identifies_parameter_without_echoing_response(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "alice")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test-folder")
    monkeypatch.setenv("YANDEX_API_KEY", "test-secret")
    reply = Reply({"error": {"param": "input", "message": "test-secret"}}, 400)
    reply.headers = {"x-request-id": "request-123"}
    monkeypatch.setattr(requests.Session, "post", lambda *args, **kwargs: reply)
    result = ai.test_connection()
    assert result["status"] == "failed"
    assert "HTTP 400" in result["message"]
    assert "параметр «input»" in result["message"]
    assert "request-123" in result["message"]
    assert "каталог" not in result["message"]
    assert "test-secret" not in result["message"]


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



def test_deepseek_analysis_compares_reference_site_and_keeps_reference_urls(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    seen = {}

    def post(self, url, **kwargs):
        payload = kwargs["json"]
        user_payload = json.loads(payload["messages"][1]["content"])
        seen.update(user_payload)
        content = json.dumps({"suggestions": [{
            "title": "Сверить структуру раздела",
            "reason": "На эталоне найден дополнительный раздел.",
            "recommendation": "Проверить, требуется ли аналогичный раздел по ТЗ.",
            "urls": ["https://reference.example/about", "https://target.example/about"],
        }]}, ensure_ascii=False)
        return Reply({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(requests.Session, "post", post)
    target = [{
        "url": "https://target.example/about", "title": "О школе",
        "text": "Сведения об учреждении", "category": "about", "details": {},
    }]
    reference = {
        "name": "Эталонная школа", "url": "https://reference.example",
        "pages": [{
            "url": "https://reference.example/about", "title": "О школе",
            "text": "Полные сведения", "category": "about", "status_code": 200,
        }],
        "findings": [{"rule": "section.about", "status": "pass", "title": "Раздел найден"}],
    }

    imported = [{
        "id": "REQ-001", "text": "Публикации должны выходить не реже одного раза в 14 дней.",
        "category": "news", "verification": "news_frequency",
        "threshold": {"max_interval_days": 14}, "review_required": True,
    }]
    result = ai.analyze(
        target, [], [], reference=reference, organization_kind="school",
        requirements=imported,
    )

    assert result["status"] == "completed"
    assert seen["imported_requirements"][0]["id"] == "REQ-001"
    assert seen["imported_requirements"][0]["threshold"] == {"max_interval_days": 14}
    assert seen["technical_specification_checklist"]["organization_type"] == "school"
    assert any("14 дней" in item for item in seen["technical_specification_checklist"]["criteria"])
    assert seen["reference_site"]["organization"] == "Эталонная школа"
    assert len(seen["reference_site"]["pages"]) == 1
    assert result["suggestions"][0]["urls"] == [
        "https://reference.example/about", "https://target.example/about"
    ]


def test_alice_uses_only_final_answer_message(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "alice")
    monkeypatch.setenv("YANDEX_API_KEY", "test-key")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test-folder")

    def post(self, url, **kwargs):
        return Reply({
            "status": "completed",
            "output": [
                {"type": "message", "phase": "commentary",
                 "content": [{"type": "output_text", "text": "Черновой комментарий."}]},
                {"type": "reasoning"},
                {"type": "message", "phase": "final_answer",
                 "content": [{"type": "output_text", "text": "OK"}]},
            ],
        })

    monkeypatch.setattr(requests.Session, "post", post)
    result = ai.test_connection()
    assert result["status"] == "ok"


@pytest.mark.parametrize(
    ("status", "details", "expected"),
    [
        ("in_progress", {}, "ещё обрабатывает"),
        ("incomplete", {"incomplete_details": {"reason": "max_output_tokens"}}, "лимит выходных токенов"),
        ("failed", {"error": {"code": "server_error"}}, "server_error"),
    ],
)
def test_alice_reports_non_completed_responses_safely(monkeypatch, status, details, expected):
    monkeypatch.setenv("AI_PROVIDER", "alice")
    monkeypatch.setenv("YANDEX_API_KEY", "test-key")
    monkeypatch.setenv("YANDEX_FOLDER_ID", "test-folder")
    monkeypatch.setattr(requests.Session, "post", lambda *args, **kwargs: Reply(
        {"status": status, **details}
    ))
    result = ai.test_connection()
    assert result["status"] == "failed"
    assert expected in result["message"]
    assert "test-key" not in result["message"]


def test_alice_is_default_provider_without_saved_configuration(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("YANDEX_API_KEY", raising=False)
    monkeypatch.delenv("YANDEX_FOLDER_ID", raising=False)
    state = ai.public_state()
    assert state["provider"] == "alice"
    assert state["enabled"] is False
    assert "Алиса AI" in state["label"]
