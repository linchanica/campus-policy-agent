"""stdio adapter: no notification sending or arbitrary local-file access."""
import json,os
from pydantic import ValidationError
os.environ.setdefault('DISABLE_LOCAL_LLM','1')
from mcp.server.mcpserver import MCPServer
from .knowledge import get_knowledge
from .rules import checks,window
from .profile import ProfilePatch
from .workflow import run,TOPICS
from .config import TZ
from datetime import datetime

mcp=MCPServer('campus-policy')

@mcp.tool()
def search_policy(query:str,topic:str|None=None)->dict:
    """Search the provided policy copies. Results require business review."""
    keys=[TOPICS[topic]['key']] if topic in TOPICS else None
    return {'sources':get_knowledge().search(query,keys),'review_status':'provided_copy_unreviewed'}

@mcp.tool()
def get_policy_evidence(source_id:str)->dict:
    """Fetch a source ID returned by search_policy."""
    return get_knowledge().by_id.get(source_id,{'error':'SOURCE_NOT_FOUND'})

@mcp.tool()
def check_eligibility(topic:str,profile:dict)->dict:
    """Compare declared information against encoded conditions, without final approval."""
    if topic not in TOPICS:return {'error':'UNKNOWN_TOPIC'}
    try:checked=ProfilePatch.model_validate(profile).model_dump(exclude_none=True)
    except ValidationError as error:
        fields=sorted({str(e['loc'][0]) if e['loc'] and e['loc'][0] in ProfilePatch.model_fields else 'user_input' for e in error.errors()})
        return {'error':'INVALID_PROFILE','fields':fields,'message':'画像枚举、范围或字段不合法，请确认后重试。'}
    result,_,_=run('我是否符合申请条件？',{},checked,topic)
    return {'decision':result['decision'],'summary':result['summary'],'conditions':result['condition_results'],'missing_fields':result['missing_fields'],'questions':result['questions'],'unresolved_items':result['unresolved_items'],'sources':result['sources'],'window_status':result['window_status'],'release_id':result['release_id'],'business_review_required':True}

@mcp.tool()
def get_materials_and_steps(topic:str)->dict:
    """Get the known materials and steps with missing-dependency warnings."""
    if topic not in TOPICS:return {'error':'UNKNOWN_TOPIC'}
    result,_,_=run('请介绍办理流程和材料',{}, {},topic)
    return {key:result[key] for key in ['decision','summary','steps','materials','materials_complete','sources','unresolved_items','window_status','release_id']}

@mcp.tool()
def prepare_handoff(question:str,unresolved_items:list[str])->dict:
    """Prepare a draft only. Does not send to a person or business system."""
    return {'state':'draft','submitted':False,'text':'咨询事项：'+question+'\n待核实：'+'；'.join(unresolved_items)+'\n请交由对应学院经办部门核实。'}

if __name__=='__main__':mcp.run(transport='stdio')

