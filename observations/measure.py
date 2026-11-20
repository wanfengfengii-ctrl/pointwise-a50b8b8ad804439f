from fractions import Fraction

MISSING = None
Measurement = Fraction | None


def parse_measurement(value: object) -> Measurement:
    if value is MISSING or isinstance(value, Fraction):
        return value
    if type(value) is int:
        return Fraction(value)
    if isinstance(value, (tuple, list)) and len(value) == 2:
        numerator, denominator = value
        if type(numerator) is int and type(denominator) is int and denominator > 0:
            return Fraction(numerator, denominator)
    raise ValueError('expected missing or an exact measurement with a positive denominator')


def encode_measurement(value: Measurement) -> list[int] | None:
    if value is MISSING:
        return None
    return [value.numerator, value.denominator]


def has_reading(value: Measurement) -> bool:
    return value is not MISSING
