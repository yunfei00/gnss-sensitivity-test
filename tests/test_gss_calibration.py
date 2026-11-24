import pytest
from desktop.core import DeviceError
from desktop.gss_calibration import GssCalibration


def test_calibrated_reference_db_not_absolute_dbm():
    c = GssCalibration("6.00.02", -120.0, 10.5, "power-meter-record-001",
                       "DUT antenna input", -125.0, -115.0)
    assert c.to_reference_db(-121.0) == 9.5
    assert "POW_LEV,v1_a1,9.5,GPS,23,0,0,1,1,1,1" in c.command(-121.0)


def test_out_of_calibrated_range_fails_closed():
    c = GssCalibration("6.00.02", -120, 10.5, "meter-001", "DUT", -122, -118)
    with pytest.raises(DeviceError):
        c.command(-123)


def test_no_evidence_or_unknown_version():
    with pytest.raises(DeviceError):
        GssCalibration("6.00.02", -120, 10, "", "DUT", -125, -115)
    with pytest.raises(DeviceError):
        GssCalibration("unknown", -120, 10, "meter", "DUT", -125, -115)
