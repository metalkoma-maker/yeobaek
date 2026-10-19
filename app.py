import os, sqlite3, secrets, hashlib, hmac, time, re, json, smtplib, ssl
from email.message import EmailMessage
from urllib.parse import urlsplit
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, g

app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024
DB = os.environ.get('DATABASE_PATH', 'data/novel.sqlite3')
SECURE = os.environ.get('COOKIE_SECURE', '0') == '1'
SEOUL = ZoneInfo('Asia/Seoul')
CHECKPOINT_INTERVAL = 30 * 60
RESET_LIFETIME = 30 * 60

def db():
    if 'db' not in g:
        os.makedirs(os.path.dirname(os.path.abspath(DB)), exist_ok=True)
        g.db = sqlite3.connect(DB, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db

@app.teardown_appcontext
def close(error):
    if 'db' in g: g.db.close()

def init():
    with app.app_context():
        db().executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,csrf TEXT NOT NULL,expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS manuscripts(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,title TEXT NOT NULL,body TEXT NOT NULL DEFAULT '',version INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS manuscript_history(manuscript_id TEXT NOT NULL REFERENCES manuscripts(id) ON DELETE CASCADE,version INTEGER NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,updated INTEGER NOT NULL,PRIMARY KEY(manuscript_id,version));
        CREATE TABLE IF NOT EXISTS manuscript_checkpoints(manuscript_id TEXT NOT NULL REFERENCES manuscripts(id) ON DELETE CASCADE,version INTEGER NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,updated INTEGER NOT NULL,created INTEGER NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('auto','manual','before_restore','legacy')),label TEXT NOT NULL DEFAULT '',PRIMARY KEY(manuscript_id,version));
        CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY,applied INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS daily(manuscript_id TEXT REFERENCES manuscripts(id) ON DELETE CASCADE,day TEXT NOT NULL,delta INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(manuscript_id,day));
        CREATE TABLE IF NOT EXISTS manuscript_order(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,ids TEXT NOT NULL,version INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY,started INTEGER NOT NULL,count INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS password_resets(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,expires INTEGER NOT NULL);
        ''')
        # Existing recent history must survive the new rolling-history policy.
        # Copy it once in one transaction, without changing manuscripts or history.
        db().execute('BEGIN IMMEDIATE')
        if not db().execute("SELECT 1 FROM schema_migrations WHERE name='history_checkpoints_v1'").fetchone():
            db().execute('''INSERT OR IGNORE INTO manuscript_checkpoints(manuscript_id,version,title,body,updated,created,kind,label)
                SELECT manuscript_id,version,title,body,updated,updated,'legacy','기존 수정 이력' FROM manuscript_history''')
            db().execute("INSERT INTO schema_migrations VALUES('history_checkpoints_v1',?)",(int(time.time()),))
        if not db().execute("SELECT 1 FROM schema_migrations WHERE name='count_spaces_v1'").fetchone():
            today=datetime.now(SEOUL).date()
            # Finish an already-started writing day with its original units.
            # A new database or a day without saved changes switches immediately.
            had_daily=db().execute('SELECT 1 FROM daily WHERE day=? LIMIT 1',(today.isoformat(),)).fetchone()
            effective=today+timedelta(days=1) if had_daily else today
            midnight=datetime(effective.year,effective.month,effective.day,tzinfo=SEOUL)
            db().execute("INSERT INTO schema_migrations VALUES('count_spaces_v1',?)",(int(midnight.timestamp()),))
        db().commit()

def day(): return datetime.now(SEOUL).date().isoformat()
def count(text): return len(re.sub(r'[\r\n\u2028\u2029]', '', text))
def count_without_spaces(text): return len(re.sub(r'\s', '', text))
def legacy_count_day():
    effective=db().execute("SELECT applied FROM schema_migrations WHERE name='count_spaces_v1'").fetchone()[0]
    return int(time.time())<effective
COUNT_BODY_SQL = "length(replace(replace(replace(replace(body,char(13),''),char(10),''),char(8232),''),char(8233),''))"
def digest(password, salt): return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
def fail(msg, code=400): return jsonify(error=msg), code

@app.before_request
def guard():
    if not request.path.startswith('/api/'): return
    if request.method != 'GET':
        origin = request.headers.get('Origin')
        if origin and origin != request.host_url.rstrip('/'): return fail('허용되지 않는 요청입니다.',403)
        if not request.is_json: return fail('JSON 요청이 필요합니다.',415)
    g.user = None
    raw = request.cookies.get('novel_session','')
    row = db().execute('SELECT s.*,u.email FROM sessions s JOIN users u ON u.id=s.user_id WHERE token=? AND expires>?',(hashlib.sha256(raw.encode()).hexdigest(),int(time.time()))).fetchone()
    if row: g.user = dict(row)
    if request.path not in ['/api/register','/api/login','/api/me',
                            '/api/account/recover-id','/api/password-reset/request','/api/password-reset/confirm']:
        if not g.user: return fail('로그인이 필요합니다.',401)
        if request.method != 'GET' and not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),g.user['csrf']): return fail('다시 로그인해 주세요.',403)

@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.path.startswith('/api/'): response.headers['Cache-Control']='no-store'
    return response

@app.after_request
def admin_brand(response):
    # admin.html is outside the restricted release bundle. Keep the served name
    # current even when the protected server copy still has the original brand.
    if request.path != '/admin' or request.method != 'GET' or response.status_code not in (200, 304):
        return response
    source = (Path(app.static_folder) / 'admin.html').read_bytes()
    branded = (source.replace('<title>여백 · 관리자</title>'.encode(),
                              '<title>소설여백 · 관리자</title>'.encode())
                     .replace('class="brand">여백</a>'.encode(),
                              'class="brand">소설여백</a>'.encode()))
    original_body = response.response
    if hasattr(original_body, 'close'):
        original_body.close()
    response.status_code = 200
    response.direct_passthrough = False
    response.set_data(branded)
    response.headers.pop('ETag', None)
    response.headers.pop('Last-Modified', None)
    response.headers['Cache-Control'] = 'no-store'
    return response

def session_response(uid,email):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db().execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,csrf,int(time.time())+60*60*24*30))
    db().commit()
    response=jsonify(email=email,csrf=csrf,is_admin=app.is_admin({'user_id':uid}))
    response.set_cookie('novel_session',token,max_age=2592000,httponly=True,secure=SECURE,samesite='Lax')
    return response

@app.post('/api/<action>')
def auth(action):
    if action not in ['login','register']: return fail('없는 경로입니다.',404)
    data=request.get_json() or {}
    email=data.get('email',''); password=data.get('password','')
    if not isinstance(email,str) or not isinstance(password,str): return fail('입력값을 확인해 주세요.')
    email=email.strip().lower()
    if len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or not 10<=len(password)<=256: return fail('이메일과 10자 이상의 비밀번호를 입력해 주세요.')
    key=hashlib.sha256((request.remote_addr+'|'+email).encode()).hexdigest(); now=int(time.time())
    db().execute('INSERT INTO attempts VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN started<? THEN 1 ELSE count+1 END,started=CASE WHEN started<? THEN excluded.started ELSE started END',(key,now,now-900,now-900))
    db().commit()
    if db().execute('SELECT count FROM attempts WHERE key=?',(key,)).fetchone()[0]>15: return fail('시도가 많습니다. 15분 후 다시 시도해 주세요.',429)
    if action=='register':
        salt=secrets.token_hex(16); uid=secrets.token_hex(16)
        try:
            db().execute('INSERT INTO users VALUES(?,?,?)',(uid,email,salt+':'+digest(password,salt)))
            db().execute('INSERT INTO user_metadata(user_id,created) VALUES(?,?)',(uid,now)); db().commit()
        except sqlite3.IntegrityError: return fail('가입할 수 없는 이메일입니다.',409)
    else:
        row=db().execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        salt,expected = row['password'].split(':') if row else ('00'*16,'')
        if not hmac.compare_digest(digest(password,salt),expected): return fail('이메일 또는 비밀번호를 확인해 주세요.',401)
        uid=row['id']
    return session_response(uid,email)

@app.get('/api/me')
def me(): return jsonify(email=g.user['email'],csrf=g.user['csrf'],is_admin=app.is_admin(g.user)) if g.user else fail('로그인이 필요합니다.',401)

@app.post('/api/logout')
def logout():
    db().execute('DELETE FROM sessions WHERE token=?',(g.user['token'],)); db().commit()
    response=jsonify(ok=True); response.delete_cookie('novel_session',secure=SECURE,samesite='Lax'); return response

def valid_email(value):
    return isinstance(value,str) and len(value.strip())<=254 and bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value.strip()))

def valid_password(value): return isinstance(value,str) and 10<=len(value)<=256

def recovery_mail_ready(reset=False):
    if not os.environ.get('SMTP_HOST') or not os.environ.get('SMTP_FROM'): return False
    if bool(os.environ.get('SMTP_USERNAME')) != bool(os.environ.get('SMTP_PASSWORD')): return False
    if reset:
        try: url=urlsplit(os.environ.get('APP_PUBLIC_URL',''))
        except ValueError: return False
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.path not in ('','/') or url.query or url.fragment: return False
    return True

def send_account_mail(address,subject,body):
    message=EmailMessage()
    message['From']=os.environ['SMTP_FROM']; message['To']=address; message['Subject']=subject
    message.set_content(body)
    mode=os.environ.get('SMTP_SECURITY','ssl')
    port=int(os.environ.get('SMTP_PORT','465' if mode=='ssl' else '587'))
    if mode not in ('ssl','starttls'): raise ValueError('SMTP_SECURITY must be ssl or starttls')
    context=ssl.create_default_context()
    if mode=='ssl': connection=smtplib.SMTP_SSL(os.environ['SMTP_HOST'],port,timeout=10,context=context)
    else: connection=smtplib.SMTP(os.environ['SMTP_HOST'],port,timeout=10)
    with connection as smtp:
        if mode=='starttls': smtp.starttls(context=context)
        if os.environ.get('SMTP_USERNAME'): smtp.login(os.environ['SMTP_USERNAME'],os.environ['SMTP_PASSWORD'])
        smtp.send_message(message)

def recovery_limit(address):
    now=int(time.time()); ip=request.remote_addr or 'unknown'
    for subject,limit in [('email:'+ip+'|'+address,5),('ip:'+ip,60)]:
        key=hashlib.sha256(('recovery:'+subject).encode()).hexdigest()
        db().execute('INSERT INTO attempts VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN started<? THEN 1 ELSE count+1 END,started=CASE WHEN started<? THEN excluded.started ELSE started END',
                     (key,now,now-900,now-900))
        if db().execute('SELECT count FROM attempts WHERE key=?',(key,)).fetchone()[0]>limit:
            db().commit(); return False
    db().commit(); return True

@app.post('/api/account/recover-id')
def recover_id():
    data=request.get_json() or {}; address=data.get('email')
    if not valid_email(address): return fail('이메일 주소를 확인해 주세요.')
    if not recovery_mail_ready(): return fail('이메일 발송이 아직 준비되지 않았습니다.',503)
    address=address.strip().lower()
    if not recovery_limit(address): return fail('요청이 많습니다. 15분 후 다시 시도해 주세요.',429)
    row=db().execute('SELECT email FROM users WHERE email=?',(address,)).fetchone()
    body=(f'소설여백 로그인 아이디는 {row["email"]}입니다.\n' if row else
          '이 주소로 등록된 소설여백 계정을 찾지 못했습니다.\n')
    try: send_account_mail(address,'소설여백 로그인 이메일 안내',body+'본인이 요청하지 않았다면 이 메일을 무시하세요.')
    except Exception:
        app.logger.exception('Account email delivery failed')
        return fail('이메일 발송에 실패했습니다. 잠시 후 다시 시도해 주세요.',503)
    return jsonify(message='입력한 이메일로 안내를 보냈습니다.')

@app.post('/api/password-reset/request')
def request_password_reset():
    data=request.get_json() or {}; address=data.get('email')
    if not valid_email(address): return fail('이메일 주소를 확인해 주세요.')
    if not recovery_mail_ready(reset=True): return fail('비밀번호 복구 메일이 아직 준비되지 않았습니다.',503)
    address=address.strip().lower()
    if not recovery_limit(address): return fail('요청이 많습니다. 15분 후 다시 시도해 주세요.',429)
    row=db().execute('SELECT id FROM users WHERE email=?',(address,)).fetchone()
    token=secrets.token_urlsafe(32) if row else None
    token_hash=hashlib.sha256(token.encode()).hexdigest() if token else None
    db().execute('DELETE FROM password_resets WHERE expires<=?',(int(time.time()),))
    if row:
        db().execute('INSERT INTO password_resets VALUES(?,?,?)',(token_hash,row['id'],int(time.time())+RESET_LIFETIME))
    db().commit()
    if token:
        link=os.environ['APP_PUBLIC_URL'].rstrip('/')+'/#reset='+token
        body='소설여백 비밀번호 재설정 링크입니다. 30분 동안 한 번만 사용할 수 있습니다.\n'+link+'\n본인이 요청하지 않았다면 이 메일을 무시하세요.'
    else: body='이 주소로 등록된 소설여백 계정을 찾지 못했습니다. 본인이 요청하지 않았다면 이 메일을 무시하세요.'
    try: send_account_mail(address,'소설여백 비밀번호 재설정',body)
    except Exception:
        if token_hash: db().execute('DELETE FROM password_resets WHERE token_hash=?',(token_hash,)); db().commit()
        app.logger.exception('Password reset email delivery failed')
        return fail('이메일 발송에 실패했습니다. 잠시 후 다시 시도해 주세요.',503)
    return jsonify(message='입력한 이메일로 안내를 보냈습니다.')

@app.post('/api/password-reset/confirm')
def confirm_password_reset():
    data=request.get_json() or {}; token=data.get('token'); password=data.get('new_password')
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token) or not valid_password(password):
        return fail('재설정 링크와 새 비밀번호를 확인해 주세요.')
    token_hash=hashlib.sha256(token.encode()).hexdigest()
    db().execute('BEGIN IMMEDIATE')
    row=db().execute('SELECT user_id FROM password_resets WHERE token_hash=? AND expires>?',(token_hash,int(time.time()))).fetchone()
    if not row: db().rollback(); return fail('재설정 링크가 만료되었거나 이미 사용됐습니다.',400)
    salt=secrets.token_hex(16)
    db().execute('UPDATE users SET password=? WHERE id=?',(salt+':'+digest(password,salt),row['user_id']))
    db().execute('DELETE FROM sessions WHERE user_id=?',(row['user_id'],))
    db().execute('DELETE FROM password_resets WHERE user_id=?',(row['user_id'],))
    db().commit()
    response=jsonify(ok=True)
    response.delete_cookie('novel_session',secure=SECURE,samesite='Lax')
    return response

@app.post('/api/account/password')
def change_password():
    data=request.get_json() or {}; old=data.get('current_password'); new=data.get('new_password')
    if not valid_password(old) or not valid_password(new): return fail('현재 비밀번호와 10자 이상의 새 비밀번호를 입력해 주세요.')
    db().execute('BEGIN IMMEDIATE')
    row=db().execute('SELECT password FROM users WHERE id=?',(g.user['user_id'],)).fetchone()
    salt,expected=row['password'].split(':')
    if not hmac.compare_digest(digest(old,salt),expected):
        db().rollback(); return fail('현재 비밀번호가 맞지 않습니다.',403)
    if hmac.compare_digest(old,new): db().rollback(); return fail('기존과 다른 비밀번호를 입력해 주세요.')
    salt=secrets.token_hex(16)
    db().execute('UPDATE users SET password=? WHERE id=?',(salt+':'+digest(new,salt),g.user['user_id']))
    db().execute('DELETE FROM sessions WHERE user_id=?',(g.user['user_id'],))
    db().execute('DELETE FROM password_resets WHERE user_id=?',(g.user['user_id'],))
    db().commit()
    return session_response(g.user['user_id'],g.user['email'])

@app.post('/api/account/delete')
def delete_account():
    data=request.get_json() or {}; password=data.get('password'); confirmation=data.get('confirmation')
    if not valid_password(password) or confirmation!='탈퇴': return fail('비밀번호와 탈퇴 확인 문구를 입력해 주세요.')
    if app.is_admin(g.user): return fail('관리자 계정은 이 화면에서 탈퇴할 수 없습니다.',403)
    db().execute('BEGIN IMMEDIATE')
    row=db().execute('SELECT password FROM users WHERE id=?',(g.user['user_id'],)).fetchone()
    salt,expected=row['password'].split(':')
    if not hmac.compare_digest(digest(password,salt),expected): db().rollback(); return fail('비밀번호가 맞지 않습니다.',403)
    db().execute('DELETE FROM users WHERE id=?',(g.user['user_id'],))
    db().commit()
    response=jsonify(ok=True)
    response.delete_cookie('novel_session',secure=SECURE,samesite='Lax')
    return response

def owned(mid): return db().execute('SELECT * FROM manuscripts WHERE id=? AND user_id=?',(mid,g.user['user_id'])).fetchone()
def pack(row):
    data=dict(row); data.pop('user_id',None)
    delta=db().execute('SELECT delta FROM daily WHERE manuscript_id=? AND day=?',(data['id'],day())).fetchone()
    data.update(total=count(data['body']),today=delta[0] if delta else 0,day=day(),
                today_count_rule='without_spaces' if legacy_count_day() else 'with_spaces')
    return data

def checkpoint(mid, row, kind, now, label=''):
    db().execute('''INSERT INTO manuscript_checkpoints(manuscript_id,version,title,body,updated,created,kind,label) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(manuscript_id,version) DO UPDATE SET
        kind=CASE WHEN manuscript_checkpoints.kind='manual' AND excluded.kind='before_restore' THEN 'manual' ELSE excluded.kind END,
        label=CASE WHEN manuscript_checkpoints.kind='manual' AND excluded.kind='before_restore' THEN manuscript_checkpoints.label ELSE excluded.label END,
        created=excluded.created WHERE excluded.kind != 'auto' ''',
                 (mid,row['version'],row['title'],row['body'],row['updated'],now,kind,label))

def prune_checkpoints(mid, now):
    """Keep recent automatic points, then one per Seoul day/month; never prune named points."""
    rows=db().execute("SELECT version,updated FROM manuscript_checkpoints WHERE manuscript_id=? AND kind='auto' ORDER BY updated DESC,version DESC",(mid,)).fetchall()
    today=datetime.fromtimestamp(now,SEOUL).date()
    cutoff=today-timedelta(days=29)
    newest_month=today.year*12+today.month-1
    keep=set(); days=set(); months=set()
    for index,row in enumerate(rows):
        written=datetime.fromtimestamp(row['updated'],SEOUL).date()
        month=written.year*12+written.month-1
        if index<10 or (cutoff<=written<=today and written not in days) or (newest_month-11<=month<=newest_month and month not in months):
            keep.add(row['version']); days.add(written); months.add(month)
    if keep:
        placeholders=','.join('?' for _ in keep)
        db().execute(f"DELETE FROM manuscript_checkpoints WHERE manuscript_id=? AND kind='auto' AND version NOT IN ({placeholders})",(mid,*keep))

def automatic_checkpoint(mid, row, now):
    if row['version']<1: return
    latest=db().execute('SELECT max(created) FROM manuscript_checkpoints WHERE manuscript_id=?',(mid,)).fetchone()[0]
    if latest is None or now-latest>=CHECKPOINT_INTERVAL or now-row['updated']>=CHECKPOINT_INTERVAL:
        checkpoint(mid,row,'auto',now)
        prune_checkpoints(mid,now)

def save_manuscript(mid, old, title, body, now, keep_before_restore=False):
    if keep_before_restore: checkpoint(mid,old,'before_restore',now,'복원 전 글')
    else: automatic_checkpoint(mid,old,now)
    db().execute('INSERT OR IGNORE INTO manuscript_history VALUES(?,?,?,?,?)',(mid,old['version'],old['title'],old['body'],old['updated']))
    db().execute('DELETE FROM manuscript_history WHERE manuscript_id=? AND version NOT IN (SELECT version FROM manuscript_history WHERE manuscript_id=? ORDER BY version DESC LIMIT 50)',(mid,mid))
    daily_counter=count_without_spaces if legacy_count_day() else count
    delta=daily_counter(body)-daily_counter(old['body'])
    db().execute('UPDATE manuscripts SET title=?,body=?,version=version+1,updated=? WHERE id=?',(title,body,now,mid))
    db().execute('INSERT INTO daily VALUES(?,?,?) ON CONFLICT(manuscript_id,day) DO UPDATE SET delta=delta+excluded.delta',(mid,day(),delta))

def next_copy_title(title, user_id):
    base=re.sub(r' · [2-9][0-9]*교$', '', title.strip() or '제목 없는 원고')
    titles=[row[0] for row in db().execute('SELECT title FROM manuscripts WHERE user_id=?',(user_id,))]
    number=1
    for existing in titles:
        match=re.search(r' · ([2-9][0-9]*)교$',existing)
        if match and existing[:match.start()]==base[:200-len(match.group(0))]:
            number=max(number,int(match[1]))
    suffix=f' · {max(2,number+1)}교'
    return base[:200-len(suffix)]+suffix

def manuscript_list_state():
    rows=db().execute('SELECT * FROM manuscripts WHERE user_id=? ORDER BY updated DESC,rowid DESC',(g.user['user_id'],)).fetchall()
    saved=db().execute('SELECT ids,version FROM manuscript_order WHERE user_id=?',(g.user['user_id'],)).fetchone()
    if saved:
        rank={mid:i for i,mid in enumerate(json.loads(saved['ids']))}
        # New manuscripts appear first; writing never moves manually ordered items.
        rows.sort(key=lambda row:(1,rank[row['id']]) if row['id'] in rank else (0,0))
    return rows,{'ids':[row['id'] for row in rows],'version':saved['version'] if saved else 0}

@app.route('/api/manuscript-order',methods=['GET','PUT'])
def manuscript_order():
    if request.method=='GET':
        return jsonify(manuscript_list_state()[1])
    data=request.get_json()
    if not isinstance(data,dict): return fail('원고 순서를 확인해 주세요.')
    ids=data.get('ids'); version=data.get('version')
    if (not isinstance(ids,list) or any(not isinstance(mid,str) or not 1<=len(mid)<=128 for mid in ids)
            or len(set(ids))!=len(ids) or type(version) is not int or version<0):
        return fail('원고 순서를 확인해 주세요.')
    db().execute('BEGIN IMMEDIATE')
    _,current=manuscript_list_state()
    if version!=current['version'] or set(ids)!=set(current['ids']):
        db().rollback()
        return jsonify(error='다른 기기에서 원고 목록이 바뀌었습니다. 확인 후 다시 옮겨 주세요.',current=current),409
    if ids==current['ids']:
        db().rollback()
        return jsonify(current)
    updated={'ids':ids,'version':current['version']+1}
    db().execute('INSERT INTO manuscript_order(user_id,ids,version) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET ids=excluded.ids,version=excluded.version',
                 (g.user['user_id'],json.dumps(ids),updated['version']))
    db().commit()
    return jsonify(updated)

@app.route('/api/manuscripts',methods=['GET','POST'])
def manuscripts():
    if request.method=='GET': return jsonify([pack(row) for row in manuscript_list_state()[0]])
    mid=secrets.token_hex(16)
    db().execute('INSERT INTO manuscripts(id,user_id,title,updated) VALUES(?,?,?,?)',(mid,g.user['user_id'],'제목 없는 원고',int(time.time()))); db().commit()
    return jsonify(pack(owned(mid))),201

@app.route('/api/manuscripts/<mid>',methods=['GET','PUT'])
def manuscript(mid):
    if request.method=='GET':
        row=owned(mid)
        return jsonify(pack(row)) if row else fail('원고를 찾을 수 없습니다.',404)
    data=request.get_json() or {}; title=data.get('title'); body=data.get('body'); version=data.get('version')
    if not isinstance(title,str) or not isinstance(body,str) or not isinstance(version,int) or len(title)>200 or len(body)>1000000: return fail('제목 또는 원고 길이를 확인해 주세요.')
    db().execute('BEGIN IMMEDIATE')
    row=owned(mid)
    if not row: db().rollback(); return fail('원고를 찾을 수 없습니다.',404)
    if row['version']!=version:
        result=pack(row); db().rollback(); return jsonify(error='다른 기기에서 수정된 원고가 있습니다.',current=result),409
    if title == row['title'] and body == row['body']:
        result=pack(row); db().rollback(); return jsonify(result)
    save_manuscript(mid,row,title,body,int(time.time()))
    db().commit(); return jsonify(pack(owned(mid)))

@app.post('/api/manuscripts/<mid>/copy')
def copy_manuscript(mid):
    data=request.get_json() or {}
    version=data.get('version'); title=data.get('title')
    if (type(version) is not int or version<0 or
            (title is not None and (not isinstance(title,str) or not 1<=len(title.strip())<=200))):
        return fail('사본 제목과 원고 버전을 확인해 주세요.')
    db().execute('BEGIN IMMEDIATE')
    source=owned(mid)
    if not source: db().rollback(); return fail('원고를 찾을 수 없습니다.',404)
    if source['version']!=version:
        result=pack(source); db().rollback()
        return jsonify(error='다른 기기에서 원고가 수정됐습니다. 다시 확인해 주세요.',current=result),409
    name=title.strip() if title is not None else next_copy_title(source['title'],g.user['user_id'])
    new_id=secrets.token_hex(16)
    db().execute('INSERT INTO manuscripts(id,user_id,title,body,version,updated) VALUES(?,?,?,?,0,?)',
                 (new_id,g.user['user_id'],name,source['body'],int(time.time())))
    db().commit()
    return jsonify(pack(owned(new_id))),201


@app.get('/api/manuscripts/<mid>/history')
def history(mid):
    if not owned(mid): return fail('원고를 찾을 수 없습니다.',404)
    rows=db().execute(f'SELECT version,title,updated,{COUNT_BODY_SQL} AS characters FROM manuscript_history WHERE manuscript_id=? ORDER BY version DESC LIMIT 50',(mid,)).fetchall()
    return jsonify([dict(x) for x in rows])

@app.get('/api/manuscripts/<mid>/history/<int:version>')
def history_item(mid,version):
    if not owned(mid): return fail('원고를 찾을 수 없습니다.',404)
    row=db().execute('SELECT version,title,body,updated FROM manuscript_history WHERE manuscript_id=? AND version=?',(mid,version)).fetchone()
    return jsonify(dict(row)) if row else fail('수정 이력을 찾을 수 없습니다.',404)

@app.route('/api/manuscripts/<mid>/checkpoints',methods=['GET','POST'])
def checkpoints(mid):
    if not owned(mid): return fail('원고를 찾을 수 없습니다.',404)
    if request.method=='GET':
        rows=db().execute(f'SELECT version,title,updated,created,kind,label,{COUNT_BODY_SQL} AS characters FROM manuscript_checkpoints WHERE manuscript_id=? ORDER BY updated DESC,version DESC',(mid,)).fetchall()
        return jsonify([dict(row) for row in rows])
    data=request.get_json() or {}
    version=data.get('version'); label=data.get('label','중요한 버전'); expected=data.get('expected_current_version')
    if (type(version) is not int or version<0 or not isinstance(label,str) or not 1<=len(label.strip())<=80
            or (expected is not None and (type(expected) is not int or expected<0))):
        return fail('보관할 버전과 이름을 확인해 주세요.')
    db().execute('BEGIN IMMEDIATE')
    current=owned(mid)
    if expected is not None and expected!=current['version']:
        result=pack(current); db().rollback(); return jsonify(error='다른 기기에서 수정된 원고가 있습니다.',current=result),409
    source=current if current['version']==version else db().execute('SELECT * FROM manuscript_checkpoints WHERE manuscript_id=? AND version=?',(mid,version)).fetchone()
    if source is None: source=db().execute('SELECT * FROM manuscript_history WHERE manuscript_id=? AND version=?',(mid,version)).fetchone()
    if source is None: db().rollback(); return fail('보관할 버전을 찾을 수 없습니다.',404)
    checkpoint(mid,source,'manual',int(time.time()),label.strip())
    db().commit()
    return jsonify(version=version,label=label.strip(),kind='manual')

@app.get('/api/manuscripts/<mid>/checkpoints/<int:version>')
def checkpoint_item(mid,version):
    if not owned(mid): return fail('원고를 찾을 수 없습니다.',404)
    row=db().execute('SELECT version,title,body,updated,kind,label FROM manuscript_checkpoints WHERE manuscript_id=? AND version=?',(mid,version)).fetchone()
    return jsonify(dict(row)) if row else fail('복원 지점을 찾을 수 없습니다.',404)

@app.post('/api/manuscripts/<mid>/restore')
def restore_manuscript(mid):
    data=request.get_json() or {}
    version=data.get('version'); source_version=data.get('source_version')
    if type(version) is not int or type(source_version) is not int or version<0 or source_version<0:
        return fail('복원할 버전을 확인해 주세요.')
    db().execute('BEGIN IMMEDIATE')
    current=owned(mid)
    if not current: db().rollback(); return fail('원고를 찾을 수 없습니다.',404)
    if current['version']!=version:
        result=pack(current); db().rollback(); return jsonify(error='다른 기기에서 수정된 원고가 있습니다.',current=result),409
    source=db().execute('SELECT title,body FROM manuscript_checkpoints WHERE manuscript_id=? AND version=?',(mid,source_version)).fetchone()
    if source is None: source=db().execute('SELECT title,body FROM manuscript_history WHERE manuscript_id=? AND version=?',(mid,source_version)).fetchone()
    if source is None: db().rollback(); return fail('복원할 버전을 찾을 수 없습니다.',404)
    if source['title']!=current['title'] or source['body']!=current['body']:
        save_manuscript(mid,current,source['title'],source['body'],int(time.time()),keep_before_restore=True)
    db().commit(); return jsonify(pack(owned(mid)))

@app.get('/')
def index(): return send_from_directory('static','index.html')
@app.get('/__app_manifest__')
def app_manifest():
    # This route is deployable with app.py even while manifest.json is protected.
    manifest = json.loads((Path(app.static_folder) / 'manifest.json').read_text(encoding='utf-8'))
    manifest['name'] = manifest['short_name'] = '소설여백'
    response = app.response_class(json.dumps(manifest, ensure_ascii=False),
                                  mimetype='application/manifest+json')
    response.headers['Cache-Control'] = 'no-store'
    return response
@app.get('/__deployment_health__')
def deployment_health(): return jsonify(api='manuscript-order-v1')
@app.get('/<path:path>')
def assets(path): return send_from_directory('static',path)

init()
from admin_panel import register_admin
register_admin(app, db, DB)
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT','8000')),debug=False)
