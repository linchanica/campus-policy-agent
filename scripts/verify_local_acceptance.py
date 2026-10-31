"""Live HTTP checks of current local release, using fictional students only."""
import concurrent.futures,json,math,sys,time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
def consultation(text,simulation=False):
    began=time.monotonic()
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=20,trust_env=False) as c:
        auth=c.post('/api/v1/auth/guest').json();headers={'Authorization':'Bearer '+auth['access_token']}
        sid=c.post('/api/v1/sessions',headers=headers,json={'topic':'lei_undergrad' if simulation else 'midterm'}).json()['session_id']
        payload={'text':text,'client_message_id':'local-acceptance-'+str(time.time_ns()),'expected_profile_revision':0}
        if simulation:payload['simulation_time']='2026-10-24T10:00:00+08:00'
        response=c.post(f'/api/v1/sessions/{sid}/messages',headers=headers,json=payload);response.raise_for_status();tid=response.json()['turn_id']
        for _ in range(160):
            result=c.get('/api/v1/turns/'+tid,headers=headers).json()
            if result['state']=='COMPLETED':break
            if result['state'] in {'FAILED','STALE'}:raise AssertionError('HTTP consultation did not complete')
            time.sleep(.5)
        else:raise AssertionError('HTTP consultation exceeded bounded wait')
        r=result['result'];assert r['sources'] and r['validation']['source_ids_valid']
        assert c.get('/api/v1/admin/workspace',headers=headers).status_code==403
        if simulation:assert 'year_of_study' not in r['profile'] and 'program_level' not in r['profile']
        return {'duration_ms':round((time.monotonic()-began)*1000),'decision':r['decision'],'generation_mode':r['generation_mode'],'profile_candidates':len(r['profile_suggestions']['candidates']),'proposal_engine':r['profile_suggestions'].get('engine'),'source_ids_valid':True,'simulation':r['simulation']}
with httpx.Client(base_url='http://127.0.0.1:8000',timeout=20,trust_env=False) as c:
    health=c.get('/health/ready');health.raise_for_status()
    meta=c.get('/api/v1/meta').json()
    assert not meta['llm_configured'] and meta['local_llm_available']
    assert c.get('/admin/').status_code==200
profile=consultation('我今年读本科二年级，想申请雷军计算机本科生奖学金。',True)
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    cases=list(pool.map(lambda _:consultation('我是人工智能学院2025级学术学位硕士，请介绍中期考核流程与材料。'),range(4)))
times=sorted(c['duration_ms'] for c in cases)
report={'status':'pass','fictional_students_only':True,'release_id':meta['release_id'],'wechat_server_configuration_present':meta['wechat_configured'],'cloud_model_enabled':meta['llm_configured'],'local_profile_http_case':profile,'parallel_clients':4,'parallel_cases':cases,'sample_p50_ms':times[math.ceil(len(times)*.5)-1],'sample_p95_ms':times[math.ceil(len(times)*.95)-1],'browser_ui_tested':False,'real_wechat_login_tested':False,'scope':'四个虚构学生并行咨询及一轮本地画像候选链路；仅为本机小样本恢复与隔离检查，不代表生产容量或微信真机验收。'}
(ROOT/'docs/verification/local_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
