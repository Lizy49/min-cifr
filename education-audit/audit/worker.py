import json
import logging
import threading
import time
from datetime import timedelta
from pathlib import Path
from sqlalchemy import select, update
from .models import Run, Organization, Result, Page, utcnow
from .crawler import Crawler, parse_html
from .rules import check
from .config import settings
from .ai import analyze

log = logging.getLogger(__name__)

def enqueue(session, org_ids):
    ids = list(dict.fromkeys(org_ids))
    count = 0
    for org in session.scalars(select(Organization).where(Organization.id.in_(ids), Organization.enabled.is_(True)).order_by(Organization.id).with_for_update()):
        existing = session.scalar(select(Run.id).where(Run.org_id == org.id, Run.status.in_(['queued','running'])).limit(1))
        if not existing:
            session.add(Run(org_id=org.id))
            count += 1
    session.commit()
    return count

def claim(factory):
    with factory() as session:
        candidate = session.scalar(select(Run.id).where(Run.status == 'queued').order_by(Run.id).limit(1))
        if candidate is None:
            return None
        changed = session.execute(update(Run).where(Run.id == candidate, Run.status == 'queued').values(
            status='running', started_at=utcnow(), heartbeat_at=utcnow()))
        session.commit()
        return candidate if changed.rowcount == 1 else None

def process(factory, run_id):
    crawler = Crawler(settings())
    try:
        with factory() as session:
            run = session.get(Run, run_id)
            org = run.organization
            url, kind, source_urls = org.url, org.kind, list(org.fact_sources)
        def progress(count):
            with factory() as session:
                session.execute(update(Run).where(Run.id == run_id).values(pages_done=count, heartbeat_at=utcnow()))
                session.commit()
        crawl = crawler.crawl(url, progress)
        results = check(kind, crawl)
        external, source_errors = [], []
        for source_url in source_urls[:5]:
            try:
                if not crawler.permitted(source_url):
                    source_errors.append('Источник запрещён robots.txt или правила недоступны: ' + source_url)
                    continue
                response = crawler.client.get(source_url)
                if response['status'] == 200 and 'html' in response['content_type']:
                    parsed = parse_html(response['url'], response['body'], response.get('encoding'))
                    parsed['status_code'], parsed['category'] = 200, 'external'
                    parsed['fetched_at'] = utcnow()
                    external.append(parsed)
                else:
                    source_errors.append(f"Источник недоступен или не HTML: {source_url} (HTTP {response['status']})")
            except Exception as exc:
                source_errors.append(f'Не удалось прочитать внешний источник {source_url}: {type(exc).__name__}')
            progress(len(crawl['pages']))
        ai = analyze(crawl['pages'], results, external)
        facts = next((r for r in results if r['rule'] == 'factcheck'), None)
        if facts and external:
            facts['explanation'] += f' Загружено внешних источников: {len(external)}. См. доказательства и подсказки ИИ.'
            facts['evidence'] = [{'url': p['url'], 'title': p['title'], 'snippet': p['text'][:900]} for p in external]
        with factory() as session:
            run = session.get(Run, run_id)
            for p in crawl['pages'] + external:
                session.add(Page(run_id=run_id, **p))
            for result in results:
                session.add(Result(run_id=run_id, **result))
            run.status = 'completed' if any(p['status_code']==200 and p['category'] not in ('file','external') for p in crawl['pages']) else 'failed'
            run.finished_at = run.heartbeat_at = utcnow()
            run.error = '' if run.status == 'completed' else 'Не удалось загрузить сайт. См. ограничения и результат доступности.'
            run.meta = {'limited': crawl['limited'], 'issues': crawl['issues'], 'source_errors': source_errors,
                        'remaining': crawl['remaining'], 'settings': settings(), 'ai': ai,
                        'kind_at_run': kind, 'url_at_run': url, 'rules_version': '1.1',
                        'spo_note': 'Чек-лист СПО — расширение задания, а не юридическая экспертиза.'}
            session.commit()
    except Exception:
        log.exception('Audit failed, run=%s', run_id)
        with factory() as session:
            run = session.get(Run, run_id)
            run.status, run.finished_at = 'failed', utcnow()
            run.error = 'Внутренняя ошибка обработки. Подробности записаны в журнал сервера; повторите запуск.'
            session.commit()
    finally:
        crawler.close()

def schedule_due(factory):
    with factory() as session:
        # Single embedded worker per installation; conditional claim also protects queued work.
        due = list(session.scalars(select(Organization).where(Organization.enabled.is_(True),
                   Organization.schedule_hours > 0, Organization.next_run <= utcnow())))
        for org in due:
            org.next_run = utcnow() + timedelta(hours=org.schedule_hours)
        ids = [o.id for o in due]
        session.commit()
        if ids:
            enqueue(session, ids)
        stale = utcnow() - timedelta(minutes=20)
        session.execute(update(Run).where(Run.status == 'running', Run.heartbeat_at < stale).values(
            status='failed', finished_at=utcnow(), error='Рабочий процесс прерван или превысил время обработки. Запустите проверку повторно.'))
        session.commit()

def loop(factory, stop):
    while not stop.is_set():
        try:
            schedule_due(factory)
            run_id = claim(factory)
            if run_id:
                process(factory, run_id)
                continue
        except Exception:
            log.exception('Worker iteration failed')
        stop.wait(3)

def start_worker(factory):
    stop = threading.Event()
    thread = threading.Thread(target=loop, args=(factory, stop), daemon=True, name='audit-worker')
    thread.start()
    return stop

def seed(factory):
    path = Path(__file__).resolve().parent.parent / 'data' / 'organizations.json'
    items = json.loads(path.read_text(encoding='utf-8'))
    with factory() as session:
        existing = set(session.scalars(select(Organization.url)))
        count = 0
        for item in items:
            if item['url'] not in existing:
                session.add(Organization(**item))
                existing.add(item['url'])
                count += 1
        session.commit()
    return count
