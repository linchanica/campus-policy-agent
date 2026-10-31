"""Immutable policy/index snapshots, explicit review records and atomic active pointers."""
import hashlib,json,re,shutil,sqlite3,threading
from pathlib import Path
from uuid import uuid4,uuid5,NAMESPACE_URL
from .config import ROOT,DATA,WORK,RELEASE,now
from .db import connect,audit,role_for

_switch_lock=threading.RLock()
REVIEW_CHECKS={'source_version','scope','dates','materials','rules','text_and_tables'}

def digest(blob):return hashlib.sha256(blob).hexdigest()
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def fingerprint():
    names=['rules.py','workflow.py','profile.py','profile_llm.py','providers.py','knowledge.py','embedding.py','cards.py']
    return digest(canonical({n:digest((ROOT/'app'/n).read_bytes()) for n in names if (ROOT/'app'/n).is_file()}).encode())

def active_id():
    try:
        with connect() as d:row=d.execute("SELECT release_id FROM active_release WHERE slot='student'").fetchone()
        return row[0] if row else RELEASE
    except sqlite3.OperationalError as error:
        if 'no such table' in str(error):return RELEASE
        raise

def load_snapshot(release_id):
    with connect() as d:row=d.execute('SELECT * FROM release_snapshots WHERE id=?',(release_id,)).fetchone()
    if not row or row['state']!='PUBLISHED':raise ValueError('发布版本不可用。')
    folder=(WORK/'releases'/release_id).resolve()
    if not folder.is_relative_to((WORK/'releases').resolve()):raise ValueError('版本路径非法。')
    blob=(folder/'manifest.json').read_bytes()
    if digest(blob)!=row['manifest_hash']:raise ValueError('发布快照清单哈希不一致。')
    data=json.loads(blob)
    index=(folder/'index_manifest.json').read_bytes()
    if digest(index)!=data['index_manifest_hash']:raise ValueError('发布索引清单不一致。')
    if digest((folder/'vectors.npy').read_bytes())!=data['vector_hash']:raise ValueError('发布向量快照不一致。')
    return folder,data

def assert_runtime(manifest):
    if manifest.get('runtime_fingerprint')!=fingerprint():raise ValueError('运行代码与发布快照不一致，请重建并复核后重新发布。')

def policy_version(p):return p.get('version_id') or p['sha256'][:16]
def touch(p):
    fields={k:p.get(k) for k in ['sha256','text','title','in_scope','source_url','metadata','correction_note']}
    p['content_revision']=digest(canonical(fields).encode());p['version_id']=p['content_revision'][:16];p['modified']=True;p['review_status']='pending_review'

def get_draft(draft_id):
    with connect() as d:row=d.execute('SELECT * FROM policy_drafts WHERE id=?',(draft_id,)).fetchone()
    if not row:raise ValueError('草稿不存在。')
    data=dict(row);data['manifest']=json.loads(data.pop('manifest_json'))
    with connect() as d:data['reviews']=[dict(r) for r in d.execute('SELECT * FROM policy_reviews WHERE draft_id=?',(draft_id,))]
    for r in data['reviews']:r['checks']=json.loads(r.pop('checks_json'))
    return data

def create_draft(uid):
    from .knowledge import get_knowledge
    kb=get_knowledge();rows=[]
    for original in kb.documents:
        p=json.loads(canonical(original));p.pop('duplicate_of',None)
        p['version_id']=policy_version(p);p['origin_release']=kb.release_id;p['modified']=False
        rows.append(p)
    cards=getattr(kb,'cards',{})
    manifest={'release_id':None,'files':rows,'cards':cards,'business_review_complete':False}
    did='draft-'+uuid4().hex
    with connect() as d:d.execute('INSERT INTO policy_drafts VALUES(?,?,?,?,0,?,?)',(did,kb.release_id,canonical(manifest),uid,'DRAFT',now()))
    audit('draft_created',did,{'actor':uid,'base':kb.release_id});return get_draft(did)

def parse_upload(blob,suffix):
    from io import BytesIO
    try:
        if suffix=='.docx':
            from zipfile import ZipFile
            with ZipFile(BytesIO(blob)) as z:
                if sum(i.file_size for i in z.infolist())>60_000_000 or len(z.infolist())>3000:raise ValueError('DOCX解压规模超限。')
            from scripts.prepare_data import docx_text
            return docx_text(blob)
        from pypdf import PdfReader
        reader=PdfReader(BytesIO(blob))
        if reader.is_encrypted:raise ValueError('请先移除PDF阅读密码并核验文件。')
        if len(reader.pages)>500:raise ValueError('PDF页数超限。')
        return '\n\n'.join(f'第{i+1}页\n{page.extract_text() or ""}' for i,page in enumerate(reader.pages))
    except ValueError:
        raise
    except Exception:
        raise ValueError('文件结构无效或无法提取文本，请核对DOCX/PDF原件。') from None


