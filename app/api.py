import json,secrets,time,threading,os,hashlib
from collections import defaultdict,deque
from contextlib import asynccontextmanager
from uuid import uuid4
from pathlib import Path
from datetime import datetime
from typing import Literal
from fastapi import FastAPI,HTTPException,Header,Depends,BackgroundTasks,Request,Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel,Field,ConfigDict
from .config import ROOT,WORK,DEV,RELEASE,now
from .db import initialize,connect,guest,user_for,audit,clear_user_sessions
from .knowledge import get_knowledge
from .profile import ProfilePatch
from .workflow import TOPICS
from .worker import process,recover
from .providers import configured
from .auth import router as auth_router
from .admin_api import router as admin_router
from .releases import active_id,find_policy,policy_version
from .identity import router as identity_router,wechat_configured
from .integrations import router as integration_router
from .tickets import router as ticket_router,queue_config,submit as submit_ticket,ConsentInput

@asynccontextmanager
async def lifespan(app):
    if not DEV:raise RuntimeError('正式环境需要配置真实身份与审核政策，当前发行版只允许本地试用。')
    initialize();get_knowledge()
    (WORK/'active-process.json').write_text(json.dumps({'pid':os.getpid(),'project':str(ROOT),'started':now()},ensure_ascii=False),encoding='utf-8')
    stop=threading.Event()
    def recovery_loop():
        while not stop.is_set():
            recover();stop.wait(2)
    threading.Thread(target=recovery_loop,daemon=True).start()
    try:yield
    finally:stop.set()

validation_schema={'type':'object','required':['detail'],'properties':{'detail':{'type':'object','required':['code','message','fields'],'properties':{'code':{'type':'string'},'message':{'type':'string'},'fields':{'type':'array','items':{'type':'string'}}}}}}
app=FastAPI(title='校院政策咨询 Agent',version='0.2.0',lifespan=lifespan,responses={422:{'description':'字段验证失败，仅返回字段名，不回显输入或凭证。','content':{'application/json':{'schema':validation_schema}}}})
@app.exception_handler(RequestValidationError)
async def validation_failed(request,exc):
    # FastAPI's default includes raw `input`, which could echo a malformed secret.
    known={'body','path','query','header'}|{name for schema in app.openapi().get('components',{}).get('schemas',{}).values() for name in schema.get('properties',{})}
    fields=sorted({'.'.join(str(p) if isinstance(p,int) or p in known else 'user_input' for p in error['loc']) for error in exc.errors()})
    return JSONResponse({'detail':{'code':'INVALID_INPUT','message':'字段格式或范围不正确，请检查标注字段。','fields':fields}},status_code=422)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(identity_router)
app.include_router(integration_router)
app.include_router(ticket_router)
app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:5173','http://localhost:5173','http://127.0.0.1:8000','http://localhost:8000'],allow_methods=['GET','POST','DELETE'],allow_headers=['Authorization','Content-Type'])
rates=defaultdict(deque)
@app.middleware('http')
async def limited(request,call_next):
    trace=secrets.token_hex(10);host=request.client.host if request.client else 'local'
    request.state.trace_id=trace
    length=request.headers.get('content-length')
    if length and (not length.isdigit() or int(length)>25_000_000):return JSONResponse({'message':'请求体超过限制。'},status_code=413)
    if request.url.path.endswith('/uploads') and not length:return JSONResponse({'message':'上传需要Content-Length。'},status_code=411)
    q=rates[host];t=time.monotonic()
    while q and q[0]<t-60:q.popleft()
    if len(q)>240:return JSONResponse({'code':'RATE_LIMITED','message':'请求较频繁，请稍后再试。','trace_id':trace},status_code=429)
    q.append(t);response=await call_next(request);response.headers['X-Trace-Id']=trace;response.headers['X-Content-Type-Options']='nosniff';return response

def error(status,code,message):raise HTTPException(status,detail={'code':code,'message':message})
def user(authorization:str=Header(default='')):
    uid=user_for(authorization.removeprefix('Bearer '))
    if not uid:error(401,'AUTH_REQUIRED','请创建本地试用会话。')
    return uid
def own(session_id,uid,d):
    s=d.execute('SELECT * FROM sessions WHERE id=? AND user_id=?',(session_id,uid)).fetchone()
    if not s:error(404,'NOT_FOUND','记录不存在或不可访问。')
    return s

@app.get('/health/live')
def live():return {'status':'ok'}
@app.get('/health/ready')
def ready():
    kb=get_knowledge()
    if kb.release_id!=RELEASE:
        from .releases import assert_runtime
        try:assert_runtime(kb.manifest)
        except ValueError:error(503,'RELEASE_CODE_MISMATCH','代码已改变，请重建并审核发布快照。')
    return {'status':'ready','release_id':kb.release_id,'policies':len(kb.documents),'mode':'local_trial'}
