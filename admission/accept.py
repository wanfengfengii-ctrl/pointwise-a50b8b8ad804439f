from station.envelope import decode_envelope
from tray.catalog import RosterCatalog

from .archive import AcceptedEnvelope, AdmissionArchive
from .identity import content_key, source_key
from .roster_check import validate_roster_binding


def accept_v1(
    archive: AdmissionArchive, catalog: RosterCatalog, roster_id: str, raw: bytes
) -> AcceptedEnvelope:
    roster = catalog.load_frozen(roster_id)
    envelope = decode_envelope(raw)
    validate_roster_binding(envelope, roster)
    return archive.bind_first(source_key(envelope), content_key(envelope), raw)
