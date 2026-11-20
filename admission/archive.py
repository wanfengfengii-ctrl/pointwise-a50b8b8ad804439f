from dataclasses import dataclass
import sqlite3

from station.envelope import V1Envelope, decode_envelope
from station.envelope_v2 import V2Envelope, decode_envelope_v2


@dataclass(frozen=True)
class AcceptedEnvelope:
    admission_id: int
    raw: bytes
    envelope: V1Envelope


@dataclass(frozen=True)
class AcceptedV2:
    admission_id: int
    raw: bytes
    envelope: V2Envelope


def _accepted(admission_id: int, raw: bytes) -> AcceptedEnvelope:
    return AcceptedEnvelope(admission_id, raw, decode_envelope(raw))


def _accepted_v2(admission_id: int, raw: bytes, roster) -> AcceptedV2:
    return AcceptedV2(admission_id, raw, decode_envelope_v2(raw, roster))


class AdmissionArchive:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        db = self.connection
        db.execute('''
            CREATE TABLE IF NOT EXISTS admitted_envelopes (
                id INTEGER PRIMARY KEY,
                station TEXT NOT NULL,
                frozen_id INTEGER NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                content BLOB NOT NULL,
                raw BLOB NOT NULL,
                UNIQUE (version, station, frozen_id)
            )
        ''')
        columns = {row[1] for row in db.execute('PRAGMA table_info(admitted_envelopes)')}
        if 'version' not in columns:
            # 既有 V1 台账迁移：重建带版本列的表，原件、接纳号与顺序全部保留。
            db.execute('BEGIN IMMEDIATE')
            with db:
                db.execute('ALTER TABLE admitted_envelopes RENAME TO admitted_envelopes_v1_legacy')
                db.execute('''
                    CREATE TABLE admitted_envelopes (
                        id INTEGER PRIMARY KEY,
                        station TEXT NOT NULL,
                        frozen_id INTEGER NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1,
                        content BLOB NOT NULL,
                        raw BLOB NOT NULL,
                        UNIQUE (version, station, frozen_id)
                    )
                ''')
                db.execute('''
                    INSERT INTO admitted_envelopes (id, station, frozen_id, version, content, raw)
                    SELECT id, station, frozen_id, 1, content, raw FROM admitted_envelopes_v1_legacy
                ''')
                db.execute('DROP TABLE admitted_envelopes_v1_legacy')
        db.execute('''
            CREATE TABLE IF NOT EXISTS admission_id_sequence (
                marker INTEGER PRIMARY KEY CHECK (marker = 1),
                next_id INTEGER NOT NULL
            )
        ''')

    def _next_admission_id(self) -> int:
        db = self.connection
        db.execute(
            'INSERT INTO admission_id_sequence (marker, next_id) VALUES (1, 1) '
            'ON CONFLICT(marker) DO NOTHING'
        )
        row = db.execute('SELECT next_id FROM admission_id_sequence WHERE marker = 1').fetchone()
        next_id = row[0]
        while db.execute(
            'SELECT 1 FROM admitted_envelopes WHERE id = ?', (next_id,)
        ).fetchone() is not None:
            next_id += 1
        db.execute('UPDATE admission_id_sequence SET next_id = ? WHERE marker = 1', (next_id + 1,))
        return next_id

    def bind_first(self, source: tuple[str, int], content: bytes, raw: bytes) -> AcceptedEnvelope:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        try:
            with db:
                first = db.execute(
                    '''SELECT id, content, raw FROM admitted_envelopes
                       WHERE version = 1 AND station = ? AND frozen_id = ?''',
                    source,
                ).fetchone()
                if first is not None:
                    admission_id, first_content, first_raw = first
                    if first_content != content:
                        raise ValueError('conflicting envelope for an admitted source revision')
                    return _accepted(admission_id, first_raw)
                admission_id = self._next_admission_id()
                db.execute(
                    '''INSERT INTO admitted_envelopes
                       (id, station, frozen_id, version, content, raw)
                       VALUES (?, ?, ?, 1, ?, ?)''',
                    (admission_id, *source, content, raw),
                )
                return _accepted(admission_id, raw)
        except sqlite3.IntegrityError as exc:
            raise ValueError('conflicting envelope for an admitted source revision') from exc

    def bind_first_v2(
        self, source: tuple[str, int], content: bytes, raw: bytes, roster
    ) -> AcceptedV2:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        try:
            with db:
                first = db.execute(
                    '''SELECT id, content, raw FROM admitted_envelopes
                       WHERE version = 2 AND station = ? AND frozen_id = ?''',
                    source,
                ).fetchone()
                if first is not None:
                    admission_id, first_content, first_raw = first
                    if first_content != content:
                        raise ValueError('conflicting V2 envelope for an admitted source revision')
                    return _accepted_v2(admission_id, first_raw, roster)
                admission_id = self._next_admission_id()
                db.execute(
                    '''INSERT INTO admitted_envelopes
                       (id, station, frozen_id, version, content, raw)
                       VALUES (?, ?, ?, 2, ?, ?)''',
                    (admission_id, *source, content, raw),
                )
                return _accepted_v2(admission_id, raw, roster)
        except sqlite3.IntegrityError as exc:
            raise ValueError('conflicting V2 envelope for an admitted source revision') from exc

    def find(self, admission_id: int) -> AcceptedEnvelope:
        if type(admission_id) is not int or not 0 < admission_id <= 2**63 - 1:
            raise KeyError(admission_id)
        row = self.connection.execute(
            'SELECT id, raw FROM admitted_envelopes WHERE id = ? AND version = 1',
            (admission_id,),
        ).fetchone()
        if row is None:
            raise KeyError(admission_id)
        return _accepted(*row)

    def find_v2(self, admission_id: int, roster) -> AcceptedV2:
        if type(admission_id) is not int or not 0 < admission_id <= 2**63 - 1:
            raise KeyError(admission_id)
        row = self.connection.execute(
            'SELECT id, raw FROM admitted_envelopes WHERE id = ? AND version = 2',
            (admission_id,),
        ).fetchone()
        if row is None:
            raise KeyError(admission_id)
        return _accepted_v2(*row, roster)

    def version_of(self, admission_id: int) -> int | None:
        """返回接纳号版别；号不存在时为 None。供选件区分 V1/V2。"""
        if type(admission_id) is not int or not 0 < admission_id <= 2**63 - 1:
            return None
        row = self.connection.execute(
            'SELECT version FROM admitted_envelopes WHERE id = ?', (admission_id,)
        ).fetchone()
        return None if row is None else row[0]
