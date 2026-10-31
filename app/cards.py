"""Version-bound, source-quoted rule cards. No arbitrary code or model-written eligibility."""
import hashlib,json,re
from datetime import datetime,date
from pydantic import BaseModel,Field,ConfigDict
from typing import Literal
from .profile import ProfilePatch,LABELS
from .rules import evaluate
from .config import TZ

class BoundText(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=120)
    detail:str=Field(default='',max_length=1200)
    source_quote:str=Field(min_length=5,max_length=2000)
    attachment_key:str|None=None

class Condition(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=120)
    detail:str=Field(max_length=1200)
    expression:dict
    source_quote:str=Field(min_length=5,max_length=2000)

class Deadline(BaseModel):
    model_config=ConfigDict(extra='forbid')
    stage:str=Field(min_length=1,max_length=60)
    end:str
    precision:Literal['date','datetime']
    source_quote:str=Field(min_length=5,max_length=2000)

class PolicyCard(BaseModel):
    model_config=ConfigDict(extra='forbid')
    topic:str
    policy_key:str
    policy_version:str
    conditions:list[Condition]=Field(default_factory=list,max_length=30)
    steps:list[BoundText]=Field(default_factory=list,max_length=20)
    materials:list[BoundText]=Field(default_factory=list,max_length=30)
    deadline:Deadline|None=None
    materials_complete:bool=False
    unresolved_items:list[str]=Field(default_factory=list,max_length=20)

NUMERIC={'academic_rank_pct','comprehensive_rank_pct','year_of_study','cohort_year'}
def validate_expression(node,depth=0):
    if depth>8 or len(json.dumps(node))>20000:raise ValueError('规则表达式过深或过大。')
    op=node.get('op')
    if op in {'all','any','not'}:
        if set(node)!={'op','children'} or not isinstance(node['children'],list) or not 1<=len(node['children'])<=20:raise ValueError('规则分组非法。')
        if op=='not' and len(node['children'])!=1:raise ValueError('not只能含一条子规则。')
        for child in node['children']:validate_expression(child,depth+1)
    else:
        if op not in {'eq','in','lte','gte'} or set(node)!={'op','field','value'}:raise ValueError('不支持的规则操作。')
        field=node['field']
        if field not in ProfilePatch.model_fields:raise ValueError('规则字段不在画像模型中。')
        if op in {'lte','gte'} and field not in NUMERIC:raise ValueError('该字段不能使用数值比较。')
        values=node['value'] if op=='in' else [node['value']]
        if not isinstance(values,list) or not 1<=len(values)<=50:raise ValueError('规则取值非法。')
        for value in values:
            if value is None:raise ValueError('规则阈值不能是未知值。')
            ProfilePatch.model_validate({field:value},strict=True)
    return node

def input_fields(node):
    if node['op'] in {'all','any','not'}:return list(dict.fromkeys(f for c in node['children'] for f in input_fields(c)))
    return [node['field']]

def version(p):return p.get('version_id',p['sha256'][:16])
def validate_card(data,documents):
    from .workflow import TOPICS
    card=PolicyCard.model_validate(data)
    if card.topic not in TOPICS or card.policy_key!=TOPICS[card.topic]['key']:raise ValueError('规则卡事项与主政策不一致。')
    p=next((p for p in documents if p['key']==card.policy_key and p['in_scope']),None)
    if not p or card.policy_version!=version(p):raise ValueError('规则卡绑定的政策版本已变化。')
    for c in card.conditions:validate_expression(c.expression)
    quotes=[c.source_quote for c in card.conditions+card.steps+card.materials]
    if card.deadline:quotes.append(card.deadline.source_quote)
    if not all(q in p['text'] for q in quotes):raise ValueError('规则卡存在无法在绑定版本中找到的原文。')
    for item in card.materials:
        if item.attachment_key and not any(d['key']==item.attachment_key and d['in_scope'] for d in documents):raise ValueError('规则卡引用的附件不存在。')
    if card.deadline:
        w=card.deadline
        at=datetime.fromisoformat(w.end) if w.precision=='datetime' else date.fromisoformat(w.end)
        if isinstance(at,datetime) and at.tzinfo is None:raise ValueError('精确时间必须包含时区。')
        if isinstance(at,datetime):at=at.astimezone(TZ)
        day=at.date() if isinstance(at,datetime) else at
        patterns=[f'{day.year}年{day.month}月{day.day}日',f'{day.month}月{day.day}日',day.isoformat()]
        if not any(pat in w.source_quote for pat in patterns):raise ValueError('截止日期没有对应原文。')
        if isinstance(at,datetime) and not any(h in w.source_quote for h in [f'{at.hour}:{at.minute:02}',f'{at.hour}点',f'{at.hour}时']):raise ValueError('原文没有给出相应具体时刻。')
    return card.model_dump(mode='json')

