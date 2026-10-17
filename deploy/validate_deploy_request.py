"""Validate a main-branch deploy request before production credentials are used."""
import argparse
import json
from pathlib import Path
import re
import subprocess

REQUEST = '.github/deploy-request.json'
SHA = re.compile(r'[0-9a-f]{40}\Z')
REQUEST_ID = re.compile(r'[0-9a-f]{32}\Z')


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, stdout=subprocess.PIPE).stdout


def validate(before, commit, root=Path('.')):
    if (not SHA.fullmatch(before) or before == '0' * 40
            or not SHA.fullmatch(commit) or before == commit):
        raise ValueError('Invalid deployment commit pair')
    changed = git('diff', '--no-renames', '--name-only', '-z', before, commit, cwd=root)
    if changed != (REQUEST + '\0').encode():
        raise ValueError('Deploy request commit must change only the request file')
    request_path = root / REQUEST
    if request_path.is_symlink() or not request_path.is_file():
        raise ValueError('Deploy request must be a regular file')
    data = json.loads(request_path.read_text(encoding='utf-8'))
    if (type(data) is not dict or set(data) != {'source_commit', 'request_id'}
            or data['source_commit'] != before
            or not isinstance(data['request_id'], str)
            or not REQUEST_ID.fullmatch(data['request_id'])):
        raise ValueError('Deploy request does not match the previous main commit')
    current_main = git('ls-remote', '--exit-code', 'origin', 'refs/heads/main', cwd=root)
    if current_main != (commit + '\trefs/heads/main\n').encode():
        raise ValueError('Deploy request commit is no longer main')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    validate(args.before, args.commit)
