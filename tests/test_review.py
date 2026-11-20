from contextlib import closing
from fractions import Fraction
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from admission import accept_v1
from observations import freeze_station, get_frozen_revision, record_readings
from review import ReportRegister, publish_v1, read_v1
from review.coverage import Coverage
from shift_example import (
    CENTER_FILENAME, FailOnce, InjectedCommitError, connect, handoff, initialize,
    open_shift, register_tray, seal_and_issue,
)
from station import decode_envelope


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.failure = FailOnce()
        self.stores = self.enterContext(open_shift(self.root, report_before_commit=self.failure))
        self.roster_id = register_tray(self.stores)

    def pair(self, alpha, beta, roster_id=None):
        roster_id = self.roster_id if roster_id is None else roster_id
        first = handoff(self.stores, 'A', roster_id, alpha)
        second = handoff(self.stores, 'B', roster_id, beta)
        return first.admission_id, second.admission_id

    def publish(self, first_id, second_id):
        return publish_v1(self.stores.archive, self.stores.catalog, self.stores.reports, first_id, second_id)

    def reopened_report(self, report_id):
        with closing(connect(self.root / CENTER_FILENAME)) as db:
            return read_v1(ReportRegister(db), report_id)

    def test_offline_overlap(self):
        parents = self.pair([('a', 0), ('b', 3)], [('b', 1), ('c', None)])
        self.stores.close_stations()
        for source in self.stores.stations.values():
            with self.assertRaises(sqlite3.ProgrammingError):
                source.journal.connection.execute('SELECT 1')
        report, receipt = self.publish(*parents)
        self.assertEqual(report.body.roster_id, self.roster_id)
        self.assertEqual(report.body.coverage, Coverage(('a', 'b'), ('b',), ('c',)))
        self.assertEqual(tuple(source.admission_id for source in report.body.sources), parents)
        self.assertEqual([(row.station, row.count, row.total, row.mean) for row in report.body.stations],
                         [('A', 2, Fraction(3), Fraction(3, 2)), ('B', 1, Fraction(1), Fraction(1))])
        self.assertEqual(receipt.report_id, report.report_id)
        self.stores.close_center()
        self.assertEqual(self.reopened_report(report.report_id), (report, receipt))

    def test_ordered_overlap(self):
        roster_id = register_tray(self.stores, ('f', 'c', 'e', 'd', 'a', 'b'), tray='ordered')
        parents = self.pair([('b', 3), ('c', 2), ('d', 1)], [('b', 6), ('a', 4), ('d', 5)], roster_id)
        self.assertEqual(self.stores.archive.find(parents[0]).envelope.summary.slots, ('c', 'd', 'b'))
        self.assertEqual(self.stores.archive.find(parents[1]).envelope.summary.slots, ('d', 'a', 'b'))
        self.stores.close_stations()
        report, receipt = self.publish(*parents)
        coverage = report.body.coverage
        self.assertEqual(coverage, Coverage(('c', 'd', 'a', 'b'), ('d', 'b'), ('f', 'e')))
        self.assertEqual((coverage.covered_count, coverage.repeated_count, coverage.uninspected_count), (4, 2, 2))
        self.stores.close_center()
        self.assertEqual(self.reopened_report(report.report_id), (report, receipt))

    def test_exact_mean(self):
        parents = self.pair([('a', 0), ('b', [1, 5]), ('c', None)], [('b', [1, 3])])
        left = self.stores.archive.find(parents[0]).envelope.summary
        right = self.stores.archive.find(parents[1]).envelope.summary
        self.assertEqual((left.slots, left.count, left.total), (('a', 'b'), 2, Fraction(1, 5)))
        self.assertEqual((right.slots, right.count, right.total), (('b',), 1, Fraction(1, 3)))
        self.stores.close_stations()
        report, receipt = self.publish(*parents)
        self.assertEqual([row.mean for row in report.body.stations], [Fraction(1, 10), Fraction(1, 3)])
        self.stores.close_center()
        restored, restored_receipt = self.reopened_report(report.report_id)
        self.assertEqual([row.mean for row in restored.body.stations], [Fraction(1, 10), Fraction(1, 3)])
        self.assertEqual(restored_receipt, receipt)

    def test_mismatched_pair(self):
        other_id = register_tray(self.stores, tray='other-tray')
        self.assertNotEqual(self.roster_id, other_id)
        first = handoff(self.stores, 'A', self.roster_id, [('a', 1)])
        wrong = handoff(self.stores, 'B', other_id, [('a', 1)])
        right = handoff(self.stores, 'B', self.roster_id, [('a', 2)])
        self.stores.close_stations()
        with self.assertRaises(ValueError):
            self.publish(first.admission_id, wrong.admission_id)
        self.assertEqual(self.stores.reports.counts(), (0, 0))
        report, _ = self.publish(first.admission_id, right.admission_id)
        self.assertEqual(report.body.coverage.repeated, ('a',))

    def test_pair_identity(self):
        first = handoff(self.stores, 'A', self.roster_id, [('a', 1)])
        same_station = handoff(self.stores, 'A', self.roster_id, [('a', 2)])
        later = register_tray(self.stores, round_id='R-02')
        other_round = handoff(self.stores, 'B', later, [('a', 1)])
        for invalid in (same_station.admission_id, other_round.admission_id, first.admission_id):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.publish(first.admission_id, invalid)
        with self.assertRaises(KeyError):
            self.publish(first.admission_id, 1000)
        with self.assertRaises(KeyError):
            read_v1(self.stores.reports, 1000)
        self.assertEqual(self.stores.reports.counts(), (0, 0))

    def test_commit_failure_then_retry(self):
        parents = self.pair([], [('b', 1)])
        self.stores.close_stations()
        self.failure.arm()
        with self.assertRaises(InjectedCommitError):
            self.publish(*parents)
        self.assertEqual(self.stores.reports.counts(), (0, 0))
        report, receipt = self.publish(*parents)
        self.assertEqual(self.stores.reports.counts(), (1, 1))
        self.assertIsNone(report.body.stations[0].mean)
        self.assertEqual(report.body.coverage.repeated, ())
        self.assertEqual(receipt.report_id, report.report_id)

    def test_retry_visibility(self):
        parents = self.pair([], [('b', 1)])
        self.stores.close_stations()
        with closing(connect(self.root / CENTER_FILENAME)) as observer_db:
            observer = ReportRegister(observer_db)
            initial = observer.counts()
            staged_ids = []

            def inspect_staged_publication():
                writer = self.stores.reports
                self.assertEqual(writer.counts(), (initial[0] + 1, initial[1] + 1))
                staged_id = writer.connection.execute('SELECT max(id) FROM reports').fetchone()[0]
                staged_ids.append(staged_id)
                report, receipt = read_v1(writer, staged_id)
                self.assertEqual(receipt.report_id, report.report_id)
                self.assertEqual(observer.counts(), initial)
                with self.assertRaises(KeyError):
                    read_v1(observer, staged_id)

            self.failure.arm(inspect_staged_publication)
            with self.assertRaises(InjectedCommitError):
                self.publish(*parents)
            self.assertEqual(len(staged_ids), 1)
            self.assertEqual(observer.counts(), initial)
            with self.assertRaises(KeyError):
                read_v1(observer, staged_ids[0])
            published = self.publish(*parents)
            self.assertEqual(observer.counts(), (initial[0] + 1, initial[1] + 1))
            self.assertEqual(read_v1(observer, published[0].report_id), published)
        self.stores.close_center()
        self.assertEqual(self.reopened_report(published[0].report_id), published)

    def test_historical_read(self):
        parents = self.pair([('a', 0), ('b', 3)], [('b', 1)])
        first_raw = self.stores.archive.find(parents[0]).raw
        self.stores.close_stations()
        published = self.publish(*parents)
        self.stores.close_center()
        with open_shift(self.root) as next_shift:
            corrected = handoff(next_shift, 'A', self.roster_id, [('b', 5), ('c', 2)])
            old_frozen = published[0].body.sources[0].frozen_id
            older = get_frozen_revision(next_shift.stations['A'].journal, old_frozen)
            old_raw = seal_and_issue(next_shift, 'A', older.reading.revision_id)
            self.assertEqual(old_raw, first_raw)
            self.assertEqual(decode_envelope(old_raw).summary.total, Fraction(3))
            self.assertEqual(accept_v1(next_shift.archive, next_shift.catalog, self.roster_id, old_raw).admission_id,
                             parents[0])
            self.assertNotEqual(corrected.admission_id, parents[0])
            self.assertEqual(corrected.envelope.summary.total, Fraction(7))
            next_shift.close_stations()
            updated, _ = publish_v1(next_shift.archive, next_shift.catalog, next_shift.reports,
                                    corrected.admission_id, parents[1])
            self.assertEqual(updated.body.coverage.uninspected, ())
            self.assertEqual(updated.body.stations[0].mean, Fraction(7, 3))
        report, receipt = self.reopened_report(published[0].report_id)
        self.assertEqual((report, receipt), published)
        self.assertEqual(report.body.coverage.uninspected, ('c',))
        self.assertEqual(report.body.stations[0].mean, Fraction(3, 2))

    def test_reopen_preserves_edits(self):
        root = self.root / 'initialized'
        roster_id = initialize(root)
        with open_shift(root) as stores:
            journal = stores.stations['A'].journal
            revision = record_readings(journal, stores.catalog, 'A', roster_id, [('b', [9, 7])])
            frozen = freeze_station(journal, 'A', revision)
            alpha_raw = seal_and_issue(stores, 'A', revision)
            alpha = accept_v1(stores.archive, stores.catalog, roster_id, alpha_raw)
            beta_current = stores.stations['B'].journal.current_revision('B', roster_id)
            beta_raw = seal_and_issue(stores, 'B', beta_current.revision_id)
            beta = accept_v1(stores.archive, stores.catalog, roster_id, beta_raw)
            signed = publish_v1(stores.archive, stores.catalog, stores.reports, alpha.admission_id, beta.admission_id)
            self.assertEqual(signed[0].body.stations[0].mean, Fraction(9, 14))
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                self.assertEqual(initialize(root), roster_id)
                with open_shift(root) as restored:
                    journal = restored.stations['A'].journal
                    self.assertEqual(journal.current_revision('A', roster_id).revision_id, revision)
                    self.assertEqual(dict(get_frozen_revision(journal, frozen).reading.records)['b'], Fraction(9, 7))
                    self.assertEqual(restored.archive.find(alpha.admission_id), alpha)
                    self.assertEqual(restored.archive.find(beta.admission_id), beta)
                    self.assertEqual(read_v1(restored.reports, signed[0].report_id), signed)
                    self.assertEqual(restored.reports.counts(), (1, 1))
