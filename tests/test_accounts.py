"""Account recovery and deletion use only the disposable test database."""
import json
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
            self.assertEqual(client.get('/api/password-reset/availability').json,{'available':False})
            self.assertEqual(client.post('/api/account/recover-id',json={'email':email}).status_code,503)
        with patch.dict('os.environ',MAIL_ENV), patch.object(module,'send_account_mail') as send:
            self.assertEqual(client.get('/api/password-reset/availability').json,{'available':True})
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
            module.db().execute('INSERT OR IGNORE INTO withdrawal_state(epoch) VALUES(?)',('a'*32,))
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
        with patch.object(module,'upload_withdrawal_receipt') as upload:
            result=client.post(target,json={'password':'old-password-123','confirmation':'탈퇴'},headers=headers)
            self.assertEqual(upload.call_count,1)
            self.assertEqual(upload.call_args.args[:2],('a'*32,uid))
        self.assertEqual(result.status_code,200)
        self.assertEqual(second.get('/api/me').status_code,401)
        with module.app.app_context():
            for table in ('users','sessions','manuscripts','manuscript_order','user_metadata','password_resets'):
                column='id' if table=='users' else 'user_id'
                self.assertEqual(module.db().execute(f'SELECT count(*) FROM {table} WHERE {column}=?',(uid,)).fetchone()[0],0,table)
            for table in ('manuscript_history','manuscript_checkpoints','daily'):
                self.assertEqual(module.db().execute(f'SELECT count(*) FROM {table} WHERE manuscript_id=?',(doc['id'],)).fetchone()[0],0,table)
            self.assertEqual(module.db().execute('SELECT remote_confirmed FROM withdrawal_requests WHERE user_id=?',(uid,)).fetchone()[0],1)

    def test_failed_offsite_receipt_keeps_account_pending_until_retry(self):
        client,email,headers=self.account('delete-retry','198.51.100.26')
        with module.app.app_context():
            uid=module.db().execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()['id']
            module.db().execute('INSERT OR IGNORE INTO withdrawal_state(epoch) VALUES(?)',('a'*32,))
            module.db().commit()
        target='/api/account/delete'; data={'password':'old-password-123','confirmation':'탈퇴'}
        with patch.object(module,'upload_withdrawal_receipt',side_effect=RuntimeError('synthetic remote outage')):
            with patch.object(module.app.logger,'exception'):
                self.assertEqual(client.post(target,json=data,headers=headers).status_code,503)
        self.assertEqual(client.post('/api/manuscripts',json={},headers=headers).status_code,423)
        with module.app.app_context():
            self.assertIsNotNone(module.db().execute('SELECT id FROM users WHERE id=?',(uid,)).fetchone())
            self.assertEqual(module.db().execute('SELECT remote_confirmed FROM withdrawal_requests WHERE user_id=?',(uid,)).fetchone()[0],0)
            with self.assertRaises(sqlite3.IntegrityError):
                module.db().execute('DELETE FROM users WHERE id=?',(uid,))
            module.db().rollback()
        with patch.object(module,'upload_withdrawal_receipt'):
            self.assertEqual(client.post(target,json=data,headers=headers).status_code,200)
        with module.app.app_context():
            self.assertIsNone(module.db().execute('SELECT id FROM users WHERE id=?',(uid,)).fetchone())

    def test_remote_receipt_removes_resurrected_account_before_serving(self):
        client,email,headers=self.account('restore-resurrection','198.51.100.27')
        doc=client.post('/api/manuscripts',json={},headers=headers).json
        with module.app.app_context():
            uid=module.db().execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()['id']
            confirmed={row['user_id'] for row in module.db().execute('SELECT user_id FROM withdrawal_requests WHERE remote_confirmed=1')}
            event={'epoch':'a'*32,'user_id':uid,'requested':123}
            def read_event(*args,**kwargs):
                self.assertFalse(module.db().in_transaction)
                return SimpleNamespace(stdout=json.dumps(event).encode())
            with patch.object(module,'read_withdrawal_receipts',return_value=confirmed|{uid}), \
                 patch.object(module.subprocess,'run',side_effect=read_event):
                module.reconcile_withdrawals('a'*32)
            self.assertIsNone(module.db().execute('SELECT id FROM users WHERE id=?',(uid,)).fetchone())
            self.assertIsNone(module.db().execute('SELECT id FROM manuscripts WHERE id=?',(doc['id'],)).fetchone())
        self.assertEqual(client.get('/api/me').status_code,401)

    def test_missing_confirmed_receipt_stops_startup_reconciliation(self):
        client,email,_=self.account('missing-receipt','198.51.100.28')
        with module.app.app_context():
            uid=module.db().execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()['id']
            module.db().execute('INSERT INTO withdrawal_requests VALUES(?,?,1)',(uid,1))
            module.db().commit()
            with patch.object(module,'read_withdrawal_receipts',return_value=set()):
                with self.assertRaisesRegex(RuntimeError,'missing a confirmed account'):
                    module.reconcile_withdrawals('a'*32)
            self.assertIsNotNone(module.db().execute('SELECT id FROM users WHERE id=?',(uid,)).fetchone())
            module.db().execute('DELETE FROM withdrawal_requests WHERE user_id=?',(uid,))
            module.db().commit()

    def test_pre_activation_database_cannot_start(self):
        previous=module.DB
        with tempfile.TemporaryDirectory() as folder:
            module.DB=str(Path(folder)/'old-backup.sqlite3')
            try:
                with self.assertRaisesRegex(RuntimeError,'activation is required'):
                    module.init()
            finally:
                module.DB=previous

    def test_withdrawal_upload_requires_readback_match(self):
        uid='b'*32; epoch='a'*32
        payload=json.dumps({'epoch':epoch,'user_id':uid,'requested':123},
                           sort_keys=True,separators=(',',':')).encode()
        with patch.object(module.subprocess,'run',side_effect=[SimpleNamespace(stdout=b''),
                                                                SimpleNamespace(stdout=payload)]) as run:
            module.upload_withdrawal_receipt(epoch,uid,123)
            self.assertEqual(run.call_count,2)
            self.assertIn('rcat',run.call_args_list[0].args[0])
        with patch.object(module.subprocess,'run',side_effect=[SimpleNamespace(stdout=b''),
                                                                SimpleNamespace(stdout=b'wrong')]):
            with self.assertRaisesRegex(RuntimeError,'readback mismatch'):
                module.upload_withdrawal_receipt(epoch,uid,123)

    def test_remote_unavailable_blocks_app_startup(self):
        with patch.dict(os.environ,{'WITHDRAWAL_TEST_MODE':'0'}), \
             patch.object(module,'read_withdrawal_receipts',side_effect=RuntimeError('synthetic Drive outage')):
            with self.assertRaisesRegex(RuntimeError,'synthetic Drive outage'):
                module.init()


if __name__=='__main__': unittest.main()
