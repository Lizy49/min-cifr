import json
import re
from datetime import datetime
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from audit.crawler import parse_html, parse_datetime, Crawler
from audit.models import Base, Organization, Run, Result
from audit.network import normalize_url, validate_public, FetchError
from audit.rules import check, TZ
from audit.web import create_app
from audit.worker import enqueue, claim, schedule_due

def page(url='https://school.example/news/item', date='2026-10-18T10:00:00+11:00', extra=None):
    value={'@type':'NewsArticle','datePublished':date}
    if extra: value.update(extra)
    html=f'<html><body><main><article><h1>Новости школы</h1><script type="application/ld+json">{json.dumps(value)}</script><p>Проведено мероприятие.</p></article></main></body></html>'
    p=parse_html(url,html.encode())
    p['status_code']=200
    return p

def crawl(pages,limited=False):
    return {'pages':pages,'issues':[],'limited':limited,'remaining':1 if limited else 0,'document_limit':12}

def results(pages,kind='school',now=None):
    return {r['rule']:r for r in check(kind,crawl(pages),now or datetime(2026,11,7,tzinfo=TZ))}

def test_news_recency_uses_publication_not_arbitrary_text():
    p=page();p['text']+=' Конкурс 07.11.2026'
    r=results([p])['news.recency']
    assert '20 дн.' in r['title']
    assert r['status']=='warning'
    assert r['evidence'][0]['url']==p['url']

def test_missing_event_date_is_unknown_not_violation():
    assert results([page()])['news.24hours']['status']=='unknown'

def test_precise_event_delay():
    p=page(date='2026-11-06T12:00:00+11:00')
    p['details']['event_end']=parse_datetime('2026-11-04T10:00:00+11:00')
    assert results([p])['news.24hours']['status']=='warning'
    p['details']['event_end']=parse_datetime('2026-11-04')
    assert results([p])['news.24hours']['status']=='unknown'

def test_day_precision_cannot_prove_24_hours():
    p=page(date='2026-11-06')
    p['details']['event_start']=parse_datetime('2026-11-01')
    assert results([p])['news.24hours']['status']=='unknown'

def test_intervals_do_not_claim_absence_from_sample():
    r=results([page(date='2026-11-06'),page(url='https://school.example/news/old',date='2026-09-01')])
    assert r['news.intervals']['status']=='unknown'

def test_quarter_wraps_year():
    p=page(url='https://school.example/events/item')
    p['category']='events'
    p['details']['event_dates']=[parse_datetime('2027-02-10T12:00:00+11:00')]
    r=results([p],now=datetime(2026,12,30,tzinfo=TZ))
    assert r['events.next']['status']=='pass'
    assert r['events.current']['status']=='unknown'

def test_timezones_are_magadan():
    r=results([page(date='2026-11-06T16:00:00Z')])['news.recency']
    assert '0 дн.' in r['title']

def test_unavailable_site_does_not_produce_missing_sections():
    r=check('garden',{'pages':[],'issues':['timeout'],'limited':False,'remaining':0,'document_limit':2})
    assert len(r)==1 and r[0]['status']=='unknown'

def test_college_specific_rules():
    r=results([page()],kind='college')
    assert 'section.admission' in r and 'admission.year' in r
    assert 'events.next' not in r

def test_document_access_denied_is_not_success_or_missing_file():
    p=page();file=page(url='https://x.example/test.pdf');file['category']='file';file['status_code']=403
    assert results([p,file])['documents.links']['status']=='unknown'
    file['status_code']=404
    assert results([p,file])['documents.links']['status']=='error'

def test_navigation_does_not_count_as_content():
    p=parse_html('https://x.example/contacts',b'<html><body><nav>Education phone +7 999 999 99 99</nav><main><h1>Contacts</h1></main></body></html>')
    assert '+7' not in p['text']

