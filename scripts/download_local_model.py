from pathlib import Path
import os,json
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('HF_HUB_DISABLE_XET','1')
from huggingface_hub import snapshot_download
path=snapshot_download('Qwen/Qwen2.5-0.5B-Instruct',revision='7ae557604adf67be50417f59c2c2f167def9a775',cache_dir=str(ROOT/'models'/'llm-cache'),allow_patterns=['*.json','*.safetensors','merges.txt','vocab.json'],max_workers=3)
info={'provider':'transformers_cpu','model':'Qwen/Qwen2.5-0.5B-Instruct','path':Path(path).relative_to(ROOT).as_posix(),'revision':Path(path).name,'status':'downloaded_not_yet_validated'}
(ROOT/'work').mkdir(exist_ok=True)
(ROOT/'work'/'local_model.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in info.items() if k!='path'},ensure_ascii=False))
