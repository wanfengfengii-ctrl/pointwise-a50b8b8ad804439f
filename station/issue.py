from observations.journal import ObservationJournal
from observations.revision import get_frozen_revision
from tray.catalog import RosterCatalog

from .envelope import V1Envelope, encode_envelope
from .outbox import Outbox
from .summary import summarize_revision


def issue_v1(
    journal: ObservationJournal, catalog: RosterCatalog, outbox: Outbox, frozen_id: int
) -> bytes:
    frozen = get_frozen_revision(journal, frozen_id)
    reading = frozen.reading
    roster = catalog.load_frozen(reading.roster_id)
    envelope = V1Envelope(
        reading.station, roster.tray, roster.round_id, roster.roster_id,
        frozen.frozen_id, summarize_revision(frozen, roster),
    )
    return outbox.save(frozen_id, encode_envelope(envelope))
