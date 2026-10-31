import pytest
from fastapi.testclient import TestClient
from app.api import app
from app.db import create_user,connect

@pytest.fixture
def c():
    with TestClient(app) as client:yield client
    with connect() as d:d.execute("DELETE FROM app_settings WHERE key='handoff_queue'")
def principal(role='student'):
    result=create_user(role,'测试'+role)
    return {'Authorization':'Bearer '+result['access_token']},result['user_id']
def configured(c):
    admin,_=principal('admin');operator,oid=principal('operator');student,suid=principal()
    config=c.post('/api/v1/admin/handoff-settings',headers=admin,json={'enabled':True,'label':'仅供测试的接待队列','operator_ids':[oid]}).json()
    sid=c.post('/api/v1/sessions',headers=student,json={}).json()['session_id']
    draft=c.post('/api/v1/handoffs/drafts',headers=student,json={'session_id':sid}).json()
    return admin,operator,student,sid,draft,config

def test_submission_requires_student_consent_and_fixed_recipient(c):
    admin,operator,student,sid,draft,cfg=configured(c)
    url='/api/v1/handoffs/'+draft['draft_id']+'/submit'
    assert c.post(url,headers=student,json={}).status_code==422
    assert c.get('/api/v1/admin/tickets',headers=operator).json()==[]
    assert c.post(url,headers=student,json={'confirmed':True,'recipient_revision':'wrong'}).status_code==409
    body={'confirmed':True,'recipient_revision':cfg['revision']}
    one=c.post(url,headers=student,json=body);two=c.post(url,headers=student,json=body)
    assert one.status_code==two.status_code==200 and one.json()['ticket_id']==two.json()['ticket_id']
    rows=c.get('/api/v1/admin/tickets',headers=operator).json()
    assert len(rows)==1 and len(rows[0]['events'])==1 and rows[0]['state']=='queued'
    assert c.delete('/api/v1/sessions',headers=student).status_code==409

def test_only_assigned_operator_can_read_or_answer_and_reply_is_idempotent(c):
    admin,operator,student,sid,draft,cfg=configured(c)
    hid=draft['draft_id'];other,_=principal('operator');outsider,_=principal()
    c.post('/api/v1/handoffs/'+hid+'/submit',headers=student,json={'confirmed':True,'recipient_revision':cfg['revision']})
    assert c.get('/api/v1/admin/tickets',headers=other).json()==[]
    assert c.get('/api/v1/handoffs',headers=outsider).json()==[]
    payload={'state':'answered','text':'虚构测试人工答复，请以经办核实为准。','client_id':'reply-idempotency-0001'}
    assert c.post('/api/v1/admin/tickets/'+hid+'/events',headers=other,json=payload).status_code==404
    first=c.post('/api/v1/admin/tickets/'+hid+'/events',headers=operator,json=payload)
    second=c.post('/api/v1/admin/tickets/'+hid+'/events',headers=operator,json=payload)
    assert first.status_code==second.status_code==200 and second.json()['duplicate']
    row=c.get('/api/v1/handoffs',headers=student).json()[0]
    assert row['state']=='answered' and len(row['events'])==2
    assert c.delete('/api/v1/sessions',headers=student).status_code==200

def test_recipient_change_invalidates_unsubmitted_consent(c):
    admin,operator,student,sid,draft,cfg=configured(c)
    other,oid=principal('operator')
    c.post('/api/v1/admin/handoff-settings',headers=admin,json={'enabled':True,'label':'另一测试接待人','operator_ids':[oid]})
    assert c.post('/api/v1/handoffs/'+draft['draft_id']+'/submit',headers=student,json={'confirmed':True,'recipient_revision':cfg['revision']}).status_code==409

def test_withdrawn_draft_is_never_exposed_to_staff(c):
    admin,operator,student,sid,draft,cfg=configured(c)
    hid=draft['draft_id']
    assert c.post('/api/v1/handoffs/'+hid+'/withdraw',headers=student).status_code==200
    assert all(row['id']!=hid for row in c.get('/api/v1/admin/tickets',headers=admin).json())
