"""Read-only administration. Authorization binds to an existing account ID."""
import hashlib
import json
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from flask import g, jsonify, request, send_from_directory, redirect


def register_admin(app, db, database_path):
    config = Path(__file__).with_name('admin_config.json')
    admin_id = None
    if config.is_file():
        data = json.loads(config.read_text())
        admin_id = data.get('user_id')
        if not isinstance(admin_id, str) or not admin_id:
            raise RuntimeError('Invalid admin account binding')

    app.is_admin = lambda user: bool(admin_id and user and user['user_id'] == admin_id)
    with app.app_context():
        db().execute('CREATE TABLE IF NOT EXISTS user_metadata(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,created INTEGER NOT NULL)')
        db().commit()

    @app.after_request
    def admin_headers(response):
        if request.path == '/admin' or request.path.startswith('/api/admin/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/admin')
    def admin_page():
        token = hashlib.sha256(request.cookies.get('novel_session', '').encode()).hexdigest()
        user = db().execute('SELECT user_id FROM sessions WHERE token=? AND expires>?', (token, int(time.time()))).fetchone()
        if not user:
            return redirect('/')
        if not app.is_admin(user):
            return '관리자 계정만 접근할 수 있습니다.', 403
        return send_from_directory(app.static_folder, 'admin.html')

    @app.get('/api/admin/overview')
    def overview():
        if not app.is_admin(g.user):
            return jsonify(error='관리자 계정만 접근할 수 있습니다.'), 403
        zone = ZoneInfo('Asia/Seoul')
        midnight = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
        start, end = int(midnight.timestamp()), int((midnight + timedelta(days=1)).timestamp())
        summary = dict(db().execute('''SELECT COUNT(*) AS members,
            SUM(CASE WHEN md.created>=? AND md.created<? THEN 1 ELSE 0 END) AS joined_today,
            SUM(CASE WHEN md.created IS NULL THEN 1 ELSE 0 END) AS unknown_join_dates
            FROM users u LEFT JOIN user_metadata md ON md.user_id=u.id''', (start, end)).fetchone())
        totals = dict(db().execute('''SELECT COUNT(*) AS manuscripts,
            COALESCE(SUM(length(CAST(title AS BLOB))+length(CAST(body AS BLOB))),0) AS content_bytes
            FROM manuscripts''').fetchone())
        try:
            page = max(1, int(request.args.get('page', '1')))
        except ValueError:
            return jsonify(error='페이지 번호를 확인해 주세요.'), 400
        query = request.args.get('q', '').strip()[:254]
        term = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        matched = db().execute("SELECT COUNT(*) FROM users WHERE email LIKE ? ESCAPE '\\'", (term,)).fetchone()[0]
        pages = max(1, (matched + 49) // 50)
        page = min(page, pages)
        members = [dict(row) for row in db().execute('''SELECT u.email,md.created AS joined,
            COUNT(m.id) AS manuscripts,
            COALESCE(SUM(length(CAST(m.title AS BLOB))+length(CAST(m.body AS BLOB))),0) AS content_bytes
            FROM users u LEFT JOIN user_metadata md ON md.user_id=u.id
            LEFT JOIN manuscripts m ON m.user_id=u.id
            WHERE u.email LIKE ? ESCAPE '\\'
            GROUP BY u.id,u.email,md.created ORDER BY md.created DESC,u.email ASC LIMIT 50 OFFSET ?''', (term, (page-1)*50)).fetchall()]
        path = Path(database_path).resolve()
        disk = shutil.disk_usage(path.parent)
        database_bytes = sum(p.stat().st_size for p in (path, Path(str(path)+'-wal'), Path(str(path)+'-shm')) if p.is_file())
        return jsonify(summary={**summary, **totals, 'joined_today': summary['joined_today'] or 0,
                               'unknown_join_dates': summary['unknown_join_dates'] or 0},
                       members=members, pagination={'page': page, 'pages': pages, 'matched': matched},
                       storage={'database_bytes': database_bytes, 'disk_total': disk.total,
                                'disk_used': disk.used, 'disk_free': disk.free},
                       checked_at=int(time.time()))
