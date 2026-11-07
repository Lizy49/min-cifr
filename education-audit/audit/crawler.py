import hashlib
import io
import json
import re
import time
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, unquote
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from .network import PublicClient, FetchError, normalize_url
from .encoding import html_soup

SECTIONS = {
    'news': ('новост', '/news', '/novosti', 'press-center'),
    'events': ('мероприят', 'событи', '/events', 'calendar'),
    'documents': ('документ', '/document', 'dokument', '/sveden/document', 'устав', 'лицензии'),
    'schedule': ('расписан', 'schedule', 'raspisanie'),
    'staff': ('педагогический состав', 'наш коллектив', 'руководство', '/employees', '/managers', '/sveden/employees'),
    'structure': ('структура', 'орган управления', '/struct'),
    'about': ('о школе', 'об учреждении', 'история', '/about', '/sveden/common'),
    'contacts': ('контакт', 'contacts'),
    'programs': ('образовательные программы', 'образовательных программ', 'специальност', 'професси', '/education', '/sveden/education'),
    'teachers': ('педагогам и сотрудникам', 'повышение квалификации', 'for-teachers'),
    'admission': ('приемная комиссия', 'приёмная комиссия', 'абитуриент', 'правила приема', 'правила приёма', 'abitur'),
    'support': ('стипенд', 'общежит', 'меры поддержки', '/grants'),
    'practice': ('трудоустройств', 'практик', '/vacant', '/jobs'),
}
DOCUMENT_EXT = ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.odt', '.rtf')
SKIP_EXT = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.zip', '.mp4', '.mp3', '.css', '.js')

def extraction_note(status_code, category, text, details):
    if status_code >= 400:
        return f'Сервер вернул HTTP {status_code}; содержимое страницы ошибки не используется как данные учреждения.'
    if details.get('document_error'):
        return details['document_error']
    if not text.strip():
        return 'Ответ получен, но текст не извлечён. Возможны пустая страница, защитная проверка или загрузка через JavaScript.'
    return ''

def classify(url, title=''):
    value = (unquote(urlsplit(url).path) + ' ' + title).lower().replace('ё', 'е')
    # Specific education sections precede generic /about URLs.
    for category in ('admission', 'schedule', 'contacts', 'documents', 'staff', 'structure',
                     'programs', 'teachers', 'support', 'practice', 'news', 'events', 'about'):
        if any(token.replace('ё', 'е') in value for token in SECTIONS[category]):
            return category
    return 'other'

