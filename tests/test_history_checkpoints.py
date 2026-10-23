"""Version recovery with a disposable database and fake manuscripts."""
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from test_app import module


class HistoryCheckpointTest(unittest.TestCase):
    def account(self, label):
        client = module.app.test_client()
        response = client.post('/api/register', json={
            'email': label + '@example.com', 'password': 'test-password-123',
        })
        self.assertEqual(response.status_code, 200)
        return client, {'X-CSRF-Token': response.json['csrf']}

    def create(self, client, headers):
        response = client.post('/api/manuscripts', json={}, headers=headers)
        self.assertEqual(response.status_code, 201)
        return '/api/manuscripts/' + response.json['id']

    def write(self, client, headers, route, version, body):
        response = client.put(route, json={
            'version': version, 'title': '가짜 원고', 'body': body,
        }, headers=headers)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def test_rapid_autosaves_keep_recent_50_and_pinned_versions(self):
        client, headers = self.account('history-rapid')
        route = self.create(client, headers)
        for version in range(70):
            self.write(client, headers, route, version, '글 ' + str(version))
        recent = client.get(route + '/history').json
        self.assertEqual(len(recent), 50)
        self.assertEqual([row['version'] for row in recent], list(range(69, 19, -1)))
        points = client.get(route + '/checkpoints').json
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]['version'], 1)
        pinned = client.post(route + '/checkpoints', json={
            'version': 30, 'label': '1차 초고',
        }, headers=headers)
        self.assertEqual(pinned.status_code, 200)
        for version in range(70, 145):
            self.write(client, headers, route, version, '글 ' + str(version))
        self.assertNotIn(30, [row['version'] for row in client.get(route + '/history').json])
        points = client.get(route + '/checkpoints').json
        self.assertEqual([(row['version'], row['kind']) for row in points], [(30, 'manual'), (1, 'auto')])
        self.assertEqual(client.get(route + '/checkpoints/30').json['body'], '글 29')

    def test_restore_preserves_previous_text_and_rejects_stale_or_foreign_changes(self):
        client, headers = self.account('history-restore')
        other, other_headers = self.account('history-restore-other')
        route = self.create(client, headers)
        first = self.write(client, headers, route, 0, '처음 글')
        self.write(client, headers, route, 1, '바뀐 글')
        checkpoint = client.post(route + '/checkpoints', json={
            'version': 1, 'label': '초고', 'expected_current_version': 2,
        }, headers=headers)
        self.assertEqual(checkpoint.status_code, 200)
        self.assertEqual(other.get(route + '/checkpoints').status_code, 404)
        self.assertEqual(other.get(route + '/checkpoints/1').status_code, 404)
        self.assertEqual(other.post(route + '/restore', json={
            'version': 2, 'source_version': 1,
        }, headers=other_headers).status_code, 404)
        self.assertEqual(client.post(route + '/restore', json={
            'version': 2, 'source_version': 1,
        }).status_code, 403)
        self.assertEqual(client.post(route + '/restore', json={
            'version': 2, 'source_version': 1,
        }, headers={**headers, 'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(client.post(route + '/restore', json={
            'version': 1, 'source_version': 1,
        }, headers=headers).status_code, 409)
        self.assertEqual(client.get(route).json['body'], '바뀐 글')
        restored = client.post(route + '/restore', json={
            'version': 2, 'source_version': 1,
        }, headers=headers)
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json['body'], first['body'])
        self.assertEqual(restored.json['version'], 3)
        self.assertEqual(client.get(route + '/checkpoints/2').json['body'], '바뀐 글')
        self.assertEqual(client.get(route + '/checkpoints/2').json['kind'], 'before_restore')
        self.assertEqual(client.get(route + '/checkpoints/1').json['label'], '초고')
        self.assertEqual(client.post(route + '/checkpoints', json={
            'version': 3, 'expected_current_version': 2,
        }, headers=headers).status_code, 409)

    def test_existing_history_stays_in_recent_list_without_creating_legacy_points(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'old.sqlite3')
            connection = sqlite3.connect(path)
            connection.executescript('''
                CREATE TABLE users(id TEXT PRIMARY KEY,email TEXT NOT NULL,password TEXT NOT NULL);
                CREATE TABLE manuscripts(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL DEFAULT '',version INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL);
                CREATE TABLE manuscript_history(manuscript_id TEXT NOT NULL,version INTEGER NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,updated INTEGER NOT NULL,PRIMARY KEY(manuscript_id,version));
                CREATE TABLE daily(manuscript_id TEXT NOT NULL,day TEXT NOT NULL,delta INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(manuscript_id,day));
                INSERT INTO users VALUES('u','fake@example.com','fake');
                INSERT INTO manuscripts VALUES('m','u','현재','현재 글',2,300);
                INSERT INTO manuscript_history VALUES('m',1,'옛 제목','옛 글',200);
            ''')
            connection.execute('INSERT INTO daily VALUES(?,?,?)',('m',module.day(),7))
            connection.commit()
            connection.close()
            old_path = module.DB
            try:
                module.DB = path
                module.init()
                module.init()
                with module.app.app_context():
                    self.assertTrue(module.legacy_count_day())
                with sqlite3.connect(path) as connection:
                    point = connection.execute("SELECT kind,label,body FROM manuscript_checkpoints WHERE manuscript_id='m'").fetchall()
                    original = connection.execute("SELECT body FROM manuscript_history WHERE manuscript_id='m'").fetchall()
                    self.assertEqual(point, [])
                    self.assertEqual(original, [('옛 글',)])
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0], 2)
                    self.assertEqual(connection.execute('SELECT delta FROM daily').fetchone()[0], 7)
                with module.app.app_context():
                    current=module.db().execute("SELECT * FROM manuscripts WHERE id='m'").fetchone()
                    module.save_manuscript('m',current,'현재','현재 글 한 칸',int(module.time.time()))
                    module.db().commit()
                    self.assertEqual(module.db().execute("SELECT delta FROM daily WHERE manuscript_id='m'").fetchone()[0],9)
            finally:
                module.DB = old_path

    def test_previously_imported_points_are_hidden_but_not_deleted(self):
        client, headers = self.account('history-legacy-hidden')
        route = self.create(client, headers)
        self.write(client, headers, route, 0, '현재 글')
        mid = route.split('/')[-1]
        with module.app.app_context():
            module.db().execute('INSERT INTO manuscript_checkpoints VALUES(?,?,?,?,?,?,?,?)',
                                (mid, 99, '가짜 이전 제목', '가짜 이전 글', 1, 1, 'legacy', '기존 수정 이력'))
            module.db().commit()
        self.assertEqual(client.get(route + '/checkpoints').json, [])
        self.assertEqual(client.get(route + '/checkpoints/99').status_code, 404)
        self.assertEqual(client.post(route + '/checkpoints', json={'version': 99, 'label': '가짜'}, headers=headers).status_code, 404)
        self.assertEqual(client.post(route + '/restore', json={'version': 1, 'source_version': 99}, headers=headers).status_code, 404)
        self.assertEqual(client.get(route + '/history').json[0]['version'], 0)
        with module.app.app_context():
            self.assertEqual(module.db().execute('SELECT body FROM manuscript_checkpoints WHERE manuscript_id=? AND version=99',
                                                 (mid,)).fetchone()[0], '가짜 이전 글')

    def test_automatic_point_after_pause_and_explicit_point_survives_cleanup(self):
        client, headers = self.account('history-pause')
        route = self.create(client, headers)
        start = int(module.time.time())
        with patch.object(module.time, 'time', return_value=start):
            self.write(client, headers, route, 0, '첫 문장')
            self.write(client, headers, route, 1, '둘째 문장')
        with patch.object(module.time, 'time', return_value=start + 1900):
            self.write(client, headers, route, 2, '나중 문장')
        versions = [row['version'] for row in client.get(route + '/checkpoints').json]
        self.assertEqual(versions, [2, 1])
        client.post(route + '/checkpoints', json={'version': 1, 'label': '중요'}, headers=headers)
        with module.app.app_context():
            module.prune_checkpoints(route.split('/')[-1], start + 400 * 86400)
            module.db().commit()
        points = client.get(route + '/checkpoints').json
        self.assertEqual([(row['version'], row['kind']) for row in points], [(2, 'auto'), (1, 'manual')])

    def test_session_checkpoint_is_idempotent_private_and_keeps_recent_fifty(self):
        client, headers = self.account('history-session')
        foreign, foreign_headers = self.account('history-session-foreign')
        route = self.create(client, headers)
        self.write(client, headers, route, 0, '저장된 글')
        path = route + '/session-checkpoint'
        self.assertEqual(client.post(path, json={'version': 1}).status_code, 403)
        self.assertEqual(foreign.post(path, json={'version': 1}, headers=foreign_headers).status_code, 404)
        self.assertEqual(client.post(path, json={'version': True}, headers=headers).status_code, 400)
        self.assertEqual(client.post(path, json={'version': 0}, headers=headers).status_code, 409)
        for _ in range(2):
            point = client.post(path, json={'version': 1}, headers=headers)
            self.assertEqual(point.status_code, 200)
        points = client.get(route + '/checkpoints').json
        self.assertEqual([row['version'] for row in points], [1])
        self.assertEqual(client.get(route + '/checkpoints/1').json['body'], '저장된 글')
        self.assertEqual([row['version'] for row in client.get(route + '/history').json], [0])

    def test_resume_after_ten_minute_pause_creates_point_before_next_edit(self):
        client, headers = self.account('history-resume')
        route = self.create(client, headers)
        start = int(module.time.time())
        with patch.object(module.time, 'time', return_value=start):
            self.write(client, headers, route, 0, '첫 문장')
            self.write(client, headers, route, 1, '쉬기 전 글')
        with patch.object(module.time, 'time', return_value=start + module.RESUME_INTERVAL + 1):
            self.write(client, headers, route, 2, '다시 쓴 글')
        self.assertEqual(client.get(route + '/checkpoints/2').json['body'], '쉬기 전 글')

    def test_continuous_writing_creates_a_point_after_about_thirty_minutes(self):
        client, headers = self.account('history-continuous')
        route = self.create(client, headers)
        start = int(module.time.time())
        for minute in range(32):
            with patch.object(module.time, 'time', return_value=start + minute * 60):
                self.write(client, headers, route, minute, '글 ' + str(minute))
        versions = [row['version'] for row in client.get(route + '/checkpoints').json]
        self.assertEqual(versions, [31, 1])

    def test_automatic_cleanup_keeps_daily_and_monthly_recovery_points(self):
        client, headers = self.account('history-retention')
        route = self.create(client, headers)
        mid = route.split('/')[-1]
        now = int(module.time.time())
        with module.app.app_context():
            for age in range(45):
                written = now - age * 86400
                module.db().execute('INSERT INTO manuscript_checkpoints VALUES(?,?,?,?,?,?,?,?)',
                                    (mid, age + 1, '가짜 제목', '가짜 글', written, written, 'auto', ''))
            module.db().execute('INSERT INTO manuscript_checkpoints VALUES(?,?,?,?,?,?,?,?)',
                                (mid, 99, '중요', '보존 글', now - 500 * 86400, now, 'manual', '오래된 초고'))
            module.prune_checkpoints(mid, now)
            module.db().commit()
        points = client.get(route + '/checkpoints').json
        kept = {row['version'] for row in points if row['kind'] == 'auto'}
        self.assertTrue(set(range(1, 30)).issubset(kept))
        self.assertLessEqual(len(kept), 33)
        self.assertEqual([row['version'] for row in points if row['kind'] == 'manual'], [99])


if __name__ == '__main__':
    unittest.main()
