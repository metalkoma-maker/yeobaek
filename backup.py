import os
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from contextlib import closing

os.umask(0o077)

source = Path("/opt/yeobaek/data/novel.sqlite3")
folder = Path("/var/backups/yeobaek")
folder.mkdir(parents=True, exist_ok=True, mode=0o700)

now = datetime.now(ZoneInfo("Asia/Seoul"))
target = folder / f"yeobaek-{now:%Y%m%d-%H%M%S-%f}.sqlite3"
temporary = target.with_suffix(".tmp")

try:
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(temporary)) as dst:
            src.backup(dst)
            result = dst.execute("PRAGMA integrity_check").fetchall()
            if result != [("ok",)]:
                raise RuntimeError("Backup integrity check failed")
    temporary.replace(target)
except Exception:
    temporary.unlink(missing_ok=True)
    raise

cutoff = (now - timedelta(days=7)).timestamp()
for old in folder.glob("yeobaek-*.sqlite3"):
    if old.stat().st_mtime < cutoff:
        old.unlink()

print(f"BACKUP OK: {target}", flush=True)
