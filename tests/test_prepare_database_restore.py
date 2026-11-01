"""A past backup may contain a withdrawn synthetic account and manuscript."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import json


source = Path(__file__).resolve().parents[1] / 'deploy/prepare_database_restore.py'
spec = importlib.util.spec_from_file_location('prepare_database_restore', source)
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


class PrepareDatabaseRestoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.current, self.backup, self.output = (root / name for name in
                                                   ('current.sqlite3', 'backup.sqlite3', 'staged.sqlite3'))
        with sqlite3.connect(self.current) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.executescript('''
                CREATE TABLE users(id TEXT PRIMARY KEY, email TEXT);
                CREATE TABLE manuscripts(id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE, body TEXT);
                CREATE TABLE manuscript_history(manuscript_id TEXT REFERENCES manuscripts(id) ON DELETE CASCADE, body TEXT);
                CREATE TABLE sessions(token TEXT, user_id TEXT REFERENCES users(id) ON DELETE CASCADE);
                CREATE TABLE password_resets(token_hash TEXT, user_id TEXT REFERENCES users(id) ON DELETE CASCADE);
                CREATE TABLE attempts(key TEXT);
                INSERT INTO users VALUES('withdrawn', 'withdrawn@example.test'), ('active', 'active@example.test');
                INSERT INTO manuscripts VALUES('old', 'withdrawn', 'withdrawn text'), ('kept', 'active', 'kept text');
                INSERT INTO manuscript_history VALUES('old', 'old text');
                INSERT INTO sessions VALUES('old token', 'withdrawn');
                INSERT INTO password_resets VALUES('old reset', 'active');
                INSERT INTO attempts VALUES('old rate limit');
            ''')
            with sqlite3.connect(self.backup) as snapshot:
                db.backup(snapshot)
            db.execute("DELETE FROM users WHERE id='withdrawn'")

    def test_withdrawn_account_and_related_text_do_not_reappear(self):
        result = restore.prepare(self.current, self.backup, self.output)
        self.assertEqual(result, {'status': 'prepared', 'backup_accounts': 2,
                                  'removed_accounts': 1, 'retained_accounts': 1,
                                  'withdrawal_receipts': None})
        with sqlite3.connect(self.output) as db:
            self.assertEqual(db.execute('SELECT id FROM users').fetchall(), [('active',)])
            self.assertEqual(db.execute('SELECT body FROM manuscripts').fetchall(), [('kept text',)])
            for table in ('manuscript_history', 'sessions', 'password_resets', 'attempts'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        with sqlite3.connect(self.backup) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 2)
        with sqlite3.connect(self.current) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 1)

    def test_without_current_database_preparation_fails_closed(self):
        self.current.unlink()
        with self.assertRaises(FileNotFoundError):
            restore.prepare(self.current, self.backup, self.output)
        self.assertFalse(self.output.exists())

    def test_current_database_with_uncheckpointed_wal_is_used(self):
        with sqlite3.connect(self.current) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA foreign_keys=ON')
            db.execute("DELETE FROM users WHERE id='active'")
        result = restore.prepare(self.current, self.backup, self.output)
        self.assertEqual(result['removed_accounts'], 2)
        with sqlite3.connect(self.output) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 0)
        self.assertFalse(Path(str(self.output) + '-wal').exists())

    def test_existing_output_and_bad_backup_are_never_overwritten(self):
        self.output.write_text('existing result')
        with self.assertRaises(FileExistsError):
            restore.prepare(self.current, self.backup, self.output)
        self.assertEqual(self.output.read_text(), 'existing result')
        self.output.unlink()
        self.backup.write_bytes(b'not sqlite')
        with self.assertRaises(sqlite3.DatabaseError):
            restore.prepare(self.current, self.backup, self.output)
        self.assertFalse(self.output.exists())

    def protect_backup(self):
        with sqlite3.connect(self.backup) as db:
            db.executescript('''
                CREATE TABLE withdrawal_state(epoch TEXT PRIMARY KEY);
                CREATE TABLE withdrawal_requests(user_id TEXT PRIMARY KEY, requested INTEGER, remote_confirmed INTEGER);
                INSERT INTO withdrawal_state VALUES('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
                CREATE TRIGGER users_delete_requires_withdrawal_receipt BEFORE DELETE ON users
                WHEN NOT EXISTS(SELECT 1 FROM withdrawal_requests WHERE user_id=OLD.id AND remote_confirmed=1)
                BEGIN SELECT RAISE(ABORT, 'withdrawal receipt required'); END;
            ''')

    def test_remote_ledger_filters_withdrawal_when_current_db_was_lost(self):
        self.protect_backup()
        self.current.unlink()
        with patch.object(restore,'remote_withdrawals',return_value={'withdrawn'}) as ledger:
            result=restore.prepare(None,self.backup,self.output,use_remote=True)
            ledger.assert_called_once_with('a'*32,restore.REMOTE,restore.RCLONE_CONFIG)
        self.assertEqual(result['removed_accounts'],1)
        self.assertEqual(result['withdrawal_receipts'],1)
        with sqlite3.connect(self.output) as db:
            self.assertEqual(db.execute('SELECT id FROM users').fetchall(),[('active',)])
            self.assertEqual(db.execute('SELECT body FROM manuscripts').fetchall(),[('kept text',)])

    def test_protected_backup_refuses_missing_or_incomplete_ledger(self):
        self.protect_backup()
        with self.assertRaisesRegex(ValueError,'requires the independent withdrawal ledger'):
            restore.prepare(self.current,self.backup,self.output)
        with patch.object(restore,'remote_withdrawals',return_value=set()):
            with self.assertRaisesRegex(ValueError,'no verified withdrawal receipt'):
                restore.prepare(self.current,self.backup,self.output,use_remote=True)
        self.assertFalse(self.output.exists())

    def test_pre_activation_backup_cannot_use_remote_ledger(self):
        with self.assertRaisesRegex(ValueError,'predates withdrawal ledger activation'):
            restore.prepare(None,self.backup,self.output,use_remote=True)
        self.assertFalse(self.output.exists())

    def test_remote_receipts_require_matching_anchor_and_contents(self):
        epoch='a'*32; uid='b'*32
        root=restore.REMOTE+'/'+epoch
        anchor=json.dumps({'epoch':epoch,'version':1}).encode()
        event=json.dumps({'epoch':epoch,'user_id':uid,'requested':100}).encode()
        files={root+'/anchor.json':anchor,root+'/users/_initialized.json':anchor,
               root+'/users/'+uid+'.json':event}
        def fake_run(command,**kwargs):
            action='lsjson' if 'lsjson' in command else 'cat'
            path=command[command.index(action)+1]
            if action=='lsjson':
                return SimpleNamespace(stdout=json.dumps([{'Path':'_initialized.json'},
                                                          {'Path':uid+'.json'}]).encode())
            return SimpleNamespace(stdout=files[path])
        with patch.object(restore.subprocess,'run',side_effect=fake_run):
            self.assertEqual(restore.remote_withdrawals(epoch),{uid})
            files[root+'/users/'+uid+'.json']=json.dumps({'epoch':epoch,'user_id':'c'*32,'requested':100}).encode()
            with self.assertRaisesRegex(ValueError,'does not match'):
                restore.remote_withdrawals(epoch)


if __name__ == '__main__':
    unittest.main()
