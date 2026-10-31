"""Consented internal handoff queue. No email, WeChat message or external webhook sending."""
import json,secrets
from uuid import uuid4
from fastapi import APIRouter,Depends
from pydantic import BaseModel,Field,ConfigDict
from typing import Literal
from .db import connect,setting,role_for,audit
from .auth import current_user,roles,fail
from .config import now

router=APIRouter(prefix='/api/v1')
def queue_config():return setting('handoff_queue',{'enabled':False,'label':'','operator_ids':[],'revision':'unconfigured'})

class QueueInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled:bool
    label:str=Field(max_length=120)
    operator_ids:list[str]=Field(max_length=50)
@router.get('/admin/handoff-settings')
def settings(uid=Depends(roles('admin'))):return queue_config()
@router.post('/admin/handoff-settings')
def configure(data:QueueInput,uid=Depends(roles('admin'))):
    if data.enabled and (not data.label.strip() or not data.operator_ids):fail(422,'RECEIVER_REQUIRED','启用队列前须填写接收方并选择真实接待账号。')
    for receiver in data.operator_ids:
        if role_for(receiver)['role'] not in {'operator','admin'}:fail(422,'INVALID_OPERATOR','接待账号不存在或没有经办权限。')
    config={**data.model_dump(),'label':data.label.strip(),'revision':uuid4().hex}
    with connect() as d:d.execute('INSERT OR REPLACE INTO app_settings VALUES(?,?)',('handoff_queue',json.dumps(config,ensure_ascii=False)))
    audit('handoff_queue_configured',uid,{'enabled':data.enabled,'receiver_count':len(data.operator_ids),'label':data.label})
    return config

class ConsentInput(BaseModel):
    confirmed:bool=False
    recipient_revision:str=''

def submit(hid,uid,data):
    with connect() as d:
        d.execute('BEGIN IMMEDIATE')
        row=d.execute('SELECT h.* FROM handoffs h JOIN sessions s ON h.session_id=s.id WHERE h.id=? AND s.user_id=?',(hid,uid)).fetchone()
        if not row:fail(404,'NOT_FOUND','记录不存在。')
        payload=json.loads(row['payload_json'])
        if row['state']!='draft':return {**payload,'state':row['state'],'submitted':row['state']!='withdrawn'}
        cfg_row=d.execute("SELECT value_json FROM app_settings WHERE key='handoff_queue'").fetchone();config=json.loads(cfg_row[0]) if cfg_row else {'enabled':False}
        if not config.get('enabled'):fail(503,'FEATURE_UNAVAILABLE','尚未启用实际接待队列，可复制摘要自行咨询。')
        if not data.confirmed:fail(422,'CONSENT_REQUIRED','请检查摘要并明确同意交给所显示的接收方。')
        if payload.get('recipient_revision')!=config['revision'] or data.recipient_revision!=config['revision']:fail(409,'RECEIVER_CHANGED','接收配置已改变，请重新生成摘要并确认。')
        payload.update(state='queued',submitted=True,submitted_at=now(),recipient_label=config['label'],recipient_ids=config['operator_ids'],ticket_id='LC-'+hid.replace('-','')[:12].upper(),receipt='已进入本系统接待队列，尚待经办人员受理。')
        d.execute("UPDATE handoffs SET state='queued',payload_json=? WHERE id=?",(json.dumps(payload,ensure_ascii=False),hid))
        d.execute('INSERT INTO ticket_events(handoff_id,actor_id,state,text,created_at) VALUES(?,?,?,?,?)',(hid,uid,'queued','学生已检查摘要并确认提交。',now()))
    audit('handoff_queued',hid,{'actor':uid,'external_message_sent':False,'recipient_revision':config['revision']})
    return payload

def events(d,hid):
    return [dict(r) for r in d.execute("SELECT e.id,e.state,e.text,e.created_at,COALESCE(r.display_name,'学生') display_name,COALESCE(r.verified_staff,0) verified_staff FROM ticket_events e LEFT JOIN user_roles r ON r.user_id=e.actor_id WHERE e.handoff_id=? ORDER BY e.id",(hid,))]

@router.get('/handoffs')
def my_tickets(uid=Depends(current_user)):
    with connect() as d:
        rows=d.execute('SELECT h.* FROM handoffs h JOIN sessions s ON h.session_id=s.id WHERE s.user_id=? ORDER BY h.created_at DESC LIMIT 100',(uid,)).fetchall()
        return [{'id':r['id'],'state':r['state'],'payload':{k:v for k,v in json.loads(r['payload_json']).items() if k!='recipient_ids'},'events':events(d,r['id'])} for r in rows]

