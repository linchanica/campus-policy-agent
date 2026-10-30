"""Prepare project-only configuration; does not launch or authenticate WorkBuddy."""
from pathlib import Path
import json,shutil
ROOT=Path(__file__).resolve().parents[1]
python=ROOT/'.venv'/'Scripts'/'python.exe'
if not python.exists():python=ROOT/'.venv'/'bin'/'python'
if not python.exists():raise SystemExit('先在本项目创建 .venv 并安装依赖。')
target=ROOT/'.workbuddy'/'mcp.json';target.parent.mkdir(exist_ok=True)
data=json.loads(target.read_text(encoding='utf-8-sig')) if target.exists() else {}
data.setdefault('mcpServers',{})['campus-policy']={'command':str(python),'args':[str(ROOT/'scripts'/'run_mcp.py')]}
target.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
skill=ROOT/'.codebuddy'/'skills'/'policy-guide';skill.mkdir(parents=True,exist_ok=True)
shutil.copy2(ROOT/'skills'/'policy-guide'/'SKILL.md',skill/'SKILL.md')
references=ROOT/'skills'/'policy-guide'/'references'
if references.exists():shutil.copytree(references,skill/'references',dirs_exist_ok=True)
print('项目 MCP 路径已配置，项目技能已同步。客户端连接与工具调用仍须单独验证。')
