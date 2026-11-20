from contextlib import closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from observations import freeze_station, get_frozen_revision, record_readings
from shift_example import CATALOG_FILENAME, connect, open_shift, register_tray
from tray import PhysicalSlot, RosterCatalog, freeze_tray
from tray.resolve import resolve_slot, slots_in_roster_order


class TrayFlowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.stores = self.enterContext(open_shift(self.root))
        self.roster_id = register_tray(self.stores)
        self.alpha = self.stores.stations['A'].journal

    def record(self, rows):
        return record_readings(self.alpha, self.stores.catalog, 'A', self.roster_id, rows)

    def test_shared_frozen_roster(self):
        for station, rows in [('A', [('b', 3), ('a', 0)]), ('B', [('c', None), ('b', 1)])]:
            with self.subTest(station=station):
                journal = self.stores.stations[station].journal
                revision = record_readings(journal, self.stores.catalog, station, self.roster_id, rows)
                frozen = get_frozen_revision(journal, freeze_station(journal, station, revision))
                self.assertEqual(frozen.reading.station, station)
                self.assertEqual(frozen.reading.roster_id, self.roster_id)
                roster = self.stores.catalog.load_frozen(frozen.reading.roster_id)
                self.assertEqual(roster.labels, ('a', 'b', 'c'))
                self.assertEqual(resolve_slot(roster, 'b'), PhysicalSlot(1, 2, 'b'))
                self.assertEqual(slots_in_roster_order(roster, ['c', 'a']), ('a', 'c'))

    def test_roster_order(self):
        labels = ('f', 'c', 'e', 'd', 'a', 'b')
        roster_id = register_tray(self.stores, labels, tray='physical-order')
        self.assertEqual(register_tray(self.stores, labels, tray='physical-order'), roster_id)
        frozen_ids = {}
        for station in ('A', 'B'):
            journal = self.stores.stations[station].journal
            revision = record_readings(
                journal, self.stores.catalog, station, roster_id, [('d', 2), ('c', 1)]
            )
            frozen_ids[station] = freeze_station(journal, station, revision)
        self.stores.catalog.connection.close()
        with closing(connect(self.root / CATALOG_FILENAME)) as db:
            reopened = RosterCatalog(db)
            for station, frozen_id in frozen_ids.items():
                journal = self.stores.stations[station].journal
                revision = get_frozen_revision(journal, frozen_id).reading
                roster = reopened.load_frozen(revision.roster_id)
                self.assertEqual(roster.roster_id, roster_id)
                self.assertEqual(roster.labels, labels)
                self.assertEqual(resolve_slot(roster, 'd').column, 4)
                self.assertEqual(slots_in_roster_order(roster, ['b', 'd', 'f']), ('f', 'd', 'b'))

    def test_invalid_layout(self):
        invalid = [
            [PhysicalSlot(3, 1, 'a')],
            [PhysicalSlot(2, 7, 'a')],
            [PhysicalSlot(True, 1, 'a')],
            [PhysicalSlot(1, 1, 'a'), PhysicalSlot(1, 1, 'b')],
            [PhysicalSlot(1, 1, 'a'), PhysicalSlot(1, 2, 'a')],
            [PhysicalSlot(1, 1, str(index)) for index in range(13)],
        ]
        for layout in invalid:
            with self.subTest(layout=layout):
                with self.assertRaises(ValueError):
                    freeze_tray(self.stores.catalog, 'invalid', 'R-01', layout)
                self.assertIsNone(self.stores.catalog.find_tray('invalid', 'R-01'))
        with self.assertRaises(ValueError):
            register_tray(self.stores, ('a', 'c', 'b'))
        self.assertEqual(self.stores.catalog.load_frozen(self.roster_id).labels, ('a', 'b', 'c'))

    def test_foreign_slot_rejects_entire_batch(self):
        register_tray(self.stores, ('x',), tray='other-tray')
        original = self.record([('a', 0), ('b', 3)])
        with self.assertRaises(ValueError):
            self.record([('b', 5), ('x', 9)])
        current = self.alpha.current_revision('A', self.roster_id)
        self.assertEqual(current.revision_id, original)
        frozen = get_frozen_revision(self.alpha, freeze_station(self.alpha, 'A', original))
        self.assertEqual(dict(frozen.reading.records), {'a': Fraction(0), 'b': Fraction(3)})
        self.assertEqual(self.alpha.connection.execute('SELECT count(*) FROM reading_revisions').fetchone(), (1,))

    def test_invalid_input(self):
        original = self.record([('a', 0)])
        with self.assertRaises(KeyError):
            record_readings(self.alpha, self.stores.catalog, 'A', 'unknown', [('a', 3)])
        for batch in ([('a', 1), ('a', 2)], [('a', [1, 0])], [('a', [1, -2])], [('a', 0.1)],
                      [('a', True)], [('a', [True, 1])], [('a',)], [(None, 2)]):
            with self.subTest(batch=batch):
                with self.assertRaises(ValueError):
                    self.record(batch)
        self.assertEqual(self.alpha.current_revision('A', self.roster_id).revision_id, original)
        self.assertEqual(self.alpha.connection.execute('SELECT count(*) FROM reading_revisions').fetchone(), (1,))

    def test_revision_history(self):
        before = self.record([('a', 0), ('b', 3), ('c', None)])
        old_frozen = freeze_station(self.alpha, 'A', before)
        after = self.record([('b', 5)])
        new_frozen = freeze_station(self.alpha, 'A', after)
        new = get_frozen_revision(self.alpha, new_frozen).reading
        old = get_frozen_revision(self.alpha, old_frozen).reading
        self.assertNotEqual(old_frozen, new_frozen)
        self.assertEqual(new.previous_id, before)
        self.assertEqual(new.roster_id, self.roster_id)
        self.assertEqual(new.round_id, 'R-01')
        self.assertEqual(new.station, 'A')
        self.assertEqual(dict(new.records), {'a': Fraction(0), 'b': Fraction(5), 'c': None})
        self.assertEqual(dict(old.records), {'a': Fraction(0), 'b': Fraction(3), 'c': None})

    def test_revision_target(self):
        old = self.record([('b', 3)])
        latest = self.record([('b', 5)])
        with self.assertRaises(ValueError):
            freeze_station(self.alpha, 'B', old)
        with self.assertRaises(KeyError):
            freeze_station(self.alpha, 'A', latest + 100)
        self.assertEqual(self.alpha.connection.execute('SELECT count(*) FROM frozen_revisions').fetchone(), (0,))
        frozen_id = freeze_station(self.alpha, 'A', old)
        self.assertEqual(freeze_station(self.alpha, 'A', old), frozen_id)
        frozen = get_frozen_revision(self.alpha, frozen_id)
        self.assertEqual(frozen.reading.revision_id, old)
        self.assertEqual(dict(frozen.reading.records), {'b': Fraction(3)})
        self.assertEqual(self.alpha.current_revision('A', self.roster_id).revision_id, latest)