@router.post('/handoffs/{hid}/withdraw')
def withdraw(hid:str,uid=Depends(current_user)):
    with connect() as d:
        d.execute('BEGIN IMMEDIATE')
        row=d.execute('SELECT h.* FROM handoffs h JOIN sessions s ON h.session_id=s.id WHERE h.id=? AND s.user_id=?',(hid,uid)).fetchone()
        if not row:fail(404,'NOT_FOUND','记录不存在。')
        if row['state'] in {'answered','closed'}:fail(409,'ALREADY_HANDLED','已有人工答复，不能撤回已完成的办理。')
        if row['state']=='withdrawn':return {'state':'withdrawn','submitted':False}
        payload=json.loads(row['payload_json']);payload.update(state='withdrawn',submitted=False)
        d.execute("UPDATE handoffs SET state='withdrawn',payload_json=? WHERE id=?",(json.dumps(payload,ensure_ascii=False),hid))
        d.execute('INSERT INTO ticket_events(handoff_id,actor_id,state,text,created_at) VALUES(?,?,?,?,?)',(hid,uid,'withdrawn','学生撤回咨询。',now()))
    audit('handoff_withdrawn',hid,{'actor':uid});return {'state':'withdrawn','submitted':False}

def may_handle(uid,payload):return role_for(uid)['role']=='admin' or uid in payload.get('recipient_ids',[])
@router.get('/admin/tickets')
def queue(uid=Depends(roles('admin','operator'))):
    with connect() as d:
        rows=d.execute("SELECT * FROM handoffs WHERE state!='draft' ORDER BY created_at DESC LIMIT 300").fetchall()
        result=[]
        for r in rows:
            payload=json.loads(r['payload_json'])
            if not payload.get('submitted_at'):continue
            if may_handle(uid,payload):result.append({'id':r['id'],'state':r['state'],'payload':payload,'events':events(d,r['id'])})
        return result

class EventInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    state:Literal['accepted','answered','closed']
    text:str=Field(min_length=1,max_length=4000)
    client_id:str=Field(min_length=8,max_length=100)
@router.post('/admin/tickets/{hid}/events')
def handle(hid:str,data:EventInput,uid=Depends(roles('admin','operator'))):
    with connect() as d:
        d.execute('BEGIN IMMEDIATE')
        row=d.execute('SELECT * FROM handoffs WHERE id=?',(hid,)).fetchone()
        if not row:fail(404,'NOT_FOUND','记录不存在。')
        payload=json.loads(row['payload_json'])
        if not may_handle(uid,payload):fail(404,'NOT_FOUND','记录不存在或未分配给你。')
        client_marker='ticket_event:'+hid+':'+data.client_id
        prior=d.execute('SELECT value_json FROM app_settings WHERE key=?',(client_marker,)).fetchone()
        if prior:
            previous=json.loads(prior[0])
            if previous['actor_id']!=uid or previous['state']!=data.state or previous['text']!=data.text:fail(409,'IDEMPOTENCY_CONFLICT','重复操作标识的内容不同。')
            return {'state':previous['state'],'duplicate':True}
        transitions={'queued':{'accepted','answered'},'accepted':{'accepted','answered'},'answered':{'closed'},'closed':set(),'withdrawn':set(),'draft':set()}
        if data.state not in transitions.get(row['state'],set()):fail(409,'INVALID_TICKET_STATE','当前工单状态不允许此操作。')
        payload['state']=data.state
        d.execute('UPDATE handoffs SET state=?,payload_json=? WHERE id=?',(data.state,json.dumps(payload,ensure_ascii=False),hid))
        d.execute('INSERT INTO ticket_events(handoff_id,actor_id,state,text,created_at) VALUES(?,?,?,?,?)',(hid,uid,data.state,data.text,now()))
        d.execute('INSERT INTO app_settings VALUES(?,?)',(client_marker,json.dumps({'actor_id':uid,'state':data.state,'text':data.text},ensure_ascii=False)))
    audit('human_ticket_updated',hid,{'actor':uid,'state':data.state,'external_message_sent':False})
    return {'state':data.state,'duplicate':False}
