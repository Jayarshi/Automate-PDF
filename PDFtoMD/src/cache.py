"""Crash-safe output publication, content hashes, a process lock and SQLite cache."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def process_lock(path: Path):
    import fcntl  # Linux/macOS, matching the ScanTailor CLI deployment target.

    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another PDFtoMD process is using this output/cache") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class Cache:
    def __init__(self, path: Path, namespace: str = ""):
        self.namespace = namespace
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                name TEXT PRIMARY KEY, input_hash TEXT NOT NULL,
                signature TEXT NOT NULL, artifacts TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS corrections (
                key TEXT PRIMARY KEY, answer TEXT NOT NULL
            );
        """)

    def valid(self, name, input_hash, signature, output_dir: Path):
        row = self.connection.execute(
            "SELECT input_hash, signature, artifacts FROM documents WHERE name=?", (name,)
        ).fetchone()
        if not row or row[:2] != (input_hash, signature):
            return False
        try:
            artifacts = json.loads(row[2])
            if not isinstance(artifacts, dict) or not artifacts:
                return False
            for filename, expected in artifacts.items():
                if Path(filename).name != filename:
                    return False
                path = output_dir / filename
                if not path.is_file() or digest(path) != expected:
                    return False
            return True
        except (OSError, ValueError):
            return False

    def record(self, name, input_hash, signature, artifacts):
        hashes = {path.name: digest(path) for path in artifacts}
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?)",
                                    (name, input_hash, signature, json.dumps(hashes)))

    def get_correction(self, key):
        row = self.connection.execute("SELECT answer FROM corrections WHERE key=?",
                                      (self.namespace + key,)).fetchone()
        return row[0] if row else None

    def put_correction(self, key, answer):
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO corrections VALUES (?, ?)",
                                    (self.namespace + key, answer))

    def close(self):
        self.connection.close()
