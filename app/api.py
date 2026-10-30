import json,secrets,time,threading,os
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
from pydantic import BaseModel,Field,ConfigDict
from .config import ROOT,WORK,DEV,RELEASE,now
from .db import initialize,connect,guest,user_for,audit,clear_user_sessions
from .knowledge import get_knowledge
from .profile import ProfilePatch
from .workflow import TOPICS
from .worker import process,recover
from .providers import configured

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

app=FastAPI(title='校院政策咨询 Agent',version='0.1.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:5173','http://localhost:5173','http://127.0.0.1:8000','http://localhost:8000'],allow_methods=['GET','POST','DELETE'],allow_headers=['Authorization','Content-Type'])
rates=defaultdict(deque)
@app.middleware('http')
async def limited(request,call_next):
    trace=secrets.token_hex(10);host=request.client.host if request.client else 'local'
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
def ready():return {'status':'ready','release_id':RELEASE,'policies':len(get_knowledge().documents),'mode':'local_trial'}
@app.get('/api/v1/meta')
def meta():
    kb=get_knowledge()
    from .local_model import available
    return {'title':'珞策 · 学生政策助手','release_id':RELEASE,'mode':'local_trial','llm_configured':configured(),'local_llm_available':available(),'index':{k:v for k,v in kb.index_info.items() if k!='chunk_ids'},'documents':len(kb.documents),'parsed':sum(p['parse_status']=='parsed' for p in kb.documents),'chunks':len(kb.chunks),'topics':[dict(t,id=id_) for id_,t in TOPICS.items()],'notice':'本地试用 · 政策整理副本待业务复核 · 人工转接仅生成摘要'}
@app.post('/api/v1/auth/guest')
def auth_guest():return guest()
@app.post('/api/v1/auth/wechat')
def auth_wechat():error(503,'FEATURE_UNAVAILABLE','尚未配置小程序账号和 AppID，请先使用本地试用。')

@app.post('/api/v1/auth/logout')
def logout(uid=Depends(user)):
    with connect() as d:
        d.execute('BEGIN IMMEDIATE')
        if d.execute("SELECT 1 FROM turns t JOIN sessions s ON s.id=t.session_id WHERE s.user_id=? AND t.state IN ('RECEIVED','RUNNING')",(uid,)).fetchone():error(409,'TURN_IN_PROGRESS','咨询仍在处理中，请完成后退出。')
        d.execute('UPDATE users SET token_hash=? WHERE id=?',(secrets.token_hex(32),uid))
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
def message(sid:str,data:MessageInput,bg:BackgroundTasks,uid=Depends(user)):
    if data.topic and data.topic not in TOPICS:error(422,'INVALID_TOPIC','未知事项')
    if data.simulation_time and (not DEV or data.simulation_time.tzinfo is None):error(422,'INVALID_TIME','回放仅供本地测试，且须指定时区。')
    payload=data.model_dump(mode='json');payload['profile_patch']=data.profile_patch.model_dump(exclude_unset=True)
    with connect() as d:
        d.execute('BEGIN IMMEDIATE');s=own(sid,uid,d)
        old=d.execute('SELECT t.* FROM messages m JOIN turns t ON t.message_id=m.id WHERE m.session_id=? AND m.client_id=?',(sid,data.client_message_id)).fetchone()
        if old:
            previous=json.loads(old['request_json']);comparison=dict(previous);comparison.pop('profile_revision',None)
            if comparison!=payload:error(409,'IDEMPOTENCY_CONFLICT','重复消息标识的内容不同。')
            return {'turn_id':old['id'],'state':old['state'],'poll_after_ms':700}
        if s['revision']!=data.expected_profile_revision:error(409,'PROFILE_REVISION_CONFLICT','资料已更新，请刷新后提交。')
        if d.execute("SELECT 1 FROM turns WHERE session_id=? AND state IN ('RECEIVED','RUNNING')",(sid,)).fetchone():error(409,'TURN_IN_PROGRESS','上一轮仍在处理中。')
        mid=str(uuid4());tid=str(uuid4());payload['profile_revision']=s['revision']
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
    p=get_knowledge().policy(pid)
    if not p or not p['in_scope'] or version not in {p['sha256'][:16],p['sha256'],'current'}:error(404,'NOT_FOUND','政策版本不存在或不在当前范围。')
    return {k:v for k,v in p.items() if k not in {'raw_file','archive_name'}}
@app.get('/api/v1/attachments/{key}')
def attachment(key:str,uid=Depends(user)):
    p=get_knowledge().policy(key)
    if not p or not p['in_scope']:error(404,'NOT_FOUND','附件不存在。')
    path=(ROOT/p['raw_file']).resolve()
    if not path.is_relative_to((ROOT/'data'/'raw').resolve()) or not path.is_file():error(404,'NOT_FOUND','附件不可用。')
    return FileResponse(path,filename=Path(p['archive_name']).name)

class HandoffInput(BaseModel):session_id:str
@app.post('/api/v1/handoffs/drafts')
def handoff(data:HandoffInput,uid=Depends(user)):
    with connect() as d:
        s=own(data.session_id,uid,d)
        row=d.execute("SELECT result_json FROM turns WHERE session_id=? AND state='COMPLETED' ORDER BY created_at DESC LIMIT 1",(s['id'],)).fetchone()
        result=json.loads(row['result_json']) if row else {}
        summary='咨询事项：'+s['title']+'\n已确认信息：'+json.dumps({k:v for k,v in json.loads(s['profile_json']).items() if not k.startswith('_')},ensure_ascii=False)+'\n待确认：'+'；'.join(result.get('unresolved_items',[]))+'\n依据：'+'；'.join(dict.fromkeys(x['title'] for x in result.get('sources',[])))+'\n请由本事项所属学院经办部门核实。当前仅生成摘要，尚未发送。'
        hid=str(uuid4());p={'draft_id':hid,'state':'draft','text':summary,'submitted':False}
        d.execute('INSERT INTO handoffs VALUES(?,?,?,?,?)',(hid,s['id'],json.dumps(p,ensure_ascii=False),'draft',now()))
        return p
@app.post('/api/v1/handoffs/{hid}/submit')
def handoff_submit(hid:str,uid=Depends(user)):
    with connect() as d:
        row=d.execute('SELECT h.id FROM handoffs h JOIN sessions s ON h.session_id=s.id WHERE h.id=? AND s.user_id=?',(hid,uid)).fetchone()
        if not row:error(404,'NOT_FOUND','记录不存在。')
    error(503,'FEATURE_UNAVAILABLE','尚未连接真实工单系统，可复制摘要自行咨询。')

@app.get('/api/v1/search')
def search(q:str=Query(min_length=1,max_length=1000),uid=Depends(user)):return get_knowledge().search(q)

static=ROOT/'frontend'/'student'/'dist'/'build'/'h5'
if static.exists():app.mount('/',StaticFiles(directory=static,html=True),name='student')

