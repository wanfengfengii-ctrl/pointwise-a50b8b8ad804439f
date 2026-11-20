"""V2 签发：两份异站资格的交集片数精确上下界与见证。"""
from admission.archive import AdmissionArchive
from admission.selection_v2 import select_v2_pair
from tray.catalog import RosterCatalog

from .overlap import calculate_bounds
from .register import OverlapBody, ReportRegister, ReportSource, ReviewReceipt, OverlapReport


def publish_v2(
    archive: AdmissionArchive,
    catalog: RosterCatalog,
    register: ReportRegister,
    first_id: int,
    second_id: int,
) -> tuple[OverlapReport, ReviewReceipt]:
    pair = select_v2_pair(archive, catalog, first_id, second_id)
    sources = tuple(
        ReportSource(member.admission_id, member.envelope.station, member.envelope.frozen_id)
        for member in pair.members
    )
    bounds = calculate_bounds(pair)
    body = OverlapBody(
        pair.roster.tray, pair.roster.round_id, pair.roster.roster_id, sources,
        bounds.lower, bounds.upper,
        bounds.lower_witness.as_tuple(), bounds.upper_witness.as_tuple(),
    )
    return register.commit_v2(body)
