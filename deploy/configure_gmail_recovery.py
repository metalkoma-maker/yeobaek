#!/usr/bin/python3 -I
"""One-time root setup for a dedicated Gmail sender; never store its password in Git.

Run interactively on the production server only after the reviewed password
recovery UI has been deployed. No manuscript or SQLite file is opened here.
"""
import getpass
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import subprocess
import tempfile
import time
from email.message import EmailMessage

CONFIG = Path('/etc/yeobaek-actions.json')
MAIL_ENV = Path('/etc/yeobaek-recovery-mail.env')
SYSTEMD = Path('/etc/systemd/system')


def account(address, password):
    address = address.strip().lower()
    password = password.replace(' ', '')
    if not re.fullmatch(r'[a-z0-9][a-z0-9.+_-]*@gmail\.com', address):
        raise ValueError('A dedicated @gmail.com sender is required')
    if not re.fullmatch(r'[a-z0-9]{16}', password):
        raise ValueError('Enter the 16-character Gmail app password, not the account password')
    return address, password


def protected(path, secret=False):
    if path.is_symlink() or (path.exists() and
                             (not path.is_file() or path.stat().st_uid != 0 or path.stat().st_nlink != 1)):
        raise ValueError('Existing mail configuration is not a regular root-owned file')
    if secret and path.exists() and path.stat().st_mode & 0o077:
        raise ValueError('Existing mail secret is readable by another account')


def write_atomic(path, contents, mode):
    fd, temporary = tempfile.mkstemp(prefix='.yeobaek-mail-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchown(stream.fileno(), 0, 0)
            os.fchmod(stream.fileno(), mode)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def command(*args):
    subprocess.run(args, check=True, timeout=30, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def availability(host):
    result = subprocess.run(
        ['/usr/bin/curl', '--noproxy', '*', '--silent', '--show-error', '--fail',
         '--max-time', '10', '--resolve', host + ':443:127.0.0.1',
         'https://' + host + '/api/password-reset/availability'],
        check=True, timeout=15, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    response = json.loads(result.stdout)
    if type(response) is not dict or type(response.get('available')) is not bool:
        raise ValueError('Reviewed password recovery API is not deployed')
    return response['available']


def send_test(address, password, recipient):
    message = EmailMessage()
    message['From'] = address
    message['To'] = recipient
    message['Subject'] = '소설여백 메일 발송 시험'
    message.set_content('소설여백 비밀번호 찾기 메일의 발송 설정을 확인하는 시험 메시지입니다.')
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10,
                          context=ssl.create_default_context()) as smtp:
        smtp.login(address, password)
        smtp.send_message(message)


def wait_availability(host, check, pause=None, attempts=20):
    pause = pause or time.sleep
    for attempt in range(attempts):
        try:
            if check(host) is True:
                return
        except (ValueError, subprocess.SubprocessError, OSError):
            pass  # The web service may still be starting after systemctl restart.
        if attempt + 1 < attempts:
            pause(0.5)
    raise ValueError('비밀번호 찾기 응답 확인 실패')


def apply_config(mail_path, dropin_path, address, password, host, service, run=command,
                 check=availability, pause=None):
    protected(mail_path, secret=True)
    protected(dropin_path)
    before = {path: path.read_bytes() if path.exists() else None for path in (mail_path, dropin_path)}
    modes = {path: (path.stat().st_mode & 0o777) if path.exists() else None
             for path in (mail_path, dropin_path)}
    contents = (f'SMTP_HOST=smtp.gmail.com\nSMTP_PORT=465\nSMTP_SECURITY=ssl\n'
                f'SMTP_FROM={address}\nSMTP_USERNAME={address}\nSMTP_PASSWORD={password}\n'
                f'APP_PUBLIC_URL=https://{host}\n').encode()
    dropin = ('[Service]\nEnvironmentFile=' + str(mail_path) + '\n').encode()
    stage = '설정 파일 기록'
    try:
        write_atomic(mail_path, contents, 0o600)
        write_atomic(dropin_path, dropin, 0o644)
        stage = '서비스 설정 읽기'
        run('/usr/bin/systemctl', 'daemon-reload')
        stage = '서비스 재시작'
        run('/usr/bin/systemctl', 'restart', service)
        stage = '비밀번호 찾기 응답 확인'
        wait_availability(host, check, pause)
        stage = '서비스 실행 상태 확인'
        run('/usr/bin/systemctl', 'is-active', '--quiet', service)
    except BaseException as error:
        try:
            for path in (mail_path, dropin_path):
                if before[path] is None:
                    path.unlink(missing_ok=True)
                else:
                    write_atomic(path, before[path], modes[path])
            run('/usr/bin/systemctl', 'daemon-reload')
            run('/usr/bin/systemctl', 'restart', service)
        except BaseException:
            raise RuntimeError('Automatic mail configuration rollback failed; administrator inspection is required') from None
        raise ValueError('메일 설정 실패 단계: ' + stage + '; 원인: ' +
                         type(error).__name__ + '; 기존 설정 복원 완료') from None


def main():
    if os.geteuid() != 0:
        raise ValueError('Run as root on the production server')
    if CONFIG.is_symlink() or not CONFIG.is_file() or CONFIG.stat().st_uid != 0:
        raise ValueError('Protected deployment configuration is required')
    config = json.loads(CONFIG.read_text())
    service, host = config['service'], config['host']
    if not re.fullmatch(r'yeobaek(?:\.service)?', service) or not re.fullmatch(r'[a-z0-9.-]+', host):
        raise ValueError('Unexpected production service or host')
    dropin_dir = SYSTEMD / ((service.removesuffix('.service')) + '.service.d')
    if dropin_dir.is_symlink() or (dropin_dir.exists() and dropin_dir.stat().st_uid != 0):
        raise ValueError('Systemd drop-in directory is not root-owned')
    command('/usr/bin/systemctl', 'is-active', '--quiet', service)
    try:
        availability(host)  # Refuse setup until the reviewed UI/API is deployed.
    except (ValueError, subprocess.SubprocessError, OSError):
        raise ValueError('비밀번호 찾기 새 버전을 먼저 운영에 배포해야 합니다') from None
    address, password = account(input('여백 전용 Gmail 주소: '),
                                getpass.getpass('Gmail 앱 비밀번호 (화면에 보이지 않음): '))
    recipient = input('시험 메일을 받을 주소 (엔터면 발신 Gmail): ').strip() or address
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', recipient) or len(recipient) > 254:
        raise ValueError('시험 수신 이메일 주소를 확인하세요')
    try:
        send_test(address, password, recipient)  # Authentication and TLS before any server change.
        if input('시험 메일을 실제로 받았다면 YES 입력: ').strip() != 'YES':
            raise ValueError('시험 메일 수신을 확인하지 않아 서버 설정을 변경하지 않았습니다')
        dropin_dir.mkdir(mode=0o755, exist_ok=True)
        apply_config(MAIL_ENV, dropin_dir / '90-yeobaek-recovery.conf',
                     address, password, host, service)
    except BaseException as error:
        if isinstance(error, (RuntimeError, ValueError)):
            raise
        raise ValueError('메일 설정 실패; 기존 서비스 설정을 유지하거나 복원했습니다 (' +
                         type(error).__name__ + ')') from None
    print('메일 설정 완료. 전용 Gmail에서 시험 메일 수신을 확인하세요.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(type(error).__name__ + ': ' + str(error).split('(')[0])
        raise SystemExit(1)
