"""Bounded crawler for public educational websites."""
from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import re
import socket
import time
from collections import deque
from datetime import datetime
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

try:
    from pypdf import PdfReader
except ImportError:  # PDF extraction is optional; availability is still checked.
    PdfReader = None

TZ_NAME = "Asia/Magadan"
MAX_RESPONSE_BYTES = 3_000_000
DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".odt", ".rtf")
SKIP_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".zip", ".mp4", ".mp3", ".css", ".js")

SECTION_TOKENS = {
    "news": ("новост", "/news", "/novosti", "press-center"),
    "events": ("мероприят", "событи", "/events", "calendar"),
    "documents": ("документ", "/document", "dokument", "/sveden/document", "устав", "лицензи"),
    "schedule": ("расписан", "schedule", "raspisanie"),
    "staff": ("педагогический состав", "наш коллектив", "руководство", "/employees", "/managers", "/sveden/employees", "коллектив"),
    "structure": ("структура", "орган управления", "/struct"),
    "about": ("о школе", "об учреждении", "история", "/about", "/sveden/common", "основные сведения"),
    "contacts": ("контакт", "contacts"),
    "programs": ("образовательные программы", "образовательных программ", "специальност", "професси", "/education", "/sveden/education"),
    "teachers": ("педагогам и сотрудникам", "повышение квалификации", "for-teachers", "сотрудникам"),
}


def normalize_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("Введите адрес сайта.")
    if "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("Поддерживаются только публичные адреса HTTP и HTTPS.")
    if parts.username or parts.password:
        raise ValueError("Адрес сайта не должен содержать логин или пароль.")
    if parts.port not in (None, 80, 443):
        raise ValueError("Разрешены только стандартные порты HTTP и HTTPS.")
    host = parts.hostname.encode("idna").decode("ascii").lower()
    if ":" in host:
        host = f"[{host}]"
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))


def validate_public_url(url: str) -> str:
    """Reject localhost, private, loopback, link-local and reserved IP targets."""
    url = normalize_url(url)
    host = urlsplit(url).hostname
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise RuntimeError("Не удалось определить адрес сайта (DNS).") from exc
    if not addresses:
        raise RuntimeError("DNS не вернул IP-адрес сайта.")
    for item in addresses:
        address = ipaddress.ip_address(item[4][0])
        if not address.is_global:
            raise RuntimeError("Обращение к локальным и служебным адресам запрещено.")
    return url


