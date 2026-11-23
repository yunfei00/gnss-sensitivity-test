from dataclasses import replace

import pytest
from geographiclib.geodesic import Geodesic

from desktop.core import RunConfig, evaluate


def observation(time=20.3, distance=101.3, satellites=4):
    t0 = 1_000_000_000
    fix = t0 + round(time * 1e9)
    coordinates = Geodesic.WGS84.Direct(0, 0, 90, distance)
    return {"integrity": "COMPLETE", "status": "OBSERVED", "source": "GPS_PROVIDER",
            "t0_monotonic_ns": t0, "first_fix_elapsed_realtime_ns": fix,
            "latitude": coordinates["lat2"], "longitude": coordinates["lon2"],
            "used_in_fix": satellites, "satellite_elapsed_ns": fix, "satellite_association": "MOCK"}


@pytest.mark.parametrize("raw,status,reason", [
    (observation(), "PASS", "THRESHOLDS_MET"),
    (observation(time=20.300000001), "FAIL", "TTFF"),
    (observation(distance=101.30001), "FAIL", "HORIZONTAL_ERROR"),
    (observation(satellites=3), "FAIL", "USED_IN_FIX"),
    (observation(satellites=None), "INVALID", "UNRELIABLE_USED_IN_FIX"),
    (observation(time=0), "INVALID", "INVALID_FIX_TIME"),
    (observation(time=31), "INVALID", "INVALID_FIX_TIME"),
    (observation() | {"mock_location": True}, "INVALID", "INVALID_FIX_SOURCE"),
    (observation() | {"latitude": 91}, "INVALID", "INVALID_COORDINATES"),
    (observation() | {"satellite_elapsed_ns": 1}, "INVALID", "UNRELIABLE_USED_IN_FIX"),
    ({"reason": "TIMEOUT", "status": "FAIL", "integrity": "COMPLETE",
      "t0_monotonic_ns": 1}, "FAIL", "TIMEOUT"),
    ({"reason": "TIMEOUT", "status": "FAIL", "integrity": "INVALID"}, "INVALID", "TIMEOUT"),
])
def test_verdict(raw, status, reason):
    result = evaluate(RunConfig(-122, 3), raw)
    assert (result["status"], result["reason"]) == (status, reason)


def test_geodesic_uses_coordinates_and_phone_clock():
    raw = observation() | {"ttff_s": 1, "horizontal_error_m": 999, "accuracy": 999}
    result = evaluate(RunConfig(-122, 3), raw)
    assert result["ttff_s"] == 20.3
    assert result["horizontal_error_m"] == pytest.approx(101.3)


@pytest.mark.parametrize("field,value", [
    ("min_power_dbm", -119), ("max_levels", 0), ("observation_s", 19),
    ("reference_lat", float("nan")), ("power_tolerance_db", 0.5), ("startup_mode", "UNKNOWN"),
    ("mock", False),
])
def test_reject_invalid_config(field, value):
    with pytest.raises(ValueError):
        replace(RunConfig(-122, 3), **{field: value})
