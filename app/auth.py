"""Project authentication and role checks; local invitations cannot verify school staff."""
import hashlib,secrets
from datetime import datetime,timedelta
from fastapi import APIRouter,Header,Depends,HTTPException
from pydantic import BaseModel,Field
from typing import Literal
from .db import connect,user_for,role_for,audit
from .config import DEV,TZ,now

router=APIRouter(prefix='/api/v1')
def fail(status,code,message):raise HTTPException(status,detail={'code':code,'message':message})
def current_user(authorization:str=Header(default='')):
    uid=user_for(authorization.removeprefix('Bearer '))
    if not uid:fail(401,'AUTH_REQUIRED','身份已失效，请重新登录或创建试用身份。')
    return uid
def roles(*allowed):
    def check(uid=Depends(current_user)):
        if role_for(uid)['role'] not in allowed:fail(403,'FORBIDDEN','当前身份没有该操作权限。')
        return uid
    return check

@router.get('/auth/me')
def me(authorization:str=Header(default=''),uid=Depends(current_user)):
    data=role_for(uid)
    with connect() as d:row=d.execute('SELECT auth_mode FROM auth_tokens WHERE token_hash=?',(hashlib.sha256(authorization.removeprefix('Bearer ').encode()).hexdigest(),)).fetchone()
    return {'user_id':uid,'role':data['role'],'display_name':data['display_name'],'verified_staff':bool(data['verified_staff']),'auth_mode':row[0]}

class InvitationInput(BaseModel):
    role:Literal['admin','editor','reviewer','operator']
    display_name:str=Field(min_length=1,max_length=80)

def make_invitation(role,display_name):
    if not DEV:fail(403,'LOCAL_AUTH_DISABLED','正式环境不能使用本地邀请登录。')
    code=secrets.token_urlsafe(32)
    expiry=(datetime.now(TZ)+timedelta(minutes=30)).isoformat()
    with connect() as d:d.execute('INSERT INTO staff_invitations VALUES(?,?,?,?,NULL)',(hashlib.sha256(code.encode()).hexdigest(),role,display_name,expiry))
    return {'code':code,'expires_at':expiry,'role':role}

@router.post('/admin/invitations')
def invite(data:InvitationInput,uid=Depends(roles('admin'))):
    result=make_invitation(data.role,data.display_name)
    audit('local_staff_invited',uid,{'role':data.role})
    return result

class LoginInput(BaseModel):code:str=Field(min_length=20,max_length=200)
@router.post('/admin/login')
def staff_login(data:LoginInput):
    if not DEV:fail(403,'LOCAL_AUTH_DISABLED','正式环境不能使用本地邀请登录。')
    from uuid import uuid4
    uid=str(uuid4());token=secrets.token_urlsafe(40);hashed=hashlib.sha256(token.encode()).hexdigest()
    expiry=(datetime.now(TZ)+timedelta(hours=8)).isoformat()
    with connect() as d:
        d.execute('BEGIN IMMEDIATE')
        invite=d.execute('SELECT * FROM staff_invitations WHERE code_hash=?',(hashlib.sha256(data.code.encode()).hexdigest(),)).fetchone()
        if not invite or invite['used_at'] or datetime.now(TZ)>=datetime.fromisoformat(invite['expires_at']):fail(401,'INVALID_INVITATION','登录码已失效或已使用，请重新生成。')
        d.execute('UPDATE staff_invitations SET used_at=? WHERE code_hash=?',(now(),invite['code_hash']))
        d.execute('INSERT INTO users VALUES(?,?,?)',(uid,hashed,now()))
        d.execute('INSERT INTO user_roles VALUES(?,?,?,0)',(uid,invite['role'],invite['display_name']))
        d.execute('INSERT INTO auth_tokens VALUES(?,?,?,?,NULL)',(hashed,uid,'local_staff',expiry))
    audit('local_staff_login',uid,{'role':invite['role'],'verified_staff':False})
    return {'access_token':token,'expires_at':expiry,'role':invite['role'],'verified_staff':False}
