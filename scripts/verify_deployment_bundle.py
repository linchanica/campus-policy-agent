"""Verify local deployment integrity without loading credentials or model inference."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
QWEN_REVISION = '7ae557604adf67be50417f59c2c2f167def9a775'
BGE_REVISION = '46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59'


def io_path(path):
    value = str(Path(path).resolve())
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return Path(value)


def digest(path):
    h = hashlib.sha256()
    with io_path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def verify(root, fresh=False):
    root = io_path(root)
    manifest = json.loads((root / 'deployment-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format_version') != 1 or manifest.get('purpose') != 'fresh_local_trial_with_pinned_models':
        raise ValueError('Unexpected deployment manifest')
    files = manifest['files']
    if len(files) != manifest.get('file_count') or manifest.get('qwen_revision') != QWEN_REVISION or manifest.get('bge_revision') != BGE_REVISION:
        raise ValueError('Manifest shape or model revision mismatch')
    if manifest.get('formal_release_ready') is not False:
        raise ValueError('Local deployment cannot claim formal release readiness')
    checked = 0
    for name, expected in files.items():
        rel = PurePosixPath(name)
        if '\\' in name or ':' in name or rel.is_absolute() or '..' in rel.parts:
            raise ValueError('Unsafe manifest path')
        path = root.joinpath(*rel.parts)
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Manifest file resolves outside deployment')
        if name == 'work/local_model.json' and not fresh:
            continue  # Loading changes status, but its model identity and relative path are checked below.
        if digest(path) != expected:
            raise ValueError('Deployment file hash mismatch: ' + name)
        checked += 1
    model = json.loads((root / 'work/local_model.json').read_text(encoding='utf-8'))
    if model.get('model') != 'Qwen/Qwen2.5-0.5B-Instruct' or model.get('revision') != QWEN_REVISION or model.get('path') != 'models/qwen2_5_0_5b':
        raise ValueError('Local model identity or portable path mismatch')
    index = json.loads((root / 'work/index_manifest.json').read_text(encoding='utf-8'))
    if index.get('engine') != 'semantic_bge' or index.get('model_revision') != BGE_REVISION or index.get('release_id') != 'provided-copies-20261030-v1':
        raise ValueError('Baseline semantic index mismatch')
    import numpy as np
    matrix = np.load(root / 'work/vectors.npy', allow_pickle=False)
    if matrix.shape != (len(index['chunk_ids']), index['dimension']) or not np.isfinite(matrix).all():
        raise ValueError('Vector snapshot shape or numerical values invalid')
    if fresh and ((root / '.env').exists() or (root / 'work/policy.db').exists()):
        raise ValueError('Fresh deployment unexpectedly contains secrets or database state')
    return {'status': 'pass', 'files_hash_verified': checked, 'semantic_chunks': len(index['chunk_ids']),
            'model_paths_relative': True, 'fresh_runtime_checked': fresh, 'formal_release_ready': False,
            'scope': 'File hashes, pinned model identity, relative model path and finite baseline vectors; not policy approval or production acceptance.'}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--fresh', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(args.root, args.fresh), ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