def test_archive_cards_have_separate_dates_and_keep_form_content():
    html=b'''<html><main><h1>News</h1><form><div itemscope itemtype="https://schema.org/NewsArticle">
    <meta itemprop="datePublished" content="2026-11-06T10:00:00+11:00">
    <div itemprop="headline"><a href="/news/1.html">First news</a></div></div>
    <div itemscope itemtype="https://schema.org/NewsArticle"><meta itemprop="datePublished" content="2026-10-01">
    <div itemprop="headline"><a href="/news/2.html">Second news</a></div></div></form></main></html>'''
    p=parse_html('https://x.example/news/',html);p['status_code']=200
    assert p['details']['published'] is None
    assert len(p['details']['news_items'])==2
    assert 'First news' in p['text']
    assert '1 дн.' in results([p])['news.recency']['title']
    assert results([p])['news.recency']['evidence'][0]['source_url']=='https://x.example/news/'

def test_gosweb_leaf_date_is_not_headline_event_date():
    html='<html><main><div><h1>04 ноября 2026 — праздник</h1><div class="gw-content-small-title_gray">02 ноября 2026 г.</div></div><p>Новость.</p></main></html>'
    p=parse_html('https://x.example/novosti-i-sobytiya/item.html',html.encode())
    assert p['category']=='news'
    assert p['details']['published']['value'].startswith('2026-11-02')
    assert p['details']['published']['precision']=='day'

def test_old_russian_encoding_is_detected_without_http_charset():
    html='<html><head><meta charset="windows-1251"></head><body><main><h1>Документы колледжа</h1></main></body></html>'
    p=parse_html('https://x.example/info/',html.encode('cp1251'))
    assert p['title']=='Документы колледжа'
    assert p['category']=='documents'

def test_legacy_encoding_repair_and_correct_text_preservation():
    from audit.encoding import repair_legacy
    text='Магаданский колледж искусств'
    broken=text.encode('cp1251').decode('latin1')
    assert repair_legacy(broken)==text
    assert repair_legacy(text)==text
    text='Сведения об образовательной организации » Магаданский колледж искусств'
    assert repair_legacy(text.encode('cp1251').decode('cp866'))==text
    assert repair_legacy(text.encode('cp1251').decode('cp1125'))==text
    broken='╤тхфхэш\xa0 юс юсЁрчютрҐхы№эющ юЁурэшчрІшш » ╠рурфрэёъшщ ъюыыхфц шёъґёёҐт'
    assert repair_legacy(broken)==text

def test_utf8_overrides_incorrect_http_latin1():
    p=parse_html('https://x.example/', '<html><h1>Новости школы</h1></html>'.encode('utf-8'),'ISO-8859-1')
    assert p['title']=='Новости школы'

def test_empty_sources_have_explicit_reasons():
    from audit.crawler import extraction_note
    assert 'HTTP 503' in extraction_note(503,'other','',{})
    assert 'JavaScript' in extraction_note(200,'other','',{})
    assert extraction_note(200,'file','',{'document_error':'Требуется OCR'})=='Требуется OCR'
    assert extraction_note(200,'news','Нормальный текст',{})==''

@pytest.mark.parametrize('value', ['http://user:pass@example.com/','ftp://example.com/','http://example.com:3306/'])
def test_unsafe_url_rejected(value):
    with pytest.raises(ValueError): normalize_url(value)

def test_private_network_rejected(monkeypatch):
    monkeypatch.setattr('audit.network.socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',0))])
    with pytest.raises(FetchError): validate_public('https://example.com/')

def test_robots_denial_is_not_empty_site():
    class Client:
        def get(self,url):
            assert url.endswith('/robots.txt')
            return {'status':200,'body':b'User-agent: *\nDisallow: /','url':url}
    c=Crawler({'max_pages':5,'max_documents':2,'seconds':10,'timeout':1,'delay':0},Client())
    data=c.crawl('https://x.example/')
    assert not data['pages'] and data['issues'] and not data['complete']

@pytest.fixture
def db():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    with factory() as session:
        org=Organization(name='Тестовая школа',kind='school',url='https://school.example/')
        session.add(org);session.commit()
    yield factory,engine
    engine.dispose()

