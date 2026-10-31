"""Validate emitted templates/styles with the installed official WeChat compilers.

This is a syntax check, separate from uni-app builds and actual simulator/device tests.
It never changes IDE settings, cleans user storage, uploads or publishes.
"""
import argparse,hashlib,json,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--devtools-dir',type=Path,required=True)
args=parser.parse_args()
compiled=ROOT/'frontend/student/dist/build/mp-weixin'
native=args.devtools_dir/'code/package.nw/node_modules/wcc-exec'
work=ROOT/'work/native-wechat-compile';work.mkdir(parents=True,exist_ok=True)
templates=sorted(compiled.rglob('*.wxml'));styles=sorted(compiled.rglob('*.wxss'))
report={'status':'running','scope':'官方本机WXML/WXSS语法检查；不代表模拟器、真机或平台审核通过。','files':{},'checks':[]}
for p in templates+styles:report['files'][p.relative_to(compiled).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
jobs=[('wxml',[str(native/'wcc.exe'),'-d','-o',str(work/'wxml.js')]+['./'+p.relative_to(compiled).as_posix() for p in templates]),('wxss',[str(native/'wcsc.exe'),'-lc','-o',str(work/'wxss.js'),'-pc',str(len(styles))]+['./'+p.relative_to(compiled).as_posix() for p in styles])]
for name,command in jobs:
    began=time.monotonic()
    try:
        result=subprocess.run(command,cwd=compiled,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
        item={'name':name,'exit_code':result.returncode,'stdout':result.stdout[-4000:],'stderr':result.stderr[-4000:]}
    except (OSError,subprocess.TimeoutExpired):item={'name':name,'exit_code':-1,'error':'官方编译器不可用或超时，请核对已安装工具路径。'}
    item['duration_ms']=round((time.monotonic()-began)*1000);report['checks'].append(item)
report['status']='pass' if templates and styles and all(c['exit_code']==0 for c in report['checks']) else 'failed'
(ROOT/'docs/verification/wechat_native_compile.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report['status']=='pass' else 1)
