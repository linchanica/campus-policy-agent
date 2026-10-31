import hashlib,json
from pathlib import Path
import pytest,httpx
from fastapi.testclient import TestClient
from app.api import app
from app.db import create_user,connect
from app import identity,integrations

@pytest.fixture
def c():
    with TestClient(app) as client:yield client
def auth(role='student'):
    result=create_user(role,'虚构用户')
    return {'Authorization':'Bearer '+result['access_token']},result
@pytest.fixture
def wechat(monkeypatch):
    monkeypatch.setenv('WX_APP_ID','wx0000000000000000');monkeypatch.setenv('WX_APP_SECRET','test-secret-not-real-000000000000')
    class Client:
        def __init__(self,*a,**k):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def get(self,url,params):
            assert url=='https://api.weixin.qq.com/sns/jscode2session'
            return httpx.Response(200,json={'openid':'fictional-openid','session_key':'must-not-be-stored'})
    monkeypatch.setattr(identity.httpx,'Client',Client)

def test_wechat_identity_is_server_verified_and_no_session_key_returned(c,wechat):
    r=c.post('/api/v1/auth/wechat',json={'code':'fictional-code'})
    assert r.status_code==200 and r.json()['auth_mode']=='wechat'
    assert not any(field in r.json() for field in ['openid','session_key','unionid'])
    h={'Authorization':'Bearer '+r.json()['access_token']}
    assert c.get('/api/v1/auth/me',headers=h).json()['verified_staff'] is False
    with connect() as d:
        stored=d.execute("SELECT subject_hash FROM identities WHERE user_id=?",(r.json()['user_id'],)).fetchone()[0]
        assert stored!= 'fictional-openid' and len(stored)==64
    assert c.post('/api/v1/auth/wechat',json={'code':'fictional-code','openid':'client-forged'}).status_code==422

def test_wechat_relogin_keeps_identity_but_issues_new_credentials(c,wechat):
    first=c.post('/api/v1/auth/wechat',json={'code':'first-code'}).json()
    second=c.post('/api/v1/auth/wechat',json={'code':'second-code'}).json()
    assert first['user_id']==second['user_id'] and first['access_token']!=second['access_token']

@pytest.mark.parametrize('payload',[[],{'errcode':'not-a-number','errmsg':'must-not-be-exposed'}])
def test_malformed_wechat_response_does_not_leak_upstream_body(c,wechat,monkeypatch,payload):
    class BadClient:
        def __init__(self,*a,**k):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def get(self,*a,**k):return httpx.Response(200,json=payload)
    monkeypatch.setattr(identity.httpx,'Client',BadClient)
    result=c.post('/api/v1/auth/wechat',json={'code':'fictional-malformed-code'})
    assert result.status_code==503 and 'must-not-be-exposed' not in result.text

def test_cross_device_binding_requires_consent_and_one_time_code(c,wechat):
    wx=c.post('/api/v1/auth/wechat',json={'code':'wx-pair-code'}).json();wxh={'Authorization':'Bearer '+wx['access_token']}
    h,guest=auth();sid=c.post('/api/v1/sessions',headers=h,json={}).json()['session_id']
    code=c.post('/api/v1/auth/pairing-codes',headers=wxh).json()['code']
    assert c.post('/api/v1/auth/pair',headers=h,json={'code':code}).status_code==422
    paired=c.post('/api/v1/auth/pair',headers=h,json={'code':code,'confirm_merge':True})
    assert paired.status_code==200 and paired.json()['user_id']==wx['user_id']
    assert c.get('/api/v1/sessions/'+sid,headers=wxh).status_code==200
    assert c.get('/api/v1/sessions',headers=h).status_code==401
    newh={'Authorization':'Bearer '+paired.json()['access_token']}
    assert c.post('/api/v1/auth/pair',headers=newh,json={'code':code,'confirm_merge':True}).status_code==401

def test_guest_cannot_mint_verified_binding_code(c):
    h,_=auth()
    assert c.post('/api/v1/auth/pairing-codes',headers=h).status_code==403

def test_secret_configuration_is_private_and_not_echoed(c,monkeypatch,tmp_path):
    for name in ['WX_APP_ID','WX_APP_SECRET','LLM_BASE_URL','LLM_MODEL','LLM_API_KEY']:monkeypatch.setenv(name,'')
    monkeypatch.setattr(integrations,'CONFIG_PATH',tmp_path/'.env');monkeypatch.setattr(integrations,'MINI_MANIFEST',tmp_path/'manifest.json')
    admin,_=auth('admin');student,_=auth();secret='fictional-secret-for-unit-test-12345'
    assert c.get('/api/v1/admin/integrations',headers=student).status_code==403
    r=c.post('/api/v1/admin/integrations',headers=admin,json={'wx_app_id':'wx0000000000000000','wx_app_secret':secret})
    assert r.status_code==200 and secret not in r.text
    r=c.get('/api/v1/admin/integrations',headers=admin)
    assert r.json()['wx_secret_configured'] and secret not in r.text
    assert secret in (tmp_path/'.env').read_text(encoding='utf-8')
    with connect() as d:
        logs=' '.join(r[0] for r in d.execute("SELECT details FROM audit_logs WHERE action='integration_config_updated'"))
        assert secret not in logs

def test_config_rejects_newline_and_partial_model_credentials(c,monkeypatch,tmp_path):
    for name in ['WX_APP_ID','WX_APP_SECRET','LLM_BASE_URL','LLM_MODEL','LLM_API_KEY']:monkeypatch.setenv(name,'')
    monkeypatch.setattr(integrations,'CONFIG_PATH',tmp_path/'.env');monkeypatch.setattr(integrations,'MINI_MANIFEST',tmp_path/'manifest.json')
    h,_=auth('admin')
    assert c.post('/api/v1/admin/integrations',headers=h,json={'wx_app_secret':'x'*32+'\nDANGEROUS=1'}).status_code==422
    assert c.post('/api/v1/admin/integrations',headers=h,json={'llm_api_key':'fake-only-key-000'}).status_code==422
    assert not (tmp_path/'.env').exists()

@pytest.mark.parametrize('field,value',[('wx_app_secret','tiny-WX-pass'),('llm_api_key','sk-12'),('llm_api_key','x'*1001)])
def test_schema_validation_never_echoes_credentials(c,field,value):
    h,_=auth('admin')
    result=c.post('/api/v1/admin/integrations',headers=h,json={field:value})
    assert result.status_code==422 and value not in result.text
    assert result.json()['detail']['code']=='INVALID_INPUT'

def test_unknown_input_keys_are_not_reflected_as_field_names(c):
    h,_=auth('admin');secret='accidentally-pasted-credential-98765'
    result=c.post('/api/v1/admin/integrations',headers=h,json={secret:'not-a-config-field'})
    assert result.status_code==422 and secret not in result.text
