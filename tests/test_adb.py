import socket
import subprocess
from threading import Event, Thread

import pytest

from desktop import adb
from desktop.adb import AdbDevice, AdbSnapshot, UsbRun
from desktop.core import LinkError


def test_windows_devices_without_usb_path_use_explicit_connection_type():
    snapshot = adb.parse_snapshot(b"""
device {
  serial: "offline-serial"
  state: OFFLINE
  connection_type: USB
  transport_id: 1
}
device {
  serial: "unauthorized-serial"
  state: UNAUTHORIZED
  connection_type: USB
  transport_id: 2
}
device {
  serial: "wireless"
  state: DEVICE
  model: "Phone"
  connection_type: SOCKET
  transport_id: 3
}
device {
  serial: "wired"
  state: DEVICE
  model: "Example_Phone"
  connection_type: USB
  transport_id: 4
}
""")
    assert [device.label for device in snapshot.selectable] == ["wired · Example Phone"]
    assert "unauthorized" in snapshot.description and "offline" in snapshot.description
    assert adb.parse_snapshot(b"").description == "未发现 USB 设备"


def test_duplicate_serial_is_ambiguous_even_when_one_channel_is_usb():
    snapshot = AdbSnapshot((AdbDevice("same", 1), AdbDevice("same", 2, usb=False)))
    assert snapshot.selectable == ()
    assert "序列号" in snapshot.description


@pytest.mark.parametrize("failure,message", [
    (subprocess.TimeoutExpired("adb", 5), "命令超时"),
    (FileNotFoundError("not on PATH"), "执行失败"),
    (subprocess.CalledProcessError(1, "adb", stderr="server error"), "server error"),
])
def test_adb_failure_has_actionable_status(monkeypatch, failure, message):
    def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(adb.subprocess, "run", fail)
    stop = Event()
    snapshots = []

    def collect(snapshot):
        snapshots.append(snapshot)
        stop.set()

    adb.monitor_devices(collect, stop)
    assert len(snapshots) == 1
    assert message in snapshots[0].description
    assert snapshots[0].selectable == ()


def test_adb_start_uses_local_listen_socket(monkeypatch):
    def start(args, **_kwargs):
        assert args == ["adb", "-L", "tcp:localhost:5037", "start-server"]
        return subprocess.CompletedProcess(args, 0, stdout="")

    monkeypatch.setattr(adb.subprocess, "run", start)
    adb.run_adb("adb", "start-server")


def test_lock_survives_unrelated_hotplug_and_latches_target_reconnect():
    target = AdbDevice("target", 1)
    other = AdbDevice("other", 2)
    lock = UsbRun(target)
    for devices in ((target,), (target, other), (target,)):
        lock.observe(AdbSnapshot(devices))
        lock.check()
    lock.observe(AdbSnapshot((AdbDevice("target", 3), other)))
    with pytest.raises(LinkError, match="USB 通信异常.*target"):
        lock.check()
    lock.observe(AdbSnapshot((target, other)))
    with pytest.raises(LinkError):
        lock.check()


def test_tracker_switches_snapshots_on_push_and_periodic_scan(monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(5)
        monkeypatch.setattr(adb, "ADB_SERVER", listener.getsockname())
        monkeypatch.setattr(adb, "SCAN_INTERVAL_S", 0.25)
        monkeypatch.setattr(adb, "run_adb", lambda *_: "")
        finished = Event()
        snapshots = []
        request = b"host:track-devices-proto-text"
        phone = b'device {\n serial: "A"\n state: DEVICE\n connection_type: USB\n transport_id: 1\n}\n'

        def frame(payload):
            return f"{len(payload):04x}".encode() + payload

        def serve():
            for packets in ((b"", phone), (phone,)):
                with listener.accept()[0] as conn, conn.makefile("rb") as reader:
                    conn.settimeout(3)
                    assert reader.read(4) == f"{len(request):04x}".encode()
                    assert reader.read(len(request)) == request
                    conn.sendall(b"OKAY" + b"".join(frame(packet) for packet in packets))
                    reader.read(1)

        def publish(snapshot):
            snapshots.append(snapshot)
            if len(snapshots) == 3:
                finished.set()

        server = Thread(target=serve)
        server.start()
        try:
            adb.monitor_devices(publish, finished)
        finally:
            server.join(6)
        assert not server.is_alive()
        assert [len(snapshot.selectable) for snapshot in snapshots] == [0, 1, 1]


def test_cli_fallback_windows_single_usb(monkeypatch):
    def command(_adb, *args):
        if args == ("devices", "-l"):
            return "List of devices attached\nABC device model:Phone transport_id:7\n127.0.0.1:5555 device transport_id:8"
        assert args == ("-d", "get-serialno")
        return "ABC"
    monkeypatch.setattr(adb, "run_adb", command)
    snapshot = adb.scan_cli("adb")
    assert [d.serial for d in snapshot.selectable] == ["ABC"]
