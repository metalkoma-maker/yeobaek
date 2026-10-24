"""Exercise the root mail installer with disposable files and fake service calls."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy import configure_gmail_recovery as setup


class GmailRecoverySetupTest(unittest.TestCase):
    def test_only_dedicated_gmail_and_app_password_shape(self):
        self.assertEqual(setup.account('  novel.test@gmail.com ', 'abcd efgh ijkl mnop'),
                         ('novel.test@gmail.com', 'abcdefghijklmnop'))
        for address, password in [('personal@naver.com', 'abcdefghijklmnop'),
                                  ('novel.test@gmail.com', 'account-password'),
                                  ('novel.test@gmail.com', 'a\n' * 16)]:
            with self.assertRaises(ValueError):
                setup.account(address, password)

    def test_failed_health_check_restores_existing_secret_and_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mail, dropin = root / 'mail.env', root / 'mail.conf'
            mail.write_bytes(b'OLD_SECRET=old\n'); dropin.write_bytes(b'[Service]\nOld=1\n')
            mail.chmod(0o600); dropin.chmod(0o644)
            calls = []
            def write(path, contents, mode):
                path.write_bytes(contents); path.chmod(mode)
            def run(*args): calls.append(args)
            with patch.object(setup, 'protected'), patch.object(setup, 'write_atomic', side_effect=write):
                with self.assertRaisesRegex(ValueError, 'remained unavailable'):
                    setup.apply_config(mail, dropin, 'novel.test@gmail.com', 'abcdefghijklmnop',
                                       'novel.example.test', 'yeobaek', run, lambda host: False)
            self.assertEqual(mail.read_bytes(), b'OLD_SECRET=old\n')
            self.assertEqual(dropin.read_bytes(), b'[Service]\nOld=1\n')
            self.assertEqual(mail.stat().st_mode & 0o777, 0o600)
            self.assertEqual(calls.count(('/usr/bin/systemctl', 'restart', 'yeobaek')), 2)

    def test_symlink_mail_file_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'target').write_text('not a mail secret')
            (root / 'mail.env').symlink_to(root / 'target')
            with self.assertRaises(ValueError):
                setup.protected(root / 'mail.env')

    def test_rollback_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mail, dropin = root / 'mail.env', root / 'mail.conf'
            def write(path, contents, mode):
                path.write_bytes(contents); path.chmod(mode)
            def run(*args):
                if args[-2:] == ('restart', 'yeobaek'):
                    raise OSError('synthetic service failure')
            with patch.object(setup, 'protected'), patch.object(setup, 'write_atomic', side_effect=write):
                with self.assertRaisesRegex(RuntimeError, 'rollback failed'):
                    setup.apply_config(mail, dropin, 'novel.test@gmail.com', 'abcdefghijklmnop',
                                       'novel.example.test', 'yeobaek', run, lambda host: True)


if __name__ == '__main__':
    unittest.main()
