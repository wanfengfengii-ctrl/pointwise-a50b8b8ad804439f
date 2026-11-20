from dataclasses import dataclass
from fractions import Fraction

from admission.selection import SelectedPair


@dataclass(frozen=True)
class StationTotals:
    station: str
    count: int
    total: Fraction
    mean: Fraction | None


def calculate_station_totals(pair: SelectedPair) -> tuple[StationTotals, ...]:
    totals = []
    for accepted in pair.members:
        envelope = accepted.envelope
        summary = envelope.summary
        mean = summary.total / summary.count if summary.count else None
        totals.append(StationTotals(envelope.station, summary.count, summary.total, mean))
    return tuple(totals)
