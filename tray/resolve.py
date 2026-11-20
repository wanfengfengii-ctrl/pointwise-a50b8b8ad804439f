from typing import Iterable

from .layout import PhysicalSlot
from .roster import FrozenRoster


def resolve_slot(roster: FrozenRoster, label: str) -> PhysicalSlot:
    for slot in roster.slots:
        if slot.label == label:
            return slot
    raise ValueError(f'slot {label!r} is not in roster {roster.roster_id}')


def slots_in_roster_order(roster: FrozenRoster, labels: Iterable[str]) -> tuple[str, ...]:
    wanted = set(labels)
    if not wanted.issubset(roster.labels):
        raise ValueError('slot set contains a label outside the frozen roster')
    return tuple(label for label in roster.labels if label in wanted)
