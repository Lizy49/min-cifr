"""Transparent checklist rules. Missing evidence is not automatically a violation."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Magadan")
STATUSES = {"pass": "Пройдено", "warning": "Замечание", "error": "Проблема", "unknown": "Нужна ручная проверка"}
PRIORITIES = {"high": "Высокий", "medium": "Средний", "low": "Низкий"}
SECTION_TITLES = {
    "news": "Новости", "events": "Мероприятия", "documents": "Документы",
    "schedule": "Расписание", "staff": "Коллектив и педагогические работники",
    "structure": "Руководство и органы управления", "about": "Сведения об учреждении",
    "contacts": "Контакты", "programs": "Образовательные программы",
    "teachers": "Педагогам и сотрудникам", "main": "Главная страница",
}
REQUIRED = {
    "school": ["news", "events", "documents", "schedule", "about", "structure", "staff", "contacts"],
    "garden": ["main", "news", "staff", "programs", "documents", "teachers", "contacts"],
}
PLACEHOLDERS = (
    r"lorem ipsum", r"укажите (?:название|цели|текст)", r"текст для примера",
    r"демонстрационный контент", r"заполните (?:этот|данный) раздел",
    r"\bзаглушк\w*\b", r"\bдемо[- ]контент\b", r"информация для примера",
)


def _stamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value["value"])
        return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)
    except (KeyError, TypeError, ValueError):
        return None


def _evidence(page, snippet=None):
    return {
        "url": page.get("url", ""), "title": page.get("title", ""),
        "snippet": (snippet or page.get("text", ""))[:900],
        "status_code": page.get("status_code", 0),
    }


def check(kind, crawl, now=None):
    if kind not in REQUIRED:
        raise ValueError(f"Неподдерживаемый тип учреждения: {kind}")
    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    pages = crawl.get("pages", [])
    html = [p for p in pages if p.get("status_code") == 200 and p.get("category") != "file"]
    files = [p for p in pages if p.get("category") == "file"]
    results = []

    def add(rule, section, status, title, explanation, recommendation="", proof=None, priority="medium"):
        results.append({
            "rule": rule, "section": section, "status": status, "priority": priority,
            "title": title, "explanation": explanation, "recommendation": recommendation,
            "evidence": proof or [],
        })

    if not html:
        add("availability", "Доступность", "unknown", "Не удалось получить содержимое сайта",
            "; ".join(crawl.get("issues", [])[:3]) or "Нет доступных HTML-страниц.",
            "Проверьте адрес и доступность сайта, затем повторите проверку.", priority="high")
        return results

    add("availability", "Доступность", "pass", "Сайт отвечает",
        f"Получено HTML-страниц: {len(html)}.", proof=[_evidence(html[0])])
    if crawl.get("limited") or crawl.get("issues"):
        add("coverage", "Охват проверки", "unknown", "Проверка выполнена не полностью",
            f"Осталось адресов: {crawl.get('remaining', 0)}; ограничений/ошибок: {len(crawl.get('issues', []))}.",
            "Учитывайте неполный охват. Для окончательного вывода проверьте сайт вручную.")

    groups = {section: [p for p in html if p.get("category") == section] for section in REQUIRED[kind]}
    # Events can be embedded in calendar pages whose URL is not named "events".
    if "events" in groups:
        groups["events"] = [p for p in html if p.get("category") == "events" or p.get("details", {}).get("event_dates")]
    for section in REQUIRED[kind]:
        found = groups[section]
        if section == "main":
            # For kindergartens the home page itself is required; another "about" page
            # must not accidentally count as the homepage.
            start_url = crawl.get("start_url")
            if start_url:
                found = [p for p in html if p.get("url") == start_url]
            else:
                # Backward-compatible fallback for unit tests and imported crawl data
                # that does not carry an explicit starting URL.
                found = html[:1]
        if not found:
            add("section." + section, SECTION_TITLES[section], "unknown", "Раздел не распознан",
                "В проверенной выборке не найден раздел с ожидаемыми признаками. Он может называться иначе или находиться за пределами обхода.",
                "Проверьте наличие раздела на сайте и при необходимости добавьте понятную ссылку.")
            continue
        filled = [p for p in found if len(p.get("text", "")) >= 160 or p.get("details", {}).get("links")]
        add("section." + section, SECTION_TITLES[section], "pass" if filled else "unknown",
            "Раздел найден" if filled else "В разделе мало извлечённого текста",
            "Обнаружена страница раздела. Сам факт наличия не подтверждает полноту сведений." if filled
            else "Страница может загружаться через JavaScript или содержать только изображения.",
            "" if filled else "Откройте раздел вручную и проверьте, заполнен ли он.", [_evidence((filled or found)[0])])

    # News dates are accepted only when associated with a news article or an archive card.
    articles = []
    for page in groups["news"]:
        details = page.get("details", {})
        published = details.get("published")
        if details.get("article") and _stamp(published):
            articles.append({
                "url": page["url"], "title": page.get("title", ""), "text": page.get("text", ""),
                "published": published, "event_start": details.get("event_start"),
                "event_end": details.get("event_end"), "source_url": page["url"],
                "status_code": page.get("status_code", 200),
            })
        for item in details.get("news_items", []):
            if _stamp(item.get("published")):
                articles.append({
                    "url": item["url"], "title": item.get("title", ""), "text": item.get("snippet", ""),
                    "published": item["published"], "event_start": None, "event_end": None,
                    "source_url": page["url"], "status_code": 200,
                })
    unique = {}
    for article in articles:
        unique[article["url"]] = article
    articles = list(unique.values())
    articles = [item for item in articles if _stamp(item["published"]).date() <= now.date()]
    articles.sort(key=lambda item: _stamp(item["published"]), reverse=True)

    if not articles:
        add("news.recency", "Новости", "unknown", "Не удалось надёжно определить даты новостей",
            "Проверка использует даты, связанные с публикациями. Произвольные даты из текста страницы не считаются датой новости.",
            "Проверьте ленту новостей вручную или настройте структурированные даты.",
            [_evidence(groups["news"][0])] if groups["news"] else [])
    else:
        latest = articles[0]
        age_days = (now.date() - _stamp(latest["published"]).date()).days
        add("news.recency", "Новости", "warning" if age_days > 14 else "pass",
            f"Последняя распознанная новость: {age_days} дн. назад",
            f"Дата публикации: {_stamp(latest['published']).date()}. Требование кейса — новость не реже одного раза в 14 дней. Вывод относится к найденной выборке.",
            "Опубликуйте актуальную новость или проверьте полноту архива." if age_days > 14 else "",
            [_evidence(latest, str(latest["published"]))], "high" if age_days > 28 else "medium")
        gaps = []
        for newer, older in zip(articles, articles[1:]):
            gap = (_stamp(newer["published"]).date() - _stamp(older["published"]).date()).days
            if gap > 14:
                gaps.append((newer, older, gap))
        add("news.intervals", "Новости", "unknown" if gaps or len(articles) < 2 else "pass",
            "Есть промежутки для ручной сверки" if gaps else
            ("Недостаточно публикаций для сравнения" if len(articles) < 2 else "В найденной выборке промежутки не превышают 14 дней"),
            f"Распознано публикаций: {len(articles)}; промежутков больше 14 дней: {len(gaps)}. Пробел в выборке сам по себе не доказывает отсутствие публикаций.",
            "Проверьте архив и пагинацию новостей." if gaps else "",
            [_evidence(item, str(item["published"])) for item in articles[:4]])

    precise_count, late = 0, []
    for article in articles:
        event = article.get("event_end") or article.get("event_start")
        published = article["published"]
        event_dt, published_dt = _stamp(event), _stamp(published)
        if event_dt and published_dt and event.get("precision") == published.get("precision") == "minute":
            precise_count += 1
            delay = (published_dt - event_dt).total_seconds() / 3600
            if delay > 24:
                late.append((article, delay))
    if articles:
        status = "warning" if late else ("pass" if precise_count == len(articles) else "unknown")
        add("news.24hours", "Новости", status,
            "Есть публикации позже 24 часов" if late else
            ("Срок проверен по точным датам" if status == "pass" else "Не хватает точного времени события или публикации"),
            f"Точные пары дат события и публикации найдены для {precise_count} из {len(articles)} публикаций. Даты только с числом и месяцем не позволяют доказать срок в 24 часа.",
            "Проверьте сроки публикации по первичным материалам." if late else "",
            [_evidence(item, f"Задержка {delay:.1f} ч.") for item, delay in late])

    if kind == "school":
        quarter_start = datetime(now.year, ((now.month - 1) // 3) * 3 + 1, 1, tzinfo=TZ)
        def next_quarter_start(date):
            month = date.month + 3
            year = date.year + (month > 12)
            month = month - 12 if month > 12 else month
            return datetime(year, month, 1, tzinfo=TZ)
        next_start = next_quarter_start(quarter_start)
        end_next = next_quarter_start(next_start)
        dated_events = []
        for page in groups["events"]:
            for event_date in page.get("details", {}).get("event_dates", []):
                dt = _stamp(event_date)
                if dt:
                    dated_events.append((page, dt))
        for key, start, end in (("current", quarter_start, next_start), ("next", next_start, end_next)):
            matches = [(p, dt) for p, dt in dated_events if start <= dt < end]
            add("events." + key, "Мероприятия", "pass" if matches else "unknown",
                ("Текущий" if key == "current" else "Следующий") + " квартал: " +
                ("мероприятия найдены" if matches else "даты не подтверждены"),
                f"Период проверки: {start.date()} — {(end - timedelta(days=1)).date()}. Используются структурированные даты мероприятий.",
                "" if matches else "Проверьте календарь мероприятий на текущий и следующий квартал.",
                [_evidence(p, str(dt)) for p, dt in matches[:5]])
        add("events.news_match", "Мероприятия", "unknown", "Связь мероприятий с новостями требует сверки",
            "Наличие плана мероприятий и новостей проверяется отдельно. Совпадение названий не доказывает, что событие состоялось.",
            "Сопоставьте прошедшие мероприятия с новостями о фактическом проведении.")

    # Contact signals are not proof that the details are correct or current.
    contact_sources = groups["contacts"] or html[:1]
    checks = [
        ("email", r"[\w.+-]+@[\w.-]+\.[a-zа-я]{2,}", "Электронная почта"),
        ("phone", r"(?:\+7|8)[\s(.-]*\d{3,5}[\s)\d.-]{5,15}\d", "Телефон"),
        ("hours", r"режим\s+работ|график\s+работ|часы\s+при[её]ма", "Режим работы / часы приёма"),
    ]
    for key, pattern, label in checks:
        matches = [page for page in contact_sources if re.search(pattern, page.get("text", ""), re.I)]
        add("contacts." + key, "Контакты", "pass" if matches else "unknown",
            label + (": найдено" if matches else ": не распознано"),
            "Проверяется наличие сведений, но не их актуальность и достоверность.",
            "" if matches else "Проверьте наличие актуальной контактной информации.",
            [_evidence(page) for page in matches[:2]])

    staff_pages = groups.get("staff", [])
    if staff_pages:
        with_photos = [p for p in staff_pages if p.get("details", {}).get("images")]
        with_education = [p for p in staff_pages if re.search(r"образован|квалификац", p.get("text", ""), re.I)]
        add("staff.completeness", "Коллектив и педагоги", "unknown", "Полнота карточек сотрудников требует ручной проверки",
            f"Страниц с изображениями: {len(with_photos)}; страниц с упоминанием образования/квалификации: {len(with_education)}. Общий признак не подтверждает заполнение каждой карточки.",
            "Проверьте фото, образование, должности и контакты в карточках каждого сотрудника.",
            [_evidence(p) for p in staff_pages[:3]])

    placeholders = []
    for page in html:
        text = page.get("text", "")
        for pattern in PLACEHOLDERS:
            match = re.search(pattern, text, re.I)
            if match:
                placeholders.append((page, text[max(0, match.start() - 80):match.end() + 160]))
                break
    add("quality.placeholders", "Качество заполнения", "warning" if placeholders else "pass",
        "Найдены возможные текстовые заглушки" if placeholders else "Текстовые заглушки не обнаружены в выборке",
        "Проверка ищет ограниченный набор шаблонных фраз. Найденная цитата может требовать ручной оценки.",
        "Замените текст-заглушку реальной информацией или отметьте ложное срабатывание." if placeholders else "",
        [_evidence(page, quote) for page, quote in placeholders[:10]], "low")

    broken_files = [p for p in files if p.get("status_code") in (404, 410)]
    uncertain_files = [p for p in files if p.get("status_code") != 200 and p not in broken_files]
    add("documents.links", "Документы", "error" if broken_files else
        ("pass" if files and not uncertain_files else "unknown"),
        f"Недоступных документов: {len(broken_files)}" if broken_files else f"Проверено файлов: {len(files)}",
        f"Файлов в выборке: {len(files)}. Полнота всего перечня документов не подтверждается ограниченным обходом.",
        "Исправьте или замените ссылки на недоступные документы." if broken_files else
        ("Повторите проверку файлов, доступ к которым ограничен." if uncertain_files else ""),
        [_evidence(p) for p in (broken_files or uncertain_files or files)[:8]], "high")

    # The Gosweb content-quality materials also ask for a visual check of banners,
    # logos and photos. Static HTML metadata is only a signal; appearance and
    # dimensions still require a person to inspect the page.
    homepage = next((p for p in html if p.get("url") == crawl.get("start_url")), html[0])
    images = homepage.get("details", {}).get("images", [])
    if images:
        missing_alt = [image for image in images if not (image.get("alt") or "").strip()]
        add("quality.homepage_images", "Главная страница", "unknown",
            "Изображения требуют визуальной проверки",
            f"Найдено изображений: {len(images)}; без альтернативного описания: {len(missing_alt)}. Размер, чёткость логотипа, соответствие баннера и качество фотографии не подтверждаются HTML-проверкой.",
            "Проверьте логотип, баннер, фотографии и их читаемость непосредственно в браузере.",
            [_evidence(homepage, image.get("url", "")) for image in images[:5]], "low")
    else:
        add("quality.homepage_images", "Главная страница", "unknown",
            "Не удалось распознать изображения главной страницы",
            "Логотип или баннер могут быть оформлены фоновым изображением или загружаться через JavaScript.",
            "Откройте главную страницу в браузере и проверьте логотип и баннер.",
            [_evidence(homepage)], "low")

    if kind == "school":
        add("quality.homepage_profile", "Главная страница", "unknown",
            "Проверьте краткое описание и оформление школы вручную",
            "В приложенном руководстве для школьных сайтов указан ориентир: краткое описание школы — 300–400 символов, изображение или логотип — 1200×900 пикселей. Краулер не может надёжно определить границы этого блока, фактическое разрешение файла, качество снимка, единообразие шрифтов и аккуратность верстки.",
            "Проверьте длину краткого описания, размер и качество изображения, единый стиль текста и отображение страницы в браузере.",
            [_evidence(homepage)], "low")

    return results