def replace_document(draft_id,key,uid,expected_revision,patch=None,blob=None,filename=None):
    from .knowledge import get_knowledge
    with connect() as d:
        d.execute('BEGIN IMMEDIATE')
        row=d.execute('SELECT * FROM policy_drafts WHERE id=?',(draft_id,)).fetchone()
        if not row or row['state']!='DRAFT':raise ValueError('草稿不存在或已锁定。')
        if row['revision']!=expected_revision:raise ValueError('DRAFT_REVISION_CONFLICT')
        data=json.loads(row['manifest_json']);p=next((p for p in data['files'] if p['key']==key),None)
        if blob is not None:
            suffix=Path(filename or '').suffix.lower()
            if suffix not in {'.docx','.pdf'}:raise ValueError('新上传仅支持DOCX或文本PDF，旧DOC须先转换。')
            if not blob or len(blob)>20_000_000:raise ValueError('文件为空或超过20MB限制。')
            text=parse_upload(blob,suffix)
            if len(re.sub(r'第\d+页|\s','',text))<10:raise ValueError('无法取得足够文本，请先OCR并核验。')
            sha=digest(blob);store=WORK/'library'/'blobs';store.mkdir(parents=True,exist_ok=True)
            target=store/(sha+suffix)
            if not target.exists():target.write_bytes(blob)
            if p is None:
                p={'key':key,'id':str(uuid5(NAMESPACE_URL,'campus-policy/'+key)),'in_scope':False,'metadata':{}}
                data['files'].append(p)
            p.update(sha256=sha,text=text,title=next(t.strip() for t in text.splitlines() if t.strip()),extension=suffix,archive_name=Path(filename).name,upload_blob=target.name,parse_status='parsed',source_url=None)
            p.pop('blob_file',None);p.pop('raw_file',None)
        if p is None:raise ValueError('政策不存在。')
        patch=patch or {}
        for k,v in patch.items():p[k]=v
        touch(p)
        d.execute('DELETE FROM policy_reviews WHERE draft_id=? AND policy_key=?',(draft_id,key))
        d.execute('UPDATE policy_drafts SET manifest_json=?,revision=revision+1 WHERE id=?',(canonical(data),draft_id))
    audit('draft_document_changed',draft_id,{'actor':uid,'policy_key':key});return get_draft(draft_id)

def review(draft_id,key,uid,expected_revision,decision,checks,notes):
    role=role_for(uid)
    with connect() as d:
        d.execute('BEGIN IMMEDIATE')
        row=d.execute('SELECT * FROM policy_drafts WHERE id=?',(draft_id,)).fetchone()
        if not row or row['state']!='DRAFT':raise ValueError('草稿不存在或已锁定。')
        if row['revision']!=expected_revision:raise ValueError('DRAFT_REVISION_CONFLICT')
        data=json.loads(row['manifest_json']);p=next((p for p in data['files'] if p['key']==key),None)
        if not p:raise ValueError('政策不存在。')
        if decision=='approved' and (set(checks)!=REVIEW_CHECKS or not all(checks.values())):raise ValueError('逐项核对尚未完成，不能通过。')
        if decision=='approved' and (not p.get('source_url') or not p['source_url'].startswith('https://')):raise ValueError('请先补充准确的HTTPS政策来源。')
        if role['verified_staff'] and row['created_by']==uid:raise ValueError('正式业务审核需要由另一位审核人员完成。')
        p['review_status']='business_reviewed' if decision=='approved' and role['verified_staff'] else ('locally_reviewed_unverified' if decision=='approved' else 'changes_requested')
        d.execute('INSERT OR REPLACE INTO policy_reviews VALUES(?,?,?,?,?,?,?,?,?,?)',(draft_id,key,row['revision'],policy_version(p),decision,uid,role['verified_staff'],notes,canonical(checks),now()))
        d.execute('UPDATE policy_drafts SET manifest_json=? WHERE id=?',(canonical(data),draft_id))
    audit('policy_review_recorded',draft_id,{'actor':uid,'policy_key':key,'decision':decision,'verified_staff':bool(role['verified_staff'])});return get_draft(draft_id)

