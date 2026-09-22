"""Stream a private recovery archive, including authoritative runtime ledgers.

Executed over SSH with the standard library; no installed collector is needed.
SQLite snapshots are individually consistent, not one cross-file transaction.
The job index is captured before quota state so its discoveries cannot precede
their already reserved credits in the snapshots.
"""
from contextlib import closing, contextmanager
from pathlib import Path
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile


def sqlite_snapshot(source, target):
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as reader, \
         closing(sqlite3.connect(target)) as writer:
        reader.backup(writer)


@contextmanager
def decision_lock(path):
    # The backup runs as the SSH user, who can read the data checkout but not
    # write the service account's lock file. flock needs no write access, so an
    # existing lock is opened read-only; msvcrt locking does need it.
    lock = path.with_suffix('.lock')
    mode = 'rb' if os.name != 'nt' and lock.exists() else 'a+b'
    with lock.open(mode) as handle:
        if os.name == 'nt':
            import msvcrt
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def archive(data, index, runtime, output):
    with tempfile.TemporaryDirectory(prefix='jobdisco-snapshot-') as folder:
        temporary = Path(folder)
        snapshots = {'sqlite/job_discovery.sqlite': index,
                     f'{data.name}/operational/jsearch_usage.sqlite': runtime / 'jsearch_usage.sqlite',
                     f'{data.name}/operational/source_access.sqlite': runtime / 'source_access.sqlite'}
        for name, source in snapshots.items():
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            sqlite_snapshot(source, target)
        ledger = data / 'operational/applications.ndjson'
        with decision_lock(ledger):
            shutil.copyfile(ledger, temporary / data.name / 'operational/applications.ndjson')
        staged = set(snapshots) | {f'{data.name}/operational/applications.ndjson'}

        def retained(info):
            if '.git' in Path(info.name).parts or info.name in staged:
                return None
            if any(info.name == name + suffix for name in snapshots for suffix in ('-wal', '-shm', '-journal')):
                return None
            return info

        with tarfile.open(fileobj=output, mode='w|gz') as stream:
            stream.add(data, arcname=data.name, filter=retained)
            for name in sorted(staged):
                stream.add(temporary / name, arcname=name)


if __name__ == '__main__':
    archive(*(Path(value) for value in sys.argv[1:4]), sys.stdout.buffer)
