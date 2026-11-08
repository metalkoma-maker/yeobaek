"""Read-only checks for the one-time deploy installer, with synthetic paths."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'deploy'))
spec = importlib.util.spec_from_file_location('upgrade_code_deploy', root / 'deploy/upgrade_code_deploy.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
repair_spec = importlib.util.spec_from_file_location('repair_wal_gateway', root / 'deploy/repair_wal_gateway.py')
repair = importlib.util.module_from_spec(repair_spec)
repair_spec.loader.exec_module(repair)
history_spec = importlib.util.spec_from_file_location('upgrade_history_gateway', root / 'deploy/upgrade_history_gateway.py')
history_upgrade = importlib.util.module_from_spec(history_spec)
history_spec.loader.exec_module(history_upgrade)


class CodeDeploySetupTest(unittest.TestCase):
    def test_single_file_history_upgrade_package_has_exact_gateway(self):
        gateway = (root / 'deploy/actions_gateway.py').read_bytes()
        self.assertEqual(history_upgrade.digest(gateway), history_upgrade.NEW_SHA256)
        self.assertEqual(history_upgrade.OLD_SHA256, repair.NEW_SHA256)
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / 'upgrade.pyz'
            with zipfile.ZipFile(package, 'w') as archive:
                archive.write(root / 'deploy/upgrade_history_gateway.py', '__main__.py')
                archive.writestr('actions_gateway.py', gateway)
            with patch.object(sys, 'argv', [str(package)]):
                self.assertEqual(history_upgrade.replacement_bytes(), gateway)
            with zipfile.ZipFile(package, 'a') as archive:
                archive.writestr('unexpected.txt', 'bad')
            with patch.object(sys, 'argv', [str(package)]):
                with self.assertRaisesRegex(ValueError, 'Unexpected upgrade package'):
                    history_upgrade.replacement_bytes()

    def test_history_gateway_upgrade_restores_previous_file_if_inspect_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'gateway'
            old, new = b'old synthetic gateway', b'new synthetic gateway'
            target.write_bytes(old)
            original_stat = Path.stat
            def synthetic_stat(path, *args, **kwargs):
                info = original_stat(path, *args, **kwargs)
                return SimpleNamespace(st_uid=0, st_mode=info.st_mode) if path == target else info
            with patch.object(history_upgrade, 'GATEWAY', target), \
                 patch.object(history_upgrade, 'OLD_SHA256', history_upgrade.digest(old)), \
                 patch.object(history_upgrade, 'NEW_SHA256', history_upgrade.digest(new)), \
                 patch.object(history_upgrade, 'replacement_bytes', return_value=new), \
                 patch.object(history_upgrade, 'verify_inspect', side_effect=['a' * 64, ValueError('bad post-install inspect')]), \
                 patch.object(history_upgrade, 'install_bytes', side_effect=lambda path, body: path.write_bytes(body)), \
                 patch.object(history_upgrade.os, 'geteuid', return_value=0), \
                 patch.object(Path, 'stat', synthetic_stat), \
                 patch.object(history_upgrade.os, 'chown'), \
                 patch.object(history_upgrade.os, 'chmod'):
                with self.assertRaisesRegex(ValueError, 'bad post-install inspect'):
                    history_upgrade.main()
            self.assertEqual(target.read_bytes(), old)

    def test_extra_ssh_authentication_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            account = SimpleNamespace(pw_dir=temporary)
            settings = ('authorizedkeyscommand none\ntrustedusercakeys none\n'
                        'authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2\n')
            with patch.object(setup.shutil, 'which', return_value='/usr/sbin/sshd'), \
                 patch.object(setup.subprocess, 'run', return_value=SimpleNamespace(stdout=settings)):
                setup.verify_ssh_key_path(account)
            settings = settings.replace('authorizedkeyscommand none', 'authorizedkeyscommand /unexpected/helper')
            with patch.object(setup.shutil, 'which', return_value='/usr/sbin/sshd'), \
                 patch.object(setup.subprocess, 'run', return_value=SimpleNamespace(stdout=settings)):
                with self.assertRaisesRegex(ValueError, 'Additional SSH'):
                    setup.verify_ssh_key_path(account)

    def test_public_key_must_be_unique(self):
        line = 'restrict,command="/old/gateway" ssh-ed25519 AAAAB3NzaC1yc2EAAAADAQABAAABAQ== previous'
        self.assertEqual(setup.one_public_key(line), 'ssh-ed25519 AAAAB3NzaC1yc2EAAAADAQABAAABAQ==')
        with self.assertRaises(ValueError):
            setup.one_public_key(line + '\n' + line)

    def test_baseline_and_database_preflight_do_not_change_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            app, state = base / 'app', base / 'state'
            (app / 'static').mkdir(parents=True)
            state.mkdir()
            for name in (*setup.FILES, 'backup.py'):
                (app / name).write_bytes(('fake ' + name).encode())
                (app / name).chmod(0o644)
            database = base / 'novel.sqlite3'
            with sqlite3.connect(database) as conn:
                conn.execute('CREATE TABLE manuscripts(body TEXT)')
                conn.execute('INSERT INTO manuscripts VALUES (?)', ('가짜 원고',))
            baseline = setup.inventory(app, (*setup.FILES, 'backup.py'))
            (state / 'baseline.json').write_text(json.dumps({'files': baseline}))
            config = {'app': str(app), 'state': str(state), 'service': 'yeobaek.service'}
            account = SimpleNamespace(pw_uid=1001, pw_gid=1001, pw_shell='/bin/sh')
            self.assertEqual(setup.validate_paths(config, database, account), (app, state))
            with sqlite3.connect(database) as conn:
                self.assertEqual(conn.execute('SELECT body FROM manuscripts').fetchone()[0], '가짜 원고')
            (app / 'backup.py').write_text('unexpected drift')
            with self.assertRaisesRegex(ValueError, 'Protected server code'):
                setup.validate_paths(config, database, account)


if __name__ == '__main__':
    unittest.main()
