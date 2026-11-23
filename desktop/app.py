"""PySide6 operator console. Instrument work runs off the GUI thread."""
from dataclasses import asdict
import json
import os
import sqlite3
from pathlib import Path
from threading import Event, Lock
from uuid import uuid4

from dotenv import load_dotenv
from PySide6.QtCore import QSignalBlocker, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
                               QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .adb import AdbSnapshot, UsbRun, monitor_devices
from .core import DeviceError, LinkError, RunConfig, UserStop
from .engine import TestEngine
from .instruments import Cmw500Manual, SimReplayPlusManual
from .mock import Faults, mock_devices
from .reports import export
from .storage import Store
from .transports import AdbTransport


class AdbMonitor(QThread):
    changed = Signal(object)

    def __init__(self, adb):
        super().__init__()
        self.adb = adb
        self.stop = Event()
        self.lock = Lock()
        self.snapshot = AdbSnapshot()
        self.usb = None

    def publish(self, snapshot):
        with self.lock:
            self.snapshot = snapshot
            if self.usb is not None:
                self.usb.observe(snapshot)
        self.changed.emit(snapshot)

    def claim(self, device):
        with self.lock:
            usb = UsbRun(device)
            usb.observe(self.snapshot)
            usb.check()
            self.usb = usb
            return usb

    def release(self):
        with self.lock:
            self.usb = None
            return self.snapshot

    def run(self):
        monitor_devices(self.publish, self.stop, self.adb)


