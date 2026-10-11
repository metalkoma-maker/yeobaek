#!/usr/bin/python3 -I
"""Root-owned forced SSH command. Six static files only; no application imports.

Production settings come only from a root-owned local configuration file.
Install with install-actions.sh; never run this against production in tests.
"""
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

CONFIG = Path('/etc/yeobaek-actions.json')
FILES = ('static/edit-history.js', 'static/font-size.js', 'static/safety-storage.js',
         'static/app.js', 'static/style.css', 'static/index.html')  # HTML last
MAX_ARCHIVE = 8 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(files):
    return sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())


def safe_path(root, name):
    path = root / name
    for ancestor in (root, *path.parents):
        if ancestor.is_symlink():
            raise ValueError('Symlink refused: ' + str(ancestor))
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Unsafe path: ' + name)
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError('Not a single regular file: ' + name)
    return path


def inventory(app, names):
    return {name: sha(safe_path(app, name).read_bytes())
            if safe_path(app, name).exists() else None for name in names}


def atomic(path, data, metadata=None):
    fd, temp = tempfile.mkstemp(prefix='.yeobaek-actions-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            if metadata:
                os.fchown(stream.fileno(), metadata['uid'], metadata['gid'])
                os.fchmod(stream.fileno(), metadata['mode'])
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_json(path, value):
    atomic(path, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())


def payload(data):
    if len(data) > MAX_ARCHIVE:
        raise ValueError('Archive too large')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) != len(FILES) + 1 or set(x.filename for x in entries) != {*FILES, 'release.json'}:
            raise ValueError('Only the six approved files and release.json are allowed')
        for entry in entries:
            mode = entry.external_attr >> 16
            if entry.file_size > MAX_FILE or entry.flag_bits & 1 or stat.S_ISLNK(mode) or entry.is_dir():
                raise ValueError('Unsafe archive entry')
        meta = json.loads(archive.read('release.json'))
        if not re.fullmatch('[0-9a-f]{40}', str(meta.get('commit', ''))):
            raise ValueError('Expected immutable Git commit')
        contents = {name: archive.read(name) for name in FILES}
        if meta.get('files') != {name: sha(body) for name, body in contents.items()}:
            raise ValueError('Release digest mismatch')
        return meta, contents


