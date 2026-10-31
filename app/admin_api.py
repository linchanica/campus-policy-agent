"""Role protected policy workspace, release history and aggregate operational metrics."""
import json,re,statistics
from uuid import uuid4
from fastapi import APIRouter,Depends,UploadFile,File,Form
from pydantic import BaseModel,Field,ConfigDict,HttpUrl
from typing import Literal
from .auth import roles,fail
from .db import connect,role_for,audit,setting
from . import releases

router=APIRouter(prefix='/api/v1/admin')
READ=roles('admin','editor','reviewer');EDIT=roles('admin','editor');REVIEW=roles('admin','reviewer');ADMIN=roles('admin')
def perform(fn,*args,**kwargs):
    try:return fn(*args,**kwargs)
    except (ValueError,KeyError) as error:
        message=str(error)
        fail(409 if '_CONFLICT' in message else 422,'WORKSPACE_CONFLICT' if '_CONFLICT' in message else 'VALIDATION_FAILED',message[:300])

@router.get('/workspace')
def workspace(uid=Depends(READ)):
    with connect() as d:
        drafts=[{k:r[k] for k in ['id','base_release_id','revision','state','created_by','created_at']} for r in d.execute('SELECT * FROM policy_drafts ORDER BY created_at DESC')]
        snapshots=[dict(r) for r in d.execute('SELECT id,state,kind,created_by,created_at FROM release_snapshots ORDER BY created_at DESC')]
    snapshots.append({'id':releases.RELEASE,'state':'PUBLISHED','kind':'baseline','created_by':'初始资料导入','created_at':'2026-10-30'})
    return {'active_release_id':releases.active_id(),'drafts':drafts,'releases':snapshots,'review_checks':sorted(releases.REVIEW_CHECKS),'identity':role_for(uid),'formal_staff_verified':bool(role_for(uid)['verified_staff'])}

@router.post('/drafts')
def create(uid=Depends(EDIT)):return perform(releases.create_draft,uid)
@router.get('/drafts/{did}')
def detail(did:str,uid=Depends(READ)):return perform(releases.get_draft,did)

class PolicyPatch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision:int=Field(ge=0)
    title:str|None=Field(default=None,min_length=1,max_length=300)
    in_scope:bool|None=None
    source_url:HttpUrl|None=None
    metadata:dict|None=None
    corrected_text:str|None=Field(default=None,max_length=500000)
    correction_note:str|None=Field(default=None,max_length=1000)
@router.post('/drafts/{did}/policies/{key}')
def patch_policy(did:str,key:str,data:PolicyPatch,uid=Depends(EDIT)):
    values=data.model_dump(exclude_unset=True);values.pop('expected_revision')
    if 'title' in values and values['title'] is None:fail(422,'INVALID_TITLE','标题不能为空。')
    if 'in_scope' in values and values['in_scope'] is None:fail(422,'INVALID_SCOPE','适用范围不能为空。')
    if data.source_url:values['source_url']=str(data.source_url)
    text=values.pop('corrected_text',None)
    if text is not None:
        if len((data.correction_note or '').strip())<10:fail(422,'CORRECTION_NOTE_REQUIRED','校正文必须记录至少10个字的核验说明。')
        values['text']=text
    return perform(releases.replace_document,did,key,uid,data.expected_revision,patch=values)

@router.post('/drafts/{did}/uploads')
async def upload(did:str,expected_revision:int=Form(...),policy_key:str=Form(default=''),file:UploadFile=File(...),uid=Depends(EDIT)):
    key=policy_key or 'u-'+uuid4().hex[:12]
    if not re.fullmatch(r'[a-z][a-z0-9_-]{1,50}',key):fail(422,'INVALID_POLICY_KEY','政策标识格式不合法。')
    blob=await file.read(20_000_001)
    return perform(releases.replace_document,did,key,uid,expected_revision,blob=blob,filename=file.filename)

class ReviewInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_revision:int=Field(ge=0)
    decision:Literal['approved','changes_requested']
    checks:dict[str,bool]
    notes:str=Field(min_length=5,max_length=2000)
@router.post('/drafts/{did}/policies/{key}/reviews')
def review(did:str,key:str,data:ReviewInput,uid=Depends(REVIEW)):
    return perform(releases.review,did,key,uid,data.expected_revision,data.decision,data.checks,data.notes)

class CardInput(BaseModel):
    expected_revision:int=Field(ge=0)
    card:dict|None=None
@router.post('/drafts/{did}/cards/{topic}')
def card(did:str,topic:str,data:CardInput,uid=Depends(EDIT)):
    return perform(releases.save_card,did,topic,data.card,uid,data.expected_revision)

class BuildInput(BaseModel):
    semantic:bool=True
    kind:Literal['trial','formal']='trial'
@router.post('/drafts/{did}/build')
def build(did:str,data:BuildInput,uid=Depends(EDIT)):
    return perform(releases.build,did,uid,data.semantic,data.kind)
class PublishInput(BaseModel):
    expected_active:str=Field(min_length=1,max_length=100)
    rollback:bool=False
@router.post('/releases/{rid}/publish')
def publish(rid:str,data:PublishInput,uid=Depends(ADMIN)):
    return perform(releases.publish,rid,uid,data.expected_active,data.rollback)

@router.get('/team')
def team(uid=Depends(roles('admin','operator'))):
    with connect() as d:return [dict(r) for r in d.execute('SELECT user_id,role,display_name,verified_staff FROM user_roles WHERE role!=? ORDER BY display_name',('student',))]

@router.get('/metrics')
def metrics(uid=Depends(roles('admin','operator'))):
    with connect() as d:
        counts={r['state']:r['n'] for r in d.execute('SELECT state,COUNT(*) n FROM turns GROUP BY state')}
        rows=d.execute("SELECT id,state,error,result_json FROM turns ORDER BY created_at DESC LIMIT 1000").fetchall()
        logs=[dict(r) for r in d.execute('SELECT id,action,object_id,details,created_at FROM audit_logs ORDER BY id DESC LIMIT 60')]
    results=[json.loads(r['result_json']) for r in rows if r['result_json']]
    durations=sorted(r.get('duration_ms',0) for r in results)
    modes={}
    for r in results:modes[r.get('generation_mode','unknown')]=modes.get(r.get('generation_mode','unknown'),0)+1
    return {'active_release_id':releases.active_id(),'task_counts':counts,'backlog':counts.get('RECEIVED',0)+counts.get('RUNNING',0),'completed_sample_count':len(durations),'p50_ms':statistics.median(durations) if durations else None,'p95_ms':durations[max(0,int(len(durations)*.95)-1)] if durations else None,'generation_modes':modes,'failures':[{'turn_id':r['id'],'state':r['state'],'error':r['error']} for r in rows if r['state'] in {'FAILED','STALE'}][:20],'audit_logs':logs,'scope':'当前数据库中最近1000个任务，包含开发与虚构样例；不是生产容量结论。'}
