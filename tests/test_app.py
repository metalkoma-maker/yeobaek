import os, tempfile, unittest, sys
os.environ['DATABASE_PATH']=tempfile.mktemp(suffix='.sqlite3')
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
import app as module

class AppTest(unittest.TestCase):
    def register(self,email):
        c=module.app.test_client(); r=c.post('/api/register',json={'email':email,'password':'test-password-123'})
        self.assertEqual(r.status_code,200); return c,{'X-CSRF-Token':r.json['csrf']}
    def test_writing_sync_privacy_conflict(self):
        a,ha=self.register('writer-a@example.com'); b,hb=self.register('writer-b@example.com')
        d=a.post('/api/manuscripts',json={},headers=ha).json
        self.assertEqual(b.get('/api/manuscripts/'+d['id']).status_code,404)
        self.assertEqual(b.put('/api/manuscripts/'+d['id'],json={'title':'x','body':'x','version':0},headers=hb).status_code,404)
        self.assertEqual(a.put('/api/manuscripts/'+d['id'],json={'title':'x','body':'x','version':0}).status_code,403)
        route='/api/manuscripts/'+d['id']
        r=a.put(route,json={'title':'밤의 이야기','body':'가 나\n다😀','version':0},headers=ha)
        self.assertEqual(r.json['total'],4);self.assertEqual(r.json['today'],4)
        second=module.app.test_client(); login=second.post('/api/login',json={'email':'writer-a@example.com','password':'test-password-123'})
        self.assertEqual(second.get(route).json['body'],'가 나\n다😀')
        self.assertEqual(a.put(route,json={'title':'x','body':'old','version':0},headers=ha).status_code,409)
        r=a.put(route,json={'title':'밤','body':'가','version':1},headers=ha)
        self.assertEqual(r.json['today'],1)
        original=module.day;module.day=lambda:'2099-01-02'
        try:
            self.assertEqual(a.get(route).json['today'],0)
            r=a.put(route,json={'title':'밤','body':'','version':2},headers=ha)
            self.assertEqual(r.json['today'],-1)
        finally:module.day=original
        self.assertEqual(a.post('/api/logout',json={},headers=ha).status_code,200)
        self.assertEqual(a.get(route).status_code,401)

if __name__=='__main__':unittest.main()
