from dataclasses import dataclass
import json
import sqlite3

from tray.roster import FrozenRoster

from .amend import apply_amendments
from .measure import Measurement, encode_measurement, parse_measurement


@dataclass(frozen=True)
class ReadingRevision:
    revision_id: int
    station: str
    roster_id: str
    tray: str
    round_id: str
    previous_id: int | None
    records: tuple[tuple[str, Measurement], ...]


@dataclass(frozen=True)
class FrozenRevision:
    frozen_id: int
    reading: ReadingRevision


_READING_COLUMNS = 'r.id, r.station, r.roster_id, r.tray, r.round_id, r.previous_id, r.records'


def _reading(row: tuple) -> ReadingRevision:
    revision_id, station, roster_id, tray, round_id, previous_id, encoded = row
    records = tuple((label, parse_measurement(value)) for label, value in json.loads(encoded))
    return ReadingRevision(revision_id, station, roster_id, tray, round_id, previous_id, records)


def _require_lookup_id(value: int) -> None:
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise KeyError(value)


class ObservationJournal:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('''
            CREATE TABLE IF NOT EXISTS reading_revisions (
                id INTEGER PRIMARY KEY,
                station TEXT NOT NULL,
                roster_id TEXT NOT NULL,
                tray TEXT NOT NULL,
                round_id TEXT NOT NULL,
                previous_id INTEGER REFERENCES reading_revisions(id),
                records TEXT NOT NULL
            )
        ''')
        connection.execute('''
            CREATE TABLE IF NOT EXISTS reading_heads (
                station TEXT NOT NULL,
                roster_id TEXT NOT NULL,
                revision_id INTEGER NOT NULL REFERENCES reading_revisions(id),
                PRIMARY KEY (station, roster_id)
            )
        ''')
        connection.execute('''
            CREATE TABLE IF NOT EXISTS frozen_revisions (
                id INTEGER PRIMARY KEY,
                revision_id INTEGER NOT NULL UNIQUE REFERENCES reading_revisions(id)
            )
        ''')

    def current_revision(self, station: str, roster_id: str) -> ReadingRevision | None:
        row = self.connection.execute(
            f'''SELECT {_READING_COLUMNS} FROM reading_heads h
                JOIN reading_revisions r ON r.id = h.revision_id
                WHERE h.station = ? AND h.roster_id = ?''',
            (station, roster_id),
        ).fetchone()
        return _reading(row) if row is not None else None

    def load_revision(self, revision_id: int) -> ReadingRevision:
        _require_lookup_id(revision_id)
        row = self.connection.execute(
            f'SELECT {_READING_COLUMNS} FROM reading_revisions r WHERE r.id = ?',
            (revision_id,),
        ).fetchone()
        if row is None:
            raise KeyError(revision_id)
        return _reading(row)

    def append_revision(
        self, station: str, roster: FrozenRoster, updates: tuple[tuple[str, Measurement], ...]
    ) -> int:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            previous = self.current_revision(station, roster.roster_id)
            records = apply_amendments(previous.records if previous else (), updates)
            encoded = json.dumps([[label, encode_measurement(value)] for label, value in records])
            result = db.execute(
                '''INSERT INTO reading_revisions (station, roster_id, tray, round_id, previous_id, records)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (station, roster.roster_id, roster.tray, roster.round_id,
                 previous.revision_id if previous else None, encoded),
            )
            revision_id = result.lastrowid
            db.execute(
                '''INSERT INTO reading_heads (station, roster_id, revision_id) VALUES (?, ?, ?)
                   ON CONFLICT (station, roster_id) DO UPDATE SET revision_id = excluded.revision_id''',
                (station, roster.roster_id, revision_id),
            )
        return revision_id

    def save_frozen(self, revision_id: int) -> int:
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            self.load_revision(revision_id)
            db.execute(
                '''INSERT INTO frozen_revisions (revision_id) VALUES (?)
                   ON CONFLICT (revision_id) DO NOTHING''',
                (revision_id,),
            )
            frozen_id = db.execute(
                'SELECT id FROM frozen_revisions WHERE revision_id = ?', (revision_id,)
            ).fetchone()[0]
        return frozen_id

    def load_frozen(self, frozen_id: int) -> FrozenRevision:
        _require_lookup_id(frozen_id)
        row = self.connection.execute(
            f'''SELECT f.id, {_READING_COLUMNS} FROM frozen_revisions f
                JOIN reading_revisions r ON r.id = f.revision_id WHERE f.id = ?''',
            (frozen_id,),
        ).fetchone()
        if row is None:
            raise KeyError(frozen_id)
        return FrozenRevision(row[0], _reading(row[1:]))
