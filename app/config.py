import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

def io_path(path):
    value=str(Path(path).absolute())
    if os.name=='nt' and not value.startswith('\\\\?\\'):
        value='\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value
    return Path(value)

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get('POLICY_LONG_PATHS')=='1':ROOT=io_path(ROOT)
env_file=ROOT/'.env'
if env_file.exists():
    for line in env_file.read_text(encoding='utf-8-sig').splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            key,value=line.split('=',1)
            os.environ.setdefault(key.strip(),value.strip().strip('"'))
WORK = Path(os.environ.get('POLICY_WORK_DIR', str(ROOT/'work'))).resolve()
if os.environ.get('POLICY_LONG_PATHS')=='1':WORK=io_path(WORK)
WORK.mkdir(parents=True, exist_ok=True)
DATA = ROOT/'data'
for directory in ['raw','converted','normalized','manifests']:
    (DATA/directory).mkdir(parents=True, exist_ok=True)
TZ=timezone(timedelta(hours=8))
RELEASE='provided-copies-20261030-v1'
DEV=os.environ.get('APP_ENV','development')=='development'
def now(): return datetime.now(TZ).isoformat()