def health(expected, config):
    host = config['host']
    subprocess.run(['/usr/bin/systemctl', 'is-active', '--quiet', config['service']], check=True, timeout=10)
    # Test local Nginx -> Gunicorn using the real Host and valid TLS certificate.
    # No public DNS/outbound route dependency; no authentication or DB-writing API.
    for name in ('/', *FILES):
        url = 'https://' + host + ('/' + name if name != '/' else '/')
        body = subprocess.run(['/usr/bin/curl', '--noproxy', '*', '--silent', '--show-error',
                               '--fail', '--max-time', '10', '--max-filesize', str(MAX_FILE),
                               '--resolve', host + ':443:127.0.0.1',
                               '-H', 'Cache-Control: no-cache', url + '?actions-health=' + uuid.uuid4().hex],
                              check=True, timeout=15, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        wanted = expected['static/index.html'] if name == '/' else expected[name]
        if sha(body) != wanted:
            raise ValueError('Served file mismatch: ' + name)


class Gateway:
    def __init__(self, app, state, check):
        self.app, self.state, self.check = app, state, check
        self.baseline = json.loads((state / 'baseline.json').read_text())['files']

    def current(self):
        return inventory(self.app, self.baseline)

    def inspect(self):
        current = self.current()
        latest = self.state / 'latest.json'
        pending = self.state / 'pending.json'
        return {'files': current, 'fingerprint': fingerprint(current),
                'pending_recovery': pending.exists(),
                'last_backup': json.loads(latest.read_text())['backup'] if latest.exists() else None}

    def require_expected(self, expected):
        current = self.current()
        if fingerprint(current) != expected:
            raise ValueError('Server changed since inspect; refused before writing')
        return current

    def backup(self, current):
        ident = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex
        directory = self.state / 'backups' / ident
        directory.mkdir(mode=0o700)
        metadata = {}
        for name in FILES:
            src = safe_path(self.app, name)
            info = src.stat() if src.exists() else None
            owner = info if info else src.parent.stat()
            metadata[name] = {'present': info is not None, 'mode': stat.S_IMODE(info.st_mode) if info else 0o644,
                              'uid': owner.st_uid, 'gid': owner.st_gid}
            if info:
                body = src.read_bytes()
                if sha(body) != current[name]:
                    raise ValueError('File changed during backup')
                dst = directory / name
                dst.parent.mkdir(mode=0o700, exist_ok=True)
                atomic(dst, body)
        record = {'backup': ident, 'before': current, 'metadata': metadata}
        write_json(directory / 'record.json', record)
        return record

    def restore(self, record):
        ident = record['backup']
        if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}', ident):
            raise ValueError('Invalid backup identifier')
        directory = self.state / 'backups' / ident
        # Validate every backup BEFORE restoring any file.
        bodies = {}
        for name in FILES:
            meta = record['metadata'][name]
            if meta['present']:
                bodies[name] = safe_path(directory, name).read_bytes()
                if sha(bodies[name]) != record['before'][name]:
                    raise ValueError('Backup digest mismatch')
        for name in FILES:
            target = safe_path(self.app, name)
            if name in bodies:
                atomic(target, bodies[name], record['metadata'][name])
            else:
                target.unlink(missing_ok=True)
        if self.current() != record['before']:
            raise ValueError('Restored inventory differs; pending recovery retained')

    def deploy(self, expected, data):
        if (self.state / 'pending.json').exists():
            raise ValueError('Interrupted transaction; inspect then rollback first')
        meta, bodies = payload(data)
        current = self.require_expected(expected)
        for name in self.baseline:
            if name not in FILES and current[name] != self.baseline[name]:
                raise ValueError('Protected backend/backup code drift: ' + name)
        self.check(current)  # Refuse if service was already unhealthy.
        record = self.backup(current)
        record.update(commit=meta['commit'], after={**current, **meta['files']})
        self.require_expected(expected)
        write_json(self.state / 'pending.json', record)
        try:
            for name in FILES:
                atomic(safe_path(self.app, name), bodies[name], record['metadata'][name])
            if self.current() != record['after']:
                raise ValueError('Post-deploy file mismatch')
            self.check(record['after'])
            write_json(self.state / 'latest.json', record)
            (self.state / 'pending.json').unlink()
        except BaseException as error:
            self.restore(record)
            (self.state / 'pending.json').unlink()
            try:
                self.check(record['before'])
            except BaseException as health_error:
                raise RuntimeError('Original files restored; service still unhealthy: ' + str(health_error)) from error
            raise RuntimeError('Deployment failed; original files restored and health verified: ' + str(error)) from error
        return {'status': 'deployed', 'backup': record['backup'], 'commit': meta['commit'],
                'fingerprint': fingerprint(record['after'])}

    def rollback(self, expected):
        self.require_expected(expected)
        pending = self.state / 'pending.json'
        source = pending if pending.exists() else self.state / 'latest.json'
        if not source.exists():
            raise ValueError('No deployment backup exists')
        record = json.loads(source.read_text())
        self.restore(record)
        # Bytes are restored even when the service has an unrelated failure.
        self.check(record['before'])
        pending.unlink(missing_ok=True)
        return {'status': 'rolled_back', 'backup': record['backup'], 'fingerprint': fingerprint(self.current())}


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise ValueError('Root-owned forced command required')
    command = os.environ.get('SSH_ORIGINAL_COMMAND', '')
    if not re.fullmatch(r'inspect|(?:deploy|rollback) [0-9a-f]{64}', command):
        raise ValueError('Only inspect, deploy HASH, rollback HASH are supported')
    # Keep interrupted operations recoverable; never accept arbitrary shell commands.
    def interrupted(signum, frame):
        raise RuntimeError('Deployment interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    if CONFIG.is_symlink() or CONFIG.stat().st_uid != 0 or CONFIG.stat().st_mode & 0o022:
        raise ValueError('Configuration must be root-owned and not writable by others')
    config = json.loads(CONFIG.read_text())
    app, state = Path(config['app']), Path(config['state'])
    if not app.is_absolute() or not state.is_absolute():
        raise ValueError('Absolute local paths required')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', config['host']) or not re.fullmatch(r'[A-Za-z0-9_.@-]+', config['service']):
        raise ValueError('Invalid configured service or host')
    with (state / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        gateway = Gateway(app, state, lambda current: health(current, config))
        if command == 'inspect':
            result = gateway.inspect()
        else:
            action, expected = command.split()
            if action == 'deploy':
                signal.alarm(60)  # Bound receiving data from an authenticated client.
                data = sys.stdin.buffer.read(MAX_ARCHIVE + 1)
                signal.alarm(0)
                result = gateway.deploy(expected, data)
            else:
                result = gateway.rollback(expected)
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print('Yeobaek deployment failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