def save_card(draft_id,topic,card,uid,expected_revision):
    from .cards import validate_card
    from .workflow import TOPICS
    if topic not in TOPICS:raise ValueError('未知事项。')
    with connect() as d:
        d.execute('BEGIN IMMEDIATE')
        row=d.execute('SELECT * FROM policy_drafts WHERE id=?',(draft_id,)).fetchone()
        if not row or row['state']!='DRAFT':raise ValueError('草稿不存在或已锁定。')
        if row['revision']!=expected_revision:raise ValueError('DRAFT_REVISION_CONFLICT')
        data=json.loads(row['manifest_json']);cards=data.setdefault('cards',{})
        if card is None:cards.pop(topic,None)
        else:
            if card.get('topic')!=topic:raise ValueError('规则卡事项不一致。')
            cards[topic]=validate_card(card,data['files'])
        key=TOPICS[topic]['key']
        d.execute('DELETE FROM policy_reviews WHERE draft_id=? AND policy_key=?',(draft_id,key))
        p=next((p for p in data['files'] if p['key']==key),None)
        if p:p['modified']=True;p['review_status']='pending_review'
        d.execute('UPDATE policy_drafts SET manifest_json=?,revision=revision+1 WHERE id=?',(canonical(data),draft_id))
    audit('draft_rule_card_changed',draft_id,{'actor':uid,'topic':topic});return get_draft(draft_id)

def build(draft_id,uid,semantic=True,kind='trial'):
    from .knowledge import Knowledge,get_knowledge
    draft=get_draft(draft_id)
    if draft['state']!='DRAFT':raise ValueError('草稿已锁定。')
    review_map={r['policy_key']:r for r in draft['reviews']}
    for p in draft['manifest']['files']:
        if not p['in_scope']:continue
        r=review_map.get(p['key'])
        if (p.get('modified') or kind=='formal') and (not r or r['decision']!='approved' or r['version_id']!=policy_version(p)):raise ValueError('尚有未审核或版本不一致的政策：'+p['key'])
        if kind=='formal' and (not r['verified_staff'] or r['reviewer_id']==draft['created_by']):raise ValueError('正式发布需要已验证学校身份的独立业务审核。')
    rid='rel-'+uuid4().hex;folder=WORK/'releases'/rid;folder.mkdir(parents=True)
    with connect() as d:
        cursor=d.execute("UPDATE policy_drafts SET state='BUILDING' WHERE id=? AND state='DRAFT' AND revision=?",(draft_id,draft['revision']))
        if cursor.rowcount!=1:raise ValueError('草稿已被修改或锁定。')
    try:
        data=draft['manifest'];(folder/'raw').mkdir()
        for p in data['files']:
            if p.get('upload_blob'):
                original=(WORK/'library'/'blobs'/p['upload_blob']).resolve()
                if not original.is_relative_to((WORK/'library'/'blobs').resolve()):raise ValueError('上传原件路径越界。')
            else:
                base=get_knowledge(p.get('origin_release') or draft['base_release_id']);original=base.original_path(base.policy(p['key']))
            if digest(original.read_bytes())!=p['sha256']:raise ValueError('原件哈希变化：'+p['key'])
            name=p['sha256']+p['extension'];shutil.copy2(original,folder/'raw'/name)
            p['blob_file']='raw/'+name;p.pop('upload_blob',None);p.pop('raw_file',None);p.pop('origin_release',None)
        data.update(release_id=rid,kind=kind,files_count=len(data['files']),runtime_fingerprint=fingerprint(),business_review_complete=kind=='formal',created_at=now(),draft_id=draft_id,review_records=draft['reviews'])
        from .cards import validate_cards
        validate_cards(data.get('cards',{}),data['files'])
        kb=Knowledge(data,index_dir=folder,storage_root=folder,release_id=rid);kb.index(semantic)
        data['index_manifest_hash']=digest((folder/'index_manifest.json').read_bytes());data['vector_hash']=digest((folder/'vectors.npy').read_bytes())
        blob=canonical(data).encode();(folder/'manifest.json').write_bytes(blob)
        with connect() as d:
            d.execute('INSERT INTO release_snapshots VALUES(?,?,?,?,?,?,?)',(rid,str(folder.relative_to(WORK)),digest(blob),'BUILT',kind,uid,now()))
            d.execute("UPDATE policy_drafts SET state='BUILT' WHERE id=?",(draft_id,))
        audit('snapshot_built',rid,{'actor':uid,'draft_id':draft_id,'kind':kind,'documents':len(data['files'])})
        return {'release_id':rid,'state':'BUILT','kind':kind,'chunks':len(kb.chunks),'business_review_complete':kind=='formal'}
    except Exception:
        with connect() as d:d.execute("UPDATE policy_drafts SET state='DRAFT' WHERE id=?",(draft_id,))
        raise

