from dataclasses import dataclass

from admission.selection import SelectedPair
from tray.resolve import slots_in_roster_order


@dataclass(frozen=True)
class Coverage:
    covered: tuple[str, ...]
    repeated: tuple[str, ...]
    uninspected: tuple[str, ...]

    @property
    def covered_count(self) -> int:
        return len(self.covered)

    @property
    def repeated_count(self) -> int:
        return len(self.repeated)

    @property
    def uninspected_count(self) -> int:
        return len(self.uninspected)


def calculate_coverage(pair: SelectedPair) -> Coverage:
    left = set(pair.first.envelope.summary.slots)
    right = set(pair.second.envelope.summary.slots)
    covered = left | right
    roster = pair.roster
    return Coverage(
        slots_in_roster_order(roster, covered),
        slots_in_roster_order(roster, left & right),
        slots_in_roster_order(roster, set(roster.labels) - covered),
    )
