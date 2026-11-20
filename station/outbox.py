import sqlite3
from typing import Callable


class Outbox:
    def __init__(self, connection: sqlite3.Connection, before_commit: Callable[[], None] | None = None):
        self.connection = connection
        self.before_commit = before_commit
        connection.execute('''
            CREATE TABLE IF NOT EXISTS issued_envelopes (
                frozen_id INTEGER PRIMARY KEY REFERENCES frozen_revisions(id),
                raw BLOB NOT NULL
            )
        ''')

    def save(self, frozen_id: int, raw: bytes) -> bytes:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            row = db.execute(
                'SELECT raw FROM issued_envelopes WHERE frozen_id = ?', (frozen_id,)
            ).fetchone()
            if row is not None:
                if row[0] != raw:
                    raise ValueError('frozen revision already has a different issued envelope')
                return row[0]
            db.execute('INSERT INTO issued_envelopes (frozen_id, raw) VALUES (?, ?)', (frozen_id, raw))
            if self.before_commit is not None:
                self.before_commit()
        return raw

    def get(self, frozen_id: int) -> bytes:
        if type(frozen_id) is not int or not 0 < frozen_id <= 2**63 - 1:
            raise KeyError(frozen_id)
        row = self.connection.execute(
            'SELECT raw FROM issued_envelopes WHERE frozen_id = ?', (frozen_id,)
        ).fetchone()
        if row is None:
            raise KeyError(frozen_id)
        return row[0]