@app.get('/api/v1/meta')
def meta():
    kb=get_knowledge()
    from .local_model import available
    return {'title':'珞策 · 学生政策助手','release_id':kb.release_id,'mode':'local_trial','llm_configured':configured(),'local_llm_available':available(),'index':{k:v for k,v in kb.index_info.items() if k!='chunk_ids'},'documents':len(kb.documents),'parsed':sum(p['parse_status']=='parsed' for p in kb.documents),'chunks':len(kb.chunks),'topics':[dict(t,id=id_) for id_,t in TOPICS.items()],'notice':'本地试用 · 政策审核状态以发布记录为准','handoff_enabled':queue_config()['enabled'],'wechat_configured':wechat_configured()}
@app.post('/api/v1/auth/guest')
def auth_guest():return guest()

@app.post('/api/v1/auth/logout')
def logout(authorization:str=Header(default=''),uid=Depends(user)):
    with connect() as d:
        d.execute('BEGIN IMMEDIATE')
        if d.execute("SELECT 1 FROM turns t JOIN sessions s ON s.id=t.session_id WHERE s.user_id=? AND t.state IN ('RECEIVED','RUNNING')",(uid,)).fetchone():error(409,'TURN_IN_PROGRESS','咨询仍在处理中，请完成后退出。')
        d.execute('UPDATE users SET token_hash=? WHERE id=?',(secrets.token_hex(32),uid))
        d.execute('UPDATE auth_tokens SET revoked_at=? WHERE token_hash=? AND user_id=?',(now(),hashlib.sha256(authorization.removeprefix('Bearer ').encode()).hexdigest(),uid))
    audit('local_guest_logout',uid)
    return {'state':'logged_out','token_revoked':True,'records_deleted':False}

@app.delete('/api/v1/sessions')
def clear_sessions(uid=Depends(user)):
    with connect() as d:
        d.execute('BEGIN IMMEDIATE')
        if not clear_user_sessions(d,uid):error(409,'TURN_IN_PROGRESS','咨询仍在处理中，请完成后清空记录。')
    audit('local_history_cleared',uid)
    return {'state':'cleared','scope':'current_local_guest','policy_files_deleted':False}

class SessionInput(BaseModel):topic:str|None=None
@app.post('/api/v1/sessions')
def session_create(data:SessionInput,uid=Depends(user)):
    if data.topic is not None and data.topic not in TOPICS:error(422,'INVALID_TOPIC','未知事项')
    sid=str(uuid4())
    with connect() as d:d.execute('INSERT INTO sessions(id,user_id,title,topic,created_at) VALUES(?,?,?,?,?)',(sid,uid,'新咨询',data.topic,now()))
    return {'session_id':sid,'profile_revision':0}
@app.get('/api/v1/sessions')
def sessions(uid=Depends(user)):
    with connect() as d:return [dict(x) for x in d.execute('SELECT id,title,topic,revision,created_at FROM sessions WHERE user_id=? ORDER BY created_at DESC LIMIT 100',(uid,))]
@app.get('/api/v1/sessions/{sid}')
def session_get(sid:str,uid=Depends(user)):
    with connect() as d:
        s=dict(own(sid,uid,d));s['profile']=json.loads(s.pop('profile_json'));s.pop('user_id')
        s['messages']=[dict(x) for x in d.execute('SELECT id,role,text,created_at FROM messages WHERE session_id=? ORDER BY created_at',(sid,))]
        s['turns']=[dict(id=x['id'],state=x['state'],result=json.loads(x['result_json']) if x['result_json'] else None,error=x['error']) for x in d.execute('SELECT * FROM turns WHERE session_id=? ORDER BY created_at',(sid,))]
        return s

class MessageInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text:str=Field(min_length=1,max_length=4000)
    client_message_id:str=Field(min_length=8,max_length=100)
    expected_profile_revision:int=Field(ge=0)
    profile_patch:ProfilePatch=Field(default_factory=ProfilePatch)
    channel:Literal['h5','mp_weixin','mcp']='h5'
    topic:str|None=None
    simulation_time:datetime|None=None

