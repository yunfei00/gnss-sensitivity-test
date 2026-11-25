import pytest
from desktop.core import DeviceError
from desktop.gss_calibration import GssCalibration
from desktop.stage45_instruments import GssCalibratedAdapter, CmwLteAdapter


def calibration():
    return GssCalibration("6.00.02", -120, 10.5, "meter-record", "DUT input", -125, -115)


def test_gss_requires_independent_power_evidence(monkeypatch):
    commands = []
    def fake_run(host, port, tx, batch, expected, log):
        commands.extend(batch)
        return (expected if expected is not None else 5), ""
    monkeypatch.setattr("desktop.stage45_instruments.run_operation", fake_run)
    gss = GssCalibratedAdapter("127.0.0.1", calibration())
    gss.start_scenario("scenario.scn")
    gss.set_power_dbm(-121)
    with pytest.raises(DeviceError, match="独立 RF"):
        gss.verify_power_dbm(-121)
    assert "POW_LEV,v1_a1,9.5" in " ".join(commands)
    assert gss.safe_stop() is True


def test_gss_evidence_verified_once_per_level(monkeypatch):
    states = [2, 5, 5, 5, 5]
    def fake_run(host, port, tx, batch, expected, log):
        if batch == ["NULL"]:
            return states.pop(0), ""
        return expected if expected is not None else 5, ""
    monkeypatch.setattr("desktop.stage45_instruments.run_operation", fake_run)
    calls = []
    gss = GssCalibratedAdapter("127.0.0.1", calibration(),
                              confirm_power=lambda value, c: calls.append(value) or "meter-001")
    gss.start_scenario("scenario.scn")
    gss.set_power_dbm(-120)
    assert gss.verify_power_dbm(-120)
    assert gss.verify_power_dbm(-120)
    assert calls == [-120]


def test_cmw_does_not_turn_off_preexisting_cell(monkeypatch):
    class Fake:
        def __init__(self, host, port, emit): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def check(self): pass
        def read(self, cmd): return "Rohde,CMW500,123"
        def cell(self): return "ON"
        def wait_connected(self): return "CONN"
        def rrc(self): return "CONN"
        def switch(self, value): raise AssertionError("must not alter already-on cell")
    monkeypatch.setattr("desktop.stage45_instruments.CmwSession", Fake)
    cmw = CmwLteAdapter("127.0.0.1")
    cmw.preflight()
    cmw.establish_lte()
    assert cmw.rrc_connected()
    assert cmw.safe_stop()
