"""One-time root upgrade for the restricted history/account code deployer.

Only the reviewed forced-command gateway is replaced. The application,
database, service, and backup jobs are untouched.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile

GATEWAY = Path('/usr/local/libexec/yeobaek-actions-gateway')
ACCOUNT = 'yeobaek-deploy'
OLD_SHA256 = '493fa22e1e65dd8f03ba2ba39575fc4d82b59a4a997dc07a3da7a14aa0481921'
NEW_SHA256 = '95e3b3561eac59e4c4ea0de20d3be3c9a7124f80597dd58a61851ad571949069'
OLD_CAPABILITY = 'code-and-additive-manuscript-order-v1'
NEW_CAPABILITY = 'code-and-additive-history-account-v1'


def digest(contents):
    return hashlib.sha256(contents).hexdigest()


def replacement_bytes():
    archive = Path(sys.argv[0])
    if archive.suffix == '.pyz' and zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as package:
            if set(package.namelist()) != {'__main__.py', 'actions_gateway.py'}:
                raise ValueError('Unexpected upgrade package contents')
            return package.read('actions_gateway.py')
    source = Path(__file__).with_name('actions_gateway.py')
    if source.is_symlink() or not source.is_file():
        raise ValueError('Reviewed replacement gateway file is missing')
    return source.read_bytes()


def install_bytes(target, contents):
    fd, temporary = tempfile.mkstemp(prefix='.yeobaek-gateway-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchown(stream.fileno(), 0, 0)
            os.fchmod(stream.fileno(), 0o755)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verify_inspect(capability):
    result = subprocess.run(['/usr/sbin/runuser', '-u', ACCOUNT, '--', '/usr/bin/env',
                             'SSH_ORIGINAL_COMMAND=inspect', '/usr/bin/python3', '-I', str(GATEWAY)],
                            check=True, timeout=20, capture_output=True, text=True)
    report = json.loads(result.stdout)
    if report.get('capability') != capability or report.get('pending_recovery'):
        raise ValueError('Gateway inspect did not report a ready code deployer')
    fingerprint = report.get('fingerprint')
    if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        raise ValueError('Gateway inspect returned an invalid fingerprint')
    return fingerprint


def main():
    if os.geteuid() != 0:
        raise ValueError('Root is required for this one-time gateway upgrade')
    replacement = replacement_bytes()
    if digest(replacement) != NEW_SHA256:
        raise ValueError('Reviewed replacement gateway hash does not match')
    if GATEWAY.is_symlink() or not GATEWAY.is_file() or GATEWAY.stat().st_uid != 0 or GATEWAY.stat().st_mode & 0o022:
        raise ValueError('Installed gateway must be a protected root-owned regular file')
    previous = GATEWAY.read_bytes()
    current_hash = digest(previous)
    if current_hash == NEW_SHA256:
        print(json.dumps({'status': 'already_installed', 'fingerprint': verify_inspect(NEW_CAPABILITY)}))
        return
    if current_hash != OLD_SHA256:
        raise ValueError('Installed gateway differs from the reviewed previous version')
    before = verify_inspect(OLD_CAPABILITY)
    backup = GATEWAY.with_name(GATEWAY.name + '.before-history-upgrade-' + uuid.uuid4().hex)
    shutil.copy2(GATEWAY, backup)
    os.chown(backup, 0, 0)
    os.chmod(backup, 0o700)
    try:
        install_bytes(GATEWAY, replacement)
        after = verify_inspect(NEW_CAPABILITY)
        if after != before:
            raise ValueError('Application file inventory changed during gateway upgrade')
    except BaseException:
        install_bytes(GATEWAY, previous)
        raise
    print(json.dumps({'status': 'upgraded', 'fingerprint': after, 'previous_gateway': str(backup)}))


if __name__ == '__main__':
    main()
