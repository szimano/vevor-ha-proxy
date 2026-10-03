"""Parse a Wunderground-format payload into metric sensor values."""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .conversions import f_to_c, in_to_mm, inhg_to_hpa, mph_to_kmh

_SENTINEL = -9999.0
_IGNORED_PARAMS = {"id", "dateutc", "action", "realtime", "rtfreq", "softwaretype"}


def _identity(value: float) -> float:
    return value


@dataclass(frozen=True)
class ReadingSpec:
    key: str
    param: str  # lowercase query parameter name
    convert: Callable[[float], float]
    decimals: int


SPECS: tuple[ReadingSpec, ...] = (
    ReadingSpec("temperature", "tempf", f_to_c, 1),
    ReadingSpec("dew_point", "dewptf", f_to_c, 1),
    ReadingSpec("humidity", "humidity", _identity, 1),
    ReadingSpec("pressure", "baromin", inhg_to_hpa, 1),
    ReadingSpec("wind_speed", "windspeedmph", mph_to_kmh, 1),
    ReadingSpec("wind_gust", "windgustmph", mph_to_kmh, 1),
    ReadingSpec("wind_direction", "winddir", _identity, 1),
    ReadingSpec("rain_last_hour", "rainin", in_to_mm, 2),
    ReadingSpec("rain_today", "dailyrainin", in_to_mm, 2),
    ReadingSpec("uv_index", "uv", _identity, 1),
    ReadingSpec("solar_radiation", "solarradiation", _identity, 1),
)
_KNOWN_PARAMS = {spec.param for spec in SPECS}


def _to_number(raw: Any) -> float | None:
    try:
        value = float(str(raw).strip())
    except ValueError:
        return None
    if not math.isfinite(value) or value == _SENTINEL:
        return None
    return value


def parse_readings(payload: Mapping[str, Any]) -> dict[str, float]:
    """Return metric values keyed by sensor key; invalid fields are skipped."""
    lowered = {str(k).lower(): v for k, v in payload.items()}
    out: dict[str, float] = {}
    for spec in SPECS:
        if spec.param not in lowered:
            continue
        value = _to_number(lowered[spec.param])
        if value is None:
            continue
        out[spec.key] = round(spec.convert(value), spec.decimals)
    return out


def unknown_params(payload: Mapping[str, Any]) -> set[str]:
    """Return parameter names we neither map nor deliberately ignore."""
    return {
        str(k)
        for k in payload
        if str(k).lower() not in _KNOWN_PARAMS | _IGNORED_PARAMS
    }
