from pathlib import Path
import sys,json,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.knowledge import get_knowledge
from app.local_model import select
from app.config import WORK
started=time.monotonic()
evidence=get_knowledge().search('雷军本科生奖学金申请的成绩排名条件',keys=['p012'],limit=3)
result=select('雷军本科生奖学金的排名条件是什么？',evidence)
assert result and result['source_ids'][0] in {x['source_id'] for x in evidence}
assert any(result['summary'] in x['text'] for x in evidence)
report={'status':'passed','model':result['model'],'mode':result['mode'],'total_seconds':round(time.monotonic()-started,2),'source_verified':True,'quote':result['summary']}
(WORK/'local_model_smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
