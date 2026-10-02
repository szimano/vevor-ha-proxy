"""Imperial to metric conversions for Wunderground-format readings."""


def f_to_c(value: float) -> float:
    return (value - 32) * 5 / 9


def inhg_to_hpa(value: float) -> float:
    return value * 33.8639


def mph_to_kmh(value: float) -> float:
    return value * 1.609344


def in_to_mm(value: float) -> float:
    return value * 25.4
