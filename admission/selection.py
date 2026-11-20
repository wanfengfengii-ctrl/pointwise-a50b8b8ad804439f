from dataclasses import dataclass

from tray.catalog import RosterCatalog
from tray.roster import FrozenRoster

from .archive import AcceptedEnvelope, AdmissionArchive


@dataclass(frozen=True)
class SelectedPair:
    roster: FrozenRoster
    first: AcceptedEnvelope
    second: AcceptedEnvelope

    @property
    def members(self) -> tuple[AcceptedEnvelope, AcceptedEnvelope]:
        return self.first, self.second


def select_pair(
    archive: AdmissionArchive, catalog: RosterCatalog, first_id: int, second_id: int
) -> SelectedPair:
    first, second = archive.find(first_id), archive.find(second_id)
    left, right = first.envelope, second.envelope
    if left.station == right.station:
        raise ValueError('a review requires two different stations')
    if (left.tray, left.round_id, left.roster_id) != (right.tray, right.round_id, right.roster_id):
        raise ValueError('selected envelopes must share a tray, round and frozen roster')
    return SelectedPair(catalog.load_frozen(left.roster_id), first, second)
