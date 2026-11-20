from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from typing import Callable

from admission import AdmissionArchive, accept_v1
from observations import ObservationJournal, freeze_station, record_readings
from observations.measure import encode_measurement
from review import ReportRegister, publish_v1, read_v1
from station import Outbox, issue_v1
from tray import PhysicalSlot, RosterCatalog, freeze_tray


STATIONS = ('A', 'B')
CENTER_FILENAME = 'center.sqlite3'
CATALOG_FILENAME = 'rosters.sqlite3'


class InjectedCommitError(sqlite3.OperationalError):
    pass


class FailOnce:
    def __init__(self):
        self.inspect = None
        self.armed = False

    def arm(self, inspect: Callable[[], None] | None = None) -> None:
        self.inspect = inspect
        self.armed = True

    def __call__(self) -> None:
        if self.armed:
            self.armed = False
            if self.inspect is not None:
                self.inspect()
            raise InjectedCommitError('injected failure before commit')


@dataclass
class StationStore:
    journal: ObservationJournal
    outbox: Outbox


@dataclass
class ShiftStores:
    catalog: RosterCatalog
    archive: AdmissionArchive
    reports: ReportRegister
    stations: dict[str, StationStore]
    station_connections: ExitStack
    center_connections: ExitStack

    def close_stations(self) -> None:
        self.station_connections.close()

    def close_center(self) -> None:
        self.center_connections.close()


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute('PRAGMA foreign_keys = ON')
    return connection


@contextmanager
def open_shift(root: Path, *, report_before_commit=None, outbox_before_commit=None):
    root.mkdir(parents=True, exist_ok=True)
    with ExitStack() as connections:
        catalog_db = connections.enter_context(closing(connect(root / CATALOG_FILENAME)))
        center_stack = connections.enter_context(ExitStack())
        center_db = center_stack.enter_context(closing(connect(root / CENTER_FILENAME)))
        station_stack = connections.enter_context(ExitStack())
        stations = {}
        for station in STATIONS:
            db = station_stack.enter_context(closing(connect(root / f'station-{station}.sqlite3')))
            stations[station] = StationStore(
                ObservationJournal(db), Outbox(db, before_commit=outbox_before_commit)
            )
        yield ShiftStores(
            RosterCatalog(catalog_db), AdmissionArchive(center_db),
            ReportRegister(center_db, before_commit=report_before_commit), stations,
            station_stack, center_stack,
        )


def register_tray(stores: ShiftStores, labels=('a', 'b', 'c'), *, tray='T-01', round_id='R-01'):
    slots = (PhysicalSlot(index // 6 + 1, index % 6 + 1, label) for index, label in enumerate(labels))
    return freeze_tray(stores.catalog, tray, round_id, slots)


def seal_and_issue(stores: ShiftStores, station: str, revision_id: int) -> bytes:
    source = stores.stations[station]
    frozen_id = freeze_station(source.journal, station, revision_id)
    return issue_v1(source.journal, stores.catalog, source.outbox, frozen_id)


def issue_readings(stores: ShiftStores, station: str, roster_id: str, readings) -> bytes:
    journal = stores.stations[station].journal
    revision_id = record_readings(journal, stores.catalog, station, roster_id, readings)
    return seal_and_issue(stores, station, revision_id)


def handoff(stores: ShiftStores, station: str, roster_id: str, readings):
    raw = issue_readings(stores, station, roster_id, readings)
    return accept_v1(stores.archive, stores.catalog, roster_id, raw)


def load_example() -> dict:
    path = Path(__file__).resolve().parent / 'examples' / 'shift.json'
    return json.loads(path.read_text(encoding='utf-8'))


def initialize(root: Path) -> str:
    sample = load_example()
    with open_shift(root) as stores:
        roster = stores.catalog.find_tray(sample['tray'], sample['round_id'])
        if roster is None:
            slots = (PhysicalSlot(*entry) for entry in sample['slots'])
            roster_id = freeze_tray(stores.catalog, sample['tray'], sample['round_id'], slots)
        else:
            roster_id = roster.roster_id
        for station, readings in sample['readings'].items():
            journal = stores.stations[station].journal
            if journal.current_revision(station, roster_id) is None:
                record_readings(journal, stores.catalog, station, roster_id, readings)
        return roster_id


def demo() -> None:
    sample = load_example()
    failure = FailOnce()
    with TemporaryDirectory(prefix='ceramic-shift-') as directory:
        root = Path(directory)
        roster_id = initialize(root)
        with open_shift(root, report_before_commit=failure) as stores:
            selected_ids = []
            for station in STATIONS:
                current = stores.stations[station].journal.current_revision(station, roster_id)
                raw = seal_and_issue(stores, station, current.revision_id)
                accepted = accept_v1(stores.archive, stores.catalog, roster_id, raw)
                selected_ids.append(accepted.admission_id)
            stores.close_stations()
            failure.arm()
            try:
                publish_v1(stores.archive, stores.catalog, stores.reports, *selected_ids)
            except InjectedCommitError:
                if stores.reports.counts() != (0, 0):
                    raise AssertionError('failed publication left a report or receipt')
            else:
                raise AssertionError('expected an injected commit failure')
            published = publish_v1(stores.archive, stores.catalog, stores.reports, *selected_ids)
            if stores.reports.counts() != (1, 1):
                raise AssertionError('retry must commit one report and one receipt')
            stores.close_center()

        with closing(connect(root / CENTER_FILENAME)) as reopened:
            loaded = read_v1(ReportRegister(reopened), published[0].report_id)
        if loaded != published:
            raise AssertionError('reopened center returned different stored results')

        report, receipt = loaded
        coverage = report.body.coverage
        actual = {
            'covered': list(coverage.covered),
            'repeated': list(coverage.repeated),
            'uninspected': list(coverage.uninspected),
            'counts': [coverage.covered_count, coverage.repeated_count, coverage.uninspected_count],
            'means': [encode_measurement(total.mean) for total in report.body.stations],
        }
        downstream = {'resample': list(coverage.uninspected)}
        if actual != sample['expected'] or downstream != sample['next_shift_expected']:
            raise AssertionError('stored report differs from the independently calculated example')
        if [source.admission_id for source in report.body.sources] != selected_ids:
            raise AssertionError('stored report has different admission parents')
        print(f'Report {report.report_id}, receipt {receipt.receipt_id}, resample {coverage.uninspected}')
        scenario = {
            'case_id': 'N6',
            'input': {'slots': sample['slots'], 'readings': sample['readings'], 'admissions': selected_ids},
            'expected': sample['expected'],
            'actual': actual,
            'downstream_expected': sample['next_shift_expected'],
            'downstream_actual': downstream,
            'code_paths': [
                'station/issue.py', 'admission/accept.py', 'review/coverage.py',
                'review/totals.py', 'review/register.py', 'review/readback.py',
            ],
            'oracle': '甲检 a、b，乙仅检 b；逐槽核对得补测 c，均值手算为 (0+3)/2 和 1/1。',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False))


if __name__ == '__main__':
    demo()
