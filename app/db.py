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
        PRAGMA user_version=1;
        ''')

def guest():
    token=secrets.token_urlsafe(40);uid=str(uuid4())
    with connect() as d:d.execute('INSERT INTO users VALUES(?,?,?)',(uid,hashlib.sha256(token.encode()).hexdigest(),now()))
    return {'user_id':uid,'access_token':token,'auth_mode':'local_guest','expires_at':(datetime.now(TZ)+timedelta(hours=TOKEN_HOURS)).isoformat()}

def user_for(token):
    with connect() as d:
        row=d.execute('SELECT id,created_at FROM users WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row or datetime.now(TZ)>=datetime.fromisoformat(row['created_at'])+timedelta(hours=TOKEN_HOURS):return None
        return row['id']

def clear_user_sessions(d,uid):
    running=d.execute("SELECT 1 FROM turns t JOIN sessions s ON s.id=t.session_id WHERE s.user_id=? AND t.state IN ('RECEIVED','RUNNING')",(uid,)).fetchone()
    if running:return False
    for table in ['handoffs','turns','messages']:
        d.execute(f'DELETE FROM {table} WHERE session_id IN (SELECT id FROM sessions WHERE user_id=?)',(uid,))
    d.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
    return True

def audit(action,object_id,details=None):
    with connect() as d:d.execute('INSERT INTO audit_logs(action,object_id,details,created_at) VALUES(?,?,?,?)',(action,object_id,json.dumps(details or {},ensure_ascii=False),now()))

