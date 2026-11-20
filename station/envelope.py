from dataclasses import dataclass
from fractions import Fraction
import json

from observations.measure import encode_measurement, parse_measurement
from tray.layout import require_name

from .summary import StationSummary


@dataclass(frozen=True)
class V1Envelope:
    station: str
    tray: str
    round_id: str
    roster_id: str
    frozen_id: int
    summary: StationSummary


_FIELDS = frozenset({'version', 'station', 'tray', 'round_id', 'roster_id', 'frozen_id',
                     'slots', 'count', 'total'})


def check_summary(summary: StationSummary) -> None:
    if not isinstance(summary.slots, tuple) or len(summary.slots) > 12:
        raise ValueError('invalid inspected slot table')
    for label in summary.slots:
        require_name(label, 'inspected slot')
    if len(set(summary.slots)) != len(summary.slots):
        raise ValueError('duplicate inspected slot')
    if type(summary.count) is not int or summary.count != len(summary.slots):
        raise ValueError('effective count does not equal the inspected slot count')
    if not isinstance(summary.total, Fraction):
        raise ValueError('station total must be an exact rational')
    if summary.count == 0 and summary.total != 0:
        raise ValueError('an empty station must report zero total')


def _check_envelope(envelope: V1Envelope) -> None:
    require_name(envelope.station, 'station')
    require_name(envelope.tray, 'tray')
    require_name(envelope.round_id, 'round')
    require_name(envelope.roster_id, 'roster id')
    if type(envelope.frozen_id) is not int or not 0 < envelope.frozen_id <= 2**63 - 1:
        raise ValueError('invalid frozen revision id')
    check_summary(envelope.summary)


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError('duplicate field in envelope')
    return fields


def encode_envelope(envelope: V1Envelope) -> bytes:
    _check_envelope(envelope)
    fields = {
        'version': 1,
        'station': envelope.station,
        'tray': envelope.tray,
        'round_id': envelope.round_id,
        'roster_id': envelope.roster_id,
        'frozen_id': envelope.frozen_id,
        'slots': envelope.summary.slots,
        'count': envelope.summary.count,
        'total': encode_measurement(envelope.summary.total),
    }
    return json.dumps(fields, sort_keys=True, separators=(',', ':')).encode('ascii')


def decode_envelope(raw: bytes) -> V1Envelope:
    if not isinstance(raw, bytes):
        raise ValueError('expected original UTF-8 envelope bytes')
    try:
        fields = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_fields)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('malformed V1 envelope') from exc
    if not isinstance(fields, dict) or fields.keys() != _FIELDS:
        raise ValueError('unexpected V1 envelope fields')
    if type(fields['version']) is not int or fields['version'] != 1:
        raise ValueError('expected version 1 envelope')
    if not isinstance(fields['slots'], list) or not isinstance(fields['total'], list):
        raise ValueError('expected a slot list and a rational pair')
    summary = StationSummary(
        tuple(fields['slots']), fields['count'], parse_measurement(fields['total'])
    )
    envelope = V1Envelope(
        fields['station'], fields['tray'], fields['round_id'], fields['roster_id'],
        fields['frozen_id'], summary,
    )
    _check_envelope(envelope)
    return envelope
