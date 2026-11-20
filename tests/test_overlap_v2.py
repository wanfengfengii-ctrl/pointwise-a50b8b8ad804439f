"""V2 标签模糊重复受检复核的回归测试。"""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from admission import AdmissionArchive, accept_v1, accept_v2
from observations import freeze_station, record_readings
from review import ReportRegister, publish_v2, read_v2
from shift_example import (
    CENTER_FILENAME, FailOnce, InjectedCommitError, connect, open_shift, register_tray,
)
from station import decode_envelope_v2, issue_v1, issue_v2

LABELS = ('a', 'b', 'c', 'd')
CONFIRMED_B = {'a': ('a',), 'b': ('b',)}


def change_wire(raw, **updates):
    data = json.loads(raw)
    data.update(updates)
    return json.dumps(data, indent=2).encode('utf-8')


class OverlapV2Tests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.failure = FailOnce()
        self.stores = self.enterContext(
            open_shift(self.root, outbox_before_commit=self.failure,
                       report_before_commit=self.failure)
        )
        self.roster_id = register_tray(self.stores, LABELS, tray='OVERLAP-01')

    def freeze(self, station, readings):
        journal = self.stores.stations[station].journal
        revision = record_readings(journal, self.stores.catalog, station, self.roster_id, readings)
        return freeze_station(journal, station, revision)

    def issue(self, station, frozen_id, candidates):
        source = self.stores.stations[station]
        return issue_v2(source.journal, self.stores.catalog, source.outbox, frozen_id, candidates)

    def accept(self, raw):
        return accept_v2(self.stores.archive, self.stores.catalog, self.roster_id, raw)

    def pair(self, frozen_a, candidates_a, frozen_b, candidates_b):
        first = self.accept(self.issue('A', frozen_a, candidates_a))
        second = self.accept(self.issue('B', frozen_b, candidates_b))
        return first.admission_id, second.admission_id

    def publish(self, ids):
        return publish_v2(self.stores.archive, self.stores.catalog, self.stores.reports, *ids)

    def test_four_slot_worked_examples(self):
        frozen_a = self.freeze('A', (('a', 0), ('b', 3), ('c', None)))
        frozen_a2 = self.freeze('A', (('a', 0), ('b', 3), ('c', None)))
        frozen_b = self.freeze('B', (('a', 8), ('b', 3)))

        ids_one = self.pair(
            frozen_a, {'a': ('a', 'b'), 'b': ('c', 'd')}, frozen_b, CONFIRMED_B
        )
        report_one, receipt_one = self.publish(ids_one)
        body = report_one.body
        self.assertEqual((body.lower, body.upper), (1, 1))
        self.assertEqual(body.lower_witness, (('a', 'c'), ('a', 'b')))
        self.assertEqual(body.upper_witness, (('a', 'c'), ('a', 'b')))
        self.assertEqual(body.sources[0].station, 'A')
        self.assertEqual(body.sources[1].station, 'B')
        self.assertEqual(receipt_one.report_id, report_one.report_id)

        ids_two = self.pair(
            frozen_a2, {'a': ('a', 'c'), 'b': ('b', 'd')}, frozen_b, CONFIRMED_B
        )
        report_two, _ = self.publish(ids_two)
        body = report_two.body
        self.assertEqual((body.lower, body.upper), (0, 2))
        self.assertEqual(body.lower_witness, (('c', 'd'), ('a', 'b')))
        self.assertEqual(body.upper_witness, (('a', 'b'), ('a', 'b')))
        # 见证中的每个槽集合都须能由各自资格兑现。
        for report, ids in ((report_one, ids_one), (report_two, ids_two)):
            families = [
                decode_envelope_v2(self.stores.archive.find_v2(i, self._roster()).raw,
                                   self._roster()).families
                for i in ids
            ]
            for witness in (report.body.lower_witness, report.body.upper_witness):
                for index in range(2):
                    self.assertIn(frozenset(witness[index]), families[index])

    def _roster(self):
        return self.stores.catalog.load_frozen(self.roster_id)

    def test_witnesses_follow_roster_order(self):
        labels = ('f', 'c', 'e', 'd', 'a', 'b')
        roster_id = register_tray(self.stores, labels, tray='physical-order')
        journal_a = self.stores.stations['A'].journal
        revision = record_readings(journal_a, self.stores.catalog, 'A', roster_id,
                                   [('d', 1), ('a', 2)])
        frozen_a = freeze_station(journal_a, 'A', revision)
        journal_b = self.stores.stations['B'].journal
        revision_b = record_readings(journal_b, self.stores.catalog, 'B', roster_id,
                                     [('f', 1), ('c', 2)])
        frozen_b = freeze_station(journal_b, 'B', revision_b)
        raw_a = issue_v2(journal_a, self.stores.catalog, self.stores.stations['A'].outbox,
                         frozen_a, {'d': ('d', 'f'), 'a': ('a', 'b')})
        raw_b = issue_v2(journal_b, self.stores.catalog, self.stores.stations['B'].outbox,
                         frozen_b, {'f': ('f',), 'c': ('c',)})
        first = accept_v2(self.stores.archive, self.stores.catalog, roster_id, raw_a)
        second = accept_v2(self.stores.archive, self.stores.catalog, roster_id, raw_b)
        report, _ = publish_v2(self.stores.archive, self.stores.catalog, self.stores.reports,
                               first.admission_id, second.admission_id)
        for witness in (report.body.lower_witness, report.body.upper_witness):
            for slots in witness:
                self.assertEqual(slots, tuple(label for label in labels if label in slots))
        self.assertEqual(report.body.upper, 1)
        self.assertEqual(report.body.lower, 0)

    def test_station_wide_infeasible_is_rejected(self):
        frozen_a = self.freeze('A', (('a', 0), ('b', 3)))
        with self.assertRaises(ValueError):
            self.issue('A', frozen_a, {'a': ('a',), 'b': ('a',)})
        row = self.stores.stations['A'].journal.connection.execute(
            'SELECT count(*) FROM issued_envelopes_v2'
        ).fetchone()
        self.assertEqual(row[0], 0)

    def test_candidate_validation(self):
        frozen_a = self.freeze('A', (('a', 0), ('b', 3), ('c', None)))
        journal = self.stores.stations['A'].journal
        outbox = self.stores.stations['A'].outbox
        invalid = [
            {'a': ('a',)},                                          # 缺键
            {'a': ('a',), 'b': ('b',), 'c': ('c',)},               # 多键（缺测行）
            {'a': ('a',), 'b': ('a', 'x')},                        # 清册外槽
            {'a': ('a', 'a'), 'b': ('b',)},                        # 候选内重复
            {'a': (), 'b': ('b',)},                                # 空候选
            {'a': ['a'], 'b': 'b'},                                # 非法容器
            {'a': ('a',), 'b': (1,)},                              # 非字符串槽
        ]
        for candidates in invalid:
            with self.subTest(candidates=candidates):
                with self.assertRaises(ValueError):
                    issue_v2(journal, self.stores.catalog, outbox, frozen_a, candidates)

    def test_empty_station_bounds(self):
        frozen_empty = self.freeze('A', (('a', None), ('b', None)))
        frozen_b = self.freeze('B', (('a', 8), ('b', 3)))
        raw_empty = self.issue('A', frozen_empty, {})
        self.assertEqual(decode_envelope_v2(raw_empty).families, (frozenset(),))
        ids = self.pair(frozen_empty, {}, frozen_b, CONFIRMED_B)
        report, _ = self.publish(ids)
        self.assertEqual((report.body.lower, report.body.upper), (0, 0))
        self.assertEqual(report.body.lower_witness, ((), ('a', 'b')))
        self.assertEqual(report.body.upper_witness, ((), ('a', 'b')))

    def test_equivalent_qualification_keeps_first_admission(self):
        frozen_b = self.freeze('B', (('a', 8), ('b', 3)))
        canonical = self.issue('B', frozen_b, CONFIRMED_B)
        first = self.accept(canonical)
        # 候选写法不同但整站集合族相同：{a} 与 {a,b}、以及 {a} 与 {b} 都只认可 {a,b}。
        for alternatives in (
            {'a': ('a', 'b'), 'b': ('a', 'b')},
            {'a': ('b',), 'b': ('a',)},
            {'a': frozenset({'a'}), 'b': frozenset({'b'})},
        ):
            with self.subTest(alternatives=alternatives):
                raw = self.issue('B', frozen_b, alternatives)
                reaccepted = self.accept(raw)
                self.assertEqual(reaccepted.admission_id, first.admission_id)
        # 来件编码变化（空白、集合族排序）但资格不变，沿用首接纳号且首存字节不动。
        payload = json.loads(canonical)
        payload['sets'].reverse()
        reencoded = json.dumps(payload, indent=4).encode('utf-8')
        self.assertNotEqual(reencoded, canonical)
        again = self.accept(reencoded)
        self.assertEqual(again.admission_id, first.admission_id)
        self.assertEqual(self.stores.archive.find_v2(first.admission_id, self._roster()).raw,
                         canonical)

    def test_conflicting_qualification_rejected_and_first_survives(self):
        frozen_a = self.freeze('A', (('a', 0), ('b', 3)))
        first_raw = self.issue('A', frozen_a, {'a': ('a', 'b'), 'b': ('c', 'd')})
        first = self.accept(first_raw)
        conflict = change_wire(first_raw, sets=[['a'], ['b']])
        with self.assertRaises(ValueError):
            self.accept(conflict)
        surviving = self.stores.archive.find_v2(first.admission_id, self._roster())
        self.assertEqual(surviving.raw, first_raw)

    def test_single_slot_candidates_are_confirmed_readings(self):
        frozen_b = self.freeze('B', (('a', 8), ('b', 3)))
        raw = self.issue('B', frozen_b, CONFIRMED_B)
        envelope = decode_envelope_v2(raw, self._roster())
        self.assertEqual(envelope.families, (frozenset({'a', 'b'}),))

    def test_bool_and_nonstring_inputs_rejected(self):
        frozen_a = self.freeze('A', (('a', 0), ('b', 3)))
        journal = self.stores.stations['A'].journal
        outbox = self.stores.stations['A'].outbox
        invalid = [
            {True: ('a',), 'b': ('b',)},
            {'a': ('a',), 'b': ('b', True)},
            {'a': ('a',), 'b': (1,)},
        ]
        for candidates in invalid:
            with self.subTest(candidates=candidates), self.assertRaises(ValueError):
                issue_v2(journal, self.stores.catalog, outbox, frozen_a, candidates)

    def test_storage_integrity_failure_maps_to_value_error(self):
        frozen_a = self.freeze('A', (('a', 0),))
        first = self.accept(self.issue('A', frozen_a, {'a': ('a', 'b')}))
        fresh_frozen = self.freeze('A', (('a', 0),))
        archive = self.stores.archive

        class CollidingArchive(AdmissionArchive):
            def _next_admission_id(self):
                return first.admission_id  # 强制撞主键，触发 IntegrityError

        broken = CollidingArchive(archive.connection)
        with self.assertRaises(ValueError):
            accept_v2(broken, self.stores.catalog, self.roster_id,
                      self.issue('A', fresh_frozen, {'a': ('a', 'c')}))
        # 失败无新增；撤除故障后用同一对接纳来源可成功接纳。
        self.assertEqual(
            archive.connection.execute(
                'SELECT count(*) FROM admitted_envelopes WHERE version = 2'
            ).fetchone()[0],
            1,
        )
        recovered = self.accept(self.issue('A', fresh_frozen, {'a': ('a', 'c')}))
        self.assertNotEqual(recovered.admission_id, first.admission_id)
        self.assertEqual(
            archive.connection.execute(
                'SELECT count(*) FROM admitted_envelopes WHERE version = 2'
            ).fetchone()[0],
            2,
        )

    def test_malformed_v2_leaves_no_binding(self):
        frozen_a = self.freeze('A', (('a', 0),))
        valid = self.issue('A', frozen_a, {'a': ('a', 'b')})
        before = self.stores.archive.connection.execute(
            'SELECT count(*) FROM admitted_envelopes'
        ).fetchone()[0]
        malformed = [
            b'{', b'\xff', b'[]',
            change_wire(valid, version=1),
            change_wire(valid, frozen_id='x'),
            change_wire(valid, sets=[]),
            change_wire(valid, sets=[['a', 'a']]),
            change_wire(valid, sets=[['a'], ['a', 'b']]),
            change_wire(valid, sets=[['nope']]),
            change_wire(valid, station=''),
            valid.replace(b'{', b'{"extra":1,', 1),
        ]
        for raw in malformed:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.accept(raw)
        after = self.stores.archive.connection.execute(
            'SELECT count(*) FROM admitted_envelopes'
        ).fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(self.accept(valid).raw, valid)

    def test_v1_and_v2_coexist_and_cross_version_publish_rejected(self):
        frozen_b = self.freeze('B', (('a', 8), ('b', 3)))
        source = self.stores.stations['B']
        v1_raw = issue_v1(source.journal, self.stores.catalog, source.outbox, frozen_b)
        v2_raw = issue_v2(source.journal, self.stores.catalog, source.outbox, frozen_b,
                          CONFIRMED_B)
        v1 = accept_v1(self.stores.archive, self.stores.catalog, self.roster_id, v1_raw)
        v2 = accept_v2(self.stores.archive, self.stores.catalog, self.roster_id, v2_raw)
        self.assertNotEqual(v1.admission_id, v2.admission_id)
        self.assertEqual(source.outbox.get(frozen_b), v1_raw)
        self.assertEqual(source.outbox.get_v2(frozen_b), v2_raw)
        frozen_a = self.freeze('A', (('a', 0), ('b', 3)))
        other = self.accept(self.issue('A', frozen_a, {'a': ('a',), 'b': ('b',)}))
        with self.assertRaises(ValueError):
            publish_v2(self.stores.archive, self.stores.catalog, self.stores.reports,
                       v1.admission_id, v2.admission_id)
        with self.assertRaises(ValueError):
            publish_v2(self.stores.archive, self.stores.catalog, self.stores.reports,
                       other.admission_id, v1.admission_id)

    def test_selection_mismatch_and_unknown_ids(self):
        frozen_a = self.freeze('A', (('a', 0),))
        first = self.accept(self.issue('A', frozen_a, {'a': ('a',)}))
        same_station = self.accept(
            self.issue('A', self.freeze('A', (('a', 0), ('b', 1),)),
                       {'a': ('a',), 'b': ('b',)})
        )
        other_roster = register_tray(self.stores, ('x',), tray='other-tray')
        journal_b = self.stores.stations['B'].journal
        revision = record_readings(journal_b, self.stores.catalog, 'B', other_roster,
                                   [('x', 1)])
        frozen_other = freeze_station(journal_b, 'B', revision)
        wrong = accept_v2(
            self.stores.archive, self.stores.catalog, other_roster,
            issue_v2(journal_b, self.stores.catalog, self.stores.stations['B'].outbox,
                     frozen_other, {'x': ('x',)}),
        )
        for invalid in (same_station.admission_id, wrong.admission_id):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.publish((first.admission_id, invalid))
        with self.assertRaises(KeyError):
            self.publish((first.admission_id, 1000))
        with self.assertRaises(KeyError):
            read_v2(self.stores.reports, 1000)
        self.assertEqual(self.stores.reports.counts_v2(), (0, 0))

    def test_commit_failure_then_retry_and_reopen(self):
        frozen_a = self.freeze('A', (('a', 0), ('b', 3)))
        frozen_b = self.freeze('B', (('a', 8), ('b', 3)))
        ids = self.pair(frozen_a, {'a': ('a', 'c'), 'b': ('b', 'd')}, frozen_b, CONFIRMED_B)
        self.stores.close_stations()
        self.failure.arm()
        with self.assertRaises(InjectedCommitError):
            self.publish(ids)
        self.assertEqual(self.stores.reports.counts_v2(), (0, 0))
        published = self.publish(ids)
        self.assertEqual(self.stores.reports.counts_v2(), (1, 1))
        self.stores.close_center()
        with closing(connect(self.root / CENTER_FILENAME)) as reopened_db:
            loaded = read_v2(ReportRegister(reopened_db), published[0].report_id)
        self.assertEqual(loaded, published)

    def test_station_issue_retry_and_conflict(self):
        frozen_a = self.freeze('A', (('a', 0), ('b', 3)))
        source = self.stores.stations['A']
        candidates = {'a': ('a', 'b'), 'b': ('c', 'd')}
        self.failure.arm()
        with self.assertRaises(InjectedCommitError):
            issue_v2(source.journal, self.stores.catalog, source.outbox, frozen_a, candidates)
        with self.assertRaises(KeyError):
            source.outbox.get_v2(frozen_a)
        raw = issue_v2(source.journal, self.stores.catalog, source.outbox, frozen_a, candidates)
        # 等价重发返回原件。
        self.assertEqual(
            issue_v2(source.journal, self.stores.catalog, source.outbox, frozen_a, candidates),
            raw,
        )
        # 同一冻结号的实质冲突拒发。
        with self.assertRaises(ValueError):
            issue_v2(source.journal, self.stores.catalog, source.outbox, frozen_a,
                     {'a': ('a', 'c'), 'b': ('b', 'd')})
        self.assertEqual(source.outbox.get_v2(frozen_a), raw)

    def test_historical_read_after_corrections(self):
        frozen_a = self.freeze('A', (('a', 0), ('b', 3)))
        frozen_b = self.freeze('B', (('a', 8), ('b', 3)))
        ids = self.pair(frozen_a, {'a': ('a', 'b'), 'b': ('c', 'd')}, frozen_b, CONFIRMED_B)
        published = self.publish(ids)
        # 追加勘误并产生新冻结修订，旧报告仍按原号领取当时结论。
        self.freeze('A', (('a', 5), ('b', 9)))
        self.stores.close_center()
        with closing(connect(self.root / CENTER_FILENAME)) as reopened_db:
            register = ReportRegister(reopened_db)
            loaded = read_v2(register, published[0].report_id)
        self.assertEqual(loaded, published)
        self.assertEqual(loaded[0].body.sources[0].frozen_id, frozen_a)

    def test_six_slot_bounds_enumeration(self):
        labels = tuple('abcdef')
        roster_id = register_tray(self.stores, labels, tray='six-slot')
        journal_a = self.stores.stations['A'].journal
        revision = record_readings(journal_a, self.stores.catalog, 'A', roster_id,
                                   [('a', 1), ('b', 2), ('c', 3)])
        frozen_a = freeze_station(journal_a, 'A', revision)
        journal_b = self.stores.stations['B'].journal
        revision_b = record_readings(journal_b, self.stores.catalog, 'B', roster_id,
                                     [('d', 1), ('e', 2), ('f', 3)])
        frozen_b = freeze_station(journal_b, 'B', revision_b)
        raw_a = issue_v2(journal_a, self.stores.catalog, self.stores.stations['A'].outbox,
                         frozen_a, {'a': ('a', 'd'), 'b': ('b', 'e'), 'c': ('c', 'f')})
        raw_b = issue_v2(journal_b, self.stores.catalog, self.stores.stations['B'].outbox,
                         frozen_b, {'d': ('a', 'd'), 'e': ('b', 'e'), 'f': ('c', 'f')})
        first = accept_v2(self.stores.archive, self.stores.catalog, roster_id, raw_a)
        second = accept_v2(self.stores.archive, self.stores.catalog, roster_id, raw_b)
        report, _ = publish_v2(self.stores.archive, self.stores.catalog, self.stores.reports,
                               first.admission_id, second.admission_id)
        self.assertEqual((report.body.lower, report.body.upper), (0, 3))
        self.assertEqual(report.body.lower_witness, (('a', 'b', 'c'), ('d', 'e', 'f')))
        self.assertEqual(report.body.upper_witness, (('a', 'b', 'c'), ('a', 'b', 'c')))
    def test_legacy_v1_archive_migration_preserves_ids_and_raw(self):
        # 先用旧版结构（无 version 列）写入 V1 接纳件，再由新 AdmissionArchive 迁移。
        legacy_path = self.root / 'legacy-center.sqlite3'
        with closing(connect(legacy_path)) as db:
            db.execute('''
                CREATE TABLE admitted_envelopes (
                    id INTEGER PRIMARY KEY,
                    station TEXT NOT NULL,
                    frozen_id INTEGER NOT NULL,
                    content BLOB NOT NULL,
                    raw BLOB NOT NULL,
                    UNIQUE (station, frozen_id)
                )
            ''')
            db.execute("INSERT INTO admitted_envelopes VALUES (1, 'A', 7, X'01', X'02')")
            db.commit()
        with closing(connect(legacy_path)) as db:
            archive = AdmissionArchive(db)
            row = db.execute(
                'SELECT id, station, frozen_id, version, raw FROM admitted_envelopes'
            ).fetchone()
            self.assertEqual(row, (1, 'A', 7, 1, b'\x02'))
            # 迁移后 V2 新接纳号不得与既有 V1 号碰撞。
            frozen_b = self.freeze('B', (('a', 8),))
            v2 = accept_v2(
                archive, self.stores.catalog, self.roster_id,
                issue_v2(self.stores.stations['B'].journal, self.stores.catalog,
                         self.stores.stations['B'].outbox, frozen_b, {'a': ('a',)}),
            )
            self.assertNotEqual(v2.admission_id, 1)
            self.assertEqual(archive.version_of(1), 1)
            self.assertIsNone(archive.version_of(999))
            self.assertEqual(
                db.execute('SELECT version FROM admitted_envelopes WHERE id = ?',
                           (v2.admission_id,)).fetchone()[0],
                2,
            )
        # 重新打开已是新结构，幂等且数据不变。
        with closing(connect(legacy_path)) as db:
            archive = AdmissionArchive(db)
            self.assertEqual(archive.version_of(1), 1)
            self.assertEqual(
                db.execute('SELECT count(*) FROM admitted_envelopes').fetchone()[0], 2
            )


if __name__ == '__main__':
    unittest.main()
