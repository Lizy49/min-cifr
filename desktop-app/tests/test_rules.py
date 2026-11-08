from datetime import datetime
from zoneinfo import ZoneInfo

from edu_audit.rules import check

TZ = ZoneInfo("Asia/Magadan")


def make_page(url, category, text="Наполнение страницы " * 30, published=None, event_dates=None,
              event_start=None, event_end=None, article=False):
    return {
        "url": url, "title": category.title(), "category": category, "text": text,
        "status_code": 200, "details": {
            "published": published, "event_dates": event_dates or [],
            "event_start": event_start, "event_end": event_end, "article": article,
            "links": [], "images": [],
        },
    }


def crawl(pages):
    return {"pages": pages, "issues": [], "limited": False, "remaining": 0, "document_limit": 12}


def test_news_older_than_fourteen_days_is_warning():
    page = make_page("https://x.example/news/a.html", "news",
                     published={"value": "2026-10-20T10:00:00+11:00", "precision": "minute"}, article=True)
    result = {item["rule"]: item for item in check("school", crawl([page]), datetime(2026, 11, 8, tzinfo=TZ))}
    assert result["news.recency"]["status"] == "warning"
    assert result["news.recency"]["evidence"][0]["url"] == page["url"]


def test_unrecognized_news_date_is_unknown_not_violation():
    result = {item["rule"]: item for item in check("garden", crawl([
        make_page("https://x.example/news/", "news", published=None)
    ]), datetime(2026, 11, 8, tzinfo=TZ))}
    assert result["news.recency"]["status"] == "unknown"


def test_exact_event_publication_delay_over_24h_is_warning():
    page = make_page("https://x.example/news/item.html", "news",
        published={"value": "2026-11-06T12:00:00+11:00", "precision": "minute"},
        event_end={"value": "2026-11-04T10:00:00+11:00", "precision": "minute"}, article=True)
    result = {item["rule"]: item for item in check("school", crawl([page]), datetime(2026, 11, 8, tzinfo=TZ))}
    assert result["news.24hours"]["status"] == "warning"


def test_date_without_time_cannot_confirm_24_hour_deadline():
    page = make_page("https://x.example/news/item.html", "news",
        published={"value": "2026-11-06", "precision": "day"},
        event_start={"value": "2026-11-05", "precision": "day"}, article=True)
    result = {item["rule"]: item for item in check("school", crawl([page]), datetime(2026, 11, 8, tzinfo=TZ))}
    assert result["news.24hours"]["status"] == "unknown"


def test_missing_section_is_unknown_not_false_positive():
    result = {item["rule"]: item for item in check("school", crawl([
        make_page("https://x.example/", "other")
    ]), datetime(2026, 11, 8, tzinfo=TZ))}
    assert result["section.documents"]["status"] == "unknown"


def test_school_checks_current_and_next_quarter():
    page = make_page("https://x.example/events/", "events", event_dates=[
        {"value": "2026-11-12T10:00:00+11:00", "precision": "minute"},
        {"value": "2027-02-12T10:00:00+11:00", "precision": "minute"},
    ])
    result = {item["rule"]: item for item in check("school", crawl([page]), datetime(2026, 11, 8, tzinfo=TZ))}
    assert result["events.current"]["status"] == "pass"
    assert result["events.next"]["status"] == "pass"


def test_every_finding_has_explanation_and_recommendation_key():
    report = check("garden", crawl([make_page("https://x.example/", "other")]))
    assert report
    assert all("explanation" in item and "recommendation" in item and "status" in item for item in report)



def test_kindergarten_homepage_does_not_count_another_page_as_home():
    page = make_page("https://x.example/about/", "about")
    result = {item["rule"]: item for item in check(
        "garden", {"start_url": "https://x.example/", **crawl([page])},
        datetime(2026, 11, 8, tzinfo=TZ)
    )}
    assert result["section.main"]["status"] == "unknown"


def test_events_are_checked_even_when_url_category_is_not_named_events():
    page = make_page(
        "https://x.example/calendar/",
        "other",
        event_dates=[{"value": "2026-11-12T10:00:00+11:00", "precision": "minute"}],
    )
    result = {item["rule"]: item for item in check(
        "school", crawl([page]), datetime(2026, 11, 8, tzinfo=TZ)
    )}
    assert result["events.current"]["status"] == "pass"


def test_homepage_visual_review_is_explicitly_unknown():
    page = make_page("https://x.example/", "other")
    page["details"]["images"] = [{"url": "https://x.example/logo.png", "alt": ""}]
    result = {item["rule"]: item for item in check(
        "school", {"start_url": "https://x.example/", **crawl([page])},
        datetime(2026, 11, 8, tzinfo=TZ)
    )}
    assert result["quality.homepage_images"]["status"] == "unknown"
    assert "визуальной" in result["quality.homepage_images"]["title"].lower()
