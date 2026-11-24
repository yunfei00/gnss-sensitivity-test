from desktop.usb_debug import exchange
from desktop.protocol import envelope
from desktop.core import LinkError
import pytest


class Transport:
    def send_command(self, request):
        self.request = request

    def receive_event(self):
        return envelope("DEVICE_STATUS", self.request["run_id"],
                        self.request["attempt_id"],
                        {"response_to": self.request["message_id"], "ready": True})


def test_debug_exchange():
    assert exchange(Transport(), "debug", "HELLO", 1)["ready"]


def test_debug_rejects_wrong_response():
    class Wrong(Transport):
        def receive_event(self):
            return envelope("DEVICE_STATUS", "other", payload={"response_to": "wrong"})
    with pytest.raises(LinkError):
        exchange(Wrong(), "debug", "PING", 1)


def test_root_shell_without_su(monkeypatch):
    from desktop.usb_debug import probe_root
    monkeypatch.setattr("desktop.usb_debug.run_adb", lambda *a, **kw: "uid=0(root)")
    assert probe_root("adb", "A")[0] == "ADB Shell 已获得 Root"


def test_root_unavailable_is_not_transport_failure(monkeypatch):
    from desktop.usb_debug import probe_root
    def command(*args, **kwargs):
        if "su" in args:
            raise LinkError("su not found")
        return "uid=2000(shell)"
    monkeypatch.setattr("desktop.usb_debug.run_adb", command)
    assert "未确认 Root" in probe_root("adb", "A")[0]
