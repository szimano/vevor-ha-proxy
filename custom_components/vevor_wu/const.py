"""Constants for the Vevor weather station integration."""
from datetime import timedelta

DOMAIN = "vevor_wu"
STALE_AFTER = timedelta(minutes=10)


def signal_update(entry_id: str) -> str:
    """Dispatcher signal fired when a new reading is stored."""
    return f"{DOMAIN}_update_{entry_id}"
