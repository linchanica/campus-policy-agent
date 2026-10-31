"""Read-only release inventory. Does not load .env, start services or approve release."""
import argparse
import ast
import ipaddress
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def public_https_origin(value):
    """Syntax check only; DNS, TLS, filing and server availability remain unchecked."""
    try:
        p = urlsplit(value)
        host = p.hostname
        if p.scheme != 'https' or not host or p.username is not None or p.password is not None:
            return False
        if p.query or p.fragment or p.path not in {'', '/'} or p.port not in {None, 443}:
            return False
        if '.' not in host or host.endswith(('.localhost', '.local', '.internal', '.invalid', '.test', '.example')):
            return False
        if host in {'localhost', 'example.com', 'example.org', 'example.net'}:
            return False
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass
        ascii_host = host.encode('idna').decode('ascii')
        return len(ascii_host) <= 253 and all(
            0 < len(label) <= 63 and not label.startswith('-') and not label.endswith('-')
            and all(c.isascii() and (c.isalnum() or c == '-') for c in label)
            for label in ascii_host.split('.')
        )
    except (ValueError, UnicodeError):
        return False


def production_guard_present():
    try:
        tree = ast.parse((ROOT / 'app/api.py').read_text(encoding='utf-8-sig'))
        lifespan = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'lifespan')
        return any(isinstance(n, ast.If) and ast.unparse(n.test) == 'not DEV'
                   and any(isinstance(child, ast.Raise) for child in n.body) for n in lifespan.body)
    except (OSError, SyntaxError, StopIteration):
        return None


def database_inventory(work):
    path = work / 'policy.db'
    if not path.is_file():
        return {'readable': False}
    try:
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3) as db:
            db.execute('PRAGMA query_only=ON')
            verified = db.execute('SELECT COUNT(*) FROM user_roles WHERE verified_staff=1').fetchone()[0]
            active = db.execute("SELECT release_id FROM active_release WHERE slot='student'").fetchone()
            row = db.execute('SELECT kind FROM release_snapshots WHERE id=?', (active[0],)).fetchone() if active else None
        return {'readable': True, 'verified_school_staff_count': verified,
                'active_release_kind': row[0] if row else 'provided_baseline'}
    except sqlite3.Error:
        # Do not echo arbitrary database content, identifiers or error context.
        return {'readable': False}


def inspect(work, api_base_url=''):
    manifest = read_json(ROOT / 'data/manifests/policies.json') or {}
    files = manifest.get('files', [])
    model = read_json(work / 'local_model.json') or {}
    index = read_json(work / 'index_manifest.json') or {}
    wechat = read_json(ROOT / 'docs/verification/wechat_import.json') or {}
    plan = read_json(ROOT / 'docs/cloud_trial_plan.json') or {}
    built = ROOT / 'frontend/student/dist/build/mp-weixin'
    js_files = list(built.rglob('*.js')) if built.is_dir() else []
    has_loopback = any('http://127.0.0.1:8000' in p.read_text(encoding='utf-8', errors='replace') for p in js_files)
    db = database_inventory(work)
    return {
        'checked_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'operation': 'read_only_inventory',
        'formal_release_ready': False,
        'budget': {'authorized_new_spend_cny': plan.get('authorized_new_spend_cny'),
                   'free_resource_provisioned': bool(plan.get('instance_id'))},
        'observed': {
            'production_startup_guard_present': production_guard_present(),
            'baseline_documents': len(files),
            'baseline_in_scope': sum(bool(p.get('in_scope')) for p in files),
            'baseline_business_reviewed': sum(p.get('review_status') == 'business_reviewed' for p in files),
            'baseline_in_scope_with_https_source': sum(bool(p.get('in_scope')) and str(p.get('source_url', '')).startswith('https://') for p in files),
            'local_model_manifest_present': bool(model),
            'local_model_path_requires_windows_migration': ':\\' in str(model.get('path', '')),
            'baseline_semantic_index_present': index.get('engine') == 'semantic_bge',
            'mini_program_build_present': bool(js_files),
            'mini_program_build_contains_loopback_api': has_loopback,
            'candidate_api_has_public_https_origin_syntax': public_https_origin(api_base_url),
            'wechat_device_test_recorded': wechat.get('device_tested') is True,
            'wechat_upload_recorded': wechat.get('uploaded') is True,
            **db,
        },
        'unverified': ['free_resource_eligibility_and_zero_cost_order', 'cloud_linux_runtime_and_model_capacity',
                       'remote_tls_and_legal_domain_configuration', 'platform_account_filing_and_category',
                       'formal_independent_policy_review_and_verified_staff_identity',
                       'production_configuration_and_recovery_acceptance', 'phone_end_to_end_acceptance'],
        'note': '仅盘点可见状态，不验证DNS/证书/备案，不执行登录、不读取.env、不上传数据或部署。正式就绪保持false；不得只修改本报告或删除启动阻断来宣称上线。',
    }


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, default=ROOT / 'work')
    parser.add_argument('--api-base-url', default='')
    args = parser.parse_args()
    print(json.dumps(inspect(args.work_dir, args.api_base_url), ensure_ascii=False, indent=2))
    return 2  # This inventory cannot authorize a formal release.


if __name__ == '__main__':
    raise SystemExit(main())
