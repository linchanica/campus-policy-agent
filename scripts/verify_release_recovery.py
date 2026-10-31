"""Isolated publication, historical evidence, rollback and backup recovery exercise."""
import json,os,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['POLICY_WORK_DIR']=tempfile.mkdtemp(prefix='release-recovery-',dir=ROOT/'work')
os.environ['APP_ENV']='development'
os.environ['DISABLE_LOCAL_LLM']='1';os.environ['DISABLE_PROFILE_LLM']='1'
for key in ['LLM_BASE_URL','LLM_MODEL','LLM_API_KEY','WX_APP_ID','WX_APP_SECRET']:os.environ[key]=''
from app.db import initialize,create_user
from app import releases,maintenance
from app.knowledge import get_knowledge
from app.workflow import run
from app.config import RELEASE,now

initialize();began=time.monotonic()
uid=create_user('admin','虚构恢复演练人员')['user_id']
def candidate(title):
    d=releases.create_draft(uid)
    d=releases.replace_document(d['id'],'p012',uid,d['revision'],patch={'title':title,'source_url':'https://example.invalid/recovery-test'})
    d=releases.review(d['id'],'p012',uid,d['revision'],'approved',{k:True for k in releases.REVIEW_CHECKS},'仅为隔离恢复演练，不代表学校审核。')
    built=releases.build(d['id'],uid,semantic=True,kind='trial')
    return built['release_id']
one=candidate('隔离恢复演练版本一');releases.publish(one,uid,RELEASE)
assert get_knowledge(one).index_info['engine']=='semantic_bge'
sources=get_knowledge(one).search('雷军计算机本科生奖学金',keys=['p012'])
two=candidate('隔离恢复演练版本二');releases.publish(two,uid,one)
assert releases.find_source(sources[0]['source_id'])['version_id']==sources[0]['version_id']
old,_,_=run('能申请雷军计算机本科生奖学金吗？',{}, {},release_id=one)
assert old['release_id']==one and old['decision']=='needs_human'
maintenance.backup();recovered=maintenance.restore_check()
assert recovered['restored_release_id']==two
releases.publish(one,uid,two,rollback=True)
assert releases.active_id()==one
releases.publish(RELEASE,uid,one,rollback=True)
assert releases.active_id()==RELEASE
report={'status':'pass','created_at':now(),'isolated_runtime':True,'live_policies_changed':False,'formal_review_created':False,'snapshots_built':2,'snapshot_index_engine':'semantic_bge','historical_source_verified':True,'accepted_turn_keeps_original_release':True,'backup_active_pointer_restored':True,'rollback_previous_release':True,'rollback_imported_baseline':True,'restored_documents':recovered['restored_documents'],'files_verified':recovered['files_verified'],'duration_seconds':round(time.monotonic()-began,2)}
(ROOT/'docs/verification/release_recovery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
