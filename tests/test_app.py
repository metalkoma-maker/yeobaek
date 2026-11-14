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
        self.assertEqual(r.json['total'],5);self.assertEqual(r.json['today'],5)
        self.assertEqual(r.json['today_count_rule'],'with_spaces')
        second=module.app.test_client(); login=second.post('/api/login',json={'email':'writer-a@example.com','password':'test-password-123'})
        self.assertEqual(second.get(route).json['body'],'가 나\n다😀')
        self.assertEqual(a.put(route,json={'title':'x','body':'old','version':0},headers=ha).status_code,409)
        r=a.put(route,json={'title':'밤','body':'가','version':1},headers=ha)
        self.assertEqual(r.json['today'],1)
        self.assertEqual(a.get(route+'/history').json[0]['characters'],5)
        original=module.day;module.day=lambda:'2099-01-02'
        try:
            self.assertEqual(a.get(route).json['today'],0)
            r=a.put(route,json={'title':'밤','body':'','version':2},headers=ha)
            self.assertEqual(r.json['today'],-1)
        finally:module.day=original
        self.assertEqual(a.post('/api/logout',json={},headers=ha).status_code,200)
        self.assertEqual(a.get(route).status_code,401)

    def test_delete_manuscript_requires_owner_csrf_and_current_version(self):
        owner,headers=self.register('delete-owner@example.com')
        other,other_headers=self.register('delete-other@example.com')
        created=owner.post('/api/manuscripts',json={},headers=headers).json
        route='/api/manuscripts/'+created['id']
        saved=owner.put(route,json={'title':'보관할 원고','body':'첫 문장','version':0},headers=headers).json
        self.assertEqual(owner.post(route+'/checkpoints',json={'version':saved['version'],'label':'중요한 버전'},headers=headers).status_code,200)
        self.assertEqual(other.delete(route,json={'version':saved['version']},headers=other_headers).status_code,404)
        self.assertEqual(owner.delete(route,json={'version':saved['version']}).status_code,403)
        self.assertEqual(owner.delete(route,json={'version':True},headers=headers).status_code,400)
        self.assertEqual(owner.delete(route,json={'version':0},headers=headers).status_code,409)
        self.assertEqual(owner.get(route).status_code,200)
        self.assertEqual(owner.delete(route,json={'version':saved['version']},headers=headers).status_code,200)
        self.assertEqual(owner.get(route).status_code,404)
        self.assertNotIn(created['id'],[item['id'] for item in owner.get('/api/manuscripts').json])
        self.assertEqual(owner.get(route+'/history').status_code,404)
        self.assertEqual(owner.get(route+'/checkpoints').status_code,404)

if __name__=='__main__':unittest.main()
