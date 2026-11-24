"""PySide6 operator console. Instrument work runs off the GUI thread."""
from collections import Counter
from dataclasses import asdict
import os
import sqlite3
from pathlib import Path
from threading import Event, Lock
from uuid import uuid4

from dotenv import load_dotenv
from PySide6.QtCore import QSignalBlocker, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFrame, QHBoxLayout, QLineEdit,
                               QMainWindow, QProgressBar, QPushButton, QTabWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .usb_debug import UsbDebugPage
from .adb import AdbSnapshot, UsbRun, monitor_devices
from .core import SAMPLES, DeviceError, LinkError, RunConfig, UserStop
from .engine import TestEngine
from .instruments import Cmw500Manual, SimReplayPlusManual
from .mock import Faults, mock_devices
from .presentation import quantity, reason_text, state_text
from .reports import export
from .storage import Store
from .transports import AdbTransport
from .widgets import STYLE, ConfigurationForm, EvidenceDialog, card, fill_attempt, label, scroll, table


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


ATTEMPT_COLUMNS = ("功率 (dBm)", "试验 ID", "判定", "TTFF (s)", "误差 (m)", "解算卫星", "原因")


class MainWindow(QMainWindow):
    def __init__(self, root):
        super().__init__()
        self.root = Path(root)
        self.worker = None
        self.closing = False
        self.adb = os.environ.get("GNSS_ADB", "").strip() or "adb"
        self.adb_monitor = AdbMonitor(self.adb)
        self.adb_monitor.changed.connect(self.update_usb)
        self.adb_monitor.finished.connect(self.close)
        self.stop_signal = Event()
        self.confirmation_dialog = None
        self.report = None
        self.attempt_rows = {}
        self.level_results = {}
        self.metrics = {}
        self.current_power = None
        self.entries = []
        self.active_run = None
        self.drafts = {}
        self.resume_draft = None
        self.mock_mode = None
        self.setWindowTitle("GNSS 灵敏度测试 · 操作台")
        self.setMinimumSize(880, 610)
        self.resize(1240, 820)
        self.setStyleSheet(STYLE)

        container = QWidget()
        container.setObjectName("workspace")
        self.setCentralWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("topbar")
        bar = QHBoxLayout(header)
        bar.setContentsMargins(24, 16, 24, 16)
        title = QVBoxLayout()
        title.setSpacing(3)
        title.addWidget(label("GNSS 灵敏度测试", "title"))
        self.state = label("待开始", "muted", wrap=True)
        title.addWidget(self.state)
        bar.addLayout(title, 1)
        self.banner = label("")
        self.banner.setObjectName("modeBadge")
        bar.addWidget(self.banner)
        layout.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(20, 14, 20, 16)
        body.setSpacing(10)
        layout.addLayout(body, 1)
        toolbar = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["MOCK · 合成设备", "现场 · USB ADB"])
        self.mode.setAccessibleName("测试模式")
        toolbar.addWidget(self.mode)
        self.serial = QComboBox()
        self.serial.setPlaceholderText("正在扫描 USB 设备…")
        self.serial.setAccessibleName("ADB USB 设备")
        self.serial.setMinimumWidth(205)
        toolbar.addWidget(self.serial, 1)
        self.start = self.button("开始测试", self.start_run, "primary")
        self.stop = self.button("安全停止", self.stop_run, "stop")
        toolbar.addWidget(self.start)
        toolbar.addWidget(self.stop)
        body.addLayout(toolbar)
        self.usb_status = label("正在扫描 USB 设备…", "muted", wrap=True)
        body.addWidget(self.usb_status)
        self.tabs = QTabWidget()
        body.addWidget(self.tabs, 1)
        self.build_dashboard()
        self.build_settings()
        self.build_history()
        self.debug_page = UsbDebugPage(self)
        self.tabs.addTab(self.debug_page, "设备调试")

        self.mode.currentIndexChanged.connect(self.change_mode)
        self.serial.currentIndexChanged.connect(lambda: self.set_busy(self.worker is not None))
        self.change_mode()
        self.reload_history()
        self.set_busy(False)
        self.tabs.currentChanged.connect(lambda: self.set_busy(self.worker is not None))
        self.adb_monitor.start()

    @staticmethod
    def button(name, action, role=None):
        button = QPushButton(name)
        if role:
            button.setProperty("role", role)
        button.clicked.connect(action)
        return button

    def build_dashboard(self):
        page = QWidget()
        panel = QVBoxLayout(page)
        panel.setContentsMargins(0, 10, 0, 0)
        panel.setSpacing(10)
        metrics = QHBoxLayout()
        self.metric_labels = {}
        for key, title in (("power", "当前功率"), ("ttff_s", "首次定位 TTFF"),
                           ("horizontal_error_m", "水平误差"), ("used_in_fix", "参与解算卫星")):
            tile, tile_layout = card(title)
            value = label("—", "value")
            value.setAccessibleName(title)
            tile_layout.addWidget(value)
            metrics.addWidget(tile, 1)
            self.metric_labels[key] = value
        panel.addLayout(metrics)
        progress, progress_layout = card()
        progress_row = QHBoxLayout()
        self.level_progress = label(f"当前档有效样本 0 / {SAMPLES}", "heading")
        self.level_counts = label("通过 0  ·  失败 0  ·  INVALID 0", "muted")
        progress_row.addWidget(self.level_progress, 1)
        progress_row.addWidget(self.level_counts)
        progress_layout.addLayout(progress_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, SAMPLES)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(8)
        self.progress.setAccessibleName("当前档有效样本")
        progress_layout.addWidget(self.progress)
        self.devices = label("等待设备预检", "muted", wrap=True)
        self.live = label("等待遥测 · TTFF、经纬度与卫星关联", "muted", wrap=True)
        progress_layout.addWidget(self.devices)
        progress_layout.addWidget(self.live)
        panel.addWidget(progress)

        attempts, attempt_layout = card("试验明细")
        self.attempts = table(ATTEMPT_COLUMNS, stretch_last=True)
        attempt_layout.addWidget(self.attempts, 1)
        panel.addWidget(attempts, 1)
        self.tabs.addTab(page, "运行监控")

    def build_settings(self):
        page = QWidget()
        panel = QVBoxLayout(page)
        panel.setContentsMargins(0, 10, 0, 0)
        panel.setSpacing(12)
        self.configuration = ConfigurationForm()
        panel.addWidget(self.configuration)
        self.fault_group, fault_layout = card("模拟调试")
        self.faults = QLineEdit()
        self.faults.setAccessibleName("Mock 故障注入")
        self.faults.setPlaceholderText("可选，逗号分隔，例如 disconnect,no_satellite")
        fault_layout.addWidget(self.faults)
        panel.addWidget(self.fault_group)
        self.config_issue = label("", "issue", wrap=True)
        panel.addWidget(self.config_issue)
        panel.addStretch()
        self.settings_page = scroll(page)
        self.tabs.addTab(self.settings_page, "测试配置")

    def build_history(self):
        page = QWidget()
        panel = QVBoxLayout(page)
        panel.setContentsMargins(0, 10, 0, 0)
        panel.setSpacing(10)
        records, records_layout = card("历史运行")
        self.history = table(("开始时间 (UTC)", "模式", "状态", "最后通过档", "运行 ID"))
        self.history.currentCellChanged.connect(self.select_history)
        records_layout.addWidget(self.history, 1)
        self.history_summary = label("暂无运行记录", "muted", wrap=True)
        records_layout.addWidget(self.history_summary)
        buttons = QHBoxLayout()
        self.resume = self.button("恢复选中运行", self.resume_run, "primary")
        self.open_report = self.button("打开 HTML 报告", self.show_report)
        self.open_folder = self.button("打开数据目录", self.show_folder)
        for button in (self.resume, self.open_report, self.open_folder):
            buttons.addWidget(button)
        buttons.addStretch()
        records_layout.addLayout(buttons)
        panel.addWidget(records, 1)
        detail, detail_layout = card("选中运行的试验明细")
        self.history_attempts = table(ATTEMPT_COLUMNS, stretch_last=True)
        detail_layout.addWidget(self.history_attempts, 1)
        panel.addWidget(detail, 1)
        self.history_page = page
        self.tabs.addTab(page, "历史与报告")

    def show_state(self, state, reason=None):
        self.state.setProperty("state", state)
        self.state.setText(f"{state_text(state)} · {reason_text(reason)}" if reason else state_text(state))
        self.state.setToolTip(f"{state}: {reason}" if reason else state)

    def show_mode(self, mock):
        self.banner.setText("MOCK · 合成数据" if mock else "现场 · USB ADB")
        self.banner.setProperty("simulated", mock)
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)

    def change_mode(self, *_):
        mock = self.mode.currentIndex() == 0
        if self.mock_mode is not None:
            self.drafts[self.mock_mode] = self.configuration.draft()
        defaults = asdict(RunConfig(-122, 3))
        if not mock:
            for key in ("scenario_id", "scenario_hash", "calibration_ref", "scenario_signals", "power_definition",
                        "reference_lat", "reference_lon", "min_power_dbm", "max_levels"):
                defaults[key] = None
        self.configuration.set_values(self.drafts.get(mock, defaults))
        self.mock_mode = mock
        self.fault_group.setVisible(mock)
        self.config_issue.clear()
        self.show_mode(mock)
        self.set_busy(self.worker is not None)

    def update_usb(self, snapshot):
        if hasattr(self, 'debug_page') and self.debug_page.worker is not None:
            self.usb_status.setText(snapshot.description)
            return
        if self.worker is not None:
            self.usb_status.show()
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
        self.usb_status.setVisible(bool(devices) or snapshot.description != "未发现 USB 设备")
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
        for widget in (self.mode, self.configuration, self.history, self.faults):
            widget.setEnabled(not busy)
        selection = self.selected()
        real_history = selection is not None and not selection[1]["config"]["mock"]
        debugging = hasattr(self, 'debug_page') and self.debug_page.worker is not None
        self.serial.setEnabled(not busy and not debugging and (not self.mock_mode or real_history or (hasattr(self, 'debug_page') and self.tabs.currentWidget() is self.debug_page)) and self.serial.count() > 0)
        if hasattr(self, 'debug_page'):
            self.debug_page.refresh(busy)
        busy = busy or debugging
        self.start.setEnabled(not busy and (self.mock_mode or self.serial.currentData() is not None))
        self.stop.setEnabled(busy and not self.stop_signal.is_set())
        self.resume.setEnabled(not busy and selection is not None and self.resume_allowed(selection[1]))
        recorded = selection[1]["evidence"].get("usb_serial") if real_history else None
        self.resume.setToolTip(f"选择原 USB 设备 {recorded} 后点击恢复" if recorded else "")
        self.open_report.setEnabled(not busy and self.report is not None)
        self.open_folder.setEnabled(not busy and selection is not None)

    def selected(self):
        row = self.history.currentRow()
        return self.entries[row] if 0 <= row < len(self.entries) else None

    def reload_history(self, preferred=None):
        prior = self.selected()
        preferred = preferred or (prior[1]["id"] if prior else None)
        entries = []
        for path in self.root.glob("*/run.sqlite"):
            try:
                with Store(path) as store:
                    entries.extend((path, run) for run in store.history())
            except (OSError, ValueError, sqlite3.Error) as exc:
                self.show_state("ERROR", str(exc))
        self.entries = sorted(entries, key=lambda entry: entry[1]["started_utc"], reverse=True)
        with QSignalBlocker(self.history):
            self.history.setRowCount(0)
            self.history.setRowCount(len(self.entries))
            for row, (_, run) in enumerate(self.entries):
                values = (run["started_utc"][:19].replace("T", " "), "MOCK" if run["config"]["mock"] else "现场",
                          state_text(run["status"]), quantity(run["threshold_dbm"], "dBm"), run["id"][:8])
                for column, text in enumerate(values):
                    item = QTableWidgetItem(text)
                    item.setToolTip(run["id"] if column == 4 else text)
                    self.history.setItem(row, column, item)
            match = next((row for row, (_, run) in enumerate(self.entries) if run["id"] == preferred), 0)
            if self.entries:
                self.history.selectRow(match)
        self.select_history()

    def read_attempts(self, path, run_id):
        with Store(path) as store:
            return [{**attempt["metrics"], "attempt_id": attempt["id"], "status": attempt["status"],
                     "reason": attempt["reason"], "power_dbm": level["power_dbm"]}
                    for level in store.levels(run_id) for attempt in store.attempts(level["id"])]

    def select_history(self, *_):
        if self.worker is not None:
            return
        selection = self.selected()
        self.report = None
        self.history_attempts.setRowCount(0)
        self.history_summary.setText("暂无运行记录" if not self.entries else "选择一条运行查看试验和报告")
        if selection is not None:
            path, run = selection
            candidate = path.parent / "report.html"
            self.report = candidate if candidate.is_file() else None
            try:
                attempts = self.read_attempts(path, run["id"])
            except (OSError, ValueError, sqlite3.Error) as exc:
                self.history_summary.setText(f"无法读取试验明细 · {exc}")
            else:
                self.history_attempts.setRowCount(len(attempts))
                for row, attempt in enumerate(attempts):
                    fill_attempt(self.history_attempts, row, attempt)
                self.history_summary.setText(
                    f"{state_text(run['status'])} · {reason_text(run['reason'])} · {len(attempts)} 条试验记录"
                )
        self.set_busy(False)

    def start_run(self):
        try:
            config = RunConfig(**self.configuration.config_values(), mock=self.mock_mode)
            self.begin(self.root / str(uuid4()) / "run.sqlite", config=config)
        except (TypeError, ValueError) as exc:
            self.config_issue.setText(str(exc))
            self.show_state("ERROR", str(exc))
            self.tabs.setCurrentWidget(self.settings_page)
        except LinkError as exc:
            self.show_state("ERROR", str(exc))

    def resume_run(self):
        selection = self.selected()
        if selection is not None and self.resume_allowed(selection[1]):
            path, run = selection
            try:
                self.begin(path, config=RunConfig(**run["config"]), run=run["id"])
            except (LinkError, OSError, ValueError, sqlite3.Error) as exc:
                self.show_state("ERROR", str(exc))

    def begin(self, path, config, run=None):
        if self.worker is not None or self.debug_page.worker is not None:
            return
        actual_mock = config.mock
        previous = self.read_attempts(path, run) if run else []
        usb = None
        if not actual_mock:
            device = self.serial.currentData()
            if device is None:
                raise LinkError("请选择一台已授权、在线的 USB 设备")
            usb = self.adb_monitor.claim(device)
            self.usb_status.setText(f"本次锁定 {device.serial}")
            self.usb_status.show()
        self.show_mode(actual_mock)
        self.show_state("PRECHECK")
        if run is not None:
            self.resume_draft = self.configuration.draft()
            self.configuration.set_values(asdict(config))
        self.config_issue.clear()
        self.active_run = run
        self.attempts.setRowCount(0)
        self.attempt_rows.clear()
        self.level_results.clear()
        self.metrics.clear()
        self.current_power = None
        self.update_progress()
        for item in previous:
            self.update_attempt(item)
        for value in self.metric_labels.values():
            value.setText("—")
        for key in ("手机", "CMW500 LTE", "GSS7000"):
            self.devices.setProperty(key, None)
        self.live.setText("等待遥测 · TTFF、经纬度与卫星关联")
        self.devices.setText("等待设备预检")
        self.stop_signal.clear()
        self.tabs.setCurrentIndex(0)
        self.worker = RunWorker(path, self.stop_signal, config, run, usb,
                                [part.strip() for part in self.faults.text().split(",")
                                 if actual_mock and part.strip()], adb=self.adb)
        self.worker.update.connect(self.update_run)
        self.worker.request_confirmation.connect(self.ask_confirmation)
        self.worker.finished_run.connect(self.complete)
        self.worker.failed.connect(lambda message: self.show_state("ERROR", message))
        self.worker.finished.connect(self.worker_done)
        self.set_busy(True)
        self.worker.start()

    def ask_confirmation(self, request):
        prompt, template, safety, done, output = request
        usb = self.worker.usb
        if not safety and (self.stop_signal.is_set() or (usb is not None and usb.lost.is_set())):
            done.set()
            return
        dialog = EvidenceDialog(self, prompt, template, safety)
        self.confirmation_dialog = (dialog, safety)

        def closed(result):
            if result == QDialog.DialogCode.Accepted:
                output["value"] = dialog.values
            if self.confirmation_dialog and self.confirmation_dialog[0] is dialog:
                self.confirmation_dialog = None
            done.set()
            dialog.deleteLater()

        dialog.finished.connect(closed)
        dialog.show()

    def stop_run(self):
        self.stop_signal.set()
        self.stop.setEnabled(False)
        self.show_state("STOPPING", "正在取消采集并确认 RF 安全")
        self.reject_run_dialog()

    def reject_run_dialog(self):
        if self.confirmation_dialog:
            dialog, safety = self.confirmation_dialog
            if not safety:
                dialog.reject()

    def update_progress(self):
        results = Counter(self.level_results.get(self.current_power, {}).values())
        valid = results["PASS"] + results["FAIL"]
        self.progress.setValue(valid)
        self.level_progress.setText(f"当前档有效样本 {valid} / {SAMPLES}")
        self.level_counts.setText(f"通过 {results['PASS']}  ·  失败 {results['FAIL']}  ·  INVALID {results['INVALID']}")

    def update_run(self, kind, item):
        if kind == "STATE":
            self.show_state(item["state"], item.get("reason"))
        elif kind == "ATTEMPT":
            self.update_attempt(item)
            if self.metrics.get("attempt_id") == item["attempt_id"]:
                self.metrics.update(item)
                self.paint_metrics()
        elif kind in {"PHONE", "LTE", "POWER"}:
            key = {"PHONE": "手机", "LTE": "CMW500 LTE", "POWER": "GSS7000"}[kind]
            if kind == "POWER":
                self.current_power = item["power_dbm"]
                self.metric_labels["power"].setText(quantity(self.current_power, "dBm"))
                self.update_progress()
                value = f"读回 {quantity(item['readback_dbm'], 'dBm')}"
            else:
                value = item.get("model" if kind == "PHONE" else "cell") or "—"
            self.devices.setProperty(key, str(value))
            self.devices.setText("   |   ".join(f"{name} {self.devices.property(name) or '—'}"
                                                for name in ("手机", "CMW500 LTE", "GSS7000")))
        elif kind in {"LOCATION_UPDATE", "FIRST_FIX", "SATELLITE_STATUS", "ATTEMPT_RESULT"}:
            if self.metrics.get("attempt_id") != item["attempt_id"]:
                self.metrics = {"attempt_id": item["attempt_id"]}
            payload = item["payload"]
            if kind == "LOCATION_UPDATE":
                if not payload.get("mock_location") and not self.metrics.get("first_fix_elapsed_realtime_ns"):
                    for key in ("latitude", "longitude"):
                        if key in payload:
                            self.metrics[key] = payload[key]
            elif kind == "SATELLITE_STATUS":
                if not self.metrics.get("satellite_association") and "used_in_fix" in payload:
                    self.metrics["used_in_fix"] = payload["used_in_fix"]
            else:
                if kind == "ATTEMPT_RESULT" and "used_in_fix" not in payload:
                    self.metrics.pop("used_in_fix", None)
                self.metrics.update(payload)
            self.paint_metrics()

    def paint_metrics(self):
        for key, unit, decimals in (("ttff_s", "s", 3), ("horizontal_error_m", "m", 2),
                                    ("used_in_fix", "", None)):
            self.metric_labels[key].setText(quantity(self.metrics.get(key), unit, decimals))
        attempt = str(self.metrics.get("attempt_id") or "—")
        latitude = quantity(self.metrics.get("latitude"), "°", 6)
        longitude = quantity(self.metrics.get("longitude"), "°", 6)
        self.live.setText(f"试验 {attempt[:8]}   |   纬度 {latitude}   |   经度 {longitude}")
        self.live.setToolTip(attempt)

    def update_attempt(self, item):
        key = item["attempt_id"]
        if key not in self.attempt_rows:
            self.attempt_rows[key] = self.attempts.rowCount()
            self.attempts.insertRow(self.attempts.rowCount())
        fill_attempt(self.attempts, self.attempt_rows[key], item)
        self.level_results.setdefault(item["power_dbm"], {})[key] = item["status"]
        self.update_progress()
        self.attempts.scrollToBottom()

    def complete(self, payload):
        result, self.report = payload
        self.active_run = result["id"]
        self.show_state(result["status"], f"{reason_text(result['reason'])} · 最后通过档 {quantity(result['threshold_dbm'], 'dBm')}")

    def worker_done(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        snapshot = self.adb_monitor.release()
        if self.resume_draft is not None:
            self.configuration.set_values(self.resume_draft)
            self.resume_draft = None
        self.reload_history(self.active_run or worker.run_id)
        self.update_usb(snapshot)
        if self.closing:
            self.close()

    def open_path(self, path):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            self.history_summary.setText(f"无法用系统默认程序打开 · {path}")

    def show_report(self):
        if self.report is not None:
            self.open_path(self.report)

    def show_folder(self):
        selection = self.selected()
        if selection is not None:
            self.open_path(selection[0].parent)

    def closeEvent(self, event):
        self.closing = True
        if self.worker is not None:
            self.stop_run()
            event.ignore()
        elif self.debug_page.worker is not None:
            self.debug_page.worker.stop.set()
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
