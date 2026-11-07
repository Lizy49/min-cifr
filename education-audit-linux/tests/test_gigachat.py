import json
import time
import uuid
import pytest
import requests
from audit import ai

@pytest.fixture
def giga(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER','gigachat')
    monkeypatch.setenv('GIGACHAT_CREDENTIALS','fake-test-authorization-key')
    monkeypatch.setenv('GIGACHAT_MODEL','GigaChat')
    monkeypatch.setenv('GIGACHAT_SCOPE','GIGACHAT_API_PERS')
    monkeypatch.delenv('GIGACHAT_CA_BUNDLE',raising=False)
    ai._tokens.clear()
    yield
    ai._tokens.clear()

class Reply:
    def __init__(self,data,code=200):self.data,self.status_code=data,code
    def json(self):return self.data

def test_gigachat_missing_key_makes_no_request(giga,monkeypatch):
    monkeypatch.setenv('GIGACHAT_CREDENTIALS','')
    def fail(*a,**k):raise AssertionError('No network expected')
    monkeypatch.setattr(requests.Session,'post',fail)
    assert ai.analyze([],[],[])['status']=='disabled'
    assert ai.test_connection()['status']=='not_configured'
    assert 'credentials' not in ai.public_state()

def test_gigachat_authorization_structured_output_cache_and_evidence(giga,monkeypatch):
    calls=[]
    def post(self,url,**kwargs):
        calls.append((url,kwargs))
        assert kwargs['verify'] is True
        assert kwargs['allow_redirects'] is False
        if '/oauth' in url:
            assert kwargs['data']['scope']=='GIGACHAT_API_PERS'
            assert kwargs['headers']['Authorization'].startswith('Basic ')
            assert uuid.UUID(kwargs['headers']['RqUID']).version==4
            return Reply({'access_token':'fake-token','expires_at':(time.time()+1800)*1000})
        assert kwargs['headers']['Authorization']=='Bearer fake-token'
        assert kwargs['json']['response_format']['type']=='json_schema'
        data={'suggestions':[{'title':'Проверить сведения','reason':'Не хватает данных',
            'recommendation':'Уточнить','urls':['https://x.example/news/','https://invented.example/']} ]}
        return Reply({'choices':[{'message':{'content':json.dumps(data)}}]})
    monkeypatch.setattr(requests.Session,'post',post)
    pages=[{'url':'https://x.example/news/','title':'Новости','text':'Текст новости', 'category':'news','details':{}}]
    for _ in range(2):
        result=ai.analyze(pages,[],[])
        assert result['status']=='completed'
        assert result['suggestions'][0]['urls']==['https://x.example/news/']
        assert 'fake-test-authorization-key' not in json.dumps(result)
    assert sum('/oauth' in url for url,_ in calls)==1
    assert len(calls)==3

def test_connection_only_reads_models(giga,monkeypatch):
    paths=[]
    def post(self,url,**kwargs):
        paths.append(url);assert '/oauth' in url
        return Reply({'access_token':'test-token','expires_at':time.time()+1800})
    def get(self,url,**kwargs):
        paths.append(url);assert url.endswith('/models')
        return Reply({'data':[{'id':'GigaChat'}]})
    monkeypatch.setattr(requests.Session,'post',post)
    monkeypatch.setattr(requests.Session,'get',get)
    assert ai.test_connection()['status']=='ok'
    assert len(paths)==2

@pytest.mark.parametrize('code',[401,403,429,500])
def test_provider_errors_do_not_leak_credentials(giga,monkeypatch,code):
    monkeypatch.setattr(requests.Session,'post',lambda *a,**k:Reply({'secret':'fake-test-authorization-key'},code))
    result=ai.analyze([],[],[])
    assert result['status']=='failed'
    assert 'fake-test-authorization-key' not in json.dumps(result)

def test_tls_failure_is_not_bypassed(giga,monkeypatch):
    def fail(*a,**kwargs):
        assert kwargs['verify'] is True
        raise requests.exceptions.SSLError('secret provider details')
    monkeypatch.setattr(requests.Session,'post',fail)
    result=ai.test_connection()
    assert result['status']=='failed' and 'сертификат' in result['message']
    assert 'secret provider details' not in result['message']

def test_expired_token_refresh(giga,monkeypatch):
    posts=[];gets=[]
    def post(self,url,**kwargs):
        posts.append(url)
        return Reply({'access_token':f'token-{len(posts)}','expires_at':time.time()+1800})
    def get(self,url,**kwargs):
        gets.append(url)
        return Reply({},401) if len(gets)==1 else Reply({'data':[{'id':'GigaChat'}]})
    monkeypatch.setattr(requests.Session,'post',post)
    monkeypatch.setattr(requests.Session,'get',get)
    assert ai.test_connection()['status']=='ok'
    assert len(posts)==2 and len(gets)==2
