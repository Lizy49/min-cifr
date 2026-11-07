"""
Основная логика проверки сайта.

Ключевой принцип: каждый вывод помечается либо как "факт" (подтверждён
конкретными данными — кодом ответа сервера, найденной датой и т.п.),
либо как "предположение" (раздел не найден в пределах обхода, дата не
распознана и т.д.) — программа никогда не выдаёт предположение за факт.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List

from core import fetcher, parser, checklist

NEWS_MAX_AGE_WEEKS_DEFAULT = 2
CRITICAL_IF_MISSING = {"documents", "contacts", "schedule", "programs"}


@dataclass
class Issue:
    section_id: str
    title: str
    severity: str  # "критично" | "важно" | "незначительно"
    kind: str       # "факт" | "предположение"
    description: str
    recommendation: str


@dataclass
class Report:
    url: str
    org_type: str
    score: float
    issues: List[Issue] = field(default_factory=list)
    pages_checked: int = 0
    links_checked: int = 0
    broken_links: int = 0
    sections_total: int = 0
    sections_present: int = 0
    checked_at: str = ""


def _section_present(keywords, link_items, page_titles):
    """Ищет упоминание раздела по ключевым словам в текстах ссылок и заголовках страниц."""
    if not keywords:
        return True
    kws = [k.lower() for k in keywords]
    for _, text in link_items:
        if any(k in text.lower() for k in kws):
            return True
    for title in page_titles:
        if any(k in title.lower() for k in kws):
            return True
    return False


def _check_news_freshness(item, page_texts, issues):
    all_dates = []
    for text in page_texts:
        all_dates.extend(parser.find_dates(text))

    if not all_dates:
        issues.append(Issue(
            section_id="news_unknown",
            title="Не удалось определить дату последней новости",
            severity="незначительно",
            kind="предположение",
            description=(
                "Автоматический поиск дат на страницах сайта не дал результата. "
                "Это НЕ означает, что новости устарели — формат дат на сайте может "
                "отличаться от распознаваемых программой форматов."
            ),
            recommendation="Проверить дату последней публикации новостей вручную.",
        ))
        return

    latest = max(all_dates)
    age_weeks = (datetime.now() - latest).days / 7
    max_age = item.get("max_age_weeks", NEWS_MAX_AGE_WEEKS_DEFAULT)

    if age_weeks > max_age:
        issues.append(Issue(
            section_id="news_stale",
            title="Новости не обновлялись длительное время",
            severity="критично" if age_weeks > max_age * 2 else "важно",
            kind="факт",
            description=(
                f"Самая свежая дата, найденная на страницах сайта — "
                f"{latest.strftime('%d.%m.%Y')} ({age_weeks:.1f} нед. назад), что "
                f"превышает ожидаемую периодичность обновления ({max_age} нед.)."
            ),
            recommendation="Опубликовать актуальные новости либо подтвердить, что мероприятий за этот период не было.",
        ))


def run_check(url, org_type, progress_callback=None):
    """
    Выполняет полную проверку сайта: обход страниц, сверку с чек-листом,
    поиск неработающих ссылок и расчёт итоговой оценки.
    progress_callback(stage: str, detail: str) вызывается для отображения прогресса в GUI.
    """
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    def report(stage, detail=""):
        if progress_callback:
            progress_callback(stage, detail)

    report("Проверка robots.txt")
    robots_ok = fetcher.is_allowed_by_robots(url)

    report("Обход страниц сайта")

    def crawl_progress(current, total, current_url):
        report(f"Загрузка страниц ({current}/{total})", current_url)

    visited, link_checks = fetcher.crawl_site(url, progress_callback=crawl_progress)

    report("Проверка ссылок на работоспособность")
    checked_statuses = fetcher.check_links_status(link_checks)

    report("Анализ содержимого страниц")

    pages_html = {u: r.html for u, r in visited.items() if r.html}
    link_items = []
    page_titles = []
    page_texts = []
    for page_url, html in pages_html.items():
        link_items.extend(parser.extract_link_items(page_url, html))
        page_titles.append(parser.extract_title(html))
        page_texts.append(parser.extract_visible_text(html))

    checklist_items = checklist.get_checklist(org_type)
    issues = []
    sections_present = 0

    for item in checklist_items:
        present = _section_present(item.get("keywords", []), link_items, page_titles)
        if present:
            sections_present += 1
            if item.get("check_freshness"):
                _check_news_freshness(item, page_texts, issues)
        else:
            issues.append(Issue(
                section_id=item["id"],
                title=f"Раздел «{item['name']}» не найден",
                severity="критично" if item["id"] in CRITICAL_IF_MISSING else "важно",
                kind="предположение",
                description=(
                    f"В пределах {len(pages_html)} проверенных страниц не найдено ссылок или "
                    f"заголовков, относящихся к разделу «{item['name']}». Раздел может быть "
                    f"расположен глубже по структуре сайта и не обнаружен при текущей глубине обхода."
                ),
                recommendation=f"Проверить вручную наличие раздела «{item['name']}» и при необходимости добавить его на сайт.",
            ))

    broken = {u: code for u, code in checked_statuses.items() if code is None or code >= 400}
    for link_url, code in list(broken.items())[:15]:
        issues.append(Issue(
            section_id="broken_link",
            title="Неработающая ссылка",
            severity="важно",
            kind="факт",
            description=(
                f"Ссылка {link_url} возвращает " + (f"код {code}" if code else "ошибку соединения") + "."
            ),
            recommendation="Проверить и исправить или удалить неработающую ссылку.",
        ))

    if not robots_ok:
        issues.append(Issue(
            section_id="robots",
            title="Проверка ограничена правилами robots.txt",
            severity="незначительно",
            kind="факт",
            description="Файл robots.txt сайта ограничивает автоматический обход некоторых страниц.",
            recommendation="Для более полной проверки уточните правила доступа с администратором сайта.",
        ))

    sections_total = len(checklist_items)
    sections_weight = (sections_present / sections_total) if sections_total else 1.0

    links_total = len(checked_statuses) or 1
    links_weight = 1 - (len(broken) / links_total)

    freshness_penalty = sum(1 for i in issues if i.section_id == "news_stale")
    freshness_weight = max(0.0, 1 - freshness_penalty * 0.3)

    score = round(100 * (0.55 * sections_weight + 0.25 * links_weight + 0.20 * freshness_weight), 1)

    return Report(
        url=url,
        org_type=org_type,
        score=score,
        issues=issues,
        pages_checked=len(pages_html),
        links_checked=len(checked_statuses),
        broken_links=len(broken),
        sections_total=sections_total,
        sections_present=sections_present,
        checked_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
