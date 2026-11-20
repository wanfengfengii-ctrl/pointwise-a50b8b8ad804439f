"""V2 关站签发：按确切冻结号发行只含匿名资格的站件。"""
from observations.journal import ObservationJournal
from observations.revision import get_frozen_revision
from tray.catalog import RosterCatalog

from .envelope_v2 import V2Envelope, encode_envelope_v2
from .outbox import Outbox
from .qualification import feasible_slot_families


def issue_v2(
    journal: ObservationJournal,
    catalog: RosterCatalog,
    outbox: Outbox,
    frozen_id: int,
    candidates: dict,
) -> bytes:
    frozen = get_frozen_revision(journal, frozen_id)
    roster = catalog.load_frozen(frozen.reading.roster_id)
    families = feasible_slot_families(frozen, roster, candidates)
    if not families:
        raise ValueError('no station-wide feasible slot assignment for the given candidates')
    envelope = V2Envelope(
        frozen.reading.station, roster.tray, roster.round_id, roster.roster_id,
        frozen.frozen_id, families,
    )
    raw = encode_envelope_v2(envelope, roster)
    return outbox.save_v2(frozen_id, raw)
