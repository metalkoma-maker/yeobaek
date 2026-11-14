"""Native cookie/CSRF and same-account browser contract on synthetic temporary DB."""
import unittest
from test_app import module


class MobileContractTest(unittest.TestCase):
    def test_native_cookie_shared_manuscripts_conflicts_history(self):
        web = module.app.test_client()
        signup = web.post('/api/register', json={'email': 'mobile-contract@example.com', 'password': 'test-password-123'})
        wh = {'X-CSRF-Token': signup.json['csrf']}
        mobile = module.app.test_client()
        login = mobile.post('/api/login', json={'email': 'mobile-contract@example.com', 'password': 'test-password-123'})
        self.assertIn('HttpOnly', login.headers['Set-Cookie'])
        mh = {'X-CSRF-Token': login.json['csrf']}
        self.assertEqual(mobile.get('/api/me').json['email'], signup.json['email'])
        created = mobile.post('/api/manuscripts', json={}, headers=mh).json
        route = '/api/manuscripts/' + created['id']
        self.assertEqual(web.get('/api/manuscripts').json[0]['id'], created['id'])
        a = web.put(route, headers=wh, json={'title': '웹 테스트', 'body': '가나다', 'version': 0}).json
        conflict = mobile.put(route, headers=mh, json={'title': '앱 테스트', 'body': '내 글', 'version': 0})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json['current']['body'], '가나다')
        self.assertEqual(web.get(route).json['body'], '가나다')
        self.assertEqual(mobile.put(route, json={'title': 'x', 'body': 'x', 'version': 1}).status_code, 403)
        self.assertEqual(mobile.put(route, headers={**mh, 'Origin': 'https://other.example'}, json={'title': 'x', 'body': 'x', 'version': 1}).status_code, 403)
        # Reading and comparing recovery B alone makes no changes.
        self.assertEqual(mobile.get(route).json['version'], 1)
        restored = mobile.put(route, headers=mh, json={'title': '앱 테스트', 'body': '내 글', 'version': a['version']})
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(web.get(route).json['body'], '내 글')
        self.assertEqual(mobile.get(route + '/history/1').json['body'], '가나다')
        for _ in range(55):
            latest = mobile.get(route).json
            self.assertEqual(mobile.put(route, headers=mh, json={'title': '가짜', 'body': str(latest['version']), 'version': latest['version']}).status_code, 200)
        self.assertEqual(len(mobile.get(route + '/history').json), 50)
        self.assertEqual(mobile.post('/api/logout', headers=mh, json={}).status_code, 200)
        self.assertEqual(mobile.get(route).status_code, 401)
        self.assertEqual(web.get(route).status_code, 200)
