"""Pinned public ONNX artifact; query-time loading is strictly offline."""
from .config import ROOT
NAME='BAAI/bge-small-zh-v1.5'
REPO='Qdrant/bge-small-zh-v1.5'
REVISION='46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59'

def load(download=False):
    from pathlib import Path
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError
    from fastembed import TextEmbedding
    options=dict(repo_id=REPO,revision=REVISION,cache_dir=str(ROOT/'models'),allow_patterns=['*.json','*.onnx'])
    try:
        path=snapshot_download(**options,local_files_only=True)
        if not all((Path(path)/f).is_file() for f in ['model_optimized.onnx','tokenizer.json','config.json']):raise LocalEntryNotFoundError('Incomplete pinned model cache')
    except LocalEntryNotFoundError:
        if not download:raise
        path=snapshot_download(**options,local_files_only=False)
    return TextEmbedding(model_name=NAME,specific_model_path=path,cache_dir=str(ROOT/'models'),threads=2,cuda=False,local_files_only=True)
