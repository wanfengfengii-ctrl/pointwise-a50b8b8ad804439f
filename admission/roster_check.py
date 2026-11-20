from station.envelope import V1Envelope
from station.envelope_v2 import V2Envelope
from station.qualification import canonical_family
from tray.resolve import slots_in_roster_order
from tray.roster import FrozenRoster


def validate_roster_binding(envelope: V1Envelope, roster: FrozenRoster) -> None:
    expected = (roster.tray, roster.round_id, roster.roster_id)
    if (envelope.tray, envelope.round_id, envelope.roster_id) != expected:
        raise ValueError('envelope provenance does not match the selected roster')
    ordered = slots_in_roster_order(roster, envelope.summary.slots)
    if ordered != envelope.summary.slots:
        raise ValueError('inspected slots must follow the frozen roster order')


def validate_v2_binding(envelope: V2Envelope, roster: FrozenRoster) -> V2Envelope:
    expected = (roster.tray, roster.round_id, roster.roster_id)
    if (envelope.tray, envelope.round_id, envelope.roster_id) != expected:
        raise ValueError('envelope provenance does not match the selected roster')
    canonical = canonical_family(roster, envelope.families)
    return V2Envelope(
        envelope.station, envelope.tray, envelope.round_id, envelope.roster_id,
        envelope.frozen_id, canonical,
    )
