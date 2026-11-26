"""Independent real-phone USB diagnostics; never creates sensitivity results."""
import json
import re
from threading import Event
from time import monotonic
from uuid import uuid4

from PySide6.QtCore import QThread, Signal, QSettings
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit, QLabel, QGridLayout, QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit

from .adb import run_adb
from .core import LinkError
from .protocol import envelope, validate
from .transports import AdbTransport


def exchange(transport, run, kind, seq, attempt=None, payload=None):
    request = envelope(kind, run, attempt, payload, seq)
    transport.send_command(request)
    response = validate(transport.receive_event())
    data = response["payload"]
    if (response["run_id"] != run or response["attempt_id"] != attempt
            or response["seq"] != 0 or data.get("response_to") != request["message_id"]):
        raise LinkError("响应与请求不匹配")
    if response["type"] != "DEVICE_STATUS":
        raise LinkError(str(data.get("reason", "响应类型错误")))
    return data


def probe_root(adb, serial):
    identity = run_adb(adb, "shell", "id", serial=serial)
    if re.search(r"\buid=0\b", identity):
        return "ADB Shell 已获得 Root", identity
    try:
        elevated = run_adb(adb, "shell", "su", "-c", "id", serial=serial)
    except LinkError as exc:
        return "未确认 Root（基础定位仍可用）", f"{identity}\n{exc}"
    return ("su 已获得 Root" if re.search(r"\buid=0\b", elevated)
            else "未确认 Root"), f"{identity}\n{elevated}"


class DebugWorker(QThread):
    log = Signal(str)
    status = Signal(dict)
    telemetry = Signal(dict)
    phase = Signal(str)

    def __init__(self, usb, adb, action, root, reference=None):
        super().__init__()
        self.usb, self.adb, self.action, self.root = usb, adb, action, root
        self.stop = Event()
        self.reference = reference

    def run(self):
        transport = AdbTransport(self.usb, self.adb)
        run, attempt = str(uuid4()), str(uuid4())
        seq = 0
        owned = False

        def command(kind, attempt=None, payload=None):
            nonlocal seq
            seq += 1
            self.usb.check()
            return exchange(transport, run, kind, seq, attempt, payload)

        try:
            self.usb.check()
            if self.action == "launch":
                self.log.emit(run_adb(self.adb, "shell", "am", "start", "-n",
                    "org.gnss.sensitivity/.MainActivity", serial=self.usb.device.serial))
                return
            if self.action == "root":
                result, evidence = probe_root(self.adb, self.usb.device.serial)
                self.status.emit({"shell_root": result})
                self.log.emit(evidence)
                return
            self.phase.emit("正在连接采集服务")
            transport.connect()
            status = command("HELLO")
            self.status.emit(status)
            self.phase.emit("通信正常")
            self.log.emit("HELLO: " + json.dumps(status, ensure_ascii=False))
            if self.action == "status":
                ping = command("PING")
                self.status.emit(ping)
                self.log.emit("PING: " + json.dumps(ping, ensure_ascii=False))
                return
            if status.get("ready") is not True or status.get("active_attempt") is not None:
                raise LinkError("手机定位未就绪或已有试验")
            if self.stop.is_set():
                return
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / ("usb-debug-" + run + ".jsonl")
            with path.open("x", encoding="utf-8") as out:
                command("CONFIGURE_RUN")
                owned = True
                command("PREPARE_ATTEMPT", attempt, {"startup_mode": "HOT",
                    "preparation_evidence": "USB diagnostic only; startup state not verified"})
                if self.stop.is_set():
                    return
                command("START_ATTEMPT", attempt, {"reference": self.reference,
                    "observation_s": 60, "satellite_tolerance_ms": 1500})
                self.phase.emit("正在定位采集")
                cursor = 0
                deadline = monotonic() + 70
                while not self.stop.is_set() and monotonic() < deadline:
                    events = command("FETCH_EVENTS", payload={"last_ack_seq": cursor}).get("events")
                    if not isinstance(events, list):
                        raise LinkError("事件列表无效")
                    finished = False
                    for event in events:
                        validate(event)
                        if event["run_id"] != run or event["attempt_id"] != attempt or event["seq"] <= cursor:
                            raise LinkError("事件身份或序列错误")
                        cursor = event["seq"]
                        if self.reference is None:
                            event["payload"].pop("horizontal_error_m", None)
                        line = json.dumps(event, ensure_ascii=False)
                        out.write(line + "\n")
                        self.telemetry.emit(event)
                        self.log.emit(line)
                        finished |= event["type"] == "ATTEMPT_RESULT"
                    if events:
                        out.flush()
                        command("ACK", payload={"seq": cursor})
                    if finished:
                        self.phase.emit("本轮采集结束，正在清理")
                        self.log.emit("采集结束（仅通信诊断，不判定灵敏度）")
                        break
                    self.stop.wait(0.25)
                else:
                    self.phase.emit("用户停止或诊断超时")
                    self.log.emit("用户停止或诊断超时")
            self.log.emit("本地日志: " + str(path))
        except Exception as exc:
            self.phase.emit("操作失败")
            self.log.emit("错误: " + str(exc))
        finally:
            if owned:
                try:
                    command("STOP_RUN")
                    if command("GET_STATUS").get("active_attempt") is not None:
                        raise LinkError("采集仍活动")
                    self.log.emit("已确认采集停止，手机服务保留")
                except Exception as exc:
                    self.phase.emit("停止未确认，请检查手机")
                    self.log.emit("停止未确认，请检查手机: " + str(exc))
            transport.disconnect()


class UsbDebugPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.worker = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("真实 USB 手机独立调试（无需仪器，不产生灵敏度结果）"))
        layout.addWidget(QLabel("选择顶部 USB 设备；手机授权精确定位并手动启动 USB 采集服务。"))
        self.settings = QSettings("GNSS", "SensitivityTest")
        reference_row = QHBoxLayout()
        self.ref_lat = QLineEdit(str(self.settings.value("usb_debug/reference_lat", "")))
        self.ref_lon = QLineEdit(str(self.settings.value("usb_debug/reference_lon", "")))
        for caption, field in (("参考纬度 (WGS84)", self.ref_lat), ("参考经度 (WGS84)", self.ref_lon)):
            reference_row.addWidget(QLabel(caption))
            field.setPlaceholderText("可留空")
            reference_row.addWidget(field)
        layout.addLayout(reference_row)
        row = QHBoxLayout()
        self.actions = []
        for title, action in (("打开 APP", "launch"), ("Root 检测", "root"),
                              ("连接 / 状态", "status"), ("启动定位采集", "collect")):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, a=action: self.begin(a))
            row.addWidget(button)
            self.actions.append(button)
        self.stop_button = QPushButton("停止采集")
        self.stop_button.clicked.connect(self.stop)
        row.addWidget(self.stop_button)
        layout.addLayout(row)
        self.values = {}
        for title, fields in (
            ("设备状态", (("phase", "运行状态"), ("model", "手机型号"),
                         ("android_version", "Android 版本"), ("app_version", "APP 版本"),
                         ("ready", "定位就绪"), ("shell_root", "ADB Root"),
                         ("root", "APP Root"), ("last_error", "手机最近异常"))),
            ("实时定位", (("ttff_s", "TTFF (s)"), ("used_in_fix", "解算卫星"),
                         ("latitude", "纬度"), ("longitude", "经度"),
                         ("satellite_count", "可见信号数"), ("horizontal_error_m", "定位误差 (m)"), ("result", "采集结果"))),
        ):
            group = QGroupBox(title)
            grid = QGridLayout(group)
            for i, (key, caption) in enumerate(fields):
                value = QLabel("—")
                value.setWordWrap(True)
                self.values[key] = value
                grid.addWidget(QLabel(caption), i // 2, (i % 2) * 2)
                grid.addWidget(value, i // 2, (i % 2) * 2 + 1)
            layout.addWidget(group)
        self.satellites = QTableWidget(0, 4)
        self.satellites.setHorizontalHeaderLabels(["卫星系统", "编号", "C/N₀ (dB-Hz)", "参与解算"])
        self.satellites.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.satellites.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.satellites, 2)
        layout.addWidget(QLabel("通信与运行日志"))
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(2000)
        layout.addWidget(self.output, 1)
        self.device_key = None

    def set_value(self, key, value):
        self.values[key].setText("—" if value is None else str(value))

    def show_status(self, status):
        for key in ("model", "android_version", "app_version", "root", "shell_root", "last_error"):
            if key in status:
                self.set_value(key, status[key])
        if "ready" in status:
            self.set_value("ready", "是" if status["ready"] is True else "否")

    def show_event(self, event):
        data = event["payload"]
        kind = event["type"]
        if kind == "LOCATION_UPDATE" and data.get("mock_location"):
            return
        for key in ("latitude", "longitude", "ttff_s", "used_in_fix", "horizontal_error_m"):
            if key in data:
                value = data[key]
                if key in ("latitude", "longitude", "ttff_s", "horizontal_error_m") and isinstance(value, (int, float)):
                    value = f"{value:.3f}" if key in ("ttff_s", "horizontal_error_m") else f"{value:.6f}"
                self.set_value(key, value)
        if kind == "SATELLITE_STATUS":
            satellites = data.get("satellites", [])
            self.set_value("satellite_count", len(satellites))
            self.satellites.setRowCount(len(satellites))
            names = {1: "GPS", 2: "SBAS", 3: "GLONASS", 4: "QZSS", 5: "北斗", 6: "Galileo", 7: "NavIC"}
            for row, sat in enumerate(satellites):
                values = (names.get(sat.get("constellation"), "其他"), sat.get("svid"),
                          sat.get("cn0_db_hz"), "是" if sat.get("used_in_fix") else "否")
                for col, value in enumerate(values):
                    self.satellites.setItem(row, col, QTableWidgetItem(str(value)))
        if kind == "ATTEMPT_RESULT":
            if "used_in_fix" not in data:
                self.set_value("used_in_fix", None)
            status, reason = data.get("status"), data.get("reason")
            result = {"OBSERVED": "定位成功", "FAIL": "定位失败", "INVALID": "本轮无效"}.get(status, "未知结果")
            self.set_value("result", f"{result} · {reason or '未知原因'}")

    def refresh(self, busy):
        device = self.window.serial.currentData()
        key = (device.serial, device.transport_id) if device else None
        if self.worker is None and key != self.device_key:
            self.device_key = key
            for field in self.values:
                self.set_value(field, None)
            self.satellites.setRowCount(0)
        for button in self.actions:
            button.setEnabled(not busy and self.worker is None and self.window.serial.currentData() is not None)
        self.stop_button.setEnabled(self.worker is not None)

    def begin(self, action):
        if self.worker is not None or self.window.worker is not None:
            return
        if getattr(self.window, "gss_page", None) and self.window.gss_page.worker is not None:
            return
        reference = None
        try:
            if action == "collect":
                a, b = self.ref_lat.text().strip(), self.ref_lon.text().strip()
                if a or b:
                    try:
                        lat, lon = float(a), float(b)
                    except ValueError:
                        raise LinkError("请输入完整有效的参考经纬度，或两项均留空")
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        raise LinkError("参考经纬度超出范围")
                    reference = {"latitude": lat, "longitude": lon}
                self.settings.setValue("usb_debug/reference_lat", a)
                self.settings.setValue("usb_debug/reference_lon", b)
            device = self.window.serial.currentData()
            if device is None:
                raise LinkError("请选择 USB 手机")
            usb = self.window.adb_monitor.claim(device)
        except LinkError as exc:
            self.output.appendPlainText(str(exc))
            return
        if action == "collect":
            for field in ("ttff_s", "used_in_fix", "latitude", "longitude", "satellite_count", "horizontal_error_m", "result"):
                self.set_value(field, None)
            self.satellites.setRowCount(0)
        self.worker = DebugWorker(usb, self.window.adb, action, self.window.root / "usb-debug", reference)
        self.worker.log.connect(self.output.appendPlainText)
        self.worker.status.connect(self.show_status)
        self.worker.telemetry.connect(self.show_event)
        self.worker.phase.connect(lambda value: self.set_value("phase", value))
        self.worker.finished.connect(self.done)
        self.window.set_busy(False)
        self.worker.start()

    def stop(self):
        if self.worker is not None:
            self.worker.stop.set()

    def done(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        snapshot = self.window.adb_monitor.release()
        self.window.update_usb(snapshot)
        self.window.set_busy(self.window.worker is not None)
        self.refresh(self.window.worker is not None)
        if self.window.serial.currentData() is not None:
            self.output.appendPlainText("本轮操作已释放，可再次点击启动定位采集（无需重启手机服务）")
        if self.window.closing:
            self.window.close()
