"""Private local configuration. Secrets never enter API responses, stdout or bundles."""
import os,json,re
from pathlib import Path
from urllib.parse import urlparse
from fastapi import APIRouter,Depends
from pydantic import BaseModel,SecretStr,Field,ConfigDict
from .auth import roles,fail
from .config import ROOT,WORK,DEV
from .db import audit

router=APIRouter(prefix='/api/v1/admin')
CONFIG_PATH=ROOT/'.env';MINI_MANIFEST=ROOT/'frontend/student/src/manifest.json'
class IntegrationsInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    wx_app_id:str|None=Field(default=None,pattern=r'^wx[0-9a-f]{16}$')
    wx_app_secret:SecretStr|None=Field(default=None,min_length=16,max_length=256)
    llm_base_url:str|None=Field(default=None,max_length=500)
    llm_model:str|None=Field(default=None,min_length=1,max_length=200)
    llm_api_key:SecretStr|None=Field(default=None,min_length=8,max_length=1000)

@router.get('/integrations')
def get_config(uid=Depends(roles('admin'))):
    return {'wx_app_id':os.getenv('WX_APP_ID',''),'wx_secret_configured':bool(os.getenv('WX_APP_SECRET')),'llm_base_url':os.getenv('LLM_BASE_URL',''),'llm_model':os.getenv('LLM_MODEL',''),'llm_key_configured':bool(os.getenv('LLM_API_KEY')),'local_only':DEV}

@router.post('/integrations')
def save_config(data:IntegrationsInput,uid=Depends(roles('admin'))):
    if not DEV:fail(403,'LOCAL_CONFIG_DISABLED','正式环境请通过受控密钥配置管理，不在网页直接修改.env。')
    mapping={'wx_app_id':'WX_APP_ID','wx_app_secret':'WX_APP_SECRET','llm_base_url':'LLM_BASE_URL','llm_model':'LLM_MODEL','llm_api_key':'LLM_API_KEY'}
    values={mapping[k]:(v.get_secret_value() if isinstance(v,SecretStr) else v) for k,v in data if v is not None}
    if any('\n' in v or '\r' in v or '\x00' in v or v!=v.strip() for v in values.values()):fail(422,'INVALID_CONFIG','配置值不能包含换行、空字符或首尾空白。')
    merged={k:values.get(k,os.getenv(k,'')) for k in mapping.values()}
    if any(merged[k] for k in ['LLM_BASE_URL','LLM_MODEL','LLM_API_KEY']):
        if not all(merged[k] for k in ['LLM_BASE_URL','LLM_MODEL','LLM_API_KEY']):fail(422,'INCOMPLETE_MODEL_CONFIG','模型地址、名称和密钥须一起配置。')
        url=urlparse(merged['LLM_BASE_URL'])
        if not (url.scheme=='https' or url.scheme=='http' and url.hostname=='127.0.0.1') or not url.hostname or url.username or url.password or url.query or url.fragment:fail(422,'INVALID_MODEL_URL','模型地址须为HTTPS或本机HTTP，不能含账号、密钥参数或片段。')
        if merged['LLM_API_KEY'] in merged['LLM_BASE_URL']:fail(422,'KEY_IN_URL','密钥不能放入接口地址。')
    old_id=os.getenv('WX_APP_ID','')
    lines=CONFIG_PATH.read_text(encoding='utf-8-sig').splitlines() if CONFIG_PATH.exists() else []
    lines=[line for line in lines if line.split('=',1)[0].strip() not in values]
    lines += [k+'='+v for k,v in values.items()]
    temporary=WORK/'private-config-next.tmp';temporary.write_text('\n'.join(lines)+'\n',encoding='utf-8');os.replace(temporary,CONFIG_PATH)
    os.environ.update(values)
    if values.get('WX_APP_ID') and MINI_MANIFEST.exists():
        content=json.loads(MINI_MANIFEST.read_text(encoding='utf-8'));content.setdefault('mp-weixin',{})['appid']=values['WX_APP_ID'];MINI_MANIFEST.write_text(json.dumps(content,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    audit('integration_config_updated',uid,{'fields':list(values),'secret_values_logged':False})
    return {'saved':True,'wx_configured':bool(merged['WX_APP_ID'] and merged['WX_APP_SECRET']),'mini_program_rebuild_required':old_id!=merged['WX_APP_ID'],'message':'本机配置已保存，密钥不会回显。AppID变更后需重新构建小程序。'}