@app.post('/api/v1/sessions/{sid}/messages',status_code=202)
def message(sid:str,data:MessageInput,bg:BackgroundTasks,request:Request,uid=Depends(user)):
    if data.topic and data.topic not in TOPICS:error(422,'INVALID_TOPIC','未知事项')
    if data.simulation_time and (not DEV or data.simulation_time.tzinfo is None):error(422,'INVALID_TIME','回放仅供本地测试，且须指定时区。')
    payload=data.model_dump(mode='json');payload['profile_patch']=data.profile_patch.model_dump(exclude_unset=True)
    with connect() as d:
        d.execute('BEGIN IMMEDIATE');s=own(sid,uid,d)
        old=d.execute('SELECT t.* FROM messages m JOIN turns t ON t.message_id=m.id WHERE m.session_id=? AND m.client_id=?',(sid,data.client_message_id)).fetchone()
        if old:
            previous=json.loads(old['request_json']);comparison=dict(previous)
            for internal in ['profile_revision','release_id','trace_id']:comparison.pop(internal,None)
            if comparison!=payload:error(409,'IDEMPOTENCY_CONFLICT','重复消息标识的内容不同。')
            return {'turn_id':old['id'],'state':old['state'],'poll_after_ms':700}
        if s['revision']!=data.expected_profile_revision:error(409,'PROFILE_REVISION_CONFLICT','资料已更新，请刷新后提交。')
        if d.execute("SELECT 1 FROM turns WHERE session_id=? AND state IN ('RECEIVED','RUNNING')",(sid,)).fetchone():error(409,'TURN_IN_PROGRESS','上一轮仍在处理中。')
        mid=str(uuid4());tid=str(uuid4());payload['profile_revision']=s['revision'];payload['release_id']=active_id();payload['trace_id']=request.state.trace_id
        d.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)',(mid,sid,'user',data.text,data.client_message_id,now()))
        d.execute('INSERT INTO turns(id,message_id,session_id,state,request_json,created_at) VALUES(?,?,?,?,?,?)',(tid,mid,sid,'RECEIVED',json.dumps(payload,ensure_ascii=False),now()))
    bg.add_task(process,tid)
    return {'turn_id':tid,'state':'RECEIVED','poll_after_ms':700}

@app.get('/api/v1/turns/{tid}')
def turn_get(tid:str,uid=Depends(user)):
    with connect() as d:
        row=d.execute('SELECT t.* FROM turns t JOIN sessions s ON s.id=t.session_id WHERE t.id=? AND s.user_id=?',(tid,uid)).fetchone()
        if not row:error(404,'NOT_FOUND','记录不存在或不可访问。')
        return {'turn_id':tid,'state':row['state'],'result':json.loads(row['result_json']) if row['result_json'] else None,'error':row['error']}

@app.get('/api/v1/policies')
def policies(q:str='',uid=Depends(user)):
    return [{k:p[k] for k in ['key','id','title','parse_status','review_status','in_scope']} for p in get_knowledge().documents if p['in_scope'] and (not q or q in p['title'])]
@app.get('/api/v1/policies/{pid}/versions/{version}')
def policy_get(pid:str,version:str,uid=Depends(user)):
    kb,p=find_policy(pid,version)
    if not p:error(404,'NOT_FOUND','政策版本不存在或不在当前范围。')
    return {**{k:v for k,v in p.items() if k not in {'raw_file','archive_name','blob_file','upload_blob','origin_release'}},'version_id':policy_version(p),'release_id':kb.release_id}
@app.get('/api/v1/attachments/{key}')
def attachment(key:str,version:str='current',uid=Depends(user)):
    kb,p=find_policy(key,version)
    if not p:error(404,'NOT_FOUND','附件不存在。')
    try:path=kb.original_path(p)
    except ValueError:error(409,'ORIGINAL_INTEGRITY_FAILED','原件完整性或路径核验失败，请联系维护人员。')
    return FileResponse(path,filename=Path(p['archive_name']).name)

class HandoffInput(BaseModel):session_id:str
@app.post('/api/v1/handoffs/drafts')
def handoff(data:HandoffInput,uid=Depends(user)):
    with connect() as d:
        s=own(data.session_id,uid,d)
        row=d.execute("SELECT result_json FROM turns WHERE session_id=? AND state='COMPLETED' ORDER BY created_at DESC LIMIT 1",(s['id'],)).fetchone()
        result=json.loads(row['result_json']) if row else {}
        summary='咨询事项：'+s['title']+'\n已确认信息：'+json.dumps({k:v for k,v in json.loads(s['profile_json']).items() if not k.startswith('_')},ensure_ascii=False)+'\n待确认：'+'；'.join(result.get('unresolved_items',[]))+'\n依据：'+'；'.join(dict.fromkeys(x['title'] for x in result.get('sources',[])))+'\n请由本事项所属学院经办部门核实。当前仅生成摘要，尚未发送。'
        config=queue_config()
        hid=str(uuid4());p={'draft_id':hid,'state':'draft','text':summary,'submitted':False,'can_submit':config['enabled'],'recipient_label':config['label'],'recipient_revision':config['revision']}
        d.execute('INSERT INTO handoffs VALUES(?,?,?,?,?)',(hid,s['id'],json.dumps(p,ensure_ascii=False),'draft',now()))
        return p
@app.post('/api/v1/handoffs/{hid}/submit')
def handoff_submit(hid:str,data:ConsentInput=ConsentInput(),uid=Depends(user)):
    return submit_ticket(hid,uid,data)

@app.get('/api/v1/search')
def search(q:str=Query(min_length=1,max_length=1000),uid=Depends(user)):return get_knowledge().search(q)

admin_static=ROOT/'frontend'/'admin'
if admin_static.exists():app.mount('/admin',StaticFiles(directory=admin_static,html=True),name='admin')
static=ROOT/'frontend'/'student'/'dist'/'build'/'h5'
if static.exists():app.mount('/',StaticFiles(directory=static,html=True),name='student')

