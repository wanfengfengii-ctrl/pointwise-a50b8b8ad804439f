"""V2 站端候选槽与整站可行槽集合族。

每条有效读数恰占一个候选槽，同一冻结快照内不同读数不得重占。
本模块把调用方给出的候选映射归约为“满足全部占用条件时能出现的整站槽集合族”。
槽集合族只含匿名资格：原读数、录入键和录入顺序都不进入结果。
"""
from typing import Iterable

from observations.measure import has_reading
from observations.revision import FrozenRevision
from tray.layout import require_name
from tray.roster import FrozenRoster


def _valid_keys(frozen: FrozenRevision) -> frozenset[str]:
    return frozenset(label for label, value in frozen.reading.records if has_reading(value))


def check_candidates(
    frozen: FrozenRevision, roster: FrozenRoster, candidates: dict
) -> dict[str, frozenset[str]]:
    """校验候选字典并返回归一成 frozenset 的候选映射。"""
    if frozen.reading.roster_id != roster.roster_id:
        raise ValueError('frozen revision belongs to a different roster')
    if not isinstance(candidates, dict):
        raise ValueError('candidates must be a dictionary keyed by station entry keys')
    valid = _valid_keys(frozen)
    if frozenset(candidates.keys()) != valid:
        raise ValueError('candidate keys must cover exactly the effective readings')
    labels = frozenset(roster.labels)
    normalized: dict[str, frozenset[str]] = {}
    for key, options in candidates.items():
        require_name(key, 'candidate entry key')
        if not isinstance(options, (list, tuple, set, frozenset)):
            raise ValueError('each candidate entry must be a list, tuple, set or frozenset')
        chosen = frozenset(options)
        if not chosen:
            raise ValueError('an effective reading needs a nonempty candidate slot set')
        if len(chosen) != len(options):
            raise ValueError('candidate slots must be distinct roster labels')
        for label in chosen:
            require_name(label, 'candidate slot')
        if not chosen.issubset(labels):
            raise ValueError('candidate slot is not part of the frozen roster')
        normalized[key] = chosen
    return normalized

def feasible_slot_families(
    frozen: FrozenRevision, roster: FrozenRoster, candidates: dict
) -> tuple[frozenset[str], ...]:
    """计算整站可行槽集合族，按清册序确定排列。"""
    normalized = check_candidates(frozen, roster, candidates)
    occupied: set[frozenset[str]] = {frozenset()}
    # 录入键的迭代顺序不影响集合族；这里固定按键名消费以保证过程确定。
    for key in sorted(normalized):
        options = normalized[key]
        updated: set[frozenset[str]] = set()
        for current in occupied:
            for slot in options:
                if slot not in current:
                    updated.add(current | {slot})
        occupied = updated
        if not occupied:
            break
    return order_families(roster, occupied)


def order_families(
    roster: FrozenRoster, families: Iterable[frozenset[str]]
) -> tuple[frozenset[str], ...]:
    """把一组槽集合按各自的清册序表示后做确定排序。"""
    ordered = [tuple(label for label in roster.labels if label in family) for family in families]
    ordered.sort()
    return tuple(frozenset(slots) for slots in ordered)


def canonical_family(
    roster: FrozenRoster, families: Iterable[Iterable[str]]
) -> tuple[frozenset[str], ...]:
    """接纳侧使用：把来件表达的集合族规范化并校验内部一致性。"""
    converted: list[frozenset[str]] = []
    labels = frozenset(roster.labels)
    for family in families:
        if not isinstance(family, (list, tuple, set, frozenset)):
            raise ValueError('each feasible slot set must be a collection of slot labels')
        slots = frozenset(family)
        if isinstance(family, (list, tuple)) and len(slots) != len(family):
            raise ValueError('a feasible slot set must not repeat a slot')
        for label in slots:
            require_name(label, 'feasible slot')
        if not slots.issubset(labels):
            raise ValueError('feasible slot set contains a label outside the frozen roster')
        converted.append(slots)
    if not converted:
        raise ValueError('a V2 station must endorse at least one feasible slot set')
    widths = {len(slots) for slots in converted}
    if len(widths) != 1:
        raise ValueError('feasible slot sets must all occupy the same number of slots')
    unique = frozenset(converted)
    if len(unique) != len(converted):
        raise ValueError('duplicate feasible slot sets in the V2 payload')
    return order_families(roster, unique)
