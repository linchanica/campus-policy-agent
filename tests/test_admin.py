import json,hashlib
import pytest
from fastapi.testclient import TestClient
from app.api import app
from app.db import create_user,connect,user_for,initialize
from app.config import RELEASE
from app.knowledge import get_knowledge
from app.workflow import run
from app import releases

@pytest.fixture
def c():
    with TestClient(app) as client:yield client
    with connect() as d:d.execute('DELETE FROM active_release')

def staff(role='admin'):
    return {'Authorization':'Bearer '+create_user(role,'虚构测试人员','local_staff')['access_token']}
def draft(c,headers):return c.post('/api/v1/admin/drafts',headers=headers).json()
def patch(c,h,d,key='p012',**fields):
    r=c.post(f"/api/v1/admin/drafts/{d['id']}/policies/{key}",headers=h,json={'expected_revision':d['revision'],**fields})
    assert r.status_code==200,r.text
    return r.json()
def approve(c,h,d,key='p012'):
    r=c.post(f"/api/v1/admin/drafts/{d['id']}/policies/{key}/reviews",headers=h,json={'expected_revision':d['revision'],'decision':'approved','checks':{k:True for k in releases.REVIEW_CHECKS},'notes':'这是虚构自动测试审核，不代表业务签署。'})
    assert r.status_code==200,r.text
    return r.json()
def publish(c,h,d):
    r=c.post(f"/api/v1/admin/drafts/{d['id']}/build",headers=h,json={'semantic':False,'kind':'trial'})
    assert r.status_code==200,r.text
    rid=r.json()['release_id']
    r=c.post(f'/api/v1/admin/releases/{rid}/publish',headers=h,json={'expected_active':releases.active_id()})
    assert r.status_code==200,r.text
    return rid

def test_roles_are_checked_server_side(c):
    s=staff('student');e=staff('editor');r=staff('reviewer')
    assert c.post('/api/v1/admin/drafts',headers=s).status_code==403
    assert c.get('/api/v1/admin/metrics',headers=s).status_code==403
    assert c.post('/api/v1/admin/drafts',headers=r).status_code==403
    d=draft(c,e)
    assert c.post(f"/api/v1/admin/drafts/{d['id']}/policies/p012/reviews",headers=e,json={'expected_revision':0,'decision':'approved','checks':{},'notes':'没有审核权限'}).status_code==403

def test_one_time_staff_login_cannot_create_verified_school_identity(c):
    h=staff();invite=c.post('/api/v1/admin/invitations',headers=h,json={'role':'reviewer','display_name':'测试审核员'}).json()
    logged=c.post('/api/v1/admin/login',json={'code':invite['code']})
    assert logged.status_code==200 and logged.json()['verified_staff'] is False
    assert c.post('/api/v1/admin/login',json={'code':invite['code']}).status_code==401

def test_migration_does_not_revive_revoked_credentials(c):
    auth=create_user();token=auth['access_token'];h={'Authorization':'Bearer '+token}
    assert c.post('/api/v1/auth/logout',headers=h).status_code==200
    initialize();initialize()
    assert user_for(token) is None

def test_draft_edits_do_not_change_student_view_and_require_review(c):
    h=staff();s=staff('student');d=draft(c,h)
    old=get_knowledge().policy('p012')['title']
    d=patch(c,h,d,title='虚构测试标题',source_url='https://example.invalid/policy')
    assert c.get('/api/v1/policies/p012/versions/current',headers=s).json()['title']==old
    bad=c.post(f"/api/v1/admin/drafts/{d['id']}/build",headers=h,json={'semantic':False})
    assert bad.status_code==422 and '未审核' in bad.text
    d=approve(c,h,d)
    assert next(p for p in d['manifest']['files'] if p['key']=='p012')['review_status']=='locally_reviewed_unverified'

def test_publication_preserves_historical_sources_and_disables_stale_rules(c):
    h=staff();s=staff('student');d=draft(c,h)
    original=get_knowledge(RELEASE).policy('p012');old_version=original['sha256'][:16]
    d=patch(c,h,d,title='仅供测试的政策新版本',source_url='https://example.invalid/policy')
    d=approve(c,h,d);rid=publish(c,h,d)
    new=c.get('/api/v1/policies/p012/versions/current',headers=s).json()
    assert new['title']=='仅供测试的政策新版本' and new['version_id']!=old_version
    old=c.get(f'/api/v1/policies/p012/versions/{old_version}',headers=s).json()
    assert old['title']==original['title']
    downloaded=c.get('/api/v1/attachments/p012',params={'version':old_version},headers=s)
    assert hashlib.sha256(downloaded.content).hexdigest()==original['sha256']
    result,_,_=run('我能申请雷军计算机本科生奖学金吗？',{}, {'college':'SAI','program_level':'undergraduate'})
    assert result['release_id']==rid and result['decision']=='needs_human' and not result['condition_results']

def test_atomic_switch_conflict_and_rollback(c):
    h=staff();one=publish(c,h,draft(c,h));two=publish(c,h,draft(c,h))
    assert c.post(f'/api/v1/admin/releases/{one}/publish',headers=h,json={'expected_active':RELEASE,'rollback':True}).status_code==409
    r=c.post(f'/api/v1/admin/releases/{one}/publish',headers=h,json={'expected_active':two,'rollback':True})
    assert r.status_code==200 and releases.active_id()==one

