import pytest
from desktop.core import DeviceError
from desktop.stage45_phone import UsbGnssAdapter


class FakePhone:
    def __init__(self, ready=True, active=None):
        self.ready, self.active = ready, active
    def command(self, kind):
        assert kind == "PING"
        return {"ready": self.ready, "active_attempt": self.active}


def test_automatic_hot_evidence_is_not_fabricated_cold_reset(tmp_path):
    adapter = UsbGnssAdapter(None, "adb", tmp_path/"audit.sqlite", None)
    adapter.phone = FakePhone()
    adapter.prepare("HOT")
    attempt, evidence = adapter.prepared
    assert attempt
    assert "AUTO_HOT" in evidence
    assert "not reset" in evidence


def test_automatic_hot_rejects_busy_or_not_ready(tmp_path):
    adapter = UsbGnssAdapter(None, "adb", tmp_path/"audit.sqlite", None)
    adapter.phone = FakePhone(active="another")
    with pytest.raises(DeviceError):
        adapter.prepare("HOT")
    adapter.phone = FakePhone(ready=False)
    with pytest.raises(DeviceError):
        adapter.prepare("HOT")
    with pytest.raises(DeviceError):
        adapter.prepare("COLD")
