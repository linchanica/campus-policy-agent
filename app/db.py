import sqlite3,json,secrets,hashlib
from contextlib import contextmanager
from uuid import uuid4
from datetime import datetime,timedelta
from .config import WORK,now,TZ
TOKEN_HOURS=24

@contextmanager
def connect():
    db=sqlite3.connect(WORK/'policy.db',timeout=20)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback();raise
    finally:db.close()

def initialize():
    with connect() as d:
        d.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),title TEXT NOT NULL,topic TEXT,profile_json TEXT NOT NULL DEFAULT '{}',revision INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),role TEXT NOT NULL,text TEXT NOT NULL,client_id TEXT,created_at TEXT NOT NULL, UNIQUE(session_id,client_id));
        CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY,message_id TEXT UNIQUE NOT NULL REFERENCES messages(id),session_id TEXT NOT NULL REFERENCES sessions(id),state TEXT NOT NULL,request_json TEXT NOT NULL,result_json TEXT,error TEXT,attempt INTEGER NOT NULL DEFAULT 0,lease_until REAL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS handoffs(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),payload_json TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY,action TEXT NOT NULL,object_id TEXT,details TEXT,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_turns_state ON turns(state,lease_until);
        CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id,created_at);
        CREATE TABLE IF NOT EXISTS auth_tokens(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),auth_mode TEXT NOT NULL,expires_at TEXT NOT NULL,revoked_at TEXT);
        CREATE TABLE IF NOT EXISTS user_roles(user_id TEXT PRIMARY KEY REFERENCES users(id),role TEXT NOT NULL,display_name TEXT NOT NULL,verified_staff INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS identities(provider TEXT NOT NULL,subject_hash TEXT NOT NULL,user_id TEXT NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,PRIMARY KEY(provider,subject_hash));
        CREATE TABLE IF NOT EXISTS pairing_codes(code_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),expires_at TEXT NOT NULL,used_at TEXT);
        CREATE TABLE IF NOT EXISTS staff_invitations(code_hash TEXT PRIMARY KEY,role TEXT NOT NULL,display_name TEXT NOT NULL,expires_at TEXT NOT NULL,used_at TEXT);
        CREATE TABLE IF NOT EXISTS policy_drafts(id TEXT PRIMARY KEY,base_release_id TEXT NOT NULL,manifest_json TEXT NOT NULL,created_by TEXT NOT NULL REFERENCES users(id),revision INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS policy_reviews(draft_id TEXT NOT NULL REFERENCES policy_drafts(id),policy_key TEXT NOT NULL,revision INTEGER NOT NULL,version_id TEXT NOT NULL,decision TEXT NOT NULL,reviewer_id TEXT NOT NULL REFERENCES users(id),verified_staff INTEGER NOT NULL,notes TEXT NOT NULL,checks_json TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(draft_id,policy_key));
        CREATE TABLE IF NOT EXISTS release_snapshots(id TEXT PRIMARY KEY,path TEXT NOT NULL,manifest_hash TEXT NOT NULL,state TEXT NOT NULL,kind TEXT NOT NULL,created_by TEXT NOT NULL REFERENCES users(id),created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS active_release(slot TEXT PRIMARY KEY,release_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS release_events(id INTEGER PRIMARY KEY,release_id TEXT NOT NULL,previous_id TEXT,actor_id TEXT NOT NULL,event TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY,value_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ticket_events(id INTEGER PRIMARY KEY,handoff_id TEXT NOT NULL REFERENCES handoffs(id),actor_id TEXT NOT NULL,state TEXT NOT NULL,text TEXT NOT NULL,created_at TEXT NOT NULL);
        PRAGMA user_version=2;
        ''')
        # Preserve valid existing opaque credentials across the additive migration.
        for row in d.execute('SELECT id,token_hash,created_at FROM users').fetchall():
            expiry=(datetime.fromisoformat(row['created_at'])+timedelta(hours=TOKEN_HOURS)).isoformat()
            d.execute('INSERT OR IGNORE INTO auth_tokens VALUES(?,?,?,?,NULL)',(row['token_hash'],row['id'],'local_guest',expiry))

def guest():
    return create_user()

def create_user(role='student',display_name='本机试用用户',auth_mode='local_guest',verified_staff=False):
    uid=str(uuid4());token=secrets.token_urlsafe(40);hashed=hashlib.sha256(token.encode()).hexdigest()
    expiry=(datetime.now(TZ)+timedelta(hours=TOKEN_HOURS)).isoformat()
    with connect() as d:
        d.execute('INSERT INTO users VALUES(?,?,?)',(uid,hashed,now()))
        d.execute('INSERT INTO user_roles VALUES(?,?,?,?)',(uid,role,display_name,int(verified_staff)))
        d.execute('INSERT INTO auth_tokens VALUES(?,?,?,?,NULL)',(hashed,uid,auth_mode,expiry))
    return {'user_id':uid,'access_token':token,'auth_mode':auth_mode,'expires_at':expiry,'role':role}

def user_for(token):
    with connect() as d:
        row=d.execute('SELECT user_id,expires_at,revoked_at FROM auth_tokens WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row or row['revoked_at'] or datetime.now(TZ)>=datetime.fromisoformat(row['expires_at']):return None
        return row['user_id']

def role_for(uid):
    with connect() as d:
        row=d.execute('SELECT * FROM user_roles WHERE user_id=?',(uid,)).fetchone()
        return dict(row) if row else {'user_id':uid,'role':'student','display_name':'学生','verified_staff':0}

def issue_token(d,uid,auth_mode):
    token=secrets.token_urlsafe(40);hashed=hashlib.sha256(token.encode()).hexdigest();expiry=(datetime.now(TZ)+timedelta(hours=TOKEN_HOURS)).isoformat()
    d.execute('UPDATE users SET token_hash=? WHERE id=?',(hashed,uid))
    d.execute('INSERT INTO auth_tokens VALUES(?,?,?,?,NULL)',(hashed,uid,auth_mode,expiry))
    return {'user_id':uid,'access_token':token,'expires_at':expiry,'auth_mode':auth_mode}

def setting(key,default=None):
    with connect() as d:row=d.execute('SELECT value_json FROM app_settings WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default

def clear_user_sessions(d,uid):
    running=d.execute("SELECT 1 FROM turns t JOIN sessions s ON s.id=t.session_id WHERE s.user_id=? AND t.state IN ('RECEIVED','RUNNING')",(uid,)).fetchone()
    if running:return False
    if d.execute("SELECT 1 FROM handoffs h JOIN sessions s ON s.id=h.session_id WHERE s.user_id=? AND h.state IN ('queued','accepted')",(uid,)).fetchone():return False
    for row in d.execute('SELECT h.id FROM handoffs h JOIN sessions s ON s.id=h.session_id WHERE s.user_id=?',(uid,)).fetchall():
        d.execute('DELETE FROM app_settings WHERE key LIKE ?',('ticket_event:'+row[0]+':%',))
    d.execute('DELETE FROM ticket_events WHERE handoff_id IN (SELECT h.id FROM handoffs h JOIN sessions s ON s.id=h.session_id WHERE s.user_id=?)',(uid,))
    for table in ['handoffs','turns','messages']:
        d.execute(f'DELETE FROM {table} WHERE session_id IN (SELECT id FROM sessions WHERE user_id=?)',(uid,))
    d.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
    return True

def audit(action,object_id,details=None):
    with connect() as d:d.execute('INSERT INTO audit_logs(action,object_id,details,created_at) VALUES(?,?,?,?)',(action,object_id,json.dumps(details or {},ensure_ascii=False),now()))

