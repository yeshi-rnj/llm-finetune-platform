import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    def __init__(self, path):
        self.path = str(path)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except BaseException:
            try:
                c.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            c.close()


def migrate(db):
    """Apply pending NNN_name.sql files in order. Returns list of applied versions."""
    applied = []
    with db.conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        done = {r["version"] for r in c.execute("SELECT version FROM schema_migrations")}
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if not re.match(r"^\d{3}_[a-z0-9_]+\.sql$", f.name) or f.stem in done:
            continue
        statements = [s.strip() for s in f.read_text(encoding="utf-8").split(";\n") if s.strip()]
        with db.conn() as c:
            for s in statements:
                c.execute(s)
            c.execute("INSERT INTO schema_migrations(version) VALUES (?)", (f.stem,))
        applied.append(f.stem)
    return applied
