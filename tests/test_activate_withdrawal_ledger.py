"""Activation protects the synthetic DB only after remote anchor readback."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


source = Path(__file__).resolve().parents[1] / 'deploy/activate_withdrawal_ledger.py'
spec = importlib.util.spec_from_file_location('activate_withdrawal_ledger', source)
activation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activation)


class ActivateWithdrawalLedgerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'synthetic.sqlite3'
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
            db.execute("INSERT INTO users VALUES('synthetic-user')")
        self.files = {}

    def remote(self, action, path, *args, input_data=None):
        if action == 'rcat':
            self.files[path] = input_data
            return b''
        if action == 'cat':
            return self.files[path]
        if action == 'lsjson':
            return json.dumps([{'Path':name.removeprefix(path+'/')}
                               for name in self.files if name.startswith(path+'/')]).encode()
        raise AssertionError(action)

    def test_activation_and_retry_guard_old_code_deletions(self):
        with patch.object(activation.os,'geteuid',return_value=0), \
             patch.object(activation,'verify_remote_config'), \
             patch.object(activation,'run',side_effect=self.remote):
            self.assertEqual(activation.activate(self.database),{'status':'activated'})
            self.assertEqual(activation.activate(self.database),{'status':'already_active'})
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM withdrawal_state').fetchone()[0],1)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM users WHERE id='synthetic-user'")

    def test_failed_remote_readback_never_activates_database(self):
        def bad_remote(action, path, input_data=None):
            return b'bad' if action == 'cat' else b''
        with patch.object(activation.os,'geteuid',return_value=0), \
             patch.object(activation,'verify_remote_config'), \
             patch.object(activation,'run',side_effect=bad_remote):
            with self.assertRaisesRegex(ValueError,'readback mismatch'):
                activation.activate(self.database)
        with sqlite3.connect(self.database) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='withdrawal_state'").fetchone())

    def test_reactivation_refuses_missing_confirmed_receipt(self):
        with patch.object(activation.os,'geteuid',return_value=0), \
             patch.object(activation,'verify_remote_config'), \
             patch.object(activation,'run',side_effect=self.remote):
            activation.activate(self.database)
            with sqlite3.connect(self.database) as db:
                db.execute("INSERT INTO withdrawal_requests VALUES('synthetic-user',1,1)")
            with self.assertRaisesRegex(ValueError,'receipt is missing'):
                activation.activate(self.database)


if __name__ == '__main__':
    unittest.main()
