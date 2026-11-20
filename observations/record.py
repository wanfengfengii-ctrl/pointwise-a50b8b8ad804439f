from typing import Iterable

from tray.catalog import RosterCatalog
from tray.layout import require_name
from tray.resolve import resolve_slot

from .journal import ObservationJournal
from .measure import parse_measurement


def record_readings(
    journal: ObservationJournal,
    catalog: RosterCatalog,
    station: str,
    roster_id: str,
    readings: Iterable[tuple[str, object]],
) -> int:
    roster = catalog.load_frozen(roster_id)
    require_name(station, 'station')
    try:
        rows = iter(readings)
    except TypeError as exc:
        raise ValueError('readings must be an iterable of pairs') from exc

    updates = {}
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            raise ValueError('each reading needs a slot and a value')
        label, value = row
        require_name(label, 'slot label')
        slot = resolve_slot(roster, label)
        if slot.label in updates:
            raise ValueError(f'duplicate reading for slot {slot.label!r}')
        updates[slot.label] = parse_measurement(value)
    return journal.append_revision(station, roster, tuple(updates.items()))
