"""Recent manuscripts and account-scoped pins use the temporary fake database."""
import json
import unittest
from test_app import module


class ManuscriptOrderTest(unittest.TestCase):
    def account(self, label):
        client = module.app.test_client()
        response = client.post('/api/register', json={
            'email': label + '@example.com', 'password': 'test-password-123'})
        self.assertEqual(response.status_code, 200)
        return client, {'X-CSRF-Token': response.json['csrf']}

    def create(self, client, headers):
        response = client.post('/api/manuscripts', json={}, headers=headers)
        self.assertEqual(response.status_code, 201)
        return response.json['id']

    def ids(self, client):
        return [row['id'] for row in client.get('/api/manuscripts').json]

    def test_recent_save_wins_over_stored_manual_order(self):
        client, headers = self.account('recent-order')
        first, second, third = [self.create(client, headers) for _ in range(3)]
        with module.app.app_context():
            db = module.db()
            db.execute('UPDATE manuscripts SET updated=100 WHERE id=?', (first,))
            db.execute('UPDATE manuscripts SET updated=200 WHERE id=?', (second,))
            db.execute('UPDATE manuscripts SET updated=300 WHERE id=?', (third,))
            db.execute('INSERT INTO manuscript_order VALUES(?,?,?)', (
                db.execute('SELECT user_id FROM manuscripts WHERE id=?', (first,)).fetchone()[0],
                json.dumps([first, second, third]), 7))
            db.commit()
        self.assertEqual(self.ids(client), [third, second, first])
        old = client.get('/api/manuscript-order').json
        self.assertEqual(old['ids'], [third, second, first])
        self.assertEqual(client.put('/api/manuscript-order', json=old, headers=headers).status_code, 409)
        saved = client.put('/api/manuscripts/' + first, json={
            'title': '최근에 쓴 원고', 'body': '가짜 글', 'version': 0}, headers=headers)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.ids(client), [first, third, second])
        with module.app.app_context():
            self.assertEqual(module.db().execute('''SELECT version FROM manuscript_order
                WHERE user_id=(SELECT user_id FROM manuscripts WHERE id=?)''',(first,)).fetchone()[0], 7)

    def test_pins_stay_in_pin_sequence_even_after_writing(self):
        client, headers = self.account('pin-order')
        first, second, third = [self.create(client, headers) for _ in range(3)]
        with module.app.app_context():
            db = module.db()
            for id, updated in [(first, 100), (second, 200), (third, 300)]:
                db.execute('UPDATE manuscripts SET updated=? WHERE id=?', (updated, id))
            db.commit()
        self.assertEqual(self.ids(client), [third, second, first])
        for id in (second, first, second):
            response = client.put('/api/manuscripts/' + id + '/pin', json={'pinned': True}, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json['pinned'])
        self.assertEqual(self.ids(client), [second, first, third])
        saved = client.put('/api/manuscripts/' + first, json={
            'title': '고정된 글', 'body': '가짜 수정', 'version': 0}, headers=headers)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.ids(client), [second, first, third])
        module.init()
        self.assertEqual(self.ids(client), [second, first, third])
        response = client.put('/api/manuscripts/' + second + '/pin', json={'pinned': False}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['pinned'])
        self.assertEqual(self.ids(client), [first, third, second])
        self.assertEqual(client.get('/api/manuscripts/' + second).json['pinned'], False)

    def test_pin_requires_owner_csrf_and_boolean(self):
        owner, headers = self.account('pin-owner')
        stranger, other_headers = self.account('pin-stranger')
        own = self.create(owner, headers)
        foreign = self.create(stranger, other_headers)
        path = '/api/manuscripts/' + own + '/pin'
        self.assertEqual(module.app.test_client().put(path, json={'pinned': True}).status_code, 401)
        self.assertEqual(owner.put(path, json={'pinned': True}).status_code, 403)
        self.assertEqual(owner.put(path, json={'pinned': True}, headers=other_headers).status_code, 403)
        self.assertEqual(owner.put('/api/manuscripts/' + foreign + '/pin',
                                   json={'pinned': True}, headers=headers).status_code, 404)
        for payload in ({}, {'pinned': 1}, {'pinned': 'true'}, []):
            with self.subTest(payload=payload):
                self.assertEqual(owner.put(path, json=payload, headers=headers).status_code, 400)
        self.assertFalse(owner.get('/api/manuscripts/' + own).json['pinned'])
        self.assertFalse(stranger.get('/api/manuscripts/' + foreign).json['pinned'])
