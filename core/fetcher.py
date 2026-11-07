"""
Загрузка страниц сайта.

Отвечает за:
- проверку robots.txt перед обходом;
- скачивание HTML с ограничением частоты запросов (чтобы не перегружать сайт);
- обход внутренних ссылок сайта в пределах одного домена;
- проверку кода ответа для собранных ссылок (поиск неработающих ссылок).
"""

import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

from core.parser import extract_links

USER_AGENT = "EduMonitorAI/1.0 (+site freshness checker for educational organizations)"
REQUEST_TIMEOUT = 10
REQUEST_DELAY = 0.6  # пауза между запросами, чтобы не создавать нагрузку на сайт
MAX_PAGES = 25
MAX_LINK_CHECKS = 40


class FetchResult:
    def __init__(self, url, status_code=None, html=None, error=None):
        self.url = url
        self.status_code = status_code
        self.html = html
        self.error = error

    @property
    def ok(self):
        return self.status_code is not None and 200 <= self.status_code < 400


def is_allowed_by_robots(base_url):
    """Проверяет, разрешает ли robots.txt обход сайта. При недоступности robots.txt не блокирует проверку."""
    try:
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(USER_AGENT, base_url)
    except Exception:
        return True


def fetch_one(url):
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        html = resp.text if resp.ok else None
        return FetchResult(url, status_code=resp.status_code, html=html)
    except requests.RequestException as exc:
        return FetchResult(url, error=str(exc))


def _same_domain(url, base_netloc):
    try:
        return urlparse(url).netloc == base_netloc
    except Exception:
        return False


def crawl_site(base_url, max_pages=MAX_PAGES, progress_callback=None):
    """
    Обходит сайт в пределах его домена, начиная с главной страницы.

    Возвращает:
        visited: dict {url: FetchResult} — реально скачанные страницы сайта;
        link_checks: dict {url: None} — все найденные ссылки (включая внешние),
                     подлежащие дальнейшей проверке на работоспособность.
    """
    base_netloc = urlparse(base_url).netloc
    visited = {}
    to_visit = [base_url]
    link_checks = {}

    while to_visit and len(visited) < max_pages:
        url = to_visit.pop(0)
        if url in visited:
            continue
        if progress_callback:
            progress_callback(len(visited) + 1, max_pages, url)

        result = fetch_one(url)
        visited[url] = result
        time.sleep(REQUEST_DELAY)

        if result.html:
            for link in extract_links(url, result.html):
                link_checks.setdefault(link, None)
                if (
                    _same_domain(link, base_netloc)
                    and link not in visited
                    and link not in to_visit
                    and len(visited) + len(to_visit) < max_pages
                ):
                    to_visit.append(link)

    return visited, link_checks


def check_links_status(link_checks, max_checks=MAX_LINK_CHECKS):
    """Проверяет код ответа для части собранных ссылок (ограничено max_checks)."""
    checked = {}
    for url in list(link_checks.keys())[:max_checks]:
        result = fetch_one(url)
        checked[url] = result.status_code
        time.sleep(REQUEST_DELAY)
    return checked