class SafeHttpClient:
    """HTTP client with redirect validation, byte limits and explicit timeouts."""

    def __init__(self, timeout: int = 10, delay: float = 0.3):
        self.timeout = timeout
        self.delay = delay
        self.last_request = 0.0
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({
            "User-Agent": "GoswebAudit/0.1 (+educational website quality checker)",
            "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.5",
        })

    def get(self, url: str) -> dict:
        current = url
        for _ in range(6):
            current = validate_public_url(current)
            wait = self.delay - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            self.last_request = time.monotonic()
            try:
                with self.session.get(
                    current, timeout=(self.timeout, self.timeout),
                    stream=True, allow_redirects=False
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            raise RuntimeError("Сайт вернул перенаправление без адреса.")
                        current = urljoin(current, location)
                        continue
                    body = bytearray()
                    deadline = time.monotonic() + self.timeout * 2
                    for chunk in response.iter_content(32768):
                        if chunk:
                            body.extend(chunk)
                            if len(body) > MAX_RESPONSE_BYTES:
                                raise RuntimeError("Ответ сайта превышает ограничение 3 МБ.")
                            if time.monotonic() > deadline:
                                raise RuntimeError("Превышено время загрузки ответа.")
                    content_type = response.headers.get("Content-Type", "")
                    charset_match = re.search(r"charset\s*=\s*['\"]?([^;\s'\"]+)", content_type, re.I)
                    return {
                        "url": current,
                        "status": response.status_code,
                        "content_type": content_type,
                        "encoding": charset_match.group(1) if charset_match else None,
                        "body": bytes(body),
                    }
            except requests.RequestException as exc:
                raise RuntimeError(f"Ошибка соединения: {type(exc).__name__}.") from exc
        raise RuntimeError("Слишком много перенаправлений.")


def parse_date(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        precision = "minute" if re.search(r"\d{1,2}:\d{2}", value) else "day"
        return {"value": parsed.isoformat(), "precision": precision}
    except ValueError:
        pass
    match = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b", value)
    if match:
        try:
            return {"value": datetime(int(match[3]), int(match[2]), int(match[1])).isoformat(), "precision": "day"}
        except ValueError:
            return None
    months = ("январ", "феврал", "март", "апрел", "мая", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр")
    match = re.search(r"\b(\d{1,2})\s+([а-яё]+)\s+(20\d{2})\b", value.lower())
    if match:
        for number, month in enumerate(months, 1):
            if match[2].startswith(month):
                try:
                    return {"value": datetime(int(match[3]), number, int(match[1])).isoformat(), "precision": "day"}
                except ValueError:
                    return None
    return None


def classify(url: str, title: str = "") -> str:
    value = (urlsplit(url).path + " " + title).lower().replace("ё", "е")
    order = ("news", "events", "documents", "schedule", "staff", "structure", "about", "contacts", "programs", "teachers")
    for category in order:
        if any(token.replace("ё", "е") in value for token in SECTION_TOKENS[category]):
            return category
    return "other"


def _walk_jsonld(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_jsonld(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_jsonld(child)


def parse_html(url: str, body: bytes, encoding: str | None = None) -> dict:
    soup = BeautifulSoup(body, "html.parser", from_encoding=encoding)
    title_node = soup.find("h1") or soup.title
    title = title_node.get_text(" ", strip=True) if title_node else ""
    category = classify(url, title)
    details = {
        "published": None, "event_start": None, "event_end": None,
        "event_dates": [], "article": False, "images": [], "links": [],
        "news_items": [],
    }
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            raw = json.loads(node.get_text())
        except (ValueError, TypeError):
            continue
        for item in _walk_jsonld(raw):
            kinds = item.get("@type", [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if any(kind in kinds for kind in ("NewsArticle", "Article", "BlogPosting")):
                details["article"] = True
                details["published"] = parse_date(item.get("datePublished")) or details["published"]
            if "Event" in kinds:
                start = parse_date(item.get("startDate"))
                end = parse_date(item.get("endDate"))
                if start:
                    details["event_dates"].append(start)
                details["event_start"] = start or details["event_start"]
                details["event_end"] = end or details["event_end"]

    for card in soup.select('[itemtype$="/NewsArticle"], [itemtype$="/Article"]'):
        date_node = card.select_one('[itemprop="datePublished"]')
        anchor = card.select_one('[itemprop="headline"] a[href], a[itemprop="url"], .gw-news-item__title-link')
        if date_node and anchor:
            published = parse_date(date_node.get("content") or date_node.get("datetime") or date_node.get_text(" ", strip=True))
            try:
                article_url = normalize_url(urljoin(url, anchor.get("href", "")))
            except ValueError:
                continue
            if published:
                details["news_items"].append({
                    "url": article_url, "title": anchor.get_text(" ", strip=True),
                    "published": published, "snippet": card.get_text(" ", strip=True)[:900],
                })

    if not details["news_items"] and len(soup.select('[itemprop="datePublished"]')) <= 1:
        node = soup.select_one('meta[property="article:published_time"], [itemprop="datePublished"]')
        if node:
            published = parse_date(node.get("content") or node.get("datetime") or node.get_text(" ", strip=True))
            if published:
                details["published"], details["article"] = published, True

    main = soup.find("main") or soup.find("article") or soup.find(id="content") or soup.body or soup
    main = BeautifulSoup(str(main), "html.parser")
    for node in main.select("script,style,nav,header,footer,aside,noscript,input,select,button,.breadcrumb,.breadcrumbs"):
        node.decompose()
    text = re.sub(r"\s+", " ", main.get_text(" ", strip=True)).strip()

    if category == "news" and not details["published"]:
        times = main.select("time")
        if len(times) == 1 and (main.find("article") or soup.find("article")):
            details["published"] = parse_date(times[0].get("datetime") or times[0].get_text())
            details["article"] = bool(details["published"])
        # Gosweb article pages put the publication date in this label, not in the headline.
        if not details["news_items"] and urlsplit(url).path.endswith(".html"):
            h1 = main.find("h1")
            parent = h1.parent if h1 else None
            label = parent.select_one(".gw-content-small-title_gray") if parent else None
            if label:
                details["published"] = parse_date(label.get_text(" ", strip=True))
                details["article"] = bool(details["published"])

    for node in soup.select('[itemprop="startDate"]'):
        date_value = parse_date(node.get("content") or node.get("datetime") or node.get_text(" ", strip=True))
        if date_value:
            details["event_dates"].append(date_value)
    if category == "events" and len(details["event_dates"]) == 1 and urlsplit(url).path.endswith(".html"):
        details["event_start"] = details["event_dates"][0]

    for image in main.select("img"):
        details["images"].append({
            "url": urljoin(url, image.get("src", "") or image.get("data-src", "")),
            "alt": image.get("alt", "")[:200],
        })
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        try:
            target = normalize_url(urljoin(url, href))
        except ValueError:
            continue
        details["links"].append({"url": target, "title": anchor.get_text(" ", strip=True)[:300]})

    return {
        "url": url, "title": title[:1000], "category": category, "text": text[:160000],
        "digest": hashlib.sha256(body).hexdigest(), "details": details,
    }


class Crawler:
    def __init__(self, max_pages=60, max_documents=12, seconds=180, timeout=12, delay=0.3, client=None):
        self.max_pages = max(1, min(int(max_pages), 300))
        self.max_documents = max(0, min(int(max_documents), 50))
        self.seconds = max(10, int(seconds))
        self.client = client or SafeHttpClient(timeout=timeout, delay=delay)
        self.robots = {}

    def permitted(self, url):
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            try:
                response = self.client.get(origin + "/robots.txt")
                if response["status"] in (401, 403) or response["status"] >= 500:
                    self.robots[origin] = False
                elif response["status"] >= 400:
                    self.robots[origin] = True
                else:
                    robot = RobotFileParser()
                    robot.parse(response["body"].decode("utf-8", errors="replace").splitlines())
                    self.robots[origin] = robot
            except Exception:
                self.robots[origin] = False
        value = self.robots[origin]
        return value if isinstance(value, bool) else value.can_fetch("GoswebAudit", url)

    def crawl(self, start_url, progress=None):
        start_url = normalize_url(start_url)
        validate_public_url(start_url)
        host = urlsplit(start_url).hostname
        queue, seen, pages, issues = deque([start_url]), set(), [], []
        deadline = time.monotonic() + self.seconds
        documents = 0
        while queue and len(pages) < self.max_pages and time.monotonic() < deadline:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            if not self.permitted(url):
                issues.append(f"Обход ограничен robots.txt или правила недоступны: {url}")
                continue
            try:
                response = self.client.get(url)
                actual_host = urlsplit(response["url"]).hostname
                if actual_host != host:
                    issues.append(f"Перенаправление на другой домен пропущено: {url}")
                    continue
                code = response["status"]
                content_type = response["content_type"].lower()
                path = urlsplit(url).path.lower()
                is_file = path.endswith(DOCUMENT_EXTENSIONS) or "application/pdf" in content_type
                if is_file:
                    documents += 1
                    text, note = "", ""
                    if code == 200 and ("pdf" in content_type or response["body"].startswith(b"%PDF")):
                        if PdfReader:
                            try:
                                reader = PdfReader(io.BytesIO(response["body"]))
                                text = "\n".join((p.extract_text() or "") for p in reader.pages[:30])[:160000]
                                if not text.strip():
                                    note = "PDF без текстового слоя; нужна ручная проверка или OCR."
                            except Exception:
                                note = "Не удалось извлечь текст PDF."
                        else:
                            note = "Файл PDF доступен; для чтения текста установите pypdf."
                    elif code == 200:
                        note = "Файл доступен, но его формат пока не анализируется автоматически."
                    page = {
                        "url": response["url"], "title": path.rsplit("/", 1)[-1],
                        "category": "file", "text": text, "digest": hashlib.sha256(response["body"]).hexdigest(),
                        "details": {"document_error": note, "links": []},
                    }
                elif "html" in content_type or b"<html" in response["body"][:1000].lower():
                    page = parse_html(response["url"], response["body"], response.get("encoding"))
                else:
                    issues.append(f"Не поддерживаемый тип ответа: {url}")
                    continue
                page["status_code"] = code
                page["fetched_at"] = datetime.now().astimezone().isoformat()
                page["content_type"] = content_type
                if code >= 400:
                    page["text"] = ""
                    issues.append(f"HTTP {code}: {url}")
                if page["category"] == "file" and documents > self.max_documents:
                    issues.append(f"Достигнут лимит документов ({self.max_documents}).")
                    continue
                pages.append(page)
                if code < 400 and page["category"] != "file":
                    candidates = []
                    for link in page["details"]["links"]:
                        target = link["url"]
                        part = urlsplit(target)
                        if part.hostname != host or target in seen or part.path.lower().endswith(SKIP_EXTENSIONS):
                            continue
                        if re.search(r"(logout|login|search|print|feedback|auth)", part.path, re.I):
                            continue
                        if part.path.lower().endswith(DOCUMENT_EXTENSIONS):
                            pending = sum(urlsplit(item).path.lower().endswith(DOCUMENT_EXTENSIONS) for item in queue)
                            if documents + pending >= self.max_documents:
                                continue
                        candidates.append(link)
                    candidates.sort(key=lambda item: classify(item["url"], item["title"]) == "other")
                    for item in candidates:
                        if item["url"] not in queue:
                            queue.append(item["url"])
                if progress:
                    progress(f"Загружено страниц: {len(pages)}")
            except Exception as exc:
                issues.append(f"{url}: {str(exc)[:300]}")
        limited = bool(queue)
        if time.monotonic() >= deadline:
            issues.append("Достигнут лимит времени обхода.")
            limited = True
        return {
            "pages": pages, "issues": issues[:100], "limited": limited,
            "remaining": len(queue), "document_limit": self.max_documents,
            "complete": not limited and not issues,
        }

    def close(self):
        if hasattr(self.client, "session"):
            self.client.session.close()
