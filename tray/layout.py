from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PhysicalSlot:
    row: int
    column: int
    label: str


def require_name(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a nonempty string')
    value.encode('utf-8')
    return value


def validate_layout(slots: Iterable[PhysicalSlot]) -> tuple[PhysicalSlot, ...]:
    try:
        ordered = tuple(slots)
    except TypeError as exc:
        raise ValueError('loading order must be iterable') from exc
    if len(ordered) > 12:
        raise ValueError('a tray holds at most twelve slots')

    positions = set()
    for slot in ordered:
        if not isinstance(slot, PhysicalSlot):
            raise ValueError('expected a PhysicalSlot')
        if type(slot.row) is not int or slot.row not in (1, 2):
            raise ValueError('row must be 1 or 2')
        if type(slot.column) is not int or not 1 <= slot.column <= 6:
            raise ValueError('column must be between 1 and 6')
        require_name(slot.label, 'slot label')
        position = (slot.row, slot.column)
        if position in positions:
            raise ValueError(f'duplicate physical position: {position}')
        positions.add(position)
    return ordered
