import os
import json
from dataclasses import asdict
from queue import Empty, Queue
from threading import get_ident
from time import monotonic, sleep

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from desktop.adb import AdbDevice, AdbSnapshot
from desktop.app import MainWindow
from desktop.core import RunConfig


def wait_for(app, predicate, timeout=15):
    end = monotonic() + timeout
    while not predicate():
        assert monotonic() < end
        app.processEvents()
        sleep(0.01)
    app.processEvents()


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def console(tmp_path, monkeypatch, app):
    snapshots = Queue()
    thread_ids = []

    def monitor(publish, stop, _adb):
        thread_ids.append(get_ident())
        while not stop.is_set():
            try:
                publish(snapshots.get(timeout=0.05))
            except Empty:
                continue

    monkeypatch.setattr("desktop.app.monitor_devices", monitor)
    window = MainWindow(tmp_path)
    window.show()
    try:
        snapshots.put(AdbSnapshot())
        wait_for(app, lambda: "未发现" in window.usb_status.text())
        assert thread_ids and thread_ids[0] != get_ident()
        yield window, snapshots.put
    finally:
        if window.worker is not None:
            window.stop_run()
            wait_for(app, lambda: window.worker is None)
        window.close()
        wait_for(app, lambda: not window.adb_monitor.isRunning() and not window.isVisible())


def test_window_start_stop_resume_history(app, console):
    window, _ = console
    try:
        window.faults.setText("hold_attempt")
        window.start.click()
        wait_for(app, lambda: "ATTEMPT_RUNNING" in window.state.text())
        assert "CMW500 LTE" in window.devices.text()
        window.stop.click()
        wait_for(app, lambda: window.worker is None)
        assert "STOPPED" in window.state.text()
        assert window.history.count() == 1
        window.history.setCurrentRow(0)
        assert window.attempts.rowCount() == 1
        window.faults.clear()
        window.resume.click()
        wait_for(app, lambda: window.worker is None)
        assert "FINISHED" in window.state.text()
        assert "TTFF" in window.live.text()
        assert window.attempts.rowCount() == 61
        assert window.report.is_file()
    finally:
        window.faults.clear()


def test_usb_discovery_selection_and_hotplug(app, console):
    window, publish = console
    window.mode.setCurrentIndex(1)
    assert not window.start.isEnabled()
    assert window.serial.placeholderText() == "未发现 USB 设备"

    denied = AdbDevice("U", 1, "UNAUTHORIZED")
    offline = AdbDevice("O", 2, "OFFLINE")
    publish(AdbSnapshot((denied, offline)))
    wait_for(app, lambda: "unauthorized" in window.usb_status.text())
    assert "offline" in window.usb_status.text()
    assert window.serial.count() == 0 and not window.start.isEnabled()

    a = AdbDevice("A", 3, model="Model A")
    b = AdbDevice("B", 4)
    publish(AdbSnapshot((a, b)))
    wait_for(app, lambda: window.serial.count() == 2)
    assert window.serial.currentIndex() == -1 and not window.start.isEnabled()
    window.serial.setCurrentIndex(1)
    assert window.serial.currentData() == b and window.start.isEnabled()
    publish(AdbSnapshot((b, a)))
    wait_for(app, lambda: window.serial.itemData(0) == b)
    assert window.serial.currentData() == b

    publish(AdbSnapshot((a,)))
    wait_for(app, lambda: window.serial.count() == 1)
    assert window.serial.currentData() == a and window.start.isEnabled()
    assert window.serial.currentText() == "A · Model A"

    publish(AdbSnapshot(error="ADB USB 扫描失败：命令超时"))
    wait_for(app, lambda: "超时" in window.usb_status.text())
    assert not window.start.isEnabled()


def test_real_run_pins_selected_serial_and_reconnection_requires_resume(app, console):
    window, publish = console
    window.mode.setCurrentIndex(1)
    config = RunConfig(-120, 1, scenario_id="demo", scenario_hash="fixture",
                       calibration_ref="fixture", scenario_signals="GPS L1", mock=False)
    window.configuration.setPlainText(json.dumps(asdict(config)))
    target = AdbDevice("target", 1)
    other = AdbDevice("other", 2)
    third = AdbDevice("third", 3)
    publish(AdbSnapshot((target,)))
    wait_for(app, window.start.isEnabled)
    window.start.click()
    wait_for(app, lambda: window.confirmation_dialog is not None)
    worker = window.worker
    assert worker.usb.device == target and not window.serial.isEnabled()

    publish(AdbSnapshot((target, other, third)))
    wait_for(app, lambda: "3 台" in window.usb_status.text())
    publish(AdbSnapshot((target, other)))
    wait_for(app, lambda: "2 台" in window.usb_status.text())
    assert window.worker is worker and not worker.usb.lost.is_set()
    assert window.serial.currentData() == target

    publish(AdbSnapshot((other,)))
    wait_for(app, lambda: window.worker is None)
    assert "PAUSED" in window.state.text() and "USB 通信异常" in window.state.text()
    assert window.serial.isEnabled()
    window.history.setCurrentRow(0)
    assert not window.resume.isEnabled()

    reconnected = AdbDevice("target", 4)
    publish(AdbSnapshot((other, reconnected)))
    wait_for(app, lambda: window.serial.count() == 2)
    assert window.worker is None and window.serial.currentData() == other
    assert not window.resume.isEnabled()
    window.serial.setCurrentIndex(1)
    assert window.resume.isEnabled() and window.worker is None
    window.resume.click()
    wait_for(app, lambda: window.confirmation_dialog is not None)
    assert window.worker.usb.device == reconnected
    window.stop.click()
    wait_for(app, lambda: window.worker is None)
