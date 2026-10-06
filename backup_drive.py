import os
import re
import json
import sqlite3
import subprocess
import tempfile
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from contextlib import closing

os.umask(0o077)
zone = ZoneInfo("Asia/Seoul")
now = datetime.now(zone)
source = Path("/opt/yeobaek/data/novel.sqlite3")
name = now.strftime("yeobaek-daily-%Y%m%d-%H%M%S-%f.sqlite3")
remote = "yeobaek_crypt:"
config = "/root/.config/rclone/rclone.conf"

def run(*args, capture=False):
    return subprocess.run(
        ["rclone", "--config", config, *args],
        check=True, timeout=600,
        capture_output=capture, text=True
    )

def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def check_db(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("Database integrity check failed")

with tempfile.TemporaryDirectory(prefix="yeobaek-drive-") as folder:
    backup = Path(folder) / name
    restored = Path(folder) / "restored.sqlite3"

    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(backup)) as dst:
            src.backup(dst)

    check_db(backup)
    run("copyto", str(backup), remote + name)
    run("copyto", remote + name, str(restored))

    if digest(backup) != digest(restored):
        raise RuntimeError("Downloaded backup does not match")
    check_db(restored)

    print("BACKUP AND RESTORE CHECK OK:", name, flush=True)

    cutoff = now - timedelta(days=30)
    items = json.loads(run("lsjson", remote, "--files-only", capture=True).stdout)
    pattern = r"yeobaek-daily-(\d{8}-\d{6}-\d{6})\.sqlite3"

    for item in items:
        path = item.get("Path", "")
        match = re.fullmatch(pattern, path)
        if not match:
            continue
        try:
            created = datetime.strptime(
                match.group(1), "%Y%m%d-%H%M%S-%f"
            ).replace(tzinfo=zone)
        except ValueError:
            continue
        if created < cutoff:
            run("deletefile", remote + path)
            print("REMOVED OLD BACKUP:", path, flush=True)

print("DAILY BACKUP COMPLETE", flush=True)
