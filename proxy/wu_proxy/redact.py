"""Helpers that keep the station's Wunderground password out of HA and logs."""
from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode

REDACTED = "REDACTED"
_SECRET_KEYS = {"password"}


def strip_secrets(params: Mapping[str, str]) -> dict[str, str]:
    """Return params without secret keys (case-insensitive)."""
    return {k: v for k, v in params.items() if k.lower() not in _SECRET_KEYS}


def redact_query(query: str) -> str:
    """Return a raw query string with secret values masked, safe to log."""
    pairs = parse_qsl(query, keep_blank_values=True)
    return urlencode(
        [(k, REDACTED if k.lower() in _SECRET_KEYS else v) for k, v in pairs]
    )
