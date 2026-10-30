import json,re,hashlib,math,threading
from collections import Counter
from pathlib import Path
from uuid import uuid5,NAMESPACE_URL
import numpy as np
from rank_bm25 import BM25Okapi
from .config import DATA,ROOT,WORK,RELEASE

SYNONYMS={'马院':'马克思主义学院','综测':'综合测评','研二':'硕士研究生','研三':'硕士研究生','国奖':'国家奖学金'}

def tokenize(text):
    for a,b in SYNONYMS.items():text=text.replace(a,b)
    text=re.sub(r'\s+','',text.lower())
    chars=re.findall(r'[\u4e00-\u9fff]|[a-z0-9]+',text)
    return chars+[a+b for a,b in zip(chars,chars[1:])]

def char_vector(text,dim=512):
    vector=np.zeros(dim,dtype=np.float32)
    for t in tokenize(text):
        n=int.from_bytes(hashlib.blake2b(t.encode(),digest_size=8).digest(),'little')
        vector[n%dim]+=1
    norm=np.linalg.norm(vector)
    return (vector/norm if norm else vector).tolist()

class Knowledge:
    def __init__(self):
        raw=json.loads((DATA/'manifests'/'policies.json').read_text(encoding='utf-8'))
        self.documents=raw['files'];self.by_key={p['key']:p for p in self.documents}
        self.chunks=[];self.model=None;self.client=None;self.lock=threading.RLock()
        seen={}
        for p in self.documents:
            if not p['in_scope'] or not p['text']:continue
            if p['sha256'] in seen:
                p['duplicate_of']=seen[p['sha256']]
                continue
            seen[p['sha256']]=p['key']
            section='正文';buffer='';start=0
            for i,para in enumerate(p['text'].splitlines()):
                if re.match(r'^[一二三四五六七八九十]+[、．.]|^第[一二三四五六七八九十]+条',para):section=para[:100]
                if len(buffer)+len(para)>650 and buffer:
                    self._chunk(p,section,buffer,start,i);buffer='';start=i
                buffer+=para+'\n'
            if buffer:self._chunk(p,section,buffer,start,len(p['text'].splitlines()))
        self.bm25=BM25Okapi([tokenize(x['text']) for x in self.chunks])
        self.by_id={c['source_id']:c for c in self.chunks}
        state=WORK/'index_manifest.json'
        self.index_info=json.loads(state.read_text(encoding='utf-8')) if state.exists() else {'engine':'character_hash_baseline','model':None,'release_id':RELEASE}

    def _chunk(self,p,section,text,start,end):
        sid=str(uuid5(NAMESPACE_URL,f"{p['sha256']}:{start}:{end}"))
        self.chunks.append({'source_id':sid,'policy_key':p['key'],'policy_id':p['id'],'version_id':p['sha256'][:16],'title':p['title'],'section':section,'locator':f'整理副本第{start+1}至{end}段','text':text.strip(),'review_status':p['review_status'],'url':p.get('source_url')})

    def index(self,semantic=False):
        from qdrant_client import QdrantClient,models
        vectors=[char_vector(c['title']+' '+c['text']) for c in self.chunks]
        info={'engine':'character_hash_baseline','model':None,'dimension':512,'release_id':RELEASE,'chunks':len(vectors)}
        if semantic:
            from .embedding import load,NAME,REVISION
            self.model=load(download=True)
            vectors=[v.tolist() for v in self.model.embed([c['title']+' '+c['text'] for c in self.chunks])]
            info.update(engine='semantic_bge',model=NAME,model_revision=REVISION,dimension=len(vectors[0]))
        target=WORK/'qdrant'
        client=QdrantClient(path=str(target))
        name='policy_chunks'
        if client.collection_exists(name):client.delete_collection(name)
        client.create_collection(name,vectors_config=models.VectorParams(size=info['dimension'],distance=models.Distance.COSINE))
        client.upsert(name,points=[models.PointStruct(id=c['source_id'],vector=v,payload={'policy_key':c['policy_key']}) for c,v in zip(self.chunks,vectors)])
        client.close()
        np.save(WORK/'vectors.npy',np.array(vectors,dtype=np.float32))
        info['chunk_ids']=[c['source_id'] for c in self.chunks]
        (WORK/'index_manifest.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
        self.index_info=info
        return info

    def search(self,query,keys=None,limit=8,mode='hybrid'):
        if mode not in {'hybrid','keyword','semantic'}:raise ValueError('Unknown retrieval mode')
        candidates=[i for i,c in enumerate(self.chunks) if keys is None or c['policy_key'] in keys]
        if keys is None:
            excluded={'申请','办理','政策','什么','怎么','可以','需要','材料','如何','是否','现在','我的','我们'}
            terms={t for t in tokenize(query) if len(t)>1 and t not in excluded}
            candidates=[i for i in candidates if len(terms.intersection(set(tokenize(self.chunks[i]['title']+' '+self.chunks[i]['text']))))>=2]
        if not candidates:return []
        scores=self.bm25.get_scores(tokenize(query))
        keywords=sorted(candidates,key=lambda i:float(scores[i]),reverse=True)[:20]
        if mode=='keyword':
            dense=None
        elif (WORK/'vectors.npy').exists() and self.index_info.get('chunk_ids')==[c['source_id'] for c in self.chunks]:
            matrix=np.load(WORK/'vectors.npy',mmap_mode='r')
            if self.index_info['engine']=='semantic_bge':
                if self.model is None:
                    from .embedding import load
                    self.model=load()
                with self.lock:q=np.array(next(self.model.query_embed(query)),dtype=np.float32)
            else:q=np.array(char_vector(query),dtype=np.float32)
            dense=matrix@q
        else:dense=np.array([np.dot(char_vector(c['text']),char_vector(query)) for c in self.chunks])
        semantic=sorted(candidates,key=lambda i:float(dense[i]),reverse=True)[:20] if dense is not None else []
        fusion=Counter()
        rankings=[keywords] if mode=='keyword' else ([semantic] if mode=='semantic' else [keywords,semantic])
        for result in rankings:
            for rank,i in enumerate(result,1):fusion[i]+=1/(60+rank)
        return [dict(self.chunks[i],score=round(v,5)) for i,v in fusion.most_common(limit)]

    def policy(self,key):
        return next((p for p in self.documents if p['key']==key or p['id']==key),None)

    def evidence(self,key,phrase):
        chunks=[c for c in self.chunks if c['policy_key']==key]
        hits=[c for c in chunks if phrase in c['text']]
        return (hits or chunks)[:2]

_knowledge=None
def get_knowledge():
    global _knowledge
    if _knowledge is None:_knowledge=Knowledge()
    return _knowledge

