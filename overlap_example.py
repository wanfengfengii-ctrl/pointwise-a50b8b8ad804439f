"""标签模糊重复受检复核：V1 对照与 V2 关站签发、重开领取演示。"""
from contextlib import ExitStack, closing, contextmanager
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from admission import AdmissionArchive, accept_v1, accept_v2
from observations import ObservationJournal, freeze_station, record_readings
from review import ReportRegister, publish_v1, publish_v2, read_v2
from shift_example import CATALOG_FILENAME, CENTER_FILENAME, connect
from station import Outbox, issue_v1, issue_v2
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


@contextmanager
def open_catalog(path: Path):
    with closing(connect(path)) as db:
        yield RosterCatalog(db)


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


def v2_demo() -> dict:
    """关站签发两份异站 V2，中心重开后按原报告号领回见证。"""
    summary = {"cases": []}
    with TemporaryDirectory(prefix="ceramic-overlap-") as directory:
        root = Path(directory)
        catalog_path = root / CATALOG_FILENAME
        center_path = root / CENTER_FILENAME
        with open_catalog(catalog_path) as catalog:
            roster_id = freeze_tray(
                catalog, "OVERLAP-01", "R-01",
                (PhysicalSlot(1, column, label) for column, label in enumerate(LABELS, 1)),
            )

        station_paths = {}
        station_frozens: dict[str, dict[str, int]] = {}
        # 准备岗与两站各自建库、录入并封存；甲站的两组候选各占一个冻结修订。
        for station, readings in READINGS.items():
            path = root / f"station-{station}.sqlite3"
            station_paths[station] = path
            with closing(connect(path)) as db, open_catalog(catalog_path) as catalog:
                journal = ObservationJournal(db)
                first_revision = record_readings(journal, catalog, station, roster_id, readings)
                first_frozen = freeze_station(journal, station, first_revision)
                if station == "A":
                    second_revision = record_readings(
                        journal, catalog, station, roster_id, readings
                    )
                    second_frozen = freeze_station(journal, station, second_revision)
                else:
                    second_frozen = first_frozen
                station_frozens[station] = {"first": first_frozen, "second": second_frozen}
        frozen_by_case = {
            CASES[0]["name"]: {
                "A": station_frozens["A"]["first"], "B": station_frozens["B"]["first"]
            },
            CASES[1]["name"]: {
                "A": station_frozens["A"]["second"], "B": station_frozens["B"]["first"]
            },
        }

        # 关站：两站各自在自己的库内按确切冻结号发行 V2，原读数留站。
        issued: dict[str, dict[str, bytes]] = {}
        for case in CASES:
            case_raws = {}
            for station in ("A", "B"):
                frozen_id = frozen_by_case[case["name"]][station]
                with closing(connect(station_paths[station])) as db, \
                        open_catalog(catalog_path) as catalog:
                    journal = ObservationJournal(db)
                    outbox = Outbox(db)
                    candidates = case["candidates"][station]
                    raw = issue_v2(journal, catalog, outbox, frozen_id, candidates)
                    # 等价重发必须领回原件。
                    if issue_v2(journal, catalog, outbox, frozen_id, candidates) != raw:
                        raise AssertionError("V2 reissue must return the stored original bytes")
                    case_raws[station] = raw
            issued[case["name"]] = case_raws

        # 中心只凭清册库和中心库接纳、签发。
        with closing(connect(center_path)) as db, open_catalog(catalog_path) as catalog:
            archive = AdmissionArchive(db)
            register = ReportRegister(db)
            published = []
            for case in CASES:
                raws = issued[case["name"]]
                first = accept_v2(archive, catalog, roster_id, raws["A"])
                second = accept_v2(archive, catalog, roster_id, raws["B"])
                report, receipt = publish_v2(
                    archive, catalog, register, first.admission_id, second.admission_id
                )
                body = report.body
                expected = tuple(case["expected_bounds"])
                if (body.lower, body.upper) != expected:
                    raise AssertionError(
                        f"{case['name']}: expected {expected}, got {(body.lower, body.upper)}"
                    )
                published.append((report.report_id, receipt.receipt_id, body))
                summary["cases"].append({
                    "name": case["name"],
                    "admissions": [first.admission_id, second.admission_id],
                    "bounds": [body.lower, body.upper],
                    "lower_witness": list(body.lower_witness),
                    "upper_witness": list(body.upper_witness),
                    "sources": [
                        {"admission_id": source.admission_id, "station": source.station,
                         "frozen_id": source.frozen_id}
                        for source in body.sources
                    ],
                })

        # 中心重开：按原报告号领回当时的双件出处、结论与回执。
        with closing(connect(center_path)) as reopened:
            register = ReportRegister(reopened)
            for index, (report_id, receipt_id, body) in enumerate(published):
                stored_report, stored_receipt = read_v2(register, report_id)
                if stored_report.body != body or stored_receipt.receipt_id != receipt_id:
                    raise AssertionError("reopened center returned a different V2 report")
                summary["cases"][index]["reopened_report_id"] = report_id
                summary["cases"][index]["reopened_receipt_id"] = stored_receipt.receipt_id
    return summary


def main() -> None:
    control = v1_control()
    print("V1_CONTROL " + json.dumps(control, ensure_ascii=False))
    demo = v2_demo()
    print("V2_OVERLAP_DEMO " + json.dumps(demo, ensure_ascii=False))


if __name__ == "__main__":
    main()
