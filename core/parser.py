"""
Разбор HTML-страниц сайта: извлечение ссылок, видимого текста, заголовков и дат,
упомянутых в тексте (для определения свежести новостей).
"""

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

MONTHS_RU = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}

_DATE_NUMERIC = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_DATE_TEXTUAL = re.compile(r"\b(\d{1,2})\s+([а-яёА-ЯЁ]+)\s+(\d{4})\b")

_SKIP_HREF_PREFIXES = ("#", "javascript:", "mailto:", "tel:")


def _is_skippable_href(href):
    return href.lower().startswith(_SKIP_HREF_PREFIXES)


def extract_links(base_url, html):
    """Возвращает множество абсолютных URL всех ссылок на странице."""
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or _is_skippable_href(href):
            continue
        links.add(urljoin(base_url, href))
    return links


def extract_link_items(base_url, html):
    """Возвращает список (url, текст_ссылки) — нужно для сопоставления с чек-листом разделов."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or _is_skippable_href(href):
            continue
        text = a.get_text(separator=" ", strip=True)
        items.append((urljoin(base_url, href), text))
    return items


def extract_visible_text(html):
    """Возвращает весь видимый текст страницы (без скриптов и стилей)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def extract_title(html):
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return ""


def find_dates(text):
    """
    Ищет даты в тексте в форматах «ДД.ММ.ГГГГ» и «5 ноября 2026».
    Возвращает список объектов datetime (без учёта времени).
    Не является гарантией правильной интерпретации всех дат на странице —
    используется как вспомогательный сигнал, а не как окончательный факт.
    """
    found = []

    for match in _DATE_NUMERIC.finditer(text):
        day, month, year = match.groups()
        try:
            found.append(datetime(int(year), int(month), int(day)))
        except ValueError:
            continue

    for match in _DATE_TEXTUAL.finditer(text):
        day, month_word, year = match.groups()
        month_word_lower = month_word.lower()
        month_num = next(
            (num for stem, num in MONTHS_RU.items() if month_word_lower.startswith(stem)),
            None,
        )
        if month_num:
            try:
                found.append(datetime(int(year), month_num, int(day)))
            except ValueError:
                continue

    return found
