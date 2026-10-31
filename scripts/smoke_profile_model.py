"""Real local inference on fictional statements; no actual student data or cloud API."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.profile_llm import propose
from app.config import ROOT,now
from app.local_model import model_info

examples=[('我今年读本科二年级，想申请雷军计算机本科生奖学金。',['year_of_study','program_level']),('我是AI学院的本科生，目前读大二。',['college','year_of_study']),('假设我是人工智能学院大二学生。',['college','year_of_study'])]
rows=[];began=time.monotonic()
for text,fields in examples:
    result=propose(text,fields)
    rows.append({'fictional_input':text,'requested_fields':fields,'result':result})
    for candidate in result['candidates']:
        assert candidate['quote'] in text and candidate['confirmation_required'] is True
assert not rows[-1]['result']['candidates']
info=model_info()
report={'status':'pass','created_at':now(),'model':info.get('model') if info else None,'fictional_inputs_only':True,'cases':rows,'supported_candidates':sum(len(r['result']['candidates']) for r in rows),'auto_confirmed':False,'cloud_called':False,'duration_seconds':round(time.monotonic()-began,2),'scope':'仅验证真实本地推理、逐字证据过滤、条件语句拒绝和无结构时表单兜底；不代表画像提取准确率验收。'}
(ROOT/'docs/verification/profile_model_smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