@pytest.fixture
def client(db,monkeypatch):
    monkeypatch.setenv('SECRET_KEY','test-secret-key-for-tests-only')
    app=create_app(*db);app.config['TESTING']=True
    return app.test_client()

def token(client,path='/'):
    html=client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([a-f0-9]+)"',html)[1]

def test_queue_csrf_and_deduplication(client,db):
    assert client.post('/checks',data={'org_ids':'1'}).status_code==400
    csrf=token(client)
    for _ in range(2):
        assert client.post('/checks',data={'org_ids':'1','csrf_token':csrf}).status_code==302
    with db[0]() as session:
        assert len(list(session.scalars(select(Run))))==1
    assert claim(db[0])==1
    assert claim(db[0]) is None

def test_report_exports_reviews_and_xss(client,db):
    with db[0]() as session:
        run=Run(org_id=1,status='completed');session.add(run);session.flush()
        session.add(Result(run_id=run.id,rule='test',section='Новости',status='warning',priority='medium',
            title='<script>alert(1)</script>',explanation='=HYPERLINK("https://bad")',recommendation='Проверить',
            evidence=[{'url':'https://school.example/news/1','title':'News','snippet':'<img src=x>'}]))
        session.commit()
    html=client.get('/runs/1').get_data(as_text=True)
    assert '&lt;script&gt;alert' in html and '<script>alert' not in html
    assert client.get('/runs/1/export.json').json['results'][0]['evidence'][0]['url'].endswith('/1')
    csv=client.get('/runs/1/export.csv').get_data(as_text=True)
    assert "'=HYPERLINK" in csv
    csrf=token(client,'/runs/1')
    assert client.post('/results/1/review',data={'csrf_token':csrf,'review':'dismissed','note':'Проверено'}).status_code==302
    assert 'Ложное срабатывание' in client.get('/runs/1').get_data(as_text=True)

def test_pages_without_results_render(client):
    for path in ('/','/history','/organizations/1','/organizations/new','/comparison','/comparison?group=spo','/methodology','/health'):
        assert client.get(path).status_code==200, path

def test_schedule_enqueues_due_only(db):
    from audit.models import utcnow
    from datetime import timedelta
    with db[0]() as session:
        org=session.get(Organization,1);org.schedule_hours=24;org.next_run=utcnow()-timedelta(seconds=1);session.commit()
    schedule_due(db[0]);schedule_due(db[0])
    with db[0]() as session:
        assert len(list(session.scalars(select(Run))))==1
        assert session.get(Organization,1).next_run>utcnow()

def test_worker_persists_sources_and_results(db,monkeypatch):
    from audit import worker
    class FakeCrawler:
        def __init__(self,*args): pass
        def crawl(self,url,progress):
            progress(1)
            return crawl([page()])
        def close(self): pass
    monkeypatch.setattr(worker,'Crawler',FakeCrawler)
    monkeypatch.setattr(worker,'analyze',lambda *args:{'enabled':False,'status':'disabled'})
    with db[0]() as session:
        session.add(Run(org_id=1,status='queued'));session.commit()
    rid=claim(db[0]);worker.process(db[0],rid)
    with db[0]() as session:
        run=session.get(Run,rid)
        assert run.status=='completed' and len(run.pages)==1
        assert run.pages[0].digest
        assert any(r.rule=='news.recency' and r.evidence for r in run.results)
        assert run.meta['rules_version']=='1.1'

def test_ai_can_be_disabled_and_failure_is_explicit(monkeypatch):
    from audit.ai import analyze
    monkeypatch.setenv('AI_PROVIDER','ollama')
    monkeypatch.delenv('OLLAMA_MODEL',raising=False)
    assert analyze([],[],[])['status']=='disabled'
    monkeypatch.setenv('OLLAMA_MODEL','not-installed')
    def fail(*a,**k):
        import requests
        raise requests.ConnectionError('offline')
    monkeypatch.setattr('requests.Session.post',fail)
    assert analyze([],[],[])['status']=='failed'
