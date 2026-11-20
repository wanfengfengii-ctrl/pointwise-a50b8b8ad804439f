from contextlib import closing
from fractions import Fraction
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from admission import AdmissionArchive, accept_v1
from observations import freeze_station, record_readings
from shift_example import (
    CENTER_FILENAME, FailOnce, InjectedCommitError, connect, issue_readings, open_shift, register_tray,
)
from station import decode_envelope, issue_v1


def change_wire(raw, **updates):
    data = json.loads(raw)
    data.update(updates)
    return json.dumps(data, indent=2).encode('utf-8')


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.failure = FailOnce()
        self.stores = self.enterContext(open_shift(self.root, outbox_before_commit=self.failure))
        self.roster_id = register_tray(self.stores)

    def issue(self, readings, station='A'):
        return issue_readings(self.stores, station, self.roster_id, readings)

    def accept(self, raw):
        return accept_v1(self.stores.archive, self.stores.catalog, self.roster_id, raw)

    def admission_count(self):
        row = self.stores.archive.connection.execute('SELECT count(*) FROM admitted_envelopes').fetchone()
        return row[0]

    def test_zero_and_missing(self):
        raw = self.issue([('b', None), ('a', 0)])
        envelope = decode_envelope(raw)
        self.assertEqual(envelope.summary.slots, ('a',))
        self.assertEqual(envelope.summary.count, 1)
        self.assertEqual(envelope.summary.total, Fraction(0))
        self.assertEqual(envelope.roster_id, self.roster_id)
        self.assertEqual(self.stores.stations['A'].outbox.get(envelope.frozen_id), raw)

    def test_empty_issue(self):
        for readings in ([], [('b', None), ('a', None)]):
            with self.subTest(readings=readings):
                accepted = self.accept(self.issue(readings))
                summary = accepted.envelope.summary
                self.assertEqual((summary.slots, summary.count, summary.total), ((), 0, Fraction(0)))

    def test_zero_in_fractional_total(self):
        summary = decode_envelope(self.issue([('c', None), ('b', [1, 5]), ('a', 0)])).summary
        self.assertEqual((summary.slots, summary.count, summary.total), (('a', 'b'), 2, Fraction(1, 5)))

    def test_station_write_retry(self):
        source = self.stores.stations['A']
        roster_id = self.roster_id
        revision = record_readings(source.journal, self.stores.catalog, 'A', roster_id, [('b', [2, 7])])
        frozen = freeze_station(source.journal, 'A', revision)
        with self.assertRaises(KeyError):
            issue_v1(source.journal, self.stores.catalog, source.outbox, frozen + 100)

        def inspect_staged_issue():
            staged = decode_envelope(source.outbox.get(frozen))
            self.assertEqual(staged.summary.total, Fraction(2, 7))

        self.failure.arm(inspect_staged_issue)
        with self.assertRaises(InjectedCommitError):
            issue_v1(source.journal, self.stores.catalog, source.outbox, frozen)
        with self.assertRaises(KeyError):
            source.outbox.get(frozen)
        raw = issue_v1(source.journal, self.stores.catalog, source.outbox, frozen)
        envelope = decode_envelope(raw)
        self.assertEqual((envelope.station, envelope.roster_id, envelope.frozen_id), ('A', roster_id, frozen))
        self.assertEqual((envelope.summary.slots, envelope.summary.count, envelope.summary.total),
                         (('b',), 1, Fraction(2, 7)))
        self.assertEqual(source.outbox.get(frozen), raw)
        self.assertEqual(issue_v1(source.journal, self.stores.catalog, source.outbox, frozen), raw)

    def test_summary_reconciliation(self):
        valid = self.issue([('b', [1, 5])])
        with self.assertRaises(ValueError):
            self.accept(change_wire(valid, count=2))
        self.assertEqual(self.admission_count(), 0)
        accepted = self.accept(valid)
        self.assertEqual(accepted.envelope.summary.count, 1)
        self.assertEqual(self.admission_count(), 1)

    def test_idempotent_acceptance(self):
        raw = self.issue([('b', 1)])
        first = self.accept(raw)
        self.stores.close_stations()
        second = self.accept(raw)
        self.assertEqual(first.admission_id, second.admission_id)
        self.assertEqual(self.stores.archive.find(first.admission_id).raw, raw)
        self.assertEqual(self.admission_count(), 1)

    def test_equivalent_encoding(self):
        canonical = self.issue([('b', [1, 3])])
        original = change_wire(canonical, total=[2, 6])
        first = self.accept(original)
        second = self.accept(canonical)
        self.assertNotEqual(original, canonical)
        self.assertEqual(second, first)
        self.assertEqual(self.stores.archive.find(first.admission_id).raw, original)
        self.assertEqual(self.admission_count(), 1)

    def test_roster_binding(self):
        valid = self.issue([('a', 0), ('b', 2)])
        other_id = register_tray(self.stores, tray='other-tray')
        with self.assertRaises(KeyError):
            accept_v1(self.stores.archive, self.stores.catalog, 'unknown', valid)
        with self.assertRaises(ValueError):
            accept_v1(self.stores.archive, self.stores.catalog, other_id, valid)
        rejected = [
            change_wire(valid, tray='wrong'),
            change_wire(valid, round_id='wrong'),
            change_wire(valid, slots=['a', 'x']),
            change_wire(valid, slots=['b', 'a']),
        ]
        for raw in rejected:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.accept(raw)
        self.assertEqual(self.admission_count(), 0)
        self.assertEqual(self.accept(valid).raw, valid)

    def test_invalid_envelopes_leave_no_binding(self):
        valid = self.issue([('a', 0)])
        malformed = [
            b'{', b'\xff', b'[]', valid.replace(b'{', b'{"version":1,', 1),
            change_wire(valid, version=2), change_wire(valid, count=True),
            change_wire(valid, total=[1, 0]), change_wire(valid, slots=['a', 'a'], count=2),
            change_wire(valid, slots=[], count=0, total=[1, 7]),
        ]
        for raw in malformed:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.accept(raw)
        self.assertEqual(self.admission_count(), 0)
        self.assertEqual(self.accept(valid).raw, valid)

    def test_conflicting_payload(self):
        original = self.issue([('a', 0), ('b', 3)])
        first = self.accept(original)
        conflict = change_wire(original, total=[5, 1])
        self.assertEqual(decode_envelope(conflict).summary.total, Fraction(5))
        with self.assertRaises(ValueError):
            self.accept(conflict)
        self.assertEqual(self.admission_count(), 1)
        self.assertEqual(self.stores.archive.find(first.admission_id), first)
        self.stores.close_center()
        with closing(connect(self.root / CENTER_FILENAME)) as db:
            restored = AdmissionArchive(db).find(first.admission_id)
            self.assertEqual(restored.raw, original)
            self.assertEqual(restored.envelope.summary.total, Fraction(3))
