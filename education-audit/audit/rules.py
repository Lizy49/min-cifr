"""Evidence-based checks. Heuristics stay 'unknown' rather than fabricated violations."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KINDS = {'school': 'Школа', 'garden': 'Детский сад', 'college': 'Колледж', 'technical': 'Техникум'}
STATUSES = {'pass': 'Пройдено', 'warning': 'Замечание', 'error': 'Проблема',
            'unknown': 'Нужна проверка', 'na': 'Не применяется'}
PRIORITIES = {'high': 'Высокий', 'medium': 'Средний', 'low': 'Низкий'}
TZ = ZoneInfo('Asia/Magadan')
SECTION_TITLES = {'news': 'Новости', 'events': 'Мероприятия', 'documents': 'Документы',
    'schedule': 'Расписание', 'staff': 'Педагогический состав и руководство',
    'structure': 'Структура и органы управления', 'about': 'Об учреждении',
    'contacts': 'Контакты', 'programs': 'Образовательные программы',
    'teachers': 'Педагогам и сотрудникам', 'admission': 'Приёмная комиссия',
    'support': 'Стипендии и меры поддержки', 'practice': 'Практика и трудоустройство'}

def stamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value['value'])
        return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)
    except (ValueError, KeyError, TypeError):
        return None

def evidence(page, snippet=None):
    return {'url': page['url'], 'title': page['title'], 'snippet': (snippet or page['text'])[:900],
            'status_code': page['status_code'], 'digest': page.get('digest', ''),
            'source_url':page.get('details',{}).get('source_url','')}

def check(kind, crawl, now=None):
    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    pages, results = crawl['pages'], []
    good = [p for p in pages if p['status_code'] == 200]
    html = [p for p in good if p['category'] != 'file']
    def add(rule, section, status, title, explanation, recommendation='', proof=None, priority='medium'):
        results.append(dict(rule=rule, section=section, status=status, priority=priority,
            title=title, explanation=explanation, recommendation=recommendation, evidence=proof or []))
    if not html:
        add('availability', 'Доступность', 'unknown', 'Не удалось проверить сайт',
            '; '.join(crawl['issues'][:3]) or 'Нет доступных HTML-страниц.',
            'Проверьте адрес и доступность сайта; повторите проверку.', priority='high')
        return results
    add('availability', 'Доступность', 'pass', 'Сайт доступен', f'Загружено HTML-страниц: {len(html)}.', proof=[evidence(html[0])])
    if crawl['limited'] or crawl['issues']:
        add('coverage', 'Охват', 'unknown', 'Обход неполный',
            f"Осталось адресов в очереди: {crawl['remaining']}. Ошибок/ограничений: {len(crawl['issues'])}.",
            'Учитывайте ограниченный охват; при необходимости увеличьте лимиты или проверьте вручную.')
    required = ['news', 'documents', 'staff', 'contacts']
    required += {'school': ['events', 'schedule', 'about', 'structure'],
                 'garden': ['programs', 'teachers'],
                 'college': ['programs', 'admission', 'schedule', 'structure', 'support', 'practice'],
                 'technical': ['programs', 'admission', 'schedule', 'structure', 'support', 'practice']}[kind]
    groups = {name: [p for p in html if p['category'] == name] for name in required}
    for category in required:
        group = groups[category]
        if not group:
            # Do not equate failure to recognize a page with absence of required content.
            add('section.' + category, SECTION_TITLES[category], 'unknown', 'Раздел не распознан',
                'Среди загруженных страниц раздел не определён. Он может иметь другое название или не попасть в обход.',
                'Откройте сайт и уточните адрес раздела.', proof=[evidence(html[0])])
        else:
            filled = [p for p in group if len(p['text']) >= 160 or any(
                re.search(r'\.(pdf|docx?|xlsx?)(?:\?|$)', a['url'], re.I) for a in p['details'].get('links', []))]
            add('section.' + category, SECTION_TITLES[category], 'pass' if filled else 'unknown',
                'Найден раздел с содержимым' if filled else 'В разделе мало извлечённого текста',
                'Наличие содержимого установлено; это не подтверждает его полноту и актуальность.' if filled else
                'Страница может загружать данные через JavaScript или содержать только изображения.',
                '' if filled else 'Проверьте раздел вручную; при необходимости заполните его.',
                [evidence((filled or group)[0])])
    articles = [p for p in html if p['category'] == 'news' and p['details'].get('article') and stamp(p['details'].get('published'))]
    for source in html:
        for item in source['details'].get('news_items',[]):
            if not any(p['url']==item['url'] for p in articles):
                articles.append({'url':item['url'],'title':item['title'],'text':item['snippet'],
                    'status_code':200,'digest':source.get('digest',''),
                    'details':{'published':item['published'],'source_url':source['url']}})
    future = [p for p in articles if stamp(p['details']['published']).date() > now.date()]
    articles = [p for p in articles if p not in future]
    if future:
        add('news.future', 'Новости', 'unknown', 'Обнаружена дата публикации в будущем',
            'Дата могла быть распознана неверно или материал запланирован.', 'Уточните дату публикации.',
            [evidence(p, str(p['details']['published'])) for p in future[:4]])
    if articles:
        articles.sort(key=lambda p: stamp(p['details']['published']), reverse=True)
        last = articles[0]
        days = (now.date() - stamp(last['details']['published']).date()).days
        add('news.recency', 'Новости', 'warning' if days > 14 else 'pass',
            f'Последняя найденная новость: {days} дн. назад',
            f"Дата публикации {stamp(last['details']['published']).date().isoformat()}. Порог кейса — 14 дней. "
            'Более свежие материалы могут находиться за пределами обхода.',
            'Проверьте полноту ленты и актуализируйте новости.' if days > 14 else '',
            [evidence(last, str(last['details']['published']))])
        gaps = [(a, b, (stamp(a['details']['published']).date() - stamp(b['details']['published']).date()).days)
                for a, b in zip(articles, articles[1:])]
        large = [g for g in gaps if g[2] > 14]
        add('news.intervals', 'Новости', 'unknown' if large or len(articles) < 2 else 'pass',
            'Есть интервалы для сверки' if large else ('Недостаточно дат для сравнения' if len(articles) < 2 else 'В найденной выборке интервалы не превышают 14 дней'),
            f'Распознано публикаций: {len(articles)}. Промежутков больше 14 дней: {len(large)}. '
            'Большой промежуток требует сверки полноты архива, а не доказывает отсутствие промежуточных новостей.',
            'Проверьте архив новостей.' if large else '',
            [evidence(p, str(p['details']['published'])) for p in articles[:4]])
    else:
        add('news.recency', 'Новости', 'unknown', 'Даты публикаций надёжно не извлечены',
            'Проверка использует структурированные даты статей, а не произвольные даты из текста.',
            'Проверьте ленту вручную или добавьте структурированные даты.')
    delays, precise = [], 0
    for page in articles:
        published, ended = page['details']['published'], page['details'].get('event_end') or page['details'].get('event_start')
        if ended and published['precision'] == ended['precision'] == 'minute':
            precise += 1
            hours = (stamp(published) - stamp(ended)).total_seconds() / 3600
            if hours > 24:
                delays.append((page, hours))
    add('news.24hours', 'Новости', 'warning' if delays else ('pass' if precise and precise == len(articles) else 'unknown'),
        'Публикации позже 24 часов' if delays else ('Срок проверен по точным датам' if precise and precise == len(articles) else 'Не хватает точных дат событий'),
        f'Статей с точными датами публикации и события: {precise} из {len(articles)}. '
        'Дата без времени недостаточна для уверенной проверки срока 24 часа.',
        'Уточните время события и публикации.', [evidence(p, f'Задержка {hours:.1f} ч.') for p, hours in delays])
    if kind == 'school':
        quarter_start = datetime(now.year, ((now.month - 1)//3)*3+1, 1, tzinfo=TZ)
        def plus_quarter(date):
            return datetime(date.year + (date.month > 9), (date.month+2) % 12+1, 1, tzinfo=TZ)
        next_q, end_q = plus_quarter(quarter_start), plus_quarter(plus_quarter(quarter_start))
        event_pages = [p for p in html if p['category'] == 'events']
        dated = [(p, stamp(d)) for p in event_pages for d in p['details'].get('event_dates', []) if stamp(d)]
        for key, start, end in [('current', quarter_start, next_q), ('next', next_q, end_q)]:
            found = [(p, date) for p, date in dated if start <= date < end]
            add('events.'+key, 'Мероприятия', 'pass' if found else 'unknown',
                f"{'Текущий' if key == 'current' else 'Следующий'} квартал: " + ('мероприятия найдены' if found else 'даты не подтверждены'),
                f'Период {start.date()} — {(end-timedelta(days=1)).date()}. Используются структурированные даты событий.',
                '' if found else 'Проверьте календарь мероприятий.', [evidence(p, str(date)) for p,date in found[:4]])
        add('events.news_match', 'Мероприятия', 'unknown', 'Связь мероприятий с новостями требует сверки',
            'Одинаковые слова в заголовках не доказывают проведение события. Материалы передаются ИИ для подсказок, если он включён.',
            'Сопоставьте прошедшие мероприятия с публикациями.')
    contact_pages = groups.get('contacts', []) + html[:1]
    contact_text = ' '.join(p['text'] for p in contact_pages).lower()
    for field, regex, label in [('email', r'[\w.+-]+@[\w.-]+\.[a-zа-я]{2,}', 'Электронная почта'),
                               ('phone', r'(?:\+7|8)[\s(.-]*\d{3,5}[\s)\d.-]{5,15}\d', 'Телефон'),
                               ('hours', r'режим\s+работ|график\s+работ|часы\s+при[её]ма', 'Режим работы / часы приёма')]:
        matching = [p for p in contact_pages if re.search(regex, p['text'], re.I)]
        add('contacts.'+field, 'Контакты', 'pass' if matching else 'unknown', label + (': найдено' if matching else ': не распознано'),
            'Проверяется наличие сведений; достоверность телефона и соблюдение часов работы требуют внешней сверки.',
            '' if matching else 'Проверьте наличие и актуальность сведений.', [evidence(p) for p in matching[:2]])
    staff = groups.get('staff', [])
    if staff:
        photos = [p for p in staff if p['details'].get('images')]
        education = [p for p in staff if re.search(r'образован|квалификац', p['text'], re.I)]
        add('staff.completeness', 'Педагогический состав', 'unknown', 'Полнота карточек сотрудников требует сверки',
            f'Страниц с изображениями: {len(photos)}, с упоминанием образования/квалификации: {len(education)}. '
            'Наличие общей фотографии или слова «образование» не подтверждает заполнение каждой карточки.',
            'Проверьте фото, образование и контакты в каждой карточке.', [evidence(p) for p in staff[:3]])
    placeholders = []
    for page in html:
        match = re.search(r'укажите (?:название|цели|текст)|текст (?:заглушки|для примера)|lorem ipsum|демонстрационный контент', page['text'], re.I)
        if match:
            placeholders.append((page, page['text'][max(0, match.start()-80):match.end()+160]))
    add('quality.placeholders', 'Качество заполнения', 'warning' if placeholders else 'pass',
        'Найдены возможные заглушки' if placeholders else 'Текстовые заглушки не обнаружены в выборке',
        'Сопоставление с типичными шаблонными фразами из методических материалов. Цитата примера может быть ложным срабатыванием.',
        'Замените шаблонный текст или отметьте ложное срабатывание.' if placeholders else '',
        [evidence(p, text) for p,text in placeholders[:10]], priority='low')
    files = [p for p in pages if p['category'] == 'file']
    broken = [p for p in files if p['status_code'] in (404, 410)]
    uncertain = [p for p in files if p['status_code'] != 200 and p not in broken]
    add('documents.links', 'Документы', 'error' if broken else ('pass' if files and not uncertain else 'unknown'),
        f'Недоступных документов: {len(broken)}' if broken else f'Проверено файлов: {len(files)}',
        f"Лимит загрузки файлов: {crawl['document_limit']}. Полный перечень определяется только в пределах обхода. "
        'Другие HTTP-ошибки рассматриваются как неопределённость, а не отсутствие файла.',
        'Восстановите файлы или замените ссылки.' if broken else ('Повторите проверку файлов с ошибками доступа.' if uncertain else ''), [evidence(p) for p in (broken or uncertain or files)[:8]], priority='high')
    if kind in ('college', 'technical'):
        admission = groups.get('admission', [])
        years = [p for p in admission if str(now.year) in p['text']]
        add('admission.year', 'Приёмная комиссия', 'unknown', 'Актуальность приёмной кампании требует проверки',
            f'Страниц с упоминанием {now.year} года: {len(years)}. Само упоминание года не подтверждает актуальность правил приёма.',
            'Проверьте год кампании, сроки, специальности и контактные данные.', [evidence(p) for p in admission[:3]])
    add('factcheck', 'Фактчекинг', 'unknown', 'Факты требуют подтверждения по внешним источникам',
        'При заданных внешних источниках будут загружены их тексты. ИИ может предложить сопоставления; '
        'отсутствие подтверждения не означает ложность новости.', 'Добавьте ссылки на независимые официальные публикации и сверьте факты.')
    return results
