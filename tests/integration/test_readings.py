import pytest

from custom_components.vevor_wu.conversions import (
    f_to_c,
    in_to_mm,
    inhg_to_hpa,
    mph_to_kmh,
)
from custom_components.vevor_wu.readings import parse_readings, unknown_params


def test_conversions():
    assert f_to_c(32) == 0
    assert f_to_c(212) == pytest.approx(100)
    assert inhg_to_hpa(29.92) == pytest.approx(1013.2, abs=0.1)
    assert mph_to_kmh(10) == pytest.approx(16.09344)
    assert in_to_mm(1) == pytest.approx(25.4)


def test_parse_converts_to_metric_and_rounds():
    out = parse_readings(
        {
            "ID": "X",
            "tempf": "50.0",
            "dewptf": "41.0",
            "humidity": "60",
            "baromin": "29.92",
            "windspeedmph": "10",
            "windgustmph": "15",
            "winddir": "270",
            "rainin": "0.1",
            "dailyrainin": "0.25",
            "UV": "3",
            "solarRadiation": "500.5",
        }
    )
    assert out == {
        "temperature": 10.0,
        "dew_point": 5.0,
        "humidity": 60.0,
        "pressure": 1013.2,
        "wind_speed": 16.1,
        "wind_gust": 24.1,
        "wind_direction": 270.0,
        "rain_last_hour": 2.54,
        "rain_today": 6.35,
        "uv_index": 3.0,
        "solar_radiation": 500.5,
    }


@pytest.mark.parametrize("bad", ["", "--", "abc", "-9999", "nan", "inf"])
def test_bad_values_are_skipped_per_field(bad):
    assert parse_readings({"tempf": bad, "humidity": "60"}) == {"humidity": 60.0}


def test_param_names_are_case_insensitive():
    assert parse_readings({"uv": "2", "SOLARRADIATION": "10"}) == {
        "uv_index": 2.0,
        "solar_radiation": 10.0,
    }


def test_unknown_params_ignores_known_and_housekeeping_keys():
    payload = {
        "ID": "x",
        "tempf": "1",
        "foo": "2",
        "action": "updateraw",
        "dateutc": "now",
        "realtime": "1",
        "rtfreq": "5",
    }
    assert unknown_params(payload) == {"foo"}
