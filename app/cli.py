import argparse,json,sqlite3,shutil,sys,subprocess
from pathlib import Path
from datetime import datetime
from .config import ROOT,DATA,WORK,RELEASE,DEV,now
from .db import initialize
from .knowledge import get_knowledge

def main():
    parser=argparse.ArgumentParser(description='校院政策咨询项目管理命令')
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ['doctor','validate-data','backup','restore-check','export-openapi','evaluate','review-export']:sub.add_parser(name)
    ingest=sub.add_parser('ingest');ingest.add_argument('--archive',type=Path)
    index=sub.add_parser('index');index.add_argument('--semantic',action='store_true')
    args=parser.parse_args();initialize()
    if args.command=='ingest':
        command=[sys.executable,str(ROOT/'scripts'/'prepare_data.py')]
        if args.archive:command+=['--archive',str(args.archive)]
        subprocess.run(command,check=True);return
    if args.command=='index':print(json.dumps({k:v for k,v in get_knowledge().index(args.semantic).items() if k!='chunk_ids'},ensure_ascii=False,indent=2));return
    if args.command in {'doctor','validate-data'}:
        kb=get_knowledge();r={'mode':'local_trial' if DEV else 'production_disabled','release_id':RELEASE,'documents':len(kb.documents),'parsed':sum(x['parse_status']=='parsed' for x in kb.documents),'unique_files':len({x['sha256'] for x in kb.documents}),'chunks':len(kb.chunks),'reviewed_policies':0,'business_review_required':True,'llm_configured':False,'index':{k:v for k,v in kb.index_info.items() if k!='chunk_ids'}}
        from .providers import configured
        r['llm_configured']=configured();print(json.dumps(r,ensure_ascii=False,indent=2));return
    if args.command=='export-openapi':
        from .api import app
        path=ROOT/'contracts'/'openapi.json';path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(app.openapi(),ensure_ascii=False,indent=2),encoding='utf-8');print(path);return
    if args.command=='evaluate':
        subprocess.run([sys.executable,str(ROOT/'scripts'/'evaluate.py')],check=True);return
    if args.command=='backup':
        from .maintenance import backup
        print(backup());return
    if args.command=='restore-check':
        from .maintenance import restore_check
        print(json.dumps(restore_check(),ensure_ascii=False,indent=2));return
    if args.command=='review-export':
        from .maintenance import export_review_queue
        print(json.dumps(export_review_queue(),ensure_ascii=False,indent=2));return

if __name__=='__main__':main()

