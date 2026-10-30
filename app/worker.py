import json,time,threading,logging
from .db import connect,audit
from .workflow import run
from .config import TZ
from datetime import datetime

log=logging.getLogger('policy.worker')

def process(turn_id):
    with connect() as d:
        d.execute('BEGIN IMMEDIATE')
        row=d.execute('SELECT * FROM turns WHERE id=?',(turn_id,)).fetchone()
        if not row or row['state'] in {'COMPLETED','FAILED','STALE'}:return
        if row['state']=='RUNNING' and (row['lease_until'] or 0)>time.time():return
        d.execute("UPDATE turns SET state='RUNNING',attempt=attempt+1,lease_until=? WHERE id=?",(time.time()+180,turn_id))
        session=d.execute('SELECT * FROM sessions WHERE id=?',(row['session_id'],)).fetchone()
        request=json.loads(row['request_json'])
        if session['revision']!=request['profile_revision']:
            d.execute("UPDATE turns SET state='STALE',error='画像已更新，请重新提交' WHERE id=?",(turn_id,));return
    try:
        at=datetime.fromisoformat(request['simulation_time']).astimezone(TZ) if request.get('simulation_time') else None
        result,profile,topic=run(request['text'],json.loads(session['profile_json']),request.get('profile_patch',{}),request.get('topic') or session['topic'],at=at,message_id=row['message_id'],simulation=at is not None)
        with connect() as d:
            d.execute('BEGIN IMMEDIATE')
            fresh=d.execute('SELECT revision FROM sessions WHERE id=?',(session['id'],)).fetchone()
            if fresh['revision']!=request['profile_revision']:
                d.execute("UPDATE turns SET state='STALE',error='画像已更新，请重新提交' WHERE id=?",(turn_id,));return
            revision=session['revision']+1
            result['profile_revision']=revision
            d.execute('UPDATE sessions SET profile_json=?,revision=?,topic=?,title=? WHERE id=?',(json.dumps(profile,ensure_ascii=False),revision,topic,request['text'][:40],session['id']))
            d.execute("UPDATE turns SET state='COMPLETED',result_json=?,lease_until=NULL WHERE id=?",(json.dumps(result,ensure_ascii=False),turn_id))
        audit('turn_completed',turn_id,{'decision':result['decision'],'release_id':result['release_id']})
    except Exception as e:
        log.exception('Turn failed: %s',turn_id)
        with connect() as d:d.execute("UPDATE turns SET state='FAILED',error=?,lease_until=NULL WHERE id=?",('处理暂时失败，请重试或使用人工咨询摘要。',turn_id))

def recover():
    with connect() as d:rows=d.execute("SELECT id FROM turns WHERE state='RECEIVED' OR (state='RUNNING' AND lease_until<?)",(time.time(),)).fetchall()
    for row in rows:process(row['id'])

def main():
    from .db import initialize
    initialize()
    while True:recover();time.sleep(2)

if __name__=='__main__':main()

