from dataclasses import dataclass
import sqlite3

from station.envelope import V1Envelope, decode_envelope


@dataclass(frozen=True)
class AcceptedEnvelope:
    admission_id: int
    raw: bytes
    envelope: V1Envelope


def _accepted(admission_id: int, raw: bytes) -> AcceptedEnvelope:
    return AcceptedEnvelope(admission_id, raw, decode_envelope(raw))


class AdmissionArchive:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        connection.execute('''
            CREATE TABLE IF NOT EXISTS admitted_envelopes (
                id INTEGER PRIMARY KEY,
                station TEXT NOT NULL,
                frozen_id INTEGER NOT NULL,
                content BLOB NOT NULL,
                raw BLOB NOT NULL,
                UNIQUE (station, frozen_id)
            )
        ''')

    def bind_first(self, source: tuple[str, int], content: bytes, raw: bytes) -> AcceptedEnvelope:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            first = db.execute(
                'SELECT id, content, raw FROM admitted_envelopes WHERE station = ? AND frozen_id = ?',
                source,
            ).fetchone()
            if first is not None:
                admission_id, first_content, first_raw = first
                if first_content != content:
                    raise ValueError('conflicting envelope for an admitted source revision')
                return _accepted(admission_id, first_raw)
            result = db.execute(
                'INSERT INTO admitted_envelopes (station, frozen_id, content, raw) VALUES (?, ?, ?, ?)',
                (*source, content, raw),
            )
            return _accepted(result.lastrowid, raw)

    def find(self, admission_id: int) -> AcceptedEnvelope:
        if type(admission_id) is not int or not 0 < admission_id <= 2**63 - 1:
            raise KeyError(admission_id)
        row = self.connection.execute(
            'SELECT id, raw FROM admitted_envelopes WHERE id = ?', (admission_id,)
        ).fetchone()
        if row is None:
            raise KeyError(admission_id)
        return _accepted(*row)
