from typing import Iterable

from .measure import Measurement


def apply_amendments(
    previous: Iterable[tuple[str, Measurement]], updates: Iterable[tuple[str, Measurement]]
) -> tuple[tuple[str, Measurement], ...]:
    records = dict(previous)
    records.update(updates)
    return tuple(records.items())
