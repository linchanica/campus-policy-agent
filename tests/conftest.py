"""All tests use a fresh runtime. No live sessions, policies or credentials are mutated."""
import os,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
(ROOT/'work').mkdir(exist_ok=True)
os.environ['POLICY_WORK_DIR']=tempfile.mkdtemp(prefix='test-suite-',dir=ROOT/'work')
os.environ['DISABLE_LOCAL_LLM']='1'
os.environ['DISABLE_PROFILE_LLM']='1'
for name in ['LLM_BASE_URL','LLM_MODEL','LLM_API_KEY','WX_APP_SECRET','WX_APP_ID']:
    os.environ[name]=''
os.environ['APP_ENV']='development'

import pytest
@pytest.fixture(autouse=True)
def isolate_external_model(monkeypatch):
    from app import providers
    monkeypatch.setattr(providers,'configured',lambda:False)
    from app.api import rates
    rates.clear()
