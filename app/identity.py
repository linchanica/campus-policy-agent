"""Server-side WeChat code exchange and consented one-time cross-device pairing."""
import os,json,hashlib,secrets
from uuid import uuid4
from datetime import datetime,timedelta
import httpx
from fastapi import APIRouter,Header,Depends
from pydantic import BaseModel,Field,ConfigDict
from .config import TZ,now
from .auth import current_user,fail
from .db import connect,user_for,issue_token,audit

router=APIRouter(prefix='/api/v1/auth')
def wechat_configured():return bool(os.getenv('WX_APP_ID') and os.getenv('WX_APP_SECRET'))
def token_mode(d,authorization):
    hashed=hashlib.sha256(authorization.removeprefix('Bearer ').encode()).hexdigest()
    row=d.execute('SELECT auth_mode FROM auth_tokens WHERE token_hash=?',(hashed,)).fetchone()
    return row[0] if row else None
def merge_guest(d,guest_uid,target_uid,authorization):
    if guest_uid==target_uid:return
    if token_mode(d,authorization)!='local_guest':fail(409,'BINDING_NOT_ALLOWED','只允许明确确认后的本地访客记录迁移，不自动合并已有实名或微信身份。')
    if d.execute("SELECT 1 FROM turns t JOIN sessions s ON s.id=t.session_id WHERE s.user_id=? AND t.state IN ('RECEIVED','RUNNING')",(guest_uid,)).fetchone():fail(409,'TURN_IN_PROGRESS','请等待当前咨询完成后再绑定。')
    d.execute('UPDATE sessions SET user_id=? WHERE user_id=?',(target_uid,guest_uid))
    d.execute('UPDATE auth_tokens SET revoked_at=? WHERE user_id=?',(now(),guest_uid))

class WechatInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    code:str=Field(min_length=1,max_length=300)
    bind_guest:bool=False
@router.post('/wechat')
def wechat_login(data:WechatInput,authorization:str=Header(default='')):
    if not wechat_configured():fail(503,'FEATURE_UNAVAILABLE','尚未配置完整的小程序AppID和AppSecret。')
    old_uid=user_for(authorization.removeprefix('Bearer ')) if data.bind_guest else None
    if data.bind_guest and not old_uid:fail(401,'AUTH_REQUIRED','绑定需要有效的当前访客凭证。')
    try:
        with httpx.Client(timeout=12,trust_env=False) as client:
            response=client.get('https://api.weixin.qq.com/sns/jscode2session',params={'appid':os.environ['WX_APP_ID'],'secret':os.environ['WX_APP_SECRET'],'js_code':data.code,'grant_type':'authorization_code'})
        if response.status_code!=200:fail(503,'WECHAT_UNAVAILABLE','微信登录交换暂不可用，请稍后重试。')
        result=response.json()
    except (httpx.HTTPError,ValueError):fail(503,'WECHAT_UNAVAILABLE','微信登录交换暂不可用，请稍后重试。')
    if not isinstance(result,dict):fail(503,'WECHAT_INVALID_RESPONSE','微信身份交换未返回有效响应。')
    if result.get('errcode'):
        try:code=int(result['errcode'])
        except (TypeError,ValueError):fail(503,'WECHAT_INVALID_RESPONSE','微信身份交换未返回有效响应。')
        fail(401 if code in {40029,40163} else 503,'WECHAT_LOGIN_FAILED','微信登录凭证失效，请重新登录。' if code in {40029,40163} else '微信接入配置或服务状态需检查。')
    if not isinstance(result.get('openid'),str) or not result['openid']:fail(503,'WECHAT_INVALID_RESPONSE','未取得有效微信身份。')
    subject=hashlib.sha256((os.environ['WX_APP_ID']+':'+result['openid']).encode()).hexdigest()
    with connect() as d:
        d.execute('BEGIN IMMEDIATE')
        identity=d.execute("SELECT user_id FROM identities WHERE provider='wechat' AND subject_hash=?",(subject,)).fetchone()
        if identity:uid=identity[0]
        else:
            uid=str(uuid4());d.execute('INSERT INTO users VALUES(?,?,?)',(uid,secrets.token_hex(32),now()))
            d.execute('INSERT INTO user_roles VALUES(?,?,?,0)',(uid,'student','微信用户'))
            d.execute('INSERT INTO identities VALUES(?,?,?,?)',('wechat',subject,uid,now()))
        if old_uid:merge_guest(d,old_uid,uid,authorization)
        auth=issue_token(d,uid,'wechat')
    audit('wechat_login',uid,{'guest_bound':bool(old_uid),'openid_logged':False,'school_identity_verified':False})
    return {**auth,'guest_bound':bool(old_uid),'school_identity_verified':False}

@router.post('/pairing-codes')
def create_pairing(authorization:str=Header(default=''),uid=Depends(current_user)):
    code=secrets.token_urlsafe(18);expiry=(datetime.now(TZ)+timedelta(minutes=5)).isoformat()
    with connect() as d:
        if token_mode(d,authorization) not in {'wechat','oidc'}:fail(403,'VERIFIED_LOGIN_REQUIRED','请先在微信端或学校身份端登录，再生成本人另一端的绑定码。')
        role=d.execute('SELECT role FROM user_roles WHERE user_id=?',(uid,)).fetchone()
        if not role or role[0]!='student':fail(403,'STUDENT_PAIRING_ONLY','此入口只绑定学生端，不迁移管理身份。')
        d.execute('INSERT INTO pairing_codes VALUES(?,?,?,NULL)',(hashlib.sha256(code.encode()).hexdigest(),uid,expiry))
    audit('pairing_code_issued',uid,{'code_logged':False})
    return {'code':code,'expires_at':expiry,'notice':'仅在本人另一端输入，五分钟内一次有效，不要发到聊天或交给他人。'}

class PairInput(BaseModel):code:str=Field(min_length=20,max_length=100);confirm_merge:bool=False
@router.post('/pair')
def pair(data:PairInput,authorization:str=Header(default=''),uid=Depends(current_user)):
    if not data.confirm_merge:fail(422,'CONSENT_REQUIRED','请先确认将当前访客记录绑定到本人另一端身份。')
    with connect() as d:
        d.execute('BEGIN IMMEDIATE')
        row=d.execute('SELECT * FROM pairing_codes WHERE code_hash=?',(hashlib.sha256(data.code.encode()).hexdigest(),)).fetchone()
        if not row or row['used_at'] or datetime.now(TZ)>=datetime.fromisoformat(row['expires_at']):fail(401,'INVALID_PAIRING_CODE','绑定码已失效或已使用。')
        merge_guest(d,uid,row['user_id'],authorization)
        d.execute('UPDATE pairing_codes SET used_at=? WHERE code_hash=?',(now(),row['code_hash']))
        auth=issue_token(d,row['user_id'],'paired_web')
    audit('guest_identity_bound',row['user_id'],{'from_guest':uid,'explicit_consent':True})
    return {**auth,'bound':True}
