"""The automatic trigger must accept only a request-only main commit."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

source = Path(__file__).resolve().parents[1] / 'deploy/validate_deploy_request.py'
spec = importlib.util.spec_from_file_location('validate_deploy_request', source)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class DeployRequestTest(unittest.TestCase):
    def test_only_request_file_and_current_main_are_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def git(*args):
                return subprocess.run(['git', *args], cwd=root, check=True, text=True,
                                      stdout=subprocess.PIPE).stdout.strip()

            git('init', '-b', 'main')
            git('config', 'user.email', 'synthetic@example.test')
            git('config', 'user.name', 'Synthetic Test')
            git('remote', 'add', 'origin', str(root))
            (root / 'app.py').write_text('synthetic app\n')
            git('add', 'app.py')
            git('commit', '-m', 'synthetic app')
            before = git('rev-parse', 'HEAD')

            request = root / validator.REQUEST
            request.parent.mkdir()
            request.write_text(json.dumps({'source_commit': before, 'request_id': 'a' * 32}))
            git('add', validator.REQUEST)
            git('commit', '-m', 'request production deploy')
            commit = git('rev-parse', 'HEAD')
            validator.validate(before, commit, root)

            request.write_text(json.dumps({'source_commit': 'b' * 40, 'request_id': 'a' * 32}))
            with self.assertRaisesRegex(ValueError, 'previous main'):
                validator.validate(before, commit, root)
            request.write_text(json.dumps({'source_commit': before, 'request_id': 'a' * 32}))

            (root / 'app.py').write_text('unreviewed change\n')
            git('add', 'app.py')
            git('commit', '-m', 'other change')
            moved = git('rev-parse', 'HEAD')
            with self.assertRaisesRegex(ValueError, 'no longer main'):
                validator.validate(before, commit, root)
            with self.assertRaisesRegex(ValueError, 'only the request'):
                validator.validate(before, moved, root)


if __name__ == '__main__':
    unittest.main()
