"""Account-scoped manual order; every test uses test_app's temporary fake DB."""
import unittest
from test_app import module


class ManuscriptOrderTest(unittest.TestCase):
    def test_public_deployment_marker_identifies_backend_without_user_data(self):
        response=module.app.test_client().get('/__deployment_health__')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json,{'api':'history-account-v1'})

    def account(self, label):
        client=module.app.test_client()
        email=label+'@example.com'
        response=client.post('/api/register',json={'email':email,'password':'test-password-123'})
        self.assertEqual(response.status_code,200)
        return client,{'X-CSRF-Token':response.json['csrf']},email

    def create(self, client, headers):
        response=client.post('/api/manuscripts',json={},headers=headers)
        self.assertEqual(response.status_code,201)
        return response.json['id']

    def test_order_sync_does_not_edit_manuscripts_history_or_statistics(self):
        a,ha,email=self.account('order-sync')
        ids=[self.create(a,ha) for _ in range(3)]
        route='/api/manuscripts/'+ids[0]
        a.put(route,json={'title':'가짜 원고','body':'가 나 다','version':0},headers=ha)
        before=[a.get('/api/manuscripts/'+mid).json for mid in ids]
        history=a.get(route+'/history').json
        state=a.get('/api/manuscript-order').json
        desired=list(reversed(state['ids']))
        response=a.put('/api/manuscript-order',json={'ids':desired,'version':state['version']},headers=ha)
        self.assertEqual(response.status_code,200)
        b=module.app.test_client()
        b.post('/api/login',json={'email':email,'password':'test-password-123'})
        self.assertEqual([row['id'] for row in b.get('/api/manuscripts').json],desired)
        self.assertEqual(b.get('/api/manuscript-order').json,response.json)
        self.assertEqual([a.get('/api/manuscripts/'+mid).json for mid in ids],before)
        self.assertEqual(a.get(route+'/history').json,history)
        # Editing a manually placed manuscript does not move it back to the top.
        a.put(route,json={'title':'수정','body':'가나다라','version':1},headers=ha)
        self.assertEqual([row['id'] for row in b.get('/api/manuscripts').json],desired)

    def test_private_authenticated_order_requires_csrf_and_valid_own_ids(self):
        a,ha,_=self.account('order-private-a')
        b,hb,_=self.account('order-private-b')
        own=self.create(a,ha); foreign=self.create(b,hb)
        state=a.get('/api/manuscript-order').json
        payload={'ids':[own],'version':state['version']}
        self.assertEqual(module.app.test_client().get('/api/manuscript-order').status_code,401)
        self.assertEqual(a.put('/api/manuscript-order',json=payload).status_code,403)
        self.assertEqual(a.put('/api/manuscript-order',json=payload,headers=hb).status_code,403)
        self.assertEqual(a.put('/api/manuscript-order',json=payload,headers={**ha,'Origin':'https://foreign.example.test'}).status_code,403)
        for malformed in ([],{'ids':'bad','version':0},{'ids':[own,own],'version':0},
                          {'ids':[own],'version':True},{'ids':[own],'version':-1},
                          {'ids':[None],'version':0}):
            with self.subTest(payload=malformed):
                self.assertEqual(a.put('/api/manuscript-order',json=malformed,headers=ha).status_code,400)
        denied=a.put('/api/manuscript-order',json={'ids':[foreign],'version':0},headers=ha)
        self.assertEqual(denied.status_code,409)
        self.assertEqual(denied.json['current']['ids'],[own])
        self.assertEqual(b.get('/api/manuscript-order').json['ids'],[foreign])
        self.assertEqual(a.get('/api/manuscript-order').json,state)

    def test_stale_order_is_rejected_without_overwriting_other_device(self):
        a,ha,_=self.account('order-conflict')
        for _ in range(3): self.create(a,ha)
        old=a.get('/api/manuscript-order').json
        desired=list(reversed(old['ids']))
        first=a.put('/api/manuscript-order',json={'ids':desired,'version':old['version']},headers=ha)
        self.assertEqual(first.status_code,200)
        stale=a.put('/api/manuscript-order',json={'ids':old['ids'],'version':old['version']},headers=ha)
        self.assertEqual(stale.status_code,409)
        self.assertEqual(stale.json['current'],first.json)
        self.assertEqual(a.get('/api/manuscript-order').json,first.json)
        unchanged=a.put('/api/manuscript-order',json=first.json,headers=ha)
        self.assertEqual(unchanged.json,first.json)

    def test_new_manuscript_is_first_and_invalidates_an_incomplete_order(self):
        a,ha,_=self.account('order-new')
        for _ in range(2): self.create(a,ha)
        old=a.get('/api/manuscript-order').json
        desired=list(reversed(old['ids']))
        stored=a.put('/api/manuscript-order',json={'ids':desired,'version':old['version']},headers=ha).json
        new=self.create(a,ha)
        self.assertEqual([row['id'] for row in a.get('/api/manuscripts').json],[new,*desired])
        stale=a.put('/api/manuscript-order',json=stored,headers=ha)
        self.assertEqual(stale.status_code,409)
        self.assertEqual(stale.json['current']['ids'],[new,*desired])
        # Additive initialization can run again without losing preferences or text.
        module.init()
        self.assertEqual(a.get('/api/manuscript-order').json,stale.json['current'])
