"""Exercise the running local app using fictional data. Never persist credentials."""
import json,time,uuid,sys
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
base=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8000'
report={'base':base,'fixture':'fictional_student','checks':[],'turns':[]}
def check(name,condition):
    report['checks'].append({'name':name,'pass':bool(condition)})
    if not condition:raise AssertionError(name)

with httpx.Client(base_url=base,timeout=120,trust_env=False) as c:
    check('health_ready',c.get('/health/ready').json()['status']=='ready')
    page=c.get('/')
    check('compiled_h5_served',page.status_code==200 and '/assets/' in page.text)
    guest=c.post('/api/v1/auth/guest').json();token=guest['access_token']
    check('guest_expiry_declared',bool(guest.get('expires_at')))
    headers={'Authorization':'Bearer '+token}
    sid=c.post('/api/v1/sessions',headers=headers,json={'topic':'lei_undergrad'}).json()['session_id']
    check('anonymous_session_denied',c.get('/api/v1/sessions/'+sid).status_code==401)
    other=c.post('/api/v1/auth/guest').json()['access_token']
    check('other_guest_denied',c.get('/api/v1/sessions/'+sid,headers={'Authorization':'Bearer '+other}).status_code==404)
    revision=0
    def turn(text,patch=None):
        global revision
        payload={'text':text,'client_message_id':'smoke-'+uuid.uuid4().hex,'expected_profile_revision':revision,'profile_patch':patch or {}}
        started=time.monotonic()
        r=c.post('/api/v1/sessions/'+sid+'/messages',headers=headers,json=payload)
        check('accepted_'+str(revision),r.status_code==202)
        tid=r.json()['turn_id']
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            response=c.get('/api/v1/turns/'+tid,headers=headers).json()
            if response['state'] in {'COMPLETED','FAILED','STALE'}:break
            time.sleep(.5)
        check('completed_'+str(revision),response['state']=='COMPLETED')
        result=response['result'];revision=result['profile_revision']
        report['turns'].append({'decision':result['decision'],'topic':result['topic'],'window':result.get('window_status',{}),'generation_mode':result['generation_mode'],'latency_ms':round((time.monotonic()-started)*1000),'source_keys':sorted({s['policy_key'] for s in result['sources']})})
        allowed={s['source_id']:s for s in result['sources']}
        model=result.get('model_explanation')
        check('real_source_ids_'+str(revision),all(i in allowed for cond in result['condition_results'] for i in cond['source_ids']))
        if model:check('model_quote_grounded_'+str(revision),bool(model['source_ids']) and any(model['summary'] in allowed[i]['text'] for i in model['source_ids']))
        same=c.post('/api/v1/sessions/'+sid+'/messages',headers=headers,json=payload)
        check('idempotent_'+str(revision),same.status_code==202 and same.json()['turn_id']==tid)
        return result
    first=turn('我是人工智能学院大二全日制普通班，学习成绩排名前18%，综测前25%，我能申请雷军本科生奖学金吗？')
    check('two_rank_rule',next(x for x in first['condition_results'] if x['name']=='学习与综测双排名')['status']=='fail')
    check('current_deadline_closed',first['window_status']['state']=='closed')
    check('local_model_really_used',first['generation_mode']=='local_llm_evidence_and_rules' and first.get('model_explanation',{}).get('mode')=='local_evidence_selection')
    second=turn('请按我确认的成绩重新核对。',{'comprehensive_rank_pct':19,'achievement_eligible':True,'has_exclusion':False,'previous_leijun':False,'another_special_award':False,'major':'人工智能','achievements':'演示用虚构竞赛成果，尚需审核'})
    check('correction_recomputed',next(x for x in second['condition_results'] if x['name']=='学习与综测双排名')['status']=='pass')
    third=turn('我是马院硕士，请确认我的信息。')
    check('conflicting_identity_not_overwritten',bool(third['conflicts']) and third['profile']['college']=='SAI')
    fourth=turn('请按我确认的学院和学历查询中期考核材料。',{'college':'MARX','program_level':'master'})
    check('marx_midterm_no_ai_rules',fourth['topic']=='midterm_marx' and fourth['decision']=='needs_human' and not fourth['condition_results'] and {s['policy_key'] for s in fourth['sources']}=={'p026'})
    ambiguous_sid=c.post('/api/v1/sessions',headers=headers,json={}).json()['session_id']
    ambiguous_turn=c.post('/api/v1/sessions/'+ambiguous_sid+'/messages',headers=headers,json={'text':'我是硕士，我能申请雷军奖学金吗？','client_message_id':'ambiguous-'+uuid.uuid4().hex,'expected_profile_revision':0}).json()['turn_id']
    for _ in range(120):
        ambiguous=c.get('/api/v1/turns/'+ambiguous_turn,headers=headers).json()
        if ambiguous['state'] in {'COMPLETED','FAILED','STALE'}:break
        time.sleep(.5)
    check('unknown_award_never_defaults_to_doctoral_scheme',ambiguous['state']=='COMPLETED' and ambiguous['result']['topic'] is None and ambiguous['result']['decision']=='needs_information' and not ambiguous['result']['condition_results'])
    source=first['sources'][0]
    detail=c.get('/api/v1/policies/'+source['policy_key']+'/versions/'+source['version_id'],headers=headers)
    check('versioned_policy_accessible',detail.status_code==200 and source['text'] in detail.json()['text'])
    check('original_attachment_accessible',c.get('/api/v1/attachments/p012',headers=headers).status_code==200)
    draft=c.post('/api/v1/handoffs/drafts',headers=headers,json={'session_id':sid}).json()
    check('handoff_draft_not_sent',draft['submitted'] is False)
    check('unconfigured_submission_explicit',c.post('/api/v1/handoffs/'+draft['draft_id']+'/submit',headers=headers).status_code==503)
    check('clear_own_history',c.delete('/api/v1/sessions',headers=headers).status_code==200)
    check('cleared_session_unavailable',c.get('/api/v1/sessions/'+sid,headers=headers).status_code==404)
    check('policy_survives_history_clear',c.get('/api/v1/attachments/p012',headers=headers).status_code==200)
    check('logout_revokes_guest',c.post('/api/v1/auth/logout',headers=headers).status_code==200 and c.get('/api/v1/sessions',headers=headers).status_code==401)
    check('other_guest_unaffected',c.get('/api/v1/sessions',headers={'Authorization':'Bearer '+other}).status_code==200)
report['passed']=sum(x['pass'] for x in report['checks']);report['total']=len(report['checks']);report['status']='pass'
folder=ROOT/'docs'/'verification';folder.mkdir(parents=True,exist_ok=True)
(folder/'live_smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':report['status'],'passed':report['passed'],'total':report['total'],'turns':report['turns']},ensure_ascii=False,indent=2))
