"""Copy editing rounds using only the disposable fake database."""
import unittest
from test_app import module


class ManuscriptCopyTest(unittest.TestCase):
    def account(self, name):
        client=module.app.test_client()
        response=client.post('/api/register',json={'email':name+'@example.com','password':'test-password-123'})
        self.assertEqual(response.status_code,200)
        return client,{'X-CSRF-Token':response.json['csrf']}

    def test_second_and_third_rounds_preserve_original_and_start_new_statistics(self):
        client,headers=self.account('copy-rounds')
        original=client.post('/api/manuscripts',json={},headers=headers).json
        path='/api/manuscripts/'+original['id']
        saved=client.put(path,json={'title':'달빛','body':'첫 문장\n다음 문장','version':0},headers=headers).json
        second=client.post(path+'/copy',json={'version':saved['version']},headers=headers)
        self.assertEqual(second.status_code,201)
        self.assertEqual(second.json['title'],'달빛 · 2교')
        self.assertEqual(second.json['body'],saved['body'])
        self.assertEqual(second.json['version'],0)
        self.assertEqual(second.json['total'],saved['total'])
        self.assertEqual(second.json['today'],0)
        self.assertEqual(client.get('/api/manuscripts/'+second.json['id']+'/history').json,[])
        third=client.post(path+'/copy',json={'version':saved['version']},headers=headers)
        self.assertEqual(third.json['title'],'달빛 · 3교')
        fourth=client.post('/api/manuscripts/'+third.json['id']+'/copy',json={'version':0},headers=headers)
        self.assertEqual(fourth.json['title'],'달빛 · 4교')
        self.assertEqual(client.get(path).json,saved)
        other_device=module.app.test_client()
        other_device.post('/api/login',json={'email':'copy-rounds@example.com','password':'test-password-123'})
        self.assertEqual([d['id'] for d in other_device.get('/api/manuscripts').json[:3]],
                         [fourth.json['id'],third.json['id'],second.json['id']])

    def test_copy_checks_account_csrf_source_version_and_title(self):
        client,headers=self.account('copy-private')
        foreign,foreign_headers=self.account('copy-foreign')
        source=client.post('/api/manuscripts',json={},headers=headers).json
        path='/api/manuscripts/'+source['id']+'/copy'
        self.assertEqual(module.app.test_client().post(path,json={'version':0}).status_code,401)
        self.assertEqual(foreign.post(path,json={'version':0},headers=foreign_headers).status_code,404)
        self.assertEqual(client.post(path,json={'version':0}).status_code,403)
        self.assertEqual(client.post(path,json={'version':0},headers={**headers,'Origin':'https://foreign.example'}).status_code,403)
        for payload in ({'version':True},{'version':-1},{'version':0,'title':''},
                        {'version':0,'title':'x'*201},{'version':0,'title':123}):
            with self.subTest(payload=payload):
                self.assertEqual(client.post(path,json=payload,headers=headers).status_code,400)
        client.put('/api/manuscripts/'+source['id'],json={'version':0,'title':'새 제목','body':'최신 글'},headers=headers)
        self.assertEqual(client.post(path,json={'version':0},headers=headers).status_code,409)
        self.assertEqual(len(client.get('/api/manuscripts').json),1)
        custom=client.post(path,json={'version':1,'title':'내가 정한 2교'},headers=headers)
        self.assertEqual(custom.status_code,201)
        self.assertEqual(custom.json['title'],'내가 정한 2교')

    def test_long_original_title_keeps_incrementing_round_number(self):
        client,headers=self.account('copy-long-title')
        source=client.post('/api/manuscripts',json={},headers=headers).json
        title='가'*200
        client.put('/api/manuscripts/'+source['id'],json={'version':0,'title':title,'body':'초고'},headers=headers)
        path='/api/manuscripts/'+source['id']+'/copy'
        second=client.post(path,json={'version':1},headers=headers).json
        third=client.post(path,json={'version':1},headers=headers).json
        self.assertEqual(second['title'],title[:195]+' · 2교')
        self.assertEqual(third['title'],title[:195]+' · 3교')


if __name__=='__main__': unittest.main()
