import json,re,time
from datetime import datetime
from .config import RELEASE,TZ,now
from .knowledge import get_knowledge
from .profile import extract,LABELS,VALUES
from .rules import checks,window
from . import providers

TOPICS={
 'lei_undergrad':{'name':'雷军计算机本科生奖学金','key':'p012','category':'奖学金','description':'学习与综测双排名、成果与互斥条件'},
 'lei_graduate':{'name':'雷军计算机研究生奖学金','key':'p013','category':'奖学金','description':'2026级特定培养路径的博士新生'},
 'midterm':{'name':'人工智能学院硕士中期考核','key':'p032','category':'培养管理','description':'2025级学术学位硕士'},
 'midterm_marx':{'name':'马院硕士中期考核','key':'p026','category':'培养管理','description':'原文检索，结构化流程待复核'},
 'phd':{'name':'人工智能学院硕博连读','key':'p032','category':'培养管理','description':'2024、2025级全日制学术学位硕士'},
 'phd_marx':{'name':'马院硕博连读','key':'p051','category':'培养管理','description':'学院细则、申请阶段与考核安排'}
}

def choose_topic(text,profile,current=None):
    if '雷军' in text:
        if '计算机' not in text and current not in {'lei_undergrad','lei_graduate'}:return None
        if '本科' in text:return 'lei_undergrad'
        if re.search(r'博士|研究生|硕士',text):return 'lei_graduate'
        if current in {'lei_undergrad','lei_graduate'}:return current
        if profile.get('program_level') in {'master','doctor'}:return 'lei_graduate'
        if profile.get('program_level')=='undergraduate':return 'lei_undergrad'
        return None
    marx=bool(re.search(r'马院|马克思主义学院',text)) or profile.get('college')=='MARX'
    if '硕博连读' in text:return 'phd_marx' if marx else 'phd'
    if '中期考核' in text:return 'midterm_marx' if marx else 'midterm'
    if re.search(r'休学|转专业|转学院|医保|签证|国家奖学金',text):return None
    if current in {'phd','phd_marx'}:
        return ('phd_marx' if profile.get('college')=='MARX' else 'phd') if profile.get('college') else current
    if current in {'midterm','midterm_marx'}:
        return ('midterm_marx' if profile.get('college')=='MARX' else 'midterm') if profile.get('college') else current
    return current if current in TOPICS else None

