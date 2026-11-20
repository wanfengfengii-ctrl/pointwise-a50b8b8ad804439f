from station.envelope import V1Envelope
from tray.resolve import slots_in_roster_order
from tray.roster import FrozenRoster


def validate_roster_binding(envelope: V1Envelope, roster: FrozenRoster) -> None:
    expected = (roster.tray, roster.round_id, roster.roster_id)
    if (envelope.tray, envelope.round_id, envelope.roster_id) != expected:
        raise ValueError('envelope provenance does not match the selected roster')
    ordered = slots_in_roster_order(roster, envelope.summary.slots)
    if ordered != envelope.summary.slots:
        raise ValueError('inspected slots must follow the frozen roster order')
