"""Independent real-phone USB diagnostics; never creates sensitivity results."""
import json
from threading import Event
from time import monotonic
from uuid import uuid4

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit, QLabel

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


class DebugWorker(QThread):
    log = Signal(str)

    def __init__(self, usb, adb, action, root):
        super().__init__()
        self.usb, self.adb, self.action, self.root = usb, adb, action, root
        self.stop = Event()

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
                self.log.emit(run_adb(self.adb, "shell", "su", "-c", "id", serial=self.usb.device.serial))
                return
            transport.connect()
            status = command("HELLO")
            self.log.emit("HELLO: " + json.dumps(status, ensure_ascii=False))
            if self.action == "status":
                self.log.emit("PING: " + json.dumps(command("PING"), ensure_ascii=False))
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
                command("START_ATTEMPT", attempt, {"reference": {"latitude": 0, "longitude": 0},
                    "observation_s": 60, "satellite_tolerance_ms": 1500})
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
                        # No known reference: never expose the dummy-reference error as a measurement.
                        event["payload"].pop("horizontal_error_m", None)
                        line = json.dumps(event, ensure_ascii=False)
                        out.write(line + "\n")
                        self.log.emit(line)
                        finished |= event["type"] == "ATTEMPT_RESULT"
                    if events:
                        out.flush()
                        command("ACK", payload={"seq": cursor})
                    if finished:
                        self.log.emit("采集结束（仅通信诊断，不判定灵敏度）")
                        break
                    self.stop.wait(0.25)
                else:
                    self.log.emit("用户停止或诊断超时")
            self.log.emit("本地日志: " + str(path))
        except Exception as exc:
            self.log.emit("错误: " + str(exc))
        finally:
            if owned:
                try:
                    command("STOP_RUN")
                    if command("GET_STATUS").get("active_attempt") is not None:
                        raise LinkError("采集仍活动")
                    self.log.emit("已确认采集停止")
                except Exception as exc:
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
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(2000)
        layout.addWidget(self.output)

    def refresh(self, busy):
        for button in self.actions:
            button.setEnabled(not busy and self.worker is None and self.window.serial.currentData() is not None)
        self.stop_button.setEnabled(self.worker is not None)

    def begin(self, action):
        if self.worker is not None or self.window.worker is not None:
            return
        try:
            device = self.window.serial.currentData()
            if device is None:
                raise LinkError("请选择 USB 手机")
            usb = self.window.adb_monitor.claim(device)
        except LinkError as exc:
            self.output.appendPlainText(str(exc))
            return
        self.worker = DebugWorker(usb, self.window.adb, action, self.window.root / "usb-debug")
        self.worker.log.connect(self.output.appendPlainText)
        self.worker.finished.connect(self.done)
        self.window.set_busy(False)
        self.worker.start()

    def stop(self):
        if self.worker is not None:
            self.worker.stop.set()

    def done(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.window.update_usb(self.window.adb_monitor.release())
        if self.window.closing:
            self.window.close()
