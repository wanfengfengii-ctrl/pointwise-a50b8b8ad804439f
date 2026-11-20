import json
import sqlite3

from .layout import PhysicalSlot
from .roster import FrozenRoster, build_roster


class RosterCatalog:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        connection.execute('''
            CREATE TABLE IF NOT EXISTS rosters (
                roster_id TEXT PRIMARY KEY NOT NULL,
                tray TEXT NOT NULL,
                round_id TEXT NOT NULL,
                layout TEXT NOT NULL,
                UNIQUE (tray, round_id)
            )
        ''')

    def save_frozen(self, roster: FrozenRoster) -> str:
        layout = json.dumps([[slot.row, slot.column, slot.label] for slot in roster.slots])
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            existing = self.find_tray(roster.tray, roster.round_id)
            if existing is not None:
                if existing != roster:
                    raise ValueError('tray and round already have a different frozen roster')
                return existing.roster_id
            db.execute(
                'INSERT INTO rosters (roster_id, tray, round_id, layout) VALUES (?, ?, ?, ?)',
                (roster.roster_id, roster.tray, roster.round_id, layout),
            )
        return roster.roster_id

    @staticmethod
    def _restore(row: tuple) -> FrozenRoster:
        roster_id, tray, round_id, encoded = row
        roster = build_roster(tray, round_id, (PhysicalSlot(*slot) for slot in json.loads(encoded)))
        if roster.roster_id != roster_id:
            raise ValueError('stored roster does not match its frozen identity')
        return roster

    def load_frozen(self, roster_id: str) -> FrozenRoster:
        if not isinstance(roster_id, str):
            raise KeyError(roster_id)
        row = self.connection.execute(
            'SELECT roster_id, tray, round_id, layout FROM rosters WHERE roster_id = ?',
            (roster_id,),
        ).fetchone()
        if row is None:
            raise KeyError(roster_id)
        return self._restore(row)

    def find_tray(self, tray: str, round_id: str) -> FrozenRoster | None:
        row = self.connection.execute(
            'SELECT roster_id, tray, round_id, layout FROM rosters WHERE tray = ? AND round_id = ?',
            (tray, round_id),
        ).fetchone()
        return self._restore(row) if row is not None else None
