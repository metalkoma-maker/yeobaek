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
                with self.assertRaisesRegex(ValueError, '비밀번호 찾기 응답 확인'):
                    setup.apply_config(mail, dropin, 'novel.test@gmail.com', 'abcdefghijklmnop',
                                       'novel.example.test', 'yeobaek', run, lambda host: False,
                                       pause=lambda delay: None)
            self.assertEqual(mail.read_bytes(), b'OLD_SECRET=old\n')
            self.assertEqual(dropin.read_bytes(), b'[Service]\nOld=1\n')
            self.assertEqual(mail.stat().st_mode & 0o777, 0o600)
            self.assertEqual(calls.count(('/usr/bin/systemctl', 'restart', 'yeobaek')), 2)

    def test_waits_for_service_to_answer_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mail, dropin = root / 'mail.env', root / 'mail.conf'
            calls, checks = [], []
            def write(path, contents, mode):
                path.write_bytes(contents); path.chmod(mode)
            def check(host):
                checks.append(host)
                if len(checks) == 1:
                    raise OSError('synthetic startup delay')
                return len(checks) >= 3
            with patch.object(setup, 'protected'), patch.object(setup, 'write_atomic', side_effect=write):
                setup.apply_config(mail, dropin, 'novel.test@gmail.com', 'abcdefghijklmnop',
                                   'novel.example.test', 'yeobaek', lambda *args: calls.append(args),
                                   check, pause=lambda delay: None)
            self.assertEqual(len(checks), 3)
            self.assertEqual(calls.count(('/usr/bin/systemctl', 'restart', 'yeobaek')), 1)

    def test_symlink_mail_file_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'target').write_text('not a mail secret')
            (root / 'mail.env').symlink_to(root / 'target')
            with self.assertRaises(ValueError):
                setup.protected(root / 'mail.env')

    def test_restart_failure_reports_stage_after_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mail, dropin = root / 'mail.env', root / 'mail.conf'
            restarts = []
            def write(path, contents, mode):
                path.write_bytes(contents); path.chmod(mode)
            def run(*args):
                if args[-2:] == ('restart', 'yeobaek'):
                    restarts.append(args)
                    if len(restarts) == 1:
                        raise OSError('synthetic restart failure')
            with patch.object(setup, 'protected'), patch.object(setup, 'write_atomic', side_effect=write):
                with self.assertRaisesRegex(ValueError, '서비스 재시작; 원인: OSError'):
                    setup.apply_config(mail, dropin, 'novel.test@gmail.com', 'abcdefghijklmnop',
                                       'novel.example.test', 'yeobaek', run, lambda host: True)
            self.assertFalse(mail.exists())
            self.assertFalse(dropin.exists())
            self.assertEqual(len(restarts), 2)

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
