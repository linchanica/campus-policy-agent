import json
from datetime import datetime
import pytest
from app.config import TZ
from app.profile import extract
from app.profile_llm import parse_candidates
from app.workflow import run


@pytest.mark.parametrize('text',[
    '学习成绩排名要前20%吗？',
    '我是人工智能学院本科生，综测要求前20%吗？',
    '我同学的成绩排名前10%，综测前8%',
    '如果我是人工智能学院大二，学习成绩前5%，能申请吗？',
    '我是人工智能学院本科生，通知规定中期考核优秀才能申请吗？',
])
def test_questions_and_other_people_are_not_profile_facts(text):
    p=extract(text)
    assert 'academic_rank_pct' not in p and 'comprehensive_rank_pct' not in p and 'midterm_result' not in p


def test_negated_or_ambiguous_identity_stays_unknown():
    assert 'study_mode' not in extract('我不是全日制硕士')
    assert 'program_level' not in extract('我是本科毕业后继续读硕士的学生')
    assert 'college' not in extract('我不是人工智能学院的学生')


def test_own_ranks_are_retained_and_not_swapped():
    p=extract('我是人工智能学院大二本科生，学习成绩排名前5%，综测前8%。')
    assert p['academic_rank_pct']==5 and p['comprehensive_rank_pct']==8 and p['year_of_study']==2


def test_model_candidates_need_literal_self_evidence_and_correct_field():
    text='我的学习成绩排名前5%，我的综测前8%。'
    raw=json.dumps({'academic_rank_pct':{'value':8,'quote':text},'comprehensive_rank_pct':{'value':8,'quote':text},'achievement_eligible':{'value':True,'quote':text}})
    candidates=parse_candidates(raw,text,['academic_rank_pct','comprehensive_rank_pct','achievement_eligible'])
    assert [c['field'] for c in candidates]==['comprehensive_rank_pct']
    assert candidates[0]['confirmation_required'] is True
    assert not parse_candidates('{"college":{"value":"SAI","quote":"我是人工智能学院"}}','我是马院学生',['college'])


def test_local_model_candidate_does_not_change_confirmed_profile(monkeypatch):
    from app import profile_llm
    suggestion={'field':'year_of_study','label':'当前年级','value':2,'quote':'我今年读本科二年级','confirmation_required':True,'status':'proposed'}
    monkeypatch.setattr(profile_llm,'propose',lambda *a,**k:{'status':'proposed','engine':'local_llm','candidates':[suggestion]})
    result,profile,_=run('我今年读本科二年级，想申请雷军计算机本科生奖学金。',{}, {},at=datetime(2026,10,24,tzinfo=TZ))
    assert result['profile_suggestions']['candidates']==[suggestion]
    assert 'year_of_study' not in profile and result['decision']=='needs_information'
    confirmed,profile,_=run('已核对并确认我的年级。',profile,{'year_of_study':2},'lei_undergrad',at=datetime(2026,10,24,tzinfo=TZ))
    assert profile['year_of_study']==2 and profile['_field_evidence']['year_of_study']['kind']=='student_confirmed_form'

def test_constrained_local_selection_keeps_typed_literal_quote(monkeypatch):
    from app import profile_llm,local_model
    monkeypatch.setenv('DISABLE_PROFILE_LLM','0')
    monkeypatch.setattr(local_model,'available',lambda:True)
    monkeypatch.setattr(local_model,'generate_json',lambda *a,**k:'1')
    result=profile_llm.propose('我今年读本科二年级。',['year_of_study'])
    assert result['candidates'][0]['value']==2 and result['candidates'][0]['confirmation_required'] is True
    monkeypatch.setattr(local_model,'generate_json',lambda *a,**k:'没有明确事实')
    assert not profile_llm.propose('我今年读本科二年级。',['year_of_study'])['candidates']


def test_configured_cloud_is_not_called_without_consent(monkeypatch):
    from app import providers,local_model
    monkeypatch.setattr(providers,'configured',lambda:True)
    monkeypatch.setattr(local_model,'available',lambda:True)
    monkeypatch.setattr(local_model,'select',lambda *a:{'summary':'测试本地证据','source_ids':[],'mode':'local_evidence_selection'})
    def forbidden(*a,**k):raise AssertionError('external HTTP must not be used')
    monkeypatch.setattr(providers.httpx,'Client',forbidden)
    result,_,_=run('请介绍中期考核材料。',{}, {})
    assert result['generation_mode']=='local_llm_evidence_and_rules'


def test_late_worker_cannot_overwrite_new_attempt_or_session(monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import app
    from app.db import connect
    from app import worker
    def superseded(*args,**kwargs):
        with connect() as d:
            d.execute("UPDATE turns SET attempt=attempt+1,state='FAILED',error='已由新的尝试终止' WHERE state='RUNNING'")
        return {'decision':'information','release_id':'fictional'}, {'college':'SAI'}, 'midterm'
    monkeypatch.setattr(worker,'run',superseded)
    with TestClient(app) as c:
        auth=c.post('/api/v1/auth/guest').json();h={'Authorization':'Bearer '+auth['access_token']}
        sid=c.post('/api/v1/sessions',headers=h,json={}).json()['session_id']
        turn=c.post(f'/api/v1/sessions/{sid}/messages',headers=h,json={'text':'测试恢复并发','client_message_id':'worker-claim-race','expected_profile_revision':0}).json()
        result=c.get('/api/v1/turns/'+turn['turn_id'],headers=h).json()
        session=c.get('/api/v1/sessions/'+sid,headers=h).json()
        assert result['state']=='FAILED' and result['result'] is None
        assert session['revision']==0 and session['profile']=={}
