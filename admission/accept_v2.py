"""V2 中心接纳：按指定清册验收原始字节，资格规范化后首存。"""
from station.envelope_v2 import decode_envelope_v2, encode_envelope_v2
from tray.catalog import RosterCatalog

from .archive import AcceptedV2, AdmissionArchive
from .roster_check import validate_v2_binding


def accept_v2(
    archive: AdmissionArchive, catalog: RosterCatalog, roster_id: str, raw: bytes
) -> AcceptedV2:
    roster = catalog.load_frozen(roster_id)
    envelope = validate_v2_binding(decode_envelope_v2(raw), roster)
    content = encode_envelope_v2(envelope, roster)
    return archive.bind_first_v2(
        (envelope.station, envelope.frozen_id), content, raw, roster
    )
