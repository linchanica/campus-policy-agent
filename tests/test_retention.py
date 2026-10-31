import json,sys
from datetime import datetime,timedelta
from app.config import TZ
from app.db import initialize,create_user,connect
from app import admin_cli

def test_retention_previews_then_deletes_only_unbound_anonymous_users(monkeypatch,capsys):
    initialize()
    anonymous=create_user()['user_id'];bound=create_user()['user_id'];admin=create_user('admin','虚构维护者')['user_id']
    with connect() as d:
        d.execute('INSERT INTO identities VALUES(?,?,?,?)',('wechat','fictional-retention-subject',bound,datetime.now(TZ).isoformat()))
        for uid in [anonymous,bound,admin]:d.execute('UPDATE users SET created_at=? WHERE id=?',((datetime.now(TZ)-timedelta(days=45)).isoformat(),uid))
    monkeypatch.setattr(sys,'argv',['admin_cli','retention','--days','30']);admin_cli.main()
    assert json.loads(capsys.readouterr().out)['dry_run'] is True
    with connect() as d:assert d.execute('SELECT 1 FROM users WHERE id=?',(anonymous,)).fetchone()
    monkeypatch.setattr(sys,'argv',['admin_cli','retention','--days','30','--apply']);admin_cli.main()
    result=json.loads(capsys.readouterr().out)
    assert result['cleared_guests']==1
    with connect() as d:
        assert not d.execute('SELECT 1 FROM users WHERE id=?',(anonymous,)).fetchone()
        assert d.execute('SELECT 1 FROM users WHERE id=?',(bound,)).fetchone()
        assert d.execute('SELECT 1 FROM users WHERE id=?',(admin,)).fetchone()
