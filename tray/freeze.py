from typing import Iterable

from .catalog import RosterCatalog
from .layout import PhysicalSlot
from .roster import build_roster


def freeze_tray(
    catalog: RosterCatalog, tray: str, round_id: str, slots: Iterable[PhysicalSlot]
) -> str:
    return catalog.save_frozen(build_roster(tray, round_id, slots))