def parse_datetime(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return {'value': parsed.isoformat(), 'precision': 'minute' if re.search(r'\d{1,2}:\d{2}', value) else 'day'}
    except ValueError:
        pass
    match = re.search(r'\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b', value)
    if match:
        try:
            return {'value': datetime(int(match[3]), int(match[2]), int(match[1])).isoformat(), 'precision': 'day'}
        except ValueError:
            return None
    months = ('январ', 'феврал', 'март', 'апрел', 'мая', 'июн', 'июл', 'август', 'сентябр', 'октябр', 'ноябр', 'декабр')
    match = re.search(r'\b(\d{1,2})\s+([а-яё]+)\s+(20\d{2})\b', value.lower())
    if match:
        for number, month in enumerate(months, 1):
            if match[2].startswith(month):
                try:
                    return {'value': datetime(int(match[3]), number, int(match[1])).isoformat(), 'precision': 'day'}
                except ValueError:
                    return None
    return None

def structured_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from structured_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from structured_objects(child)

def parse_html(url, body, encoding=None):
    soup, detected_encoding = html_soup(body, encoding)
    title_node = soup.find('h1') or soup.title
    title = title_node.get_text(' ', strip=True) if title_node else ''
    category = classify(url, title)
    links = []
    for a in soup.select('a[href]'):
        href = a.get('href', '').strip()
        if href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
            continue
        try:
            target = normalize_url(urljoin(url, href))
        except ValueError:
            continue
        links.append({'url': target, 'title': a.get_text(' ', strip=True)[:400]})
    details = {'published': None, 'event_start': None, 'event_end': None,
               'event_dates': [], 'article': False, 'images': [], 'links': links, 'news_items': [], 'encoding': detected_encoding}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            values = structured_objects(json.loads(script.get_text()))
            for obj in values:
                types = obj.get('@type', [])
                types = [types] if isinstance(types, str) else types
                if any(t in types for t in ('NewsArticle', 'Article', 'BlogPosting')):
                    details['article'] = True
                    details['published'] = parse_datetime(obj.get('datePublished')) or details['published']
                if 'Event' in types:
                    start = parse_datetime(obj.get('startDate'))
                    if start:
                        details['event_dates'].append(start)
                    details['event_start'] = start or details['event_start']
                    details['event_end'] = parse_datetime(obj.get('endDate')) or details['event_end']
        except (ValueError, TypeError):
            continue
    for card in soup.select('[itemtype$="/NewsArticle"], [itemtype$="/Article"]'):
        date_node = card.select_one('[itemprop="datePublished"]')
        anchor = card.select_one('[itemprop="headline"] a[href], a[itemprop="url"], .gw-news-item__title-link')
        if date_node and anchor:
            published = parse_datetime(date_node.get('content') or date_node.get('datetime') or date_node.get_text(' ',strip=True))
            try:
                article_url = normalize_url(urljoin(url,anchor.get('href','')))
            except ValueError:
                continue
            if published:
                details['news_items'].append({'url':article_url, 'title':anchor.get_text(' ',strip=True), 'published':published,
                                             'snippet':card.get_text(' ',strip=True)[:900]})
    for selector in ('meta[property="article:published_time"]', '[itemprop="datePublished"]'):
        # A date inside an archive card is that card's publication date, not the archive's.
        if len(soup.select('[itemprop="datePublished"]'))>1 or details['news_items']:
            continue
        node = soup.select_one(selector)
        if node:
            stamp = parse_datetime(node.get('content') or node.get('datetime') or node.get_text(' ', strip=True))
            if stamp:
                details['published'], details['article'] = stamp, True
                break
    main = soup.find('main') or soup.find('article') or soup.find(id='content') or soup.body or soup
    # Navigation and page chrome cannot count as actual section content.
    main = BeautifulSoup(str(main), 'html.parser')
    for node in main.select('script, style, nav, header, footer, aside, noscript, input, select, button, .breadcrumb, .breadcrumbs'):
        node.decompose()
    text = re.sub(r'\s+', ' ', main.get_text(' ', strip=True)).strip()
    if category == 'news' and not details['published']:
        # A single time element on a leaf article is usable; archive pages with many times are not.
        times = main.select('time')
        if len(times) == 1 and (main.find('article') or soup.find('article')):
            details['published'] = parse_datetime(times[0].get('datetime') or times[0].get_text())
            details['article'] = bool(details['published'])
        # Gosweb leaf pages expose their publication label immediately after h1.
        # Read that specific label, never the event date embedded in a headline.
        if not details['news_items'] and urlsplit(url).path.endswith('.html'):
            h1 = main.find('h1')
            parent = h1.parent if h1 else None
            label = parent.select_one('.gw-content-small-title_gray') if parent else None
            if label:
                details['published'] = parse_datetime(label.get_text(' ',strip=True))
                details['article'] = bool(details['published'])
    for node in soup.select('[itemprop="startDate"]'):
        date = parse_datetime(node.get('content') or node.get('datetime') or node.get_text(' ',strip=True))
        if date:
            details['event_dates'].append(date)
    if category == 'events' and len(details['event_dates'])==1 and urlsplit(url).path.endswith('.html'):
        details['event_start']=details['event_dates'][0]
    for image in main.select('img'):
        src = image.get('src', '') or image.get('data-src', '')
        details['images'].append({'url': urljoin(url, src), 'alt': image.get('alt', '')[:200]})
    details['phones'] = sorted(set(re.findall(r'(?:\+7|8)[\s(.-]*\d{3,5}[\s)\d.-]{5,15}\d', text)))[:30]
    details['emails'] = sorted(set(re.findall(r'[\w.+-]+@[\w.-]+\.[a-zа-я]{2,}', text, re.I)))[:30]
    return {'url': url, 'title': title[:1000], 'category': category,
            'text': text[:160000], 'digest': hashlib.sha256(body).hexdigest(), 'details': details}

class Crawler:
    def __init__(self, config, client=None):
        self.config = config
        self.client = client or PublicClient(config['timeout'], config['delay'])
        self.robots = {}

    def permitted(self, url):
        parts = urlsplit(url)
        origin = f'{parts.scheme}://{parts.netloc}'
        if origin not in self.robots:
            try:
                response = self.client.get(origin + '/robots.txt')
                robot = RobotFileParser()
                if response['status'] in (401, 403) or response['status'] >= 500:
                    self.robots[origin] = False
                elif response['status'] >= 400:
                    self.robots[origin] = True
                else:
                    robot.parse(response['body'].decode('utf-8', errors='replace').splitlines())
                    self.robots[origin] = robot
            except FetchError:
                self.robots[origin] = False
        value = self.robots[origin]
        return value if isinstance(value, bool) else value.can_fetch('EducationAudit', url)

    def crawl(self, start_url, progress=lambda count: None):
        start_url = normalize_url(start_url)
        queue, seen, pages = deque([start_url]), set(), []
        host = urlsplit(start_url).hostname
        deadline = time.monotonic() + self.config['seconds']
        issues, documents, count = [], 0, 0
        while queue and count < self.config['max_pages'] and time.monotonic() < deadline:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            if not self.permitted(url):
                issues.append(f'robots.txt запрещает обход или не удалось прочитать правила: {url}')
                continue
            count += 1
            try:
                response = self.client.get(url)
                actual_host = urlsplit(response['url']).hostname
                if len(pages) == 0 and url == start_url:
                    host = actual_host
                elif actual_host != host:
                    issues.append(f'Переход за пределы сайта пропущен: {url}')
                    continue
                body, code, content_type = response['body'], response['status'], response['content_type'].lower()
                is_document = urlsplit(url).path.lower().endswith(DOCUMENT_EXT) or 'application/pdf' in content_type
                if is_document:
                    documents += 1
                    text, doc_error = '', ''
                    if code == 200 and ('pdf' in content_type or body.startswith(b'%PDF')):
                        try:
                            from pypdf import PdfReader
                            reader = PdfReader(io.BytesIO(body))
                            text = '\n'.join((page.extract_text() or '') for page in reader.pages[:30])[:160000]
                            if not text.strip():
                                doc_error = 'PDF без текстового слоя; требуется OCR или ручная проверка.'
                        except Exception:
                            doc_error = 'Не удалось извлечь текст PDF.'
                    elif code == 200:
                        doc_error = 'Файл доступен; содержание этого формата автоматически не разобрано.'
                    page = {'url': response['url'], 'title': unquote(urlsplit(url).path.split('/')[-1]),
                            'category': 'file', 'text': text, 'digest': hashlib.sha256(body).hexdigest(),
                            'details': {'document_error': doc_error, 'content_type': content_type, 'links': []}}
                elif 'html' in content_type or b'<html' in body[:1000].lower():
                    page = parse_html(response['url'], body, response.get('encoding'))
                else:
                    issues.append(f'Неподдерживаемый тип ответа: {url}')
                    continue
                page['status_code'] = code
                page['fetched_at'] = datetime.now(timezone.utc).replace(tzinfo=None)
                if code >= 400:
                    page['text'] = ''
                    issues.append(f'HTTP {code}: {url}')
                page['details']['extraction_note'] = extraction_note(code,page['category'],page['text'],page['details'])
                pages.append(page)
                if code < 400 and page['category'] != 'file':
                    candidates = []
                    for link in page['details']['links']:
                        target = link['url']
                        part = urlsplit(target)
                        if part.hostname != host or target in seen or part.path.lower().endswith(SKIP_EXT):
                            continue
                        if re.search(r'(logout|login|search|print|feedback|auth)', part.path, re.I):
                            continue
                        if part.path.lower().endswith(DOCUMENT_EXT):
                            pending_docs = sum(urlsplit(u).path.lower().endswith(DOCUMENT_EXT) for u in queue)
                            if documents + pending_docs >= self.config['max_documents']:
                                continue
                        candidates.append(link)
                    candidates.sort(key=lambda a: classify(a['url'], a['title']) == 'other')
                    # Prioritize section roots discovered on the home page, then pagination and leaves.
                    for item in candidates:
                        if item['url'] not in queue:
                            queue.append(item['url'])
                progress(len(pages))
            except FetchError as exc:
                issues.append(f'{url}: {exc}')
        limited = bool(queue)
        return {'pages': pages, 'issues': issues[:80], 'limited': limited,
                'remaining': len(queue), 'document_limit': self.config['max_documents'],
                'complete': not limited and not issues}

    def close(self):
        self.client.close()
