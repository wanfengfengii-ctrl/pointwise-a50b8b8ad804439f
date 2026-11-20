from station.envelope import V1Envelope, encode_envelope


def source_key(envelope: V1Envelope) -> tuple[str, int]:
    return envelope.station, envelope.frozen_id


def content_key(envelope: V1Envelope) -> bytes:
    return encode_envelope(envelope)