def publish(release_id,uid,expected_active,rollback=False):
    if release_id==RELEASE:
        if not rollback:raise ValueError('初始资料版本只可作为回滚目标。')
        from .knowledge import get_knowledge
        kb=get_knowledge(RELEASE)
        for p in kb.documents:kb.original_path(p)
        with _switch_lock,connect() as d:
            d.execute('BEGIN IMMEDIATE')
            current=d.execute("SELECT release_id FROM active_release WHERE slot='student'").fetchone();current=current[0] if current else RELEASE
            if current!=expected_active:raise ValueError('ACTIVE_RELEASE_CONFLICT')
            d.execute('DELETE FROM active_release WHERE slot=?',('student',))
            d.execute('INSERT INTO release_events(release_id,previous_id,actor_id,event,created_at) VALUES(?,?,?,?,?)',(RELEASE,current,uid,'rollback',now()))
        audit('release_rollback',RELEASE,{'actor':uid,'previous':current})
        return {'release_id':RELEASE,'previous_id':current,'kind':'baseline','state':'PUBLISHED'}
    with _switch_lock,connect() as d:
        d.execute('BEGIN IMMEDIATE')
        row=d.execute('SELECT * FROM release_snapshots WHERE id=?',(release_id,)).fetchone()
        if not row or row['state'] not in {'BUILT','PUBLISHED'}:raise ValueError('候选版本未构建完成。')
        if rollback and row['state']!='PUBLISHED':raise ValueError('回滚目标必须是曾发布的版本。')
        current=d.execute("SELECT release_id FROM active_release WHERE slot='student'").fetchone();current=current[0] if current else RELEASE
        if expected_active!=current:raise ValueError('ACTIVE_RELEASE_CONFLICT')
        folder=WORK/'releases'/release_id;blob=(folder/'manifest.json').read_bytes()
        if digest(blob)!=row['manifest_hash']:raise ValueError('候选清单哈希失败。')
        data=json.loads(blob);assert_runtime(data)
        if digest((folder/'index_manifest.json').read_bytes())!=data['index_manifest_hash'] or digest((folder/'vectors.npy').read_bytes())!=data['vector_hash']:raise ValueError('候选索引完整性失败。')
        for p in data['files']:
            path=(folder/p['blob_file']).resolve()
            if not path.is_relative_to((folder/'raw').resolve()) or digest(path.read_bytes())!=p['sha256']:raise ValueError('候选原件校验失败。')
        d.execute("UPDATE release_snapshots SET state='PUBLISHED' WHERE id=?",(release_id,))
        d.execute("INSERT OR REPLACE INTO active_release VALUES('student',?)",(release_id,))
        d.execute('INSERT INTO release_events(release_id,previous_id,actor_id,event,created_at) VALUES(?,?,?,?,?)',(release_id,current,uid,'rollback' if rollback else 'publish',now()))
    audit('release_rollback' if rollback else 'release_published',release_id,{'actor':uid,'previous':current})
    return {'release_id':release_id,'previous_id':current,'kind':row['kind'],'state':'PUBLISHED'}

def find_policy(pid,version='current'):
    from .knowledge import get_knowledge
    current=get_knowledge();p=current.policy(pid)
    if p and p['in_scope'] and (version=='current' or version in {policy_version(p),p['sha256']}):return current,p
    if version=='current':return None,None
    with connect() as d:ids=[r[0] for r in d.execute("SELECT id FROM release_snapshots WHERE state='PUBLISHED' ORDER BY created_at DESC")]
    for rid in [RELEASE]+ids:
        kb=get_knowledge(rid);p=kb.policy(pid)
        if p and p['in_scope'] and version in {policy_version(p),p['sha256']}:return kb,p
    return None,None


def find_source(source_id):
    from .knowledge import get_knowledge
    current=get_knowledge();source=current.by_id.get(source_id)
    if source:return source
    with connect() as d:ids=[r[0] for r in d.execute("SELECT id FROM release_snapshots WHERE state='PUBLISHED' ORDER BY created_at DESC")]
    for rid in [RELEASE]+ids:
        kb=get_knowledge(rid)
        if source_id in kb.by_id:return kb.by_id[source_id]
    return {'error':'SOURCE_NOT_FOUND'}
