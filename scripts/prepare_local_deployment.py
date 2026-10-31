"""Build a fresh local-trial deployment with pinned models, no secrets or live database."""
import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
QWEN_REVISION = '7ae557604adf67be50417f59c2c2f167def9a775'
BGE_REVISION = '46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59'
BGE_PATH = f'models/models--Qdrant--bge-small-zh-v1.5/snapshots/{BGE_REVISION}'
FORBIDDEN = {'.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache'}


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


def relative_path(value):
    p = PurePosixPath(value)
    if not value or '\\' in value or ':' in value or p.is_absolute() or '..' in p.parts:
        raise ValueError('Unsafe relative package path')
    if any(part in FORBIDDEN for part in p.parts):
        raise ValueError('Forbidden package directory')
    if p.name in {'.env', 'mcp.json', 'project.private.config.json'} or p.suffix in {'.db', '.pyc'}:
        raise ValueError('Private runtime file in source package')
    if p.name.startswith('.env.') and p.name != '.env.example':
        raise ValueError('Private environment file in source package')
    return p


def private_values():
    result = []
    path = ROOT / '.env'
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            value = value.strip().strip('"').strip("'")
            if key.strip() in {'WX_APP_SECRET', 'LLM_API_KEY'} and len(value) >= 8:
                result.append(value.encode())
    return result


def scan_file(path, secrets):
    overlap = max((len(x) for x in secrets), default=1) - 1
    tail = b''
    with io_path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            data = tail + chunk
            if any(value in data for value in secrets):
                raise ValueError('Configured secret detected; deployment export stopped')
            tail = data[-overlap:] if overlap else b''


def build(source_zip, destination, archive):
    if destination.exists() or archive.exists() or Path(str(archive) + '.partial').exists():
        raise ValueError('Choose new output paths; existing files will not be replaced')
    destination = io_path(destination)
    destination.mkdir(parents=True)
    print('Verifying and extracting sanitized source package...', flush=True)
    with zipfile.ZipFile(source_zip) as z:
        manifest_bytes = z.read('policy-agent/docs/package_manifest.json')
        expected = json.loads(manifest_bytes)['files']
        names = [n for n in z.namelist() if not n.endswith('/')]
        if len(set(names)) != len(names) or len(names) != len(expected) + 1:
            raise ValueError('Unexpected or duplicated source package members')
        for name in names:
            if not name.startswith('policy-agent/'):
                raise ValueError('Unexpected source package prefix')
            rel = relative_path(name[len('policy-agent/'):])
            if rel.parts[0] in {'work', 'models'}:
                raise ValueError('Source package contains runtime state')
            blob = z.read(name)
            if rel.as_posix() != 'docs/package_manifest.json' and hashlib.sha256(blob).hexdigest() != expected.get(rel.as_posix()):
                raise ValueError('Source package hash mismatch')
            target = destination.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
    work = destination / 'work'
    work.mkdir()
    source_model = json.loads((ROOT / 'work/local_model.json').read_text(encoding='utf-8'))
    if source_model.get('revision') != QWEN_REVISION or source_model.get('model') != 'Qwen/Qwen2.5-0.5B-Instruct':
        raise ValueError('Unexpected local model identity')
    qwen = Path(source_model['path'])
    if not qwen.is_absolute():
        qwen = ROOT / qwen
    if not qwen.resolve().is_relative_to((ROOT / 'models').resolve()):
        raise ValueError('Model path is outside the project model cache')
    model_roots = [(qwen, 'models/qwen2_5_0_5b'), (ROOT / BGE_PATH, BGE_PATH)]
    print('Copying pinned Qwen and BGE weights from the existing local cache...', flush=True)
    for source, target_relative in model_roots:
        if not (io_path(source) / 'config.json').is_file():
            raise ValueError('Pinned model cache is incomplete')
        for path in io_path(source).iterdir():
            if not path.is_file() or path.suffix not in {'.json', '.txt', '.safetensors', '.onnx'}:
                continue
            target = destination / target_relative / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            if digest(path) != digest(target):
                raise ValueError('Copied model hash mismatch')
    if not (destination / 'models/qwen2_5_0_5b/model.safetensors').is_file() or not (destination / BGE_PATH / 'model_optimized.onnx').is_file():
        raise ValueError('Required model weight file missing')
    index = json.loads((ROOT / 'work/index_manifest.json').read_text(encoding='utf-8'))
    if index.get('engine') != 'semantic_bge' or index.get('release_id') != 'provided-copies-20261030-v1' or index.get('model_revision') != BGE_REVISION:
        raise ValueError('Only the pinned baseline semantic index is eligible for this clean deployment')
    for name in ['index_manifest.json', 'vectors.npy']:
        shutil.copyfile(ROOT / 'work' / name, work / name)
    local_model = {'provider': 'transformers_cpu', 'model': source_model['model'], 'revision': QWEN_REVISION,
                   'path': 'models/qwen2_5_0_5b', 'status': 'copied_requires_target_validation'}
    (work / 'local_model.json').write_text(json.dumps(local_model, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.copyfile(destination / 'docs/本地部署准备与迁移.md', destination / 'DEPLOYMENT.md')
    secrets = private_values()
    files = {}
    print('Checking file integrity and secret exclusion...', flush=True)
    for path in sorted(destination.rglob('*')):
        if path.is_file():
            scan_file(path, secrets)
            files[path.relative_to(destination).as_posix()] = digest(path)
    manifest = {
        'format_version': 1, 'created_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'purpose': 'fresh_local_trial_with_pinned_models', 'formal_release_ready': False,
        'source_package_sha256': digest(source_zip), 'files': files, 'file_count': len(files),
        'mutable_model_config': 'work/local_model.json',
        'qwen_revision': QWEN_REVISION, 'bge_revision': BGE_REVISION,
        'includes_model_weights': True, 'includes_dependencies': False, 'includes_live_database': False,
        'includes_secrets': False, 'secrets_checked': len(secrets),
        'note': 'Fresh baseline policies and index only. No live sessions, identities, local invitations, secrets, or policy draft history. Windows dependencies require installation; Linux unverified.'
    }
    (destination / 'deployment-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Writing deployment archive (model weights stored without recompression)...', flush=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(archive) + '.partial')
    with zipfile.ZipFile(temporary, 'w', allowZip64=True) as z:
        for path in sorted(destination.rglob('*')):
            if path.is_file():
                compression = zipfile.ZIP_STORED if path.suffix in {'.safetensors', '.onnx'} else zipfile.ZIP_DEFLATED
                z.write(path, 'policy-agent-local/' + path.relative_to(destination).as_posix(), compress_type=compression)
    with zipfile.ZipFile(temporary) as z:
        if z.testzip() is not None:
            raise ValueError('Deployment ZIP integrity failed')
    temporary.rename(archive)
    return {'status': 'built_requires_target_validation', 'file_count': len(files) + 1,
            'bytes': archive.stat().st_size, 'sha256': digest(archive), 'includes_live_database': False,
            'includes_dependencies': False, 'configured_secrets_absent': True}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-zip', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source_zip.resolve(), args.destination.resolve(), args.archive.resolve())
    (args.archive.parent / '本地部署包校验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