def test_first_publication_can_roll_back_to_imported_baseline(c):
    h=staff();rid=publish(c,h,draft(c,h))
    r=c.post(f'/api/v1/admin/releases/{RELEASE}/publish',headers=h,json={'expected_active':rid,'rollback':True})
    assert r.status_code==200 and releases.active_id()==RELEASE
    assert get_knowledge().policy('p012')['sha256']==get_knowledge(RELEASE).policy('p012')['sha256']

def test_unpublished_candidate_is_not_a_rollback_target(c):
    h=staff();d=draft(c,h)
    rid=c.post(f"/api/v1/admin/drafts/{d['id']}/build",headers=h,json={'semantic':False}).json()['release_id']
    assert c.post(f'/api/v1/admin/releases/{rid}/publish',headers=h,json={'expected_active':RELEASE,'rollback':True}).status_code==422

@pytest.mark.parametrize('filename',['broken.docx','broken.pdf'])
def test_invalid_upload_is_a_validation_error_and_draft_unchanged(c,filename):
    h=staff();d=draft(c,h)
    r=c.post(f"/api/v1/admin/drafts/{d['id']}/uploads",headers=h,data={'expected_revision':'0'},files={'file':(filename,b'not a valid document')})
    assert r.status_code==422
    same=c.get(f"/api/v1/admin/drafts/{d['id']}",headers=h).json()
    assert same['revision']==0 and len(same['manifest']['files'])==45

def test_local_review_cannot_publish_formal_snapshot(c):
    h=staff();d=draft(c,h)
    bad=c.post(f"/api/v1/admin/drafts/{d['id']}/build",headers=h,json={'semantic':False,'kind':'formal'})
    assert bad.status_code==422 and releases.active_id()==RELEASE

def test_rule_card_is_bound_to_exact_policy_version(c):
    h=staff();d=draft(c,h);p=next(p for p in d['manifest']['files'] if p['key']=='p012')
    card={'topic':'lei_undergrad','policy_key':'p012','policy_version':'wrong','conditions':[],'steps':[],'materials':[],'materials_complete':False}
    bad=c.post(f"/api/v1/admin/drafts/{d['id']}/cards/lei_undergrad",headers=h,json={'expected_revision':0,'card':card})
    assert bad.status_code==422
    card['policy_version']=p['version_id']
    card['conditions']=[{'name':'禁止执行','detail':'测试','expression':{'op':'python','field':'college','value':'SAI'},'source_quote':'学习成绩以及综合测评排名均处于本专业前20%'}]
    assert c.post(f"/api/v1/admin/drafts/{d['id']}/cards/lei_undergrad",headers=h,json={'expected_revision':0,'card':card}).status_code==422

def test_publish_rejects_tampered_index(c):
    from pathlib import Path
    from app.config import WORK
    h=staff();d=draft(c,h)
    built=c.post(f"/api/v1/admin/drafts/{d['id']}/build",headers=h,json={'semantic':False}).json()
    path=WORK/'releases'/built['release_id']/'vectors.npy'
    path.write_bytes(path.read_bytes()+b'tampered')
    bad=c.post(f"/api/v1/admin/releases/{built['release_id']}/publish",headers=h,json={'expected_active':RELEASE})
    assert bad.status_code==422 and releases.active_id()==RELEASE

def test_reviewed_card_drives_matching_and_literal_source_claims(c):
    from datetime import datetime
    from app.config import TZ
    h=staff();d=draft(c,h);d=patch(c,h,d,key='p032',source_url='https://example.invalid/midterm')
    p=next(p for p in d['manifest']['files'] if p['key']=='p032')
    quote=p['text'][:900]
    card={'topic':'midterm','policy_key':'p032','policy_version':p['version_id'],'conditions':[
        {'name':'学院与身份','detail':'按本测试卡核对学院和学位类型。','expression':{'op':'all','children':[{'op':'eq','field':'college','value':'SAI'},{'op':'eq','field':'program_level','value':'master'},{'op':'eq','field':'degree_type','value':'academic'}]},'source_quote':quote},
        {'name':'入学年份','detail':'核对通知列出的2025级。','expression':{'op':'eq','field':'cohort_year','value':2025},'source_quote':quote}],
        'steps':[],'materials':[],'materials_complete':False,'unresolved_items':['此为自动测试卡。']}
    result=c.post(f"/api/v1/admin/drafts/{d['id']}/cards/midterm",headers=h,json={'expected_revision':d['revision'],'card':card})
    assert result.status_code==200,result.text
    d=approve(c,h,result.json(),key='p032');rid=publish(c,h,d)
    data,_,_=run('我能参加中期考核吗？',{}, {'college':'SAI','program_level':'master','degree_type':'academic','cohort_year':2025},at=datetime(2026,10,24,tzinfo=TZ),release_id=rid)
    assert data['decision']=='preliminary_match' and len(data['claims'])==2
    assert all(c['source_ids'] for c in data['claims'])
    assert {s['policy_key'] for s in data['sources']}=={'p032'}
