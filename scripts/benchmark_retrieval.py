"""Small-corpus retrieval comparison; no claims about LLM or production capacity."""
import os,sys,json,time,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['DISABLE_LOCAL_LLM']='1'
from app.knowledge import get_knowledge
from app.config import now

kb=get_knowledge()
cases=[json.loads(line) for line in (ROOT/'evals'/'cases.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
cases=[c for c in cases if c['category']=='retrieval']
report={'created_at':now(),'corpus_chunks':len(kb.chunks),'queries':len(cases),'scope':'同一小语料与固定查询集上的政策级 hit@5；共享前置关键词范围门槛，非独立测试集，无人工条款相关性标注；延迟仅为当前机器顺序检索，不含LLM。','modes':{}}
for mode in ['keyword','semantic','hybrid']:
    start=time.perf_counter();kb.search(cases[0]['query'],mode=mode);cold_ms=round((time.perf_counter()-start)*1000,1)
    rows=[]
    for case in cases:
        start=time.perf_counter();hits=kb.search(case['query'],limit=5,mode=mode)
        rows.append({'case_id':case['case_id'],'hit':case['expected_policy_key'] in {s['policy_key'] for s in hits},'latency_ms':round((time.perf_counter()-start)*1000,2)})
    latency=sorted(r['latency_ms'] for r in rows)
    report['modes'][mode]={'hit_at_5':sum(r['hit'] for r in rows)/len(rows),'hit_count':sum(r['hit'] for r in rows),'denominator':len(rows),'initial_query_ms':cold_ms,'p50_ms':round(statistics.median(latency),2),'p95_ms':latency[max(0,int(.95*len(latency))-1)],'results':rows}
(ROOT/'evals'/'ablation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:{a:b for a,b in v.items() if a!='results'} for k,v in report['modes'].items()},ensure_ascii=False,indent=2))
