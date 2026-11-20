"""V2 选件：同盘同轮同冻结清册的异站 V2 接纳件。"""
from dataclasses import dataclass

from station.envelope_v2 import decode_envelope_v2
from tray.catalog import RosterCatalog
from tray.roster import FrozenRoster

from .archive import AcceptedV2, AdmissionArchive


@dataclass(frozen=True)
class SelectedV2Pair:
    roster: FrozenRoster
    first: AcceptedV2
    second: AcceptedV2

    @property
    def members(self) -> tuple[AcceptedV2, AcceptedV2]:
        return self.first, self.second


def _provenance_roster_id(archive: AdmissionArchive, admission_id: int) -> str:
    row = archive.connection.execute(
        'SELECT raw FROM admitted_envelopes WHERE id = ? AND version = 2', (admission_id,)
    ).fetchone()
    if row is None:
        raise KeyError(admission_id)
    return decode_envelope_v2(row[0]).roster_id


def select_v2_pair(
    archive: AdmissionArchive, catalog: RosterCatalog, first_id: int, second_id: int
) -> SelectedV2Pair:
    # V2 入口收到任何已存在的 V1 接纳号都报 ValueError；未知号保持 KeyError。
    for admission_id in (first_id, second_id):
        version = archive.version_of(admission_id)
        if version is None:
            raise KeyError(admission_id)
        if version == 1:
            raise ValueError('a V2 review cannot select a V1 admission')
    roster = catalog.load_frozen(_provenance_roster_id(archive, first_id))
    first = archive.find_v2(first_id, roster)
    second = archive.find_v2(second_id, roster)
    left, right = first.envelope, second.envelope
    if left.station == right.station:
        raise ValueError('a review requires two different stations')
    if (left.tray, left.round_id, left.roster_id) != (right.tray, right.round_id, right.roster_id):
        raise ValueError('selected envelopes must share a tray, round and frozen roster')
    return SelectedV2Pair(roster, first, second)
