"""V2 站件信封：只交接匿名资格与出处，不携带原读数。"""
from dataclasses import dataclass
import json

from tray.layout import require_name

from .qualification import canonical_family
from tray.roster import FrozenRoster


@dataclass(frozen=True)
class V2Envelope:
    station: str
    tray: str
    round_id: str
    roster_id: str
    frozen_id: int
    families: tuple[frozenset[str], ...]


_FIELDS = frozenset({'version', 'station', 'tray', 'round_id', 'roster_id',
                     'frozen_id', 'sets'})


def _check_identity(envelope: V2Envelope) -> None:
    require_name(envelope.station, 'station')
    require_name(envelope.tray, 'tray')
    require_name(envelope.round_id, 'round')
    require_name(envelope.roster_id, 'roster id')
    if type(envelope.frozen_id) is not int or not 0 < envelope.frozen_id <= 2**63 - 1:
        raise ValueError('invalid frozen revision id')
    if not isinstance(envelope.families, tuple) or not envelope.families:
        raise ValueError('a V2 envelope must carry a nonempty feasible family')


def _encode_sets(families: tuple[frozenset[str], ...], roster: FrozenRoster) -> list[list[str]]:
    return [[label for label in roster.labels if label in family] for family in families]


def encode_envelope_v2(envelope: V2Envelope, roster: FrozenRoster) -> bytes:
    _check_identity(envelope)
    fields = {
        'version': 2,
        'station': envelope.station,
        'tray': envelope.tray,
        'round_id': envelope.round_id,
        'roster_id': envelope.roster_id,
        'frozen_id': envelope.frozen_id,
        'sets': _encode_sets(envelope.families, roster),
    }
    return json.dumps(fields, sort_keys=True, separators=(',', ':')).encode('ascii')


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError('duplicate field in envelope')
    return fields


def decode_envelope_v2(raw: bytes, roster: FrozenRoster | None = None) -> V2Envelope:
    """解析 V2 原件。

    提供 ``roster`` 时顺带把集合族按清册规范化（接纳路径使用）；
    纯解析只做结构校验，保持对坏件的 ValueError 语义。
    """
    if not isinstance(raw, bytes):
        raise ValueError('expected original UTF-8 envelope bytes')
    try:
        fields = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_fields)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('malformed V2 envelope') from exc
    if not isinstance(fields, dict) or fields.keys() != _FIELDS:
        raise ValueError('unexpected V2 envelope fields')
    if type(fields['version']) is not int or fields['version'] != 2:
        raise ValueError('expected version 2 envelope')
    if not isinstance(fields['sets'], list):
        raise ValueError('expected a list of feasible slot sets')
    if roster is not None:
        families = canonical_family(roster, fields['sets'])
    else:
        families = _structural_sets(fields['sets'])
    envelope = V2Envelope(
        fields['station'], fields['tray'], fields['round_id'], fields['roster_id'],
        fields['frozen_id'], families,
    )
    _check_identity(envelope)
    return envelope


def _structural_sets(sets: list) -> tuple[frozenset[str], ...]:
    families: list[frozenset[str]] = []
    for family in sets:
        if not isinstance(family, list):
            raise ValueError('each feasible slot set must be a list of labels')
        members: set[str] = set()
        for label in family:
            require_name(label, 'feasible slot')
            members.add(label)
        if len(members) != len(family):
            raise ValueError('a feasible slot set must not repeat a slot')
        families.append(frozenset(members))
    if not families:
        raise ValueError('a V2 envelope must carry a nonempty feasible family')
    if len(frozenset(families)) != len(families):
        raise ValueError('duplicate feasible slot sets in the V2 payload')
    widths = {len(family) for family in families}
    if len(widths) != 1:
        raise ValueError('feasible slot sets must all occupy the same number of slots')
    return tuple(families)
