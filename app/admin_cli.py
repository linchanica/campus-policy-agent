"""Local administrator bootstrap. Credentials are written only to an ignored local file."""
import argparse,json
from .config import WORK,DEV,now
from .db import initialize,connect,clear_user_sessions,audit
from .auth import make_invitation
from datetime import datetime,timedelta
from .config import TZ

def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('invite');p.add_argument('--role',choices=['admin','editor','reviewer','operator'],default='admin');p.add_argument('--name',default='项目维护者')
    p=sub.add_parser('retention');p.add_argument('--days',type=int,required=True);p.add_argument('--apply',action='store_true')
    args=parser.parse_args();initialize()
    if args.command=='invite':
        if not DEV:raise SystemExit('正式环境不能使用本地邀请引导。')
        invitation=make_invitation(args.role,args.name)
        path=WORK/'admin-login-code.txt'
        path.write_text('本地管理后台：http://127.0.0.1:8000/admin/\n一次性登录码：'+invitation['code']+'\n过期时间：'+invitation['expires_at']+'\n仅为本地开发角色，未验证学校身份。\n',encoding='utf-8')
        print('本地一次性登录码已写入 work/admin-login-code.txt（30分钟有效）。请本人读取并在管理页面登录；不要把登录码发到聊天里。')
        return
    if not 1<=args.days<=3650:raise SystemExit('保留天数须为1至3650。')
    cutoff=(datetime.now(TZ)-timedelta(days=args.days)).isoformat()
    with connect() as d:
        rows=d.execute("SELECT u.id FROM users u LEFT JOIN user_roles r ON r.user_id=u.id WHERE u.created_at<? AND COALESCE(r.role,'student')='student' AND NOT EXISTS(SELECT 1 FROM identities i WHERE i.user_id=u.id)",(cutoff,)).fetchall()
        ids=[r[0] for r in rows];cleared=0
        if args.apply:
            d.execute('BEGIN IMMEDIATE')
            for uid in ids:
                if not d.execute("SELECT 1 FROM users u LEFT JOIN user_roles r ON r.user_id=u.id WHERE u.id=? AND COALESCE(r.role,'student')='student' AND NOT EXISTS(SELECT 1 FROM identities i WHERE i.user_id=u.id)",(uid,)).fetchone():continue
                if not clear_user_sessions(d,uid):continue
                d.execute('DELETE FROM auth_tokens WHERE user_id=?',(uid,));d.execute('DELETE FROM user_roles WHERE user_id=?',(uid,));d.execute('DELETE FROM users WHERE id=?',(uid,));cleared+=1
    if args.apply:audit('local_guest_retention_applied','maintenance',{'days':args.days,'cleared_guests':cleared})
    print(json.dumps({'dry_run':not args.apply,'cutoff':cutoff,'candidate_guests':len(ids),'cleared_guests':cleared,'skips_running_jobs':True,'verified_identities_deleted':False},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
