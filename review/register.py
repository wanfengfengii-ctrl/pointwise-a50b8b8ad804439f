from dataclasses import asdict, dataclass
import json
import sqlite3
from typing import Callable

from observations.measure import encode_measurement, parse_measurement

from .coverage import Coverage
from .totals import StationTotals


@dataclass(frozen=True)
class ReportSource:
    admission_id: int
    station: str
    frozen_id: int


@dataclass(frozen=True)
class ReviewBody:
    tray: str
    round_id: str
    roster_id: str
    sources: tuple[ReportSource, ...]
    coverage: Coverage
    stations: tuple[StationTotals, ...]


@dataclass(frozen=True)
class ReviewReport:
    report_id: int
    body: ReviewBody


@dataclass(frozen=True)
class ReviewReceipt:
    receipt_id: int
    report_id: int


def _encode_body(body: ReviewBody) -> str:
    data = {
        'tray': body.tray,
        'round_id': body.round_id,
        'roster_id': body.roster_id,
        'sources': [asdict(source) for source in body.sources],
        'coverage': asdict(body.coverage),
        'stations': [
            {'station': total.station, 'count': total.count,
             'total': encode_measurement(total.total), 'mean': encode_measurement(total.mean)}
            for total in body.stations
        ],
    }
    return json.dumps(data, separators=(',', ':'))


def _decode_body(encoded: str) -> ReviewBody:
    data = json.loads(encoded)
    stations = tuple(
        StationTotals(row['station'], row['count'], parse_measurement(row['total']),
                      parse_measurement(row['mean']))
        for row in data['stations']
    )
    coverage = data['coverage']
    return ReviewBody(
        data['tray'], data['round_id'], data['roster_id'],
        tuple(ReportSource(**row) for row in data['sources']),
        Coverage(tuple(coverage['covered']), tuple(coverage['repeated']),
                 tuple(coverage['uninspected'])),
        stations,
    )


class ReportRegister:
    def __init__(self, connection: sqlite3.Connection, before_commit: Callable[[], None] | None = None):
        self.connection = connection
        self.before_commit = before_commit
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY,
                body TEXT NOT NULL
            )
        ''')
        connection.execute('''
            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY,
                report_id INTEGER NOT NULL UNIQUE REFERENCES reports(id)
            )
        ''')

    def commit(self, body: ReviewBody) -> tuple[ReviewReport, ReviewReceipt]:
        encoded = _encode_body(body)
        db = self.connection
        db.execute('BEGIN IMMEDIATE')
        with db:
            report_id = db.execute('INSERT INTO reports (body) VALUES (?)', (encoded,)).lastrowid
            receipt_id = db.execute(
                'INSERT INTO receipts (report_id) VALUES (?)', (report_id,)
            ).lastrowid
            if self.before_commit is not None:
                self.before_commit()
        return ReviewReport(report_id, body), ReviewReceipt(receipt_id, report_id)

    def load(self, report_id: int) -> tuple[ReviewReport, ReviewReceipt]:
        if type(report_id) is not int or not 0 < report_id <= 2**63 - 1:
            raise KeyError(report_id)
        row = self.connection.execute(
            '''SELECT p.body, r.id FROM reports p JOIN receipts r ON r.report_id = p.id
               WHERE p.id = ?''',
            (report_id,),
        ).fetchone()
        if row is None:
            raise KeyError(report_id)
        body, receipt_id = row
        return ReviewReport(report_id, _decode_body(body)), ReviewReceipt(receipt_id, report_id)

    def counts(self) -> tuple[int, int]:
        return self.connection.execute(
            'SELECT (SELECT count(*) FROM reports), (SELECT count(*) FROM receipts)'
        ).fetchone()
