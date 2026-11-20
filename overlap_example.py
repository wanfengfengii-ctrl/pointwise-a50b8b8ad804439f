"""Inputs for the overlap extension and an executable V1 control."""
from contextlib import ExitStack, closing
import json
import sqlite3

from admission import AdmissionArchive, accept_v1
from observations import ObservationJournal, freeze_station, record_readings
from review import ReportRegister, publish_v1
from station import Outbox, issue_v1
from tray import PhysicalSlot, RosterCatalog, freeze_tray

LABELS = ("a", "b", "c", "d")
READINGS = {"A": (("a", 0), ("b", 3), ("c", None)), "B": (("a", 8), ("b", 3))}
CONFIRMED_B = {"a": ("a",), "b": ("b",)}
CASES = (
    {"name": "one_from_each_group",
     "candidates": {"A": {"a": ("a", "b"), "b": ("c", "d")}, "B": CONFIRMED_B},
     "expected_bounds": (1, 1)},
    {"name": "both_or_neither",
     "candidates": {"A": {"a": ("a", "c"), "b": ("b", "d")}, "B": CONFIRMED_B},
     "expected_bounds": (0, 2)},
)


def connect_memory(stack):
    return stack.enter_context(closing(sqlite3.connect(":memory:")))


def v1_control():
    with ExitStack() as shared:
        catalog = RosterCatalog(connect_memory(shared))
        center = connect_memory(shared)
        archive = AdmissionArchive(center)
        register = ReportRegister(center)
        slots = (PhysicalSlot(1, column, label) for column, label in enumerate(LABELS, 1))
        roster_id = freeze_tray(catalog, "OVERLAP-01", "R-01", slots)
        admissions = []
        with ExitStack() as sources:
            for name, readings in READINGS.items():
                db = connect_memory(sources)
                journal = ObservationJournal(db)
                revision = record_readings(journal, catalog, name, roster_id, readings)
                frozen = freeze_station(journal, name, revision)
                raw = issue_v1(journal, catalog, Outbox(db), frozen)
                accepted = accept_v1(archive, catalog, roster_id, raw)
                admissions.append(accepted.admission_id)
        report, receipt = publish_v1(archive, catalog, register, *admissions)
        repeated = report.body.coverage.repeated
        if repeated != ("a", "b") or receipt.report_id != report.report_id:
            raise AssertionError("V1 control: expected a and b in the fixed overlap report")
        return {"v1_fixed_repeated": repeated, "v2_input_examples": CASES}


if __name__ == "__main__":
    print(json.dumps(v1_control(), ensure_ascii=False))
