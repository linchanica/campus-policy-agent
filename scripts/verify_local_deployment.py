"""Extract the actual deployment ZIP and test it on a separate loopback port."""
import argparse
import hashlib
import importlib.util
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

import httpx

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def io_path(path):
    value = str(Path(path).resolve())
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return Path(value)


def verify(archive):
    began = time.monotonic()
    checks = []

    def check(name, condition):
        checks.append({'name': name, 'pass': bool(condition)})
        if not condition:
            raise AssertionError(name)

    print('Extracting the actual deployment ZIP to an isolated runtime...', flush=True)
    archive_hash = digest(archive)
    folder = io_path(tempfile.mkdtemp(prefix='deploy-qa-', dir=ROOT / 'work'))
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            rel = PurePosixPath(name)
            if not rel.parts or rel.parts[0] != 'policy-agent-local' or rel.is_absolute() or '..' in rel.parts or '\\' in name or ':' in name:
                raise ValueError('Unsafe deployment archive member')
            target = folder.joinpath(*rel.parts)
            if name.endswith('/'):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as source, target.open('wb') as dest:
                    import shutil
                    shutil.copyfileobj(source, dest)
    stage = folder / 'policy-agent-local'
    spec = importlib.util.spec_from_file_location('bundle_integrity', stage / 'scripts/verify_deployment_bundle.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    initial = module.verify(stage, fresh=True)
    check('fresh_bundle_hashes_and_vectors_valid', initial['status'] == 'pass')
    env = dict(os.environ, APP_ENV='development', POLICY_WORK_DIR=str(stage / 'work'),
               POLICY_LONG_PATHS='1', PYTHONPATH=str(stage), PYTHONIOENCODING='utf-8',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
               HF_HOME=str(stage / 'work/hf-home'), DISABLE_LOCAL_LLM='0', DISABLE_PROFILE_LLM='0')
    for key in ['LLM_BASE_URL', 'LLM_MODEL', 'LLM_API_KEY', 'WX_APP_ID', 'WX_APP_SECRET']:
        env[key] = ''
    with httpx.Client(timeout=3, trust_env=False) as live:
        try:
            original_before = live.get('http://127.0.0.1:8000/health/ready').json()
        except (httpx.HTTPError, ValueError):
            original_before = None
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    process = None
    logs = (stage / 'work/deployment-qa.log').open('w', encoding='utf-8')

    def stop():
        nonlocal process
        if process is not None and process.poll() is None:
            process.terminate()  # Only the child process created below.
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
        process = None

    def start():
        nonlocal process
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.api:app', '--host', '127.0.0.1', '--port', str(port)],
                                   cwd=stage, env=env, stdout=logs, stderr=logs, creationflags=creationflags)
        address = 'http://127.0.0.1:' + str(port)
        deadline = time.monotonic() + 60
        with httpx.Client(timeout=2, trust_env=False) as probe:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError('Isolated server exited; inspect its local QA log')
                try:
                    if probe.get(address + '/health/ready').status_code == 200:
                        return address
                except httpx.HTTPError:
                    pass
                time.sleep(.4)
        raise AssertionError('Isolated server startup timeout')

    def consult(client, headers, sid, revision, text, client_id):
        r = client.post('/api/v1/sessions/' + sid + '/messages', headers=headers,
                        json={'text': text, 'client_message_id': client_id, 'expected_profile_revision': revision})
        check(client_id + '_accepted', r.status_code == 202)
        tid = r.json()['turn_id']
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            reply = client.get('/api/v1/turns/' + tid, headers=headers).json()
            if reply['state'] in {'COMPLETED', 'FAILED', 'STALE'}:
                break
            time.sleep(.5)
        check(client_id + '_completed', reply['state'] == 'COMPLETED')
        result = reply['result']
        check(client_id + '_source_ids_valid', bool(result['sources']) and result['validation']['source_ids_valid'])
        model = result.get('model_explanation') or {}
        evidence = {s['source_id']: s['text'] for s in result['sources']}
        check(client_id + '_real_qwen_grounded_quote', result['generation_mode'] == 'local_llm_evidence_and_rules'
              and model.get('mode') == 'local_evidence_selection'
              and any(model.get('summary') in evidence.get(sid, '') for sid in model.get('source_ids', [])))
        return result

    try:
        print('Starting relocated server with offline model loading; original port 8000 is untouched...', flush=True)
        address = start()
        with sqlite3.connect(stage / 'work/policy.db') as db:
            check('no_live_users_or_sessions_migrated', db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0
                  and db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0)
        with httpx.Client(base_url=address, timeout=135, trust_env=False) as c:
            check('compiled_h5_served', c.get('/').status_code == 200 and '/assets/' in c.get('/').text)
            check('admin_page_served', c.get('/admin/').status_code == 200)
            meta = c.get('/api/v1/meta').json()
            check('local_model_available_without_cloud_or_wechat_credentials', meta['local_llm_available']
                  and not meta['llm_configured'] and not meta['wechat_configured'])
            check('anonymous_policy_access_denied', c.get('/api/v1/policies').status_code == 401)
            token = c.post('/api/v1/auth/guest').json()['access_token']
            headers = {'Authorization': 'Bearer ' + token}
            sid = c.post('/api/v1/sessions', headers=headers, json={'topic': 'midterm'}).json()['session_id']
            first = consult(c, headers, sid, 0, '部署验收使用虚构信息：我是人工智能学院2025级学术学位硕士，中期考核需要哪些步骤和材料？', 'deployment-first-consult')
            check('student_admin_workspace_denied', c.get('/api/v1/admin/workspace', headers=headers).status_code == 403)
            other = c.post('/api/v1/auth/guest').json()['access_token']
            check('other_student_session_denied', c.get('/api/v1/sessions/' + sid, headers={'Authorization': 'Bearer ' + other}).status_code == 404)
            source = first['sources'][0]
            detail = c.get('/api/v1/policies/' + source['policy_key'] + '/versions/' + source['version_id'], headers=headers)
            check('versioned_policy_contains_quoted_text', detail.status_code == 200 and source['text'] in detail.json()['text'])
            policies = json.loads((stage / 'data/manifests/policies.json').read_text(encoding='utf-8'))['files']
            expected_attachment = next(p['sha256'] for p in policies if p['key'] == 'p033')
            attachment = c.get('/api/v1/attachments/p033', headers=headers)
            check('registration_form_hash_matches_original', attachment.status_code == 200
                  and hashlib.sha256(attachment.content).hexdigest() == expected_attachment)
        saved = json.loads((stage / 'work/local_model.json').read_text(encoding='utf-8'))
        check('qwen_path_stays_relative_after_real_inference', saved['path'] == 'models/qwen2_5_0_5b'
              and saved['status'] == 'loaded_and_validated')
        check('bundle_immutable_files_unchanged_after_inference', module.verify(stage)['status'] == 'pass')
        print('Restarting only the isolated child and rechecking the persisted model path...', flush=True)
        stop()
        address = start()
        with httpx.Client(base_url=address, timeout=135, trust_env=False) as c:
            check('fictional_session_survives_own_server_restart', c.get('/api/v1/sessions/' + sid, headers=headers).status_code == 200)
            consult(c, headers, sid, first['profile_revision'], '请再说明中期考核登记表及提交材料。', 'deployment-after-restart')
        check('archive_unchanged', digest(archive) == archive_hash)
    finally:
        stop()
        logs.close()
    with httpx.Client(timeout=3, trust_env=False) as live:
        try:
            original_after = live.get('http://127.0.0.1:8000/health/ready').json()
        except (httpx.HTTPError, ValueError):
            original_after = None
    check('original_local_service_preserved', original_before == original_after)
    return {'status': 'pass', 'checked_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
            'checks': checks, 'passed': len(checks), 'archive_sha256': archive_hash,
            'fresh_bundle_hashes_verified': initial['files_hash_verified'],
            'models': ['Qwen2.5-0.5B-Instruct', 'BAAI/bge-small-zh-v1.5'],
            'real_inference_before_and_after_restart': True, 'model_hub_offline_mode': True,
            'live_database_copied': False, 'credentials_copied': False, 'original_service_restarted': False,
            'dependencies_reused_from_current_windows_venv': True, 'new_machine_install_tested': False,
            'linux_or_docker_tested': False, 'cloud_deployed': False, 'wechat_published': False,
            'scope': 'Actual delivered ZIP extracted to a new directory; real loopback HTTP consultation, pinned offline BGE/Qwen, attachment hash, permissions and restart verified. Reuses installed Windows dependencies; not a production or phone acceptance.',
            'duration_seconds': round(time.monotonic() - began, 2)}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--report', type=Path, default=ROOT / 'docs/verification/local_deployment.json')
    args = parser.parse_args()
    report = verify(args.archive)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'checks'}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
