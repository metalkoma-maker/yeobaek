"""Account recovery and deletion use only the disposable test database."""
import re
import unittest
from unittest.mock import patch
from test_app import module

MAIL_ENV={"SMTP_HOST":"mail.example.test","SMTP_FROM":"hello@example.test","APP_PUBLIC_URL":"https://novel.example.test","SMTP_USERNAME":"","SMTP_PASSWORD":""}


class AccountTest(unittest.TestCase):
    def account(self, name, ip):
        client=module.app.test_client()
        client.environ_base['REMOTE_ADDR']=ip
        email=name+'@example.com'
        result=client.post('/api/register',json={'email':email,'password':'old-password-123'})
        self.assertEqual(result.status_code,200)
        return client,email,{'X-CSRF-Token':result.json['csrf']}

    def test_recovery_mail_is_configured_and_does_not_reveal_registration(self):
        client,email,_=self.account('mail-account','198.51.100.21')
        with patch.dict('os.environ',{'SMTP_HOST':'','SMTP_FROM':'','APP_PUBLIC_URL':''}):
            self.assertEqual(client.post('/api/account/recover-id',json={'email':email}).status_code,503)
        with patch.dict('os.environ',MAIL_ENV), patch.object(module,'send_account_mail') as send:
            known=client.post('/api/account/recover-id',json={'email':email})
            unknown=client.post('/api/account/recover-id',json={'email':'missing@example.test'})
            self.assertEqual(known.status_code,200)
            self.assertEqual(known.json,unknown.json)
            self.assertEqual(send.call_count,2)
            self.assertIn(email,send.call_args_list[0].args[2])
            self.assertEqual(client.post('/api/account/recover-id',json={'email':'bad'}).status_code,400)

    def test_reset_link_is_single_use_expires_and_revokes_sessions(self):
        client,email,_=self.account('reset-account','198.51.100.22')
        second=module.app.test_client()
        self.assertEqual(second.post('/api/login',json={'email':email,'password':'old-password-123'}).status_code,200)
        with patch.dict('os.environ',MAIL_ENV), patch.object(module,'send_account_mail') as send:
            result=client.post('/api/password-reset/request',json={'email':email})
        self.assertEqual(result.status_code,200)
        token=re.search(r'#reset=([A-Za-z0-9_-]{43})',send.call_args.args[2]).group(1)
        with module.app.app_context():
            row=module.db().execute('SELECT token_hash FROM password_resets WHERE user_id=(SELECT id FROM users WHERE email=?)',(email,)).fetchone()
            self.assertIsNotNone(row)
            self.assertNotEqual(row['token_hash'],token)
        path='/api/password-reset/confirm'
        self.assertEqual(client.post(path,json={'token':token,'new_password':'short'}).status_code,400)
        self.assertEqual(client.post(path,json={'token':token,'new_password':'new-password-123'}).status_code,200)
        self.assertEqual(client.post(path,json={'token':token,'new_password':'third-password-123'}).status_code,400)
        self.assertEqual(second.get('/api/me').status_code,401)
        self.assertEqual(client.post('/api/login',json={'email':email,'password':'old-password-123'}).status_code,401)
        self.assertEqual(client.post('/api/login',json={'email':email,'password':'new-password-123'}).status_code,200)
        with patch.dict('os.environ',MAIL_ENV), patch.object(module,'send_account_mail') as send:
            client.post('/api/password-reset/request',json={'email':email})
        expired=re.search(r'#reset=([A-Za-z0-9_-]{43})',send.call_args.args[2]).group(1)
        with module.app.app_context():
            module.db().execute('UPDATE password_resets SET expires=0 WHERE user_id=(SELECT id FROM users WHERE email=?)',(email,))
            module.db().commit()
        self.assertEqual(client.post(path,json={'token':expired,'new_password':'next-password-123'}).status_code,400)

    def test_failed_mail_does_not_leave_live_reset_link_and_requests_are_limited(self):
        client,email,_=self.account('mail-failure','198.51.100.25')
        with patch.dict('os.environ',MAIL_ENV), patch.object(module,'send_account_mail',side_effect=RuntimeError('fake smtp failure')):
            with patch.object(module.app.logger,'exception'):
                self.assertEqual(client.post('/api/password-reset/request',json={'email':email}).status_code,503)
        with module.app.app_context():
            uid=module.db().execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()['id']
            self.assertEqual(module.db().execute('SELECT count(*) FROM password_resets WHERE user_id=?',(uid,)).fetchone()[0],0)
        with patch.dict('os.environ',MAIL_ENV), patch.object(module,'send_account_mail'):
            for _ in range(4): self.assertEqual(client.post('/api/account/recover-id',json={'email':email}).status_code,200)
            self.assertEqual(client.post('/api/account/recover-id',json={'email':email}).status_code,429)

    def test_change_password_requires_current_password_and_revokes_other_devices(self):
        client,email,headers=self.account('change-account','198.51.100.23')
        second=module.app.test_client()
        second.post('/api/login',json={'email':email,'password':'old-password-123'})
        path='/api/account/password'
        self.assertEqual(client.post(path,json={'current_password':'wrong-password-123','new_password':'new-password-123'},headers=headers).status_code,403)
        self.assertEqual(client.post(path,json={'current_password':'old-password-123','new_password':'new-password-123'}).status_code,403)
        changed=client.post(path,json={'current_password':'old-password-123','new_password':'new-password-123'},headers=headers)
        self.assertEqual(changed.status_code,200)
        self.assertNotEqual(changed.json['csrf'],headers['X-CSRF-Token'])
        self.assertEqual(second.get('/api/me').status_code,401)
        self.assertEqual(client.get('/api/me').status_code,200)
        self.assertEqual(client.post('/api/login',json={'email':email,'password':'old-password-123'}).status_code,401)

    def test_delete_cascades_manuscripts_history_drafts_and_sessions(self):
        client,email,headers=self.account('delete-account','198.51.100.24')
        doc=client.post('/api/manuscripts',json={},headers=headers).json
        path='/api/manuscripts/'+doc['id']
        client.put(path,json={'title':'초고','body':'지울 글','version':0},headers=headers)
        self.assertEqual(client.post(path+'/checkpoints',json={'version':1,'label':'삭제 확인용'},headers=headers).status_code,200)
        self.assertEqual(client.put('/api/manuscript-order',json={'ids':[doc['id']],'version':0},headers=headers).status_code,200)
        with module.app.app_context():
            uid=module.db().execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()['id']
            module.db().execute('INSERT INTO password_resets VALUES(?,?,?)',('f'*64,uid,9999999999))
            module.db().commit()
        second=module.app.test_client()
        second.post('/api/login',json={'email':email,'password':'old-password-123'})
        target='/api/account/delete'
        self.assertEqual(client.post(target,json={'password':'old-password-123','confirmation':'x'},headers=headers).status_code,400)
        self.assertEqual(client.post(target,json={'password':'wrong-password-123','confirmation':'탈퇴'},headers=headers).status_code,403)
        self.assertEqual(client.post(target,json={'password':'old-password-123','confirmation':'탈퇴'}).status_code,403)
        with patch.object(module.app,'is_admin',return_value=True):
            self.assertEqual(client.post(target,json={'password':'old-password-123','confirmation':'탈퇴'},headers=headers).status_code,403)
        self.assertEqual(client.get(path).status_code,200)
        result=client.post(target,json={'password':'old-password-123','confirmation':'탈퇴'},headers=headers)
        self.assertEqual(result.status_code,200)
        self.assertEqual(second.get('/api/me').status_code,401)
        with module.app.app_context():
            for table in ('users','sessions','manuscripts','manuscript_order','user_metadata','password_resets'):
                column='id' if table=='users' else 'user_id'
                self.assertEqual(module.db().execute(f'SELECT count(*) FROM {table} WHERE {column}=?',(uid,)).fetchone()[0],0,table)
            for table in ('manuscript_history','manuscript_checkpoints','daily'):
                self.assertEqual(module.db().execute(f'SELECT count(*) FROM {table} WHERE manuscript_id=?',(doc['id'],)).fetchone()[0],0,table)


if __name__=='__main__': unittest.main()
