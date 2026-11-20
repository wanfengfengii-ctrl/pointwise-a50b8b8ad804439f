"""两份 V2 资格的交集片数上下界与见证槽集合。"""
from dataclasses import dataclass

from admission.selection_v2 import SelectedV2Pair
from tray.resolve import slots_in_roster_order


@dataclass(frozen=True)
class OverlapWitness:
    first: tuple[str, ...]
    second: tuple[str, ...]

    def as_tuple(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return self.first, self.second


@dataclass(frozen=True)
class OverlapBounds:
    lower: int
    upper: int
    lower_witness: OverlapWitness
    upper_witness: OverlapWitness


def _ordered(roster, family) -> tuple[str, ...]:
    return slots_in_roster_order(roster, family)


def calculate_bounds(pair: SelectedV2Pair) -> OverlapBounds:
    roster = pair.roster
    left_families = pair.first.envelope.families
    right_families = pair.second.envelope.families
    lower = None
    upper = -1
    lower_witness = upper_witness = None
    # 槽位至多十二，两端集合族均为有限精确枚举，可直接求全部组合的精确极值。
    for left in left_families:
        left_set = set(left)
        for right in right_families:
            overlap = len(left_set & set(right))
            witness = OverlapWitness(_ordered(roster, left), _ordered(roster, right))
            if lower is None or overlap < lower:
                lower, lower_witness = overlap, witness
            if overlap > upper:
                upper, upper_witness = overlap, witness
    return OverlapBounds(lower, upper, lower_witness, upper_witness)
