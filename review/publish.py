from admission.archive import AdmissionArchive
from admission.selection import select_pair
from tray.catalog import RosterCatalog

from .coverage import calculate_coverage
from .register import ReportRegister, ReportSource, ReviewBody, ReviewReceipt, ReviewReport
from .totals import calculate_station_totals


def publish_v1(
    archive: AdmissionArchive,
    catalog: RosterCatalog,
    register: ReportRegister,
    first_id: int,
    second_id: int,
) -> tuple[ReviewReport, ReviewReceipt]:
    pair = select_pair(archive, catalog, first_id, second_id)
    sources = tuple(
        ReportSource(member.admission_id, member.envelope.station, member.envelope.frozen_id)
        for member in pair.members
    )
    body = ReviewBody(
        pair.roster.tray, pair.roster.round_id, pair.roster.roster_id, sources,
        calculate_coverage(pair), calculate_station_totals(pair),
    )
    return register.commit(body)
