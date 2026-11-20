from dataclasses import dataclass
from fractions import Fraction

from observations.journal import FrozenRevision
from observations.measure import has_reading
from tray.resolve import slots_in_roster_order
from tray.roster import FrozenRoster


@dataclass(frozen=True)
class StationSummary:
    slots: tuple[str, ...]
    count: int
    total: Fraction


def summarize_revision(frozen: FrozenRevision, roster: FrozenRoster) -> StationSummary:
    if frozen.reading.roster_id != roster.roster_id:
        raise ValueError('revision belongs to a different roster')
    valid = {label: value for label, value in frozen.reading.records if has_reading(value)}
    ordered = slots_in_roster_order(roster, valid)
    total = sum((valid[label] for label in ordered), Fraction(0))
    return StationSummary(ordered, len(ordered), total)
