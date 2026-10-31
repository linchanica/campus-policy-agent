"""Local data audit and isolated recovery. Never marks policy copies approved."""
import hashlib,json,os,shutil,sqlite3,subprocess,sys,time
from pathlib import Path
from datetime import datetime
import numpy as np
from .config import ROOT,DATA,WORK,RELEASE,now,io_path

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write_report(name,report):
    folder=ROOT/'docs'/'verification';folder.mkdir(parents=True,exist_ok=True)
    (folder/name).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

def export_review_queue():
    manifest=json.loads((DATA/'manifests'/'policies.json').read_text(encoding='utf-8'))
    rows=[]
    for p in manifest['files']:
        raw=(ROOT/p['raw_file']).resolve()
        valid=raw.is_relative_to((DATA/'raw').resolve()) and raw.is_file() and digest(raw)==p['sha256']
        rows.append({'policy_key':p['key'],'title':p['title'],'sha256':p['sha256'],'in_scope':p['in_scope'],'parse_status':p['parse_status'],'raw_hash_valid':valid,'origin':'provided_copy','official_source_url':p.get('source_url'),'review_status':'pending_business_review','reviewer':None,'reviewed_at':None,'checks':{'official_version_confirmed':None,'college_and_student_scope_confirmed':None,'effective_dates_and_stages_confirmed':None,'paragraphs_and_tables_confirmed':None,'referenced_attachments_complete':None,'encoded_conditions_confirmed':None},'notes':[]})
    report={'release_id':RELEASE,'generated_at':now(),'count':len(rows),'business_review_complete':False,'note':'哈希核对仅验证本地副本完整性，不能证明官网来源、政策有效性或审核通过。请由具备职责的学校或学院业务人员复核。','known_gaps':['雷军奖学金正文引用的完整材料清单等附件未取得','马院部分附件与转硕文号待核实','原通知日期边界不能自行补成具体时刻'],'items':rows}
    folder=ROOT/'docs';folder.mkdir(exist_ok=True)
    (folder/'policy-review-queue.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(x['raw_hash_valid'] for x in rows):raise ValueError('Some originals fail integrity checks')
    return {'documents':len(rows),'raw_hashes_valid':True,'business_review_complete':False}

def backup():
    folder=io_path(WORK/'backups'/datetime.now().strftime('%Y%m%d_%H%M%S_%f'));folder.mkdir(parents=True)
    runtime=folder/'work';runtime.mkdir()
    with sqlite3.connect(WORK/'policy.db') as source,sqlite3.connect(runtime/'policy.db') as target:source.backup(target)
    shutil.copytree(DATA,folder/'data')
    with sqlite3.connect(runtime/'policy.db') as saved:
        ids=[r[0] for r in saved.execute('SELECT id FROM release_snapshots')]
        active=saved.execute("SELECT release_id FROM active_release WHERE slot='student'").fetchone()
    for rid in ids:
        release_path=(WORK/'releases'/rid).resolve()
        if not release_path.is_relative_to((WORK/'releases').resolve()):raise ValueError('Release path outside snapshot storage')
        shutil.copytree(io_path(release_path),runtime/'releases'/rid)
    if (WORK/'library').exists():shutil.copytree(WORK/'library',runtime/'library')
    paths=['app','scripts','contracts','skills','tests','evals','docs','.workbuddy','.codebuddy','frontend/admin','frontend/student/src','frontend/student/dist/build','README.md','AGENTS.md','.env.example','requirements.txt','requirements.lock.txt','frontend/student/package.json','frontend/student/pnpm-lock.yaml','frontend/student/pnpm-workspace.yaml','frontend/student/tsconfig.json','frontend/student/vite.config.ts','frontend/student/index.html']
    for name in paths:
        source=ROOT/name;dest=folder/name
        if not source.exists():continue
        dest.parent.mkdir(parents=True,exist_ok=True)
        if source.is_dir():shutil.copytree(source,dest,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        else:shutil.copy2(source,dest)
    for name in ['index_manifest.json','vectors.npy']:
        if (WORK/name).is_file():shutil.copy2(WORK/name,runtime/name)
    release={'release_id':active[0] if active else RELEASE,'snapshots':len(ids),'created_at':now(),'mode':'local_trial','excluded':['.env secrets','model weights','virtual environment','node_modules'],'model_recovery':'重新下载 README 指定模型；本次恢复验证不运行模型推理。'}
    (folder/'release.json').write_text(json.dumps(release,ensure_ascii=False,indent=2),encoding='utf-8')
    files={p.relative_to(folder).as_posix():digest(p) for p in folder.rglob('*') if p.is_file()}
    (folder/'backup_manifest.json').write_text(json.dumps({'files':files,'count':len(files)},ensure_ascii=False,indent=2),encoding='utf-8')
    return folder

def restore_check():
    began=time.monotonic()
    backups=sorted(p for p in (WORK/'backups').glob('*') if (p/'backup_manifest.json').is_file())
    if not backups:raise ValueError('先运行当前版本 backup 命令，创建带完整性清单的备份。')
    source=io_path(backups[-1])
    manifest=json.loads((source/'backup_manifest.json').read_text(encoding='utf-8'))
    for relative,expected in manifest['files'].items():
        path=(source/relative).resolve()
        if not path.is_relative_to(source.resolve()) or digest(path)!=expected:raise ValueError('Backup hash mismatch: '+relative)
    target=io_path(WORK/'restore-checks'/datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    shutil.copytree(source,target)
    with sqlite3.connect(target/'work'/'policy.db') as d:
        if d.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database integrity failed')
        if d.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Database foreign key check failed')
        sessions=d.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
    policies=json.loads((target/'data'/'manifests'/'policies.json').read_text(encoding='utf-8'))['files']
    for p in policies:
        if digest(target/p['raw_file'])!=p['sha256']:raise ValueError('Restored original failed: '+p['key'])
        if (target/'data'/'normalized'/(p['key']+'.txt')).read_text(encoding='utf-8')!=p['text']:raise ValueError('Restored text mismatch')
    index_path=target/'work'/'index_manifest.json'
    chunks=None
    if index_path.exists():
        index=json.loads(index_path.read_text(encoding='utf-8'));matrix=np.load(target/'work'/'vectors.npy')
        if matrix.shape!=(len(index['chunk_ids']),index['dimension']):raise ValueError('Restored vector snapshot mismatch')
        chunks=len(index['chunk_ids'])
    env=dict(os.environ,POLICY_WORK_DIR=str(target/'work'),POLICY_LONG_PATHS='1',DISABLE_LOCAL_LLM='1',DISABLE_PROFILE_LLM='1',APP_ENV='development',PYTHONDONTWRITEBYTECODE='1')
    for key in ['LLM_BASE_URL','LLM_MODEL','LLM_API_KEY','WX_APP_ID','WX_APP_SECRET']:env.pop(key,None)
    process=subprocess.run([sys.executable,'-m','app.cli','doctor'],cwd=target,env=env,capture_output=True,text=True,encoding='utf-8',check=True)
    doctor=json.loads(process.stdout)
    expected=len(policies)
    if doctor['release_id']!=RELEASE:
        folder=target/'work'/'releases'/doctor['release_id'];released=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        expected=len(released['files'])
        for p in released['files']:
            path=(folder/p['blob_file']).resolve()
            if not path.is_relative_to((folder/'raw').resolve()) or digest(path)!=p['sha256']:raise ValueError('Restored release original mismatch')
        chunks=json.loads((folder/'index_manifest.json').read_text(encoding='utf-8'))['chunks']
    if doctor['documents']!=expected:raise ValueError('Restored code cannot read active dataset')
    report={'status':'pass','created_at':now(),'snapshot':source.name,'files_verified':len(manifest['files']),'restored_documents':expected,'restored_release_id':doctor['release_id'],'restored_sessions':sessions,'vector_chunks':chunks,'restored_code_doctor_passed':True,'live_runtime_overwritten':False,'model_inference_retested':False,'scope':'实际复制到隔离目录，检查数据库与外键、原件、标准文本、全部已登记发布快照和活动指针、向量快照，并从恢复源码运行doctor；不是正式环境切换或模型权重恢复验收。','duration_ms':round((time.monotonic()-began)*1000)}
    write_report('restore_check.json',report)
    return report