class RunWorker(QThread):
    update = Signal(str, dict)
    request_confirmation = Signal(object)
    finished_run = Signal(object)
    failed = Signal(str)

    def __init__(self, path, stop, config=None, run=None, usb=None, faults=(), adb="adb"):
        super().__init__()
        self.path, self.stop = path, stop
        self.config, self.run_id, self.usb, self.faults = config, run, usb, faults
        self.adb = adb

    def check_running(self):
        if self.usb is not None:
            self.usb.check()
        if self.stop.is_set():
            raise UserStop("USER_STOP")

    def confirmation(self, prompt, template, safety=False):
        if not safety:
            self.check_running()
        done = Event()
        output = {}
        self.request_confirmation.emit((prompt, template, safety, done, output))
        while not done.wait(0.1):
            if not safety:
                self.check_running()
        if not safety:
            self.check_running()
        value = output.get("value")
        if not isinstance(value, dict) or not isinstance(value.get("evidence"), str) or not value["evidence"].strip():
            raise DeviceError("操作取消或缺少现场证据")
        return value

    def preparation(self, attempt, mode):
        value = self.confirmation(
            f"轮次 {attempt}\n按机型已验证的步骤准备 {mode}。记录操作、退出码及前后状态。",
            {"verified": False, "mode": mode, "evidence": ""}
        )
        if value.get("verified") is not True or value.get("mode") != mode:
            raise DeviceError(f"未验证 {mode} 启动准备")
        return value["evidence"]

    def run(self):
        try:
            with Store(self.path) as store:
                resume = self.run_id is not None
                config = store.config(self.run_id) if resume else self.config
                if not resume:
                    self.run_id = store.create_run(config)
                if config.mock:
                    devices = mock_devices(config, Faults(self.faults))
                else:
                    if self.usb is None:
                        raise LinkError("须选择唯一的 USB 设备")
                    serial = self.usb.device.serial
                    recorded = store.run(self.run_id)["evidence"].get("usb_serial")
                    if recorded and recorded != serial:
                        raise LinkError(f"恢复须选择原 USB 设备 {recorded}")
                    if not resume:
                        store.evidence(self.run_id, usb_serial=serial)
                    devices = (SimReplayPlusManual(self.confirmation),
                               Cmw500Manual(self.confirmation), AdbTransport(self.usb, self.adb))

                def notify(kind, payload):
                    if self.usb is not None and kind == "PHONE":
                        store.evidence(self.run_id, usb_serial=self.usb.device.serial)
                    self.update.emit(kind, payload)

                controller = TestEngine(store, self.run_id, *devices, stop=self.stop,
                                        notify=notify, prepare=self.preparation)
                try:
                    result = controller.execute(resume=resume)
                finally:
                    report = export(store, self.run_id)
                self.finished_run.emit((result, report))
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, root):
        super().__init__()
        self.root = Path(root)
        self.worker = None
        self.adb = os.environ.get("GNSS_ADB", "").strip() or "adb"
        self.adb_monitor = AdbMonitor(self.adb)
        self.adb_monitor.changed.connect(self.update_usb)
        self.adb_monitor.finished.connect(self.close)
        self.stop_signal = Event()
        self.confirmation_dialog = None
        self.report = None
        self.attempt_rows = {}
        self.metrics = {}
        self.entries = []
        self.setWindowTitle("GNSS 灵敏度测试")
        self.resize(1160, 810)
        container = QWidget()
        self.setCentralWidget(container)
        layout = QVBoxLayout(container)
        self.mode = QComboBox()
        self.mode.addItems(["MOCK · 合成设备", "现场 · USB ADB + 人工仪器确认"])
        self.mode.currentIndexChanged.connect(self.change_mode)
        self.configuration = QPlainTextEdit()
        self.configuration.setMaximumHeight(160)
        self.serial = QComboBox()
        self.serial.setPlaceholderText("正在扫描 USB 设备…")
        self.serial.currentIndexChanged.connect(lambda: self.set_busy(self.worker is not None))
        self.usb_status = QLabel("正在扫描 USB 设备…")
        self.usb_status.setWordWrap(True)
        self.faults = QLineEdit()
        self.faults.setPlaceholderText("逗号分隔，例如 disconnect,no_satellite")
        form = QFormLayout()
        form.addRow("模式", self.mode)
        form.addRow("运行配置 (JSON)", self.configuration)
        form.addRow("ADB USB 设备", self.serial)
        form.addRow("", self.usb_status)
        form.addRow("Mock 故障注入", self.faults)
        layout.addLayout(form)
        self.banner = QLabel()
        self.state = QLabel("IDLE")
        self.devices = QLabel("等待设备预检")
        self.live = QLabel("等待遥测")
        for label in (self.banner, self.state, self.devices, self.live):
            label.setWordWrap(True)
            layout.addWidget(label)
        buttons = QHBoxLayout()
        self.start = QPushButton("开始")
        self.stop = QPushButton("停止")
        self.resume = QPushButton("恢复选中运行")
        self.open_report = QPushButton("打开报告")
        for button, action in ((self.start, self.start_run), (self.stop, self.stop_run),
                               (self.resume, self.resume_run), (self.open_report, self.show_report)):
            button.clicked.connect(action)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.attempts = QTableWidget(0, 7)
        self.attempts.setHorizontalHeaderLabels(
            ["功率 (dBm)", "试验 ID", "结果", "TTFF (s)", "误差 (m)", "卫星数", "原因"])
        self.attempts.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.attempts.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.attempts, 3)
        layout.addWidget(QLabel("历史运行"))
        self.history = QListWidget()
        self.history.currentRowChanged.connect(self.select_history)
        layout.addWidget(self.history, 1)
        self.change_mode()
        self.reload_history()
        self.set_busy(False)
        self.adb_monitor.start()

    def change_mode(self, *_):
        mock = self.mode.currentIndex() == 0
        defaults = asdict(RunConfig(-122, 3))
        defaults["mock"] = mock
        if not mock:
            for key in ("scenario_id", "scenario_hash", "calibration_ref", "scenario_signals", "power_definition"):
                defaults[key] = ""
            for key in ("reference_lat", "reference_lon", "min_power_dbm", "max_levels"):
                defaults[key] = None
        self.configuration.setPlainText(json.dumps(defaults, ensure_ascii=False, indent=2))
        self.banner.setText("MOCK · 合成设备与定位" if mock else "现场 · CMW500 LTE 环境 · USB ADB 数据 · 人工仪器证据")
        self.set_busy(self.worker is not None)

    def update_usb(self, snapshot):
        if self.worker is not None:
            usb = self.worker.usb
            if usb is not None and usb.lost.is_set():
                self.usb_status.setText(f"{usb.reason} · 须人工恢复 · {snapshot.description}")
                self.reject_run_dialog()
            elif usb is not None:
                self.usb_status.setText(f"本次锁定 {usb.device.serial} · {snapshot.description}")
            else:
                self.usb_status.setText(snapshot.description)
            return

        selected = self.serial.currentData()
        devices = snapshot.selectable
        with QSignalBlocker(self.serial):
            self.serial.clear()
            self.serial.setPlaceholderText("请选择 USB 设备" if devices else "未发现 USB 设备")
            for device in devices:
                self.serial.addItem(device.label, device)
            index = next((i for i, device in enumerate(devices)
                          if selected and device.serial == selected.serial), -1)
            self.serial.setCurrentIndex(0 if len(devices) == 1 else index)
        self.usb_status.setText(snapshot.description)
        self.set_busy(False)

    def resume_allowed(self, run):
        if run["status"] == "FINISHED":
            return False
        if run["config"]["mock"]:
            return True
        selected = self.serial.currentData()
        recorded = run["evidence"].get("usb_serial")
        return selected is not None and (not recorded or selected.serial == recorded)

    def set_busy(self, busy):
        for widget in (self.mode, self.configuration, self.history):
            widget.setEnabled(not busy)
        mock = self.mode.currentIndex() == 0
        selection = self.selected()
        real_history = selection is not None and not selection[1]["config"]["mock"]
        self.serial.setEnabled(not busy and (not mock or real_history) and self.serial.count() > 0)
        self.start.setEnabled(not busy and (mock or self.serial.currentData() is not None))
        self.faults.setEnabled(not busy and mock)
        self.stop.setEnabled(busy and not self.stop_signal.is_set())
        self.resume.setEnabled(not busy and selection is not None and self.resume_allowed(selection[1]))
        recorded = selection[1]["evidence"].get("usb_serial") if real_history else None
        self.resume.setToolTip(f"选择原 USB 设备 {recorded} 后点击恢复" if recorded else "")
        self.open_report.setEnabled(not busy and self.report is not None)

    def selected(self):
        row = self.history.currentRow()
        return self.entries[row] if 0 <= row < len(self.entries) else None

    def reload_history(self):
        entries = []
        for path in sorted(self.root.glob("*/run.sqlite")):
            try:
                with Store(path) as store:
                    entries.extend((path, run) for run in store.history())
            except (OSError, ValueError, sqlite3.Error) as exc:
                self.state.setText(str(exc))
        self.entries = sorted(entries, key=lambda entry: entry[1]["started_utc"], reverse=True)
        self.history.clear()
        for _, run in self.entries:
            self.history.addItem(f"{'MOCK' if run['config']['mock'] else '现场'} | {run['started_utc']} | "
                                 f"{run['status']} | {run['threshold_dbm']} dBm | {run['id']}")

    def select_history(self, *_):
        if self.worker is not None:
            return
        selection = self.selected()
        if selection is not None:
            path, run = selection
            candidate = path.parent / "report.html"
            self.report = candidate if candidate.is_file() else None
            self.attempts.setRowCount(0)
            self.attempt_rows.clear()
            with Store(path) as store:
                for level in store.levels(run["id"]):
                    for attempt in store.attempts(level["id"]):
                        self.update_attempt({**attempt["metrics"], "attempt_id": attempt["id"],
                                             "power_dbm": level["power_dbm"]})
        self.set_busy(False)

    def start_run(self):
        try:
            data = json.loads(self.configuration.toPlainText())
            data["mock"] = self.mode.currentIndex() == 0
            config = RunConfig(**data)
            path = self.root / str(uuid4()) / "run.sqlite"
            self.begin(path, config=config)
        except (TypeError, ValueError, LinkError) as exc:
            self.state.setText(str(exc))

    def resume_run(self):
        selection = self.selected()
        if selection is not None and self.resume_allowed(selection[1]):
            path, run = selection
            try:
                self.begin(path, run=run["id"], mock=run["config"]["mock"])
            except LinkError as exc:
                self.state.setText(str(exc))

    def begin(self, path, config=None, run=None, mock=None):
        if self.worker is not None:
            return
        actual_mock = config.mock if config else mock
        usb = None
        if not actual_mock:
            device = self.serial.currentData()
            if device is None:
                raise LinkError("请选择一台已授权、在线的 USB 设备")
            usb = self.adb_monitor.claim(device)
            self.usb_status.setText(f"本次锁定 {device.serial}")
        self.banner.setText("MOCK · 合成设备与定位" if actual_mock else "现场 · USB ADB + CMW500 LTE")
        if run is None:
            self.attempts.setRowCount(0)
            self.attempt_rows.clear()
        self.metrics.clear()
        for label in ("手机", "CMW500 LTE", "GSS7000"):
            self.devices.setProperty(label, None)
        self.live.setText("等待遥测")
        self.devices.setText("等待设备预检")
        self.stop_signal.clear()
        self.worker = RunWorker(path, self.stop_signal, config, run, usb,
                                [part.strip() for part in self.faults.text().split(",")
                                 if actual_mock and part.strip()], adb=self.adb)
        self.worker.update.connect(self.update_run)
        self.worker.request_confirmation.connect(self.ask_confirmation)
        self.worker.finished_run.connect(self.complete)
        self.worker.failed.connect(self.state.setText)
        self.worker.finished.connect(self.worker_done)
        self.set_busy(True)
        self.worker.start()

    def ask_confirmation(self, request):
        prompt, template, safety, done, output = request
        usb = self.worker.usb
        if not safety and (self.stop_signal.is_set() or (usb is not None and usb.lost.is_set())):
            done.set()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("确认 GNSS RF 已停止" if safety else "现场操作确认")
        layout = QVBoxLayout(dialog)
        message = QLabel(prompt)
        message.setWordWrap(True)
        layout.addWidget(message)
        editor = QPlainTextEdit(json.dumps(template, ensure_ascii=False, indent=2))
        layout.addWidget(editor)
        problem = QLabel()
        layout.addWidget(problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)

        def accept():
            try:
                value = json.loads(editor.toPlainText())
                if not isinstance(value, dict) or not str(value.get("evidence") or "").strip():
                    raise ValueError("请填写 JSON 对象及现场证据引用")
            except ValueError as exc:
                problem.setText(str(exc))
                return
            output["value"] = value
            dialog.accept()

        buttons.accepted.connect(accept)
        buttons.rejected.connect(dialog.reject)
        self.confirmation_dialog = (dialog, safety)

        def closed(_):
            if self.confirmation_dialog and self.confirmation_dialog[0] is dialog:
                self.confirmation_dialog = None
            done.set()
            dialog.deleteLater()

        dialog.finished.connect(closed)
        dialog.resize(620, 400)
        dialog.show()

    def stop_run(self):
        self.stop_signal.set()
        self.stop.setEnabled(False)
        self.state.setText("STOPPING · 正在取消采集并确认 RF 安全")
        self.reject_run_dialog()

    def reject_run_dialog(self):
        if self.confirmation_dialog:
            dialog, safety = self.confirmation_dialog
            if not safety:
                dialog.reject()

    def update_run(self, kind, item):
        if kind == "STATE":
            self.state.setText(f"{item['state']} · {item.get('reason') or ''}")
        elif kind == "ATTEMPT":
            self.update_attempt(item)
        elif kind in {"PHONE", "LTE", "POWER"}:
            key = {"PHONE": "手机", "LTE": "CMW500 LTE", "POWER": "GSS7000"}[kind]
            value = {"PHONE": item.get("model"), "LTE": item.get("cell"),
                     "POWER": f"{item.get('power_dbm')} / {item.get('readback_dbm')} dBm"}[kind]
            self.devices.setProperty(key, str(value))
            self.devices.setText("   |   ".join(f"{label} {self.devices.property(label) or '—'}"
                                                for label in ("手机", "CMW500 LTE", "GSS7000")))
        elif kind in {"LOCATION_UPDATE", "FIRST_FIX", "SATELLITE_STATUS", "ATTEMPT_RESULT"}:
            if self.metrics.get("attempt_id") != item["attempt_id"]:
                self.metrics = {"attempt_id": item["attempt_id"]}
            self.metrics.update(item["payload"])
            self.live.setText("   |   ".join(f"{label} {self.metrics.get(key, '—')}" for label, key in (
                ("经度", "longitude"), ("纬度", "latitude"), ("TTFF", "ttff_s"),
                ("误差 (m)", "horizontal_error_m"), ("参与解算卫星", "used_in_fix"))))

    def update_attempt(self, item):
        key = item["attempt_id"]
        if key not in self.attempt_rows:
            self.attempt_rows[key] = self.attempts.rowCount()
            self.attempts.insertRow(self.attempts.rowCount())
        row = self.attempt_rows[key]
        for index, field in enumerate(("power_dbm", "attempt_id", "status", "ttff_s",
                                        "horizontal_error_m", "used_in_fix", "reason")):
            value = item.get(field)
            display = f"{value:.3f}" if isinstance(value, float) else str(value if value is not None else "—")
            self.attempts.setItem(row, index, QTableWidgetItem(display))
        self.attempts.scrollToBottom()

    def complete(self, payload):
        result, self.report = payload
        self.state.setText(f"{result['status']} · {result['reason']} · 最后通过档 {result['threshold_dbm']}")

    def worker_done(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        snapshot = self.adb_monitor.release()
        self.reload_history()
        self.update_usb(snapshot)

    def show_report(self):
        if self.report is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.report.resolve())))

    def closeEvent(self, event):
        if self.worker is not None:
            self.stop_run()
            event.ignore()
        elif self.adb_monitor.isRunning():
            self.adb_monitor.stop.set()
            event.ignore()
        else:
            event.accept()


def launch():
    load_dotenv()
    app = QApplication([])
    window = MainWindow(os.environ.get("GNSS_RESULTS_DIR", "results"))
    window.show()
    return app.exec()
