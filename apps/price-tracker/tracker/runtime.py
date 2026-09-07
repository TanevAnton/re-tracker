"""Local process locking and durable, immutable report snapshots."""
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3


@contextmanager
def lock(database):
    path = Path(str(database)+'.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as handle:
        try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc: raise RuntimeError('Another tracker process holds the database lock') from exc
        try: yield
        finally: fcntl.flock(handle,fcntl.LOCK_UN)


def backup(db, path):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path)) as target: db.backup(target)


def point_output(output, snapshot):
    output = Path(output).absolute()
    output.parent.mkdir(parents=True,exist_ok=True)
    link = output.with_name(output.name+'.next')
    if link.is_symlink(): link.unlink()
    link.symlink_to(Path(snapshot).absolute(), target_is_directory=True)
    if output.exists() and not output.is_symlink():
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        output.rename(output.with_name(output.name+'.previous-'+stamp))
    os.replace(link, output)
