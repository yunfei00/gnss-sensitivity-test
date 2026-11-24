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


def test_debug_page_releases_and_reenables_actions(tmp_path):
    from PySide6.QtWidgets import QApplication, QComboBox
    from desktop.usb_debug import UsbDebugPage
    from desktop.adb import AdbDevice, AdbSnapshot
    from types import SimpleNamespace
    app = QApplication.instance() or QApplication([])
    serial = QComboBox()
    device = AdbDevice("A", 1)
    serial.addItem("A", device)
    snapshot = AdbSnapshot((device,))
    window = SimpleNamespace(serial=serial, worker=None, closing=False,
        adb_monitor=SimpleNamespace(release=lambda: snapshot),
        update_usb=lambda snapshot: None, set_busy=lambda busy: None)
    page = UsbDebugPage(window)
    for _ in range(2):
        page.worker = SimpleNamespace(deleteLater=lambda: None)
        page.refresh(False)
        assert not page.actions[-1].isEnabled()
        page.done()
        assert page.worker is None
        assert page.actions[-1].isEnabled()
        assert not page.stop_button.isEnabled()
