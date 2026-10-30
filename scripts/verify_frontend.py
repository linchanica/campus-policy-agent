"""Run and record the real uni-app checks; no browser or WeChat login automation."""
import argparse,subprocess,shutil,os,time,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--node',default=shutil.which('node'));parser.add_argument('--pnpm-script')
args=parser.parse_args()
env=dict(os.environ)
if args.node:env['PATH']=str(Path(args.node).parent)+os.pathsep+env.get('PATH','')
prefix=[args.node,args.pnpm_script] if args.pnpm_script else [shutil.which('pnpm') or 'pnpm']
report={'status':'running','browser_ui_tested':False,'wechat_device_tested':False,'commands':[]}
for name in ['typecheck','build:h5','build:mp-weixin']:
    start=time.monotonic();p=subprocess.run(prefix+['run',name],cwd=ROOT/'frontend'/'student',env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
    report['commands'].append({'command':'pnpm run '+name,'exit_code':p.returncode,'duration_ms':round((time.monotonic()-start)*1000),'stdout':p.stdout,'stderr':p.stderr})
    if p.returncode:break
report['status']='pass' if len(report['commands'])==3 and all(x['exit_code']==0 for x in report['commands']) else 'failed'
report['artifacts']={}
for target in ['h5/index.html','mp-weixin/app.json']:
    path=ROOT/'frontend'/'student'/'dist'/'build'/target
    report['artifacts'][target]={'exists':path.is_file(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}
folder=ROOT/'docs'/'verification';folder.mkdir(parents=True,exist_ok=True)
(folder/'frontend_build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':report['status'],'checks':[{'command':x['command'],'exit_code':x['exit_code']} for x in report['commands']],'artifacts':report['artifacts']},ensure_ascii=False,indent=2))
raise SystemExit(0 if report['status']=='pass' else 1)
