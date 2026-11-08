from edu_audit.crawler import classify, normalize_url, parse_date, parse_html


def test_gosweb_news_item_publication_date_not_event_headline():
    html = """<html><body><main><div><h1>04 ноября 2026 — праздник</h1>
    <div class="gw-content-small-title_gray">02 ноября 2026 г.</div></div>
    <p>Новость о мероприятии.</p></main></body></html>"""
    page = parse_html("https://school.example/novosti-i-sobytiya/item.html", html.encode())
    assert page["details"]["published"]["value"].startswith("2026-11-02")
    assert page["details"]["published"]["precision"] == "day"


def test_archive_cards_keep_individual_publication_dates():
    html = b'''<html><main><h1>News</h1><div itemscope itemtype="https://schema.org/NewsArticle">
    <meta itemprop="datePublished" content="2026-11-06T10:00:00+11:00">
    <div itemprop="headline"><a href="/news/1.html">First news</a></div></div>
    <div itemscope itemtype="https://schema.org/NewsArticle">
    <meta itemprop="datePublished" content="2026-10-01">
    <div itemprop="headline"><a href="/news/2.html">Second news</a></div></div></main></html>'''
    page = parse_html("https://school.example/news/", html)
    assert len(page["details"]["news_items"]) == 2
    assert page["details"]["published"] is None
    assert page["details"]["news_items"][0]["url"] == "https://school.example/news/1.html"


def test_classifies_common_education_sections():
    assert classify("https://school.example/novosti/") == "news"
    assert classify("https://school.example/raspisanie/") == "schedule"
    assert classify("https://school.example/sveden/document/") == "documents"


def test_date_parser_tracks_precision():
    assert parse_date("2026-11-06")["precision"] == "day"
    assert parse_date("2026-11-06T12:30:00+11:00")["precision"] == "minute"


def test_url_normalization_rejects_credentials_and_non_http():
    import pytest
    with pytest.raises(ValueError):
        normalize_url("https://user:password@school.example/")
    with pytest.raises(ValueError):
        normalize_url("ftp://school.example/")
