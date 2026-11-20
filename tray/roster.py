from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Iterable

from .layout import PhysicalSlot, require_name, validate_layout


@dataclass(frozen=True)
class FrozenRoster:
    roster_id: str
    tray: str
    round_id: str
    slots: tuple[PhysicalSlot, ...]

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(slot.label for slot in self.slots)


def build_roster(tray: str, round_id: str, slots: Iterable[PhysicalSlot]) -> FrozenRoster:
    require_name(tray, 'tray')
    require_name(round_id, 'round')
    ordered = validate_layout(slots)
    labels = {slot.label for slot in ordered}
    if len(labels) != len(ordered):
        raise ValueError('duplicate slot label')

    layout = [[slot.row, slot.column, slot.label] for slot in ordered]
    identity = json.dumps([tray, round_id, layout], separators=(',', ':'))
    roster_id = sha256(identity.encode('ascii')).hexdigest()
    return FrozenRoster(roster_id, tray, round_id, ordered)