def run(text,old_profile,patch,current_topic=None,at=None,message_id=None,simulation=False,release_id=None):
    started=time.monotonic();kb=get_knowledge(release_id)
    if kb.release_id!=RELEASE:
        from .releases import assert_runtime
        assert_runtime(kb.manifest)
    profile=dict(old_profile);evidence=dict(profile.pop('_field_evidence',{}));conflicts={}
    found=extract(text)
    for key,value in found.items():
        if key.startswith('_'):continue
        if profile.get(key) is not None and profile[key]!=value and key not in patch:
            conflicts[key]={'old':profile[key],'new':value}
        else:profile[key]=value;evidence[key]={'message_id':message_id,'kind':'student_statement'}
    for key,value in patch.items():
        profile[key]=value;evidence[key]={'message_id':message_id,'kind':'student_confirmed_form'}
    profile['_field_evidence']=evidence
    topic=choose_topic(text,profile,current_topic)
    at=at or datetime.now(TZ)
    keys=[TOPICS[topic]['key']] if topic else None
    retrieved=kb.search(text,keys=keys,limit=8)
    sources={x['source_id']:x for x in retrieved}
    result={'topic':topic,'summary':'','decision':'information','profile':profile,'condition_results':[],'questions':[],'missing_fields':[],'conflicts':conflicts,'steps':[],'materials':[],'materials_complete':True,'sources':[],'unresolved_items':['当前依据为用户提供的整理副本，尚待学校或学院业务人员复核。'] if not kb.manifest.get('business_review_complete') else ['已取得审核发布快照，个体条件及实际证明材料仍须经办审核。'],'query_time':at.isoformat(),'simulation':simulation,'release_id':kb.release_id,'generation_mode':'evidence_and_rules','model_explanation':None,'handoff':{'state':'draft_available','submitted':False},'events':['识别事项与画像','混合检索','范围与时间检查']}
    qualification=bool(re.search(r'能[否不]?申|可以申|能不能|符合|资格|能报|能参加|是否满足|想申请|要申请',text) or patch)
    policy=kb.policy(TOPICS[topic]['key']) if topic else None
    baseline=get_knowledge(RELEASE).policy(TOPICS[topic]['key']) if topic else None
    stale_rules=bool(topic and (not policy or not policy['in_scope'] or policy.get('content_revision',policy['sha256'])!=baseline['sha256']))
    if conflicts:
        result['decision']='needs_information'
        for key,v in conflicts.items():result['questions'].append(f"你本轮提供的{LABELS.get(key,key)}与已确认信息不同，请在资料面板确认是否由“{VALUES.get(v['old'],v['old'])}”改为“{VALUES.get(v['new'],v['new'])}”。")
        result['summary']='发现身份或条件变化，确认后会重新匹配政策。'
        result['missing_fields']=list(conflicts)
    elif topic in kb.cards:
        from .cards import apply_card
        result['sources']=list(sources.values());apply_card(result,kb,topic,profile,at,qualification)
        sources={s['source_id']:s for s in result['sources']}
    elif stale_rules:
        result['decision']='needs_human';result['summary']='该事项的政策版本已更新，尚无与新版本绑定并复核的结构化规则卡。请查阅当前原文并由经办人员核实。'
        result['window_status']={'state':'unknown','raw':None};result['materials_complete']=False
        result['unresolved_items'].append('没有套用旧版本的条件、截止日期或材料清单。')
    elif topic=='midterm_marx':
        result['decision']='needs_human'
        result['summary']='你正在咨询马院中期考核，应核对马院通知。当前结构化流程仅覆盖人工智能学院中期考核，请查看马院检索原文并向对应学院确认。'
        result['window_status']={'state':'unknown','raw':None}
        result['materials_complete']=False
        result['unresolved_items'].append('马院中期考核尚未完成结构化规则与流程复核，不套用其他学院的条件、时间或附件。')
    elif topic:
        key=TOPICS[topic]['key'];win=window(topic,at);result['window_status']=win
        if qualification:
            missing=[]
            for name,status,fields,detail,phrase in checks(topic,profile):
                src=kb.evidence(key,phrase)
                for s in src:sources[s['source_id']]=s
                result['condition_results'].append({'name':name,'status':status,'detail':detail,'source_ids':[s['source_id'] for s in src]})
                if status=='unknown':missing.extend(f for f in fields if profile.get(f) is None)
            result['missing_fields']=list(dict.fromkeys(missing))
            statuses=[c['status'] for c in result['condition_results']]
            result['decision']='not_met' if 'fail' in statuses else ('needs_information' if 'unknown' in statuses else 'preliminary_match')
            if result['decision']=='needs_information':
                result['questions']=['请补充'+ '、'.join(LABELS[x] for x in result['missing_fields'][:2])+'。'] if result['missing_fields'] else ['部分条件需要经办人员结合证明材料核实。']
            result['summary']={'not_met':'按你已确认的信息，存在不满足的已编码条件。','needs_information':'还需补充或核实部分信息，才能完成条件对照。','preliminary_match':'按自述信息，已编码条件初步匹配；其他基本要求及证明材料仍须审核。'}[result['decision']]
        else:result['summary']='已定位适用事项的通知，以下提供有原文依据的办理信息。'
        if win['state']=='closed':result['summary']='该轮个人申报已超过原通知截止时间（'+win['raw']+'）。尚无延期或补报依据。'+result['summary']
        elif win['state']=='boundary_uncertain':result['summary']='原通知写明“'+win['raw']+'”，当前处于边界日期或时刻，请先向经办方确认。'+result['summary']
        if topic.startswith('lei'):
            result['materials_complete']=False
            result['materials']=[{'name':'按正文填写报名表或专项奖学金申请表，并提供相应证明材料','status':'正文明确，完整清单待补','source_ids':[s['source_id'] for s in kb.evidence(key,'个人申报')]}]
            result['unresolved_items'].append('通知引用的完整材料清单等附件未在原压缩包中取得，不能补造完整要求。')
            result['steps']=[{'name':'个人申报','detail':'按本轮通知提交信息和纸质材料；原窗口已截止时不代表仍可新申报。'},{'name':'资格审核与评审','detail':'由评审组织审定材料、组织评审，最终结果以审核和公示为准。'}]
        elif topic=='midterm':
            result['materials']=[{'name':'武汉大学学术学位硕士研究生中期考核登记表','attachment_key':'p033','status':'原件已取得，待业务复核'}]
            result['steps']=[{'name':'平台申请与准备登记表','detail':'在研究生综合服务平台提交中期考核申请，填写登记表并交考核组秘书。'},{'name':'汇报与考核','detail':'按学院实际分组安排参加汇报，结果经审核、公示及归档。'}]
        elif topic=='phd':
            result['materials']=[{'name':name,'attachment_key':key_,'status':'原件已取得，待业务复核'} for name,key_ in [('硕博连读研究生申请表','p034'),('硕博连读生资格考核登记表','p035'),('人工智能学院硕博连读研究生推荐表 两份','p036')]]+[{'name':'科研成果及检索报告等支撑材料','status':'按正文及经办要求核对'}]
            result['steps']=[{'name':'提交申请与证明材料','detail':'原通知要求提交至学院教学与科研管理办公室A208室；日期边界另行确认。'},{'name':'审核与选拔考核','detail':'依据学院通知及后续安排参加审核、汇报与答辩，再公示选拔结果。'}]
        else:
            result['materials_complete']=False
            result['materials']=[{'name':'硕博连读申请表、两位专家推荐信、英语水平与科研成果证明','status':'正文列明；表格版本及完整依据待核实'}]
            result['steps']=[{'name':'申请提报','detail':'经本人硕导和学科点审核同意后，到教学办申请登记。'},{'name':'初审与考核','detail':'核对个人申请截止与学院考核阶段，按实际通知参加笔试、面试和公示。'}]
            result['unresolved_items'].append('马院细则引用的部分附件与转硕文号有待核对，不自行修正。')
        for phrase in ['个人申报','申请','考核安排','材料','评审程序']:
            for s in kb.evidence(key,phrase):sources[s['source_id']]=s
    else:
        result['window_status']={'state':'unknown','raw':None}
        if not retrieved or max(s.get('score',0) for s in retrieved)==0:
            result['decision']='needs_human';result['summary']='当前资料不足以支持具体结论，请明确事项或联系经办方。'
        else:
            result['summary']='下面是与问题相关的政策原文。当前结构化流程覆盖雷军奖学金、中期考核和硕博连读，请选择事项以继续精准匹配。'
            result['decision']='evidence_only'
        result['questions']=['你要咨询奖学金、中期考核，还是硕博连读？']
        if '雷军' in text:
            result['decision']='needs_information'
            result['summary']='当前资料包含雷军计算机本科生奖学金和雷军计算机研究生奖学金，两者对象不同。其他同名雷军奖学金不能直接套用这些条件。'
            result['questions']=['请先确认你指的是雷军计算机奖学金，还是其他同名奖学金。若是前者，可选择本科生或研究生奖学金事项继续。']
            if '计算机' in text:result['questions']=['你咨询本科生奖学金，还是面向2026级特定博士新生的研究生奖学金？']
    result['sources']=list(sources.values()) if topic in kb.cards else list(sources.values())[:16]
    allowed={s['source_id'] for s in result['sources']}
    for c in result['condition_results']:c['source_ids']=[x for x in c['source_ids'] if x in allowed]
    result['validation']={'source_ids_valid':all(c['source_ids'] for c in result['condition_results']) if result['condition_results'] else True,'policy_review':'business_reviewed' if kb.manifest.get('business_review_complete') else 'pending_business_review','reviewed_approval':False}
    if not result['validation']['source_ids_valid']:
        result['decision']='needs_human';result['summary']='关键条件缺少可核验出处，请由经办人员核实。'
    for item in result['materials']:
        if item.get('attachment_key'):
            attached=kb.policy(item['attachment_key'])
            if attached:item['attachment_version']=attached.get('version_id',attached['sha256'][:16])
    result['profile_suggestions']={'status':'not_needed','candidates':[]}
    if result['decision']=='needs_information' and not conflicts and result.get('window_status',{}).get('state')!='closed':
        from .profile_llm import propose
        result['profile_suggestions']=propose(text,[f for f in result['missing_fields'] if profile.get(f) is None])
        if result['profile_suggestions']['candidates']:result['events'].append('本地模型提出画像候选，等待学生确认')
    from .local_model import available
    if available():
        try:
            result['model_explanation']=providers.grounded_summary(text,result['sources'])
            if result['model_explanation']:result['generation_mode']='local_llm_evidence_and_rules'
        except Exception:result['unresolved_items'].append('模型解释暂不可用，已保留政策原文和程序条件结果。')
    result['events']+=['逐项条件核对','来源标识核验','生成办理卡']
    result['duration_ms']=round((time.monotonic()-started)*1000)
    return result,profile,topic