def validate_cards(cards,documents):
    for topic,card in cards.items():
        if card.get('topic')!=topic:raise ValueError('规则卡键与事项不一致。')
        validate_card(card,documents)

def quoted_sources(kb,key,quote):
    p=kb.policy(key);start=p['text'].index(quote);a=p['text'][:start].count('\n');b=p['text'][:start+len(quote)].count('\n')
    alias=p.get('duplicate_of',key)
    return [s for s in kb.chunks if s['policy_key']==alias and s['paragraph_start']<=b and s['paragraph_end']>a]

def apply_card(result,kb,topic,profile,at,qualification):
    data=validate_card(kb.cards[topic],kb.documents);card=PolicyCard.model_validate(data)
    sources={s['source_id']:s for s in result['sources']};claims=[]
    def bind(kind,item):
        evidence=quoted_sources(kb,card.policy_key,item.source_quote)
        for s in evidence:sources[s['source_id']]=s
        cid=hashlib.sha256((topic+kind+item.name+item.source_quote).encode()).hexdigest()[:20]
        claims.append({'claim_id':cid,'kind':kind,'source_ids':[s['source_id'] for s in evidence],'source_quote':item.source_quote})
        return cid,[s['source_id'] for s in evidence]
    result['condition_results']=[];result['missing_fields']=[];result['questions']=[]
    if qualification:
        for c in card.conditions:
            state=evaluate(c.expression,profile);cid,ids=bind('condition',c)
            result['condition_results'].append({'name':c.name,'status':state,'detail':c.detail,'claim_id':cid,'source_ids':ids})
            if state=='unknown':result['missing_fields']+= [f for f in input_fields(c.expression) if profile.get(f) is None]
        states=[c['status'] for c in result['condition_results']]
        result['decision']='needs_human' if not states else ('not_met' if 'fail' in states else ('needs_information' if 'unknown' in states else 'preliminary_match'))
        result['missing_fields']=list(dict.fromkeys(result['missing_fields']))
        if result['decision']=='needs_information':result['questions']=['请补充'+'、'.join(LABELS[x] for x in result['missing_fields'][:2])+'。']
    else:result['decision']='information'
    result['summary']={'information':'已取得此版本审核规则卡对应的流程和材料。','needs_human':'此规则卡没有可执行资格条件，请向经办方核实。','not_met':'按自述信息，存在不满足的已编码条件。','needs_information':'请补充关键条件后继续核对。','preliminary_match':'自述信息与此版本已编码条件初步匹配，最终仍须业务审核。'}[result['decision']]
    result['steps']=[];result['materials']=[]
    for kind,items in [('steps',card.steps),('materials',card.materials)]:
        for item in items:
            cid,ids=bind(kind,item);entry={'name':item.name,'detail':item.detail,'status':'规则卡原文依据，待最终业务办理核实','claim_id':cid,'source_ids':ids}
            if item.attachment_key:entry['attachment_key']=item.attachment_key
            result[kind].append(entry)
    result['materials_complete']=card.materials_complete
    result['unresolved_items']+=card.unresolved_items
    result['window_status']={'state':'unknown','raw':None}
    if card.deadline:
        w=card.deadline;end=datetime.fromisoformat(w.end).astimezone(TZ) if w.precision=='datetime' else date.fromisoformat(w.end)
        current=at if w.precision=='datetime' else at.date()
        state='closed' if current>end else ('boundary_uncertain' if current==end else 'open_by_original_notice')
        result['window_status']={'state':state,'raw':w.source_quote,'stage':w.stage}
        if state=='closed':result['summary']='此版本原通知个人办理窗口已截止。'+result['summary']
        if state=='boundary_uncertain':result['summary']='当前位于原文日期或时刻边界，请先向经办方确认。'+result['summary']
    result['sources']=list(sources.values());result['claims']=claims
    if any(not c['source_ids'] for c in claims):raise ValueError('规则卡关键结论缺少片段引用。')
    return result
