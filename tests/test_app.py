import os
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
from desktop.widgets import EvidenceDialog


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


def test_real_only_and_manual_refresh(console):
    window, _ = console
    assert window.mode.count() == 1
    assert not window.mock_mode
    assert not window.start.isEnabled()
    window.search_usb.click()
    assert window.adb_monitor.stop.refresh.is_set()


def test_usb_discovery_selection_and_hotplug(app, console):
    window, publish = console
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
    config = RunConfig(-120, 1, scenario_id="demo", scenario_hash="fixture",
                       calibration_ref="fixture", scenario_signals="GPS L1", mock=False)
    window.configuration.set_values(asdict(config))
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
    assert window.state.property("state") == "PAUSED" and "USB 通信异常" in window.state.text()
    assert window.serial.isEnabled()
    window.history.setCurrentCell(0, 0)
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


def test_real_config_requires_device(console):
    window, _ = console
    assert not window.start.isEnabled()
    assert window.configuration.fields["min_power_dbm"][0].text() == ""


def test_evidence_form_requires_explicit_safety_and_valid_readback(app):
    dialog = EvidenceDialog(None, "核对仪器", {"running": None, "power_dbm": None,
                                              "rf_off": None, "evidence": ""}, safety=True)
    dialog.submit()
    assert dialog.values is None
    assert "场景正在运行" in dialog.problem.text()
    dialog.fields["running"].setCurrentIndex(1)
    dialog.fields["power_dbm"].setText("NaN")
    dialog.submit()
    assert dialog.values is None
    assert "有限" in dialog.problem.text()
    dialog.fields["running"].setCurrentIndex(2)
    dialog.fields["power_dbm"].clear()
    dialog.fields["rf_off"].setCurrentIndex(1)
    dialog.fields["evidence"].setPlainText("现场日志编号 125")
    dialog.submit()
    assert dialog.values == {"running": False, "power_dbm": None, "rf_off": True, "evidence": "现场日志编号 125"}
