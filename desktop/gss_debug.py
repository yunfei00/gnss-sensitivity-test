"""Independent GSS7000 remote command workbench."""
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QThread, Signal, QSettings
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel, QPlainTextEdit, QMessageBox, QDoubleSpinBox)
from .gss_versions import DIALECTS
from .gss_remote import exchange, render_command, describe_response, XML_END, run_operation

OPERATIONS = (("identify", "型号 / 版本"), ("state", "查询状态"),
              ("current", "当前场景"), ("scenario", "加载场景"), ("trigger", "软件触发模式"), ("start", "启动场景"), ("stop", "停止场景"),
              ("power", "设置 GPS 功率（参考 dB）"), ("read_power", "读取功率"), ("time", "查询场景时间"))
DEFAULTS = {"identify": "*IDN?", "state": "NULL", "current": "SC_NAME",
            "scenario": "SC,{value}", "trigger": "TR,0", "start": "RU", "stop": "-,EN,1",
            "power": "-,POW_LEV,v1,{value},GPS,23,0,0,1,1,1,1"}
ENDS = {"LF": b"\n", "CRLF": b"\r\n", "CR": b"\r", "无": b""}


class Probe(QThread):
    result = Signal(str)
    success = Signal(int, str)
    def __init__(self, args):
        super().__init__()
        self.args = args
    def run(self):
        try:
            if len(self.args) == 6:
                state, data = run_operation(*self.args[:5], self.result.emit)
                self.success.emit(state, data)
                self.result.emit("PASS: " + str(state) + " " + data)
                return
            raw = exchange(*self.args)
            self.result.emit("响应: " + raw)
            if self.args[4] == XML_END:
                self.result.emit(describe_response(raw))
        except Exception as exc:
            self.result.emit("FAIL / 未验证（执行状态可能未知）: " + str(exc))


class GssDebugPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.worker = None
        self.settings = QSettings("GNSS-Sensitivity", "GSS7000")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("独立 TCP 调试：每条命令新建连接；须核对现场协议。发送成功不等于 RF 状态已验证。"))
        form = QFormLayout()
        self.host = QLineEdit(str(self.settings.value("host", "")))
        self.port = QLineEdit(str(self.settings.value("port", "15650") or "15650"))
        self.tx, self.rx = QComboBox(), QComboBox()
        for box in (self.tx, self.rx):
            box.addItems(list(ENDS))
        self.rx.insertItem(0, "XML")
        self.rx.setCurrentIndex(0)
        self.tx.setCurrentText(str(self.settings.value("tx", "LF")))
        self.rx.setCurrentText(str(self.settings.value("rx", "XML")))
        self.version = QComboBox()
        self.version.addItems(list(DIALECTS))
        self.version.setCurrentText(str(self.settings.value("version", "6.00.02")))
        form.addRow("SimREPLAYplus 版本（手动确认）", self.version)
        form.addRow("仪器 IP / 主机", self.host)
        form.addRow("远控端口", self.port)
        form.addRow("发送结束符", self.tx)
        form.addRow("响应结束符（无 = 不读回）", self.rx)
        self.operation = QComboBox()
        for key, title in OPERATIONS:
            self.operation.addItem(title, key)
        self.template = QLineEdit()
        self.value = QLineEdit()
        self.operation.currentIndexChanged.connect(self.load_template)
        form.addRow("操作", self.operation)
        form.addRow("指令模板", self.template)
        form.addRow("参数（场景完整路径 / GPS 参考 dB；非 dBm）", self.value)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.save = QPushButton("保存本地指令")
        self.save.clicked.connect(self.save_template)
        self.send = QPushButton("执行选定操作")
        self.send.clicked.connect(self.execute)
        row.addWidget(self.save)
        row.addWidget(self.send)
        layout.addLayout(row)
        self.raw = QLineEdit()
        self.raw.setPlaceholderText("输入单条已核对的原始指令")
        row = QHBoxLayout()
        row.addWidget(self.raw)
        self.raw_send = QPushButton("发送原始指令")
        self.raw_send.clicked.connect(lambda: self.submit(self.raw.text()))
        row.addWidget(self.raw_send)
        layout.addLayout(row)
        self.quick_buttons = {}
        for entries in ((("连接 / 状态", "state"), ("仪表信息", "identify"), ("当前场景", "current")), (("加载场景", "scenario"), ("启动场景", "start"), ("停止并复位", "stop")), (("设置 GPS 参考功率", "power"), ("读取 GPS 参考功率", "read_power"), ("查询场景时间", "time"))):
            buttons = QHBoxLayout()
            for title, key in entries:
                button = QPushButton(title)
                button.clicked.connect(lambda checked=False, k=key: self.quick(k))
                self.quick_buttons[key] = button
                buttons.addWidget(button)
            layout.addLayout(buttons)
        self.scenario_path = QLineEdit()
        self.scenario_path.setPlaceholderText("仪表上的场景完整路径")
        layout.addWidget(self.scenario_path)
        self.power = QDoubleSpinBox()
        self.power.setRange(-200, 100)
        self.power.setSuffix(" dB (参考值，非 dBm)")
        layout.addWidget(self.power)
        self.svid = QLineEdit("23")
        self.svid.setPlaceholderText("场景中实际启用的 GPS SVID")
        layout.addWidget(self.svid)
        self.power_status = QLabel("已确认设置值：未知（非仪表读回）")
        layout.addWidget(self.power_status)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(2000)
        layout.addWidget(self.output, 1)
        self.version.currentTextChanged.connect(self.version_changed)
        self.host.textChanged.connect(self.invalidate_power)
        self.port.textChanged.connect(self.invalidate_power)
        self.tx.currentTextChanged.connect(self.invalidate_power)
        self.version_changed()

    def invalidate_power(self, *_):
        self.power_status.setText("已确认设置值：未知（非仪表读回）")

    def version_changed(self, *_):
        self.settings.setValue("version", self.version.currentText())
        self.invalidate_power()
        self.quick_buttons["read_power"].setEnabled(DIALECTS[self.version.currentText()].read_power)
        self.load_template()

    def quick(self, key):
        if self.worker is not None or self.window.worker is not None:
            return
        try:
            host, port = self.host.text().strip(), int(self.port.text())
            if not host or not 1 <= port <= 65535:
                raise ValueError("无效地址或端口")
            dialect = DIALECTS[self.version.currentText()]
            commands = [DEFAULTS[key]] if key not in ("read_power", "time") else []
            expected = None
            if key == "scenario":
                path = self.scenario_path.text().strip()
                if not path or any(c in path for c in '\\r\\n"'):
                    raise ValueError("请输入有效的仪表场景路径")
                commands = ['SC,"' + path + '"']
                expected = 2
            elif key == "start":
                commands, expected = ["TR,0", "RU"], 5
            elif key == "stop":
                expected = 2
            elif key == "power":
                commands = [render_command(DEFAULTS[key], self.power.value())]
            elif key == "read_power":
                svid = int(self.svid.text())
                commands = [dialect.power_query(svid)]
            elif key == "time":
                commands = [dialect.time_command]
            if key in ("scenario", "start", "stop", "power") and QMessageBox.question(self, "确认操作", "确认屏蔽环境、场景及功率单位后执行？") != QMessageBox.StandardButton.Yes:
                return
            self.invalidate_power()
            self.append("版本: " + dialect.version)
            self.worker = Probe((host, port, ENDS[self.tx.currentText()], commands, expected, True))
            if key == "power":
                value = self.power.value()
                self.worker.success.connect(lambda state, data: self.power_status.setText(f"已确认设置值：{value:g} dB（非仪表读回）"))
            self.worker.result.connect(self.append)
            self.worker.finished.connect(self.done)
            self.window.set_busy(False)
            self.worker.start()
        except Exception as exc:
            self.append("FAIL: " + str(exc))

    def load_template(self):
        key = self.operation.currentData()
        dialect = DIALECTS[self.version.currentText()]
        default = dialect.time_command if key == "time" else DEFAULTS.get(key, "")
        if key == "read_power":
            default = dialect.power_query(23) if dialect.read_power else ""
        self.template.setText(str(self.settings.value("commands/" + dialect.version + "/" + key, "") or default))

    def save_template(self):
        self.settings.setValue("commands/" + self.version.currentText() + "/" + self.operation.currentData(), self.template.text())
        self.settings.setValue("host", self.host.text())
        self.settings.setValue("port", self.port.text())
        self.settings.setValue("tx", self.tx.currentText())
        self.settings.setValue("rx", self.rx.currentText())
        self.settings.sync()

    def execute(self):
        try:
            key = self.operation.currentData()
            if key == "read_power" and not DIALECTS[self.version.currentText()].read_power:
                raise ValueError("该版本不支持远程功率读回")
            value = self.value.text().strip() if key in ("scenario", "power") else None
            if value == "":
                raise ValueError("参数不能为空")
            if key == "power":
                import math
                if not math.isfinite(float(value)):
                    raise ValueError("功率必须是有限数值")
            self.submit(render_command(self.template.text(), value))
        except Exception as exc:
            self.append(str(exc))

    def append(self, message):
        line = datetime.now().isoformat(timespec="seconds") + " " + message
        self.output.appendPlainText(line)
        try:
            path = Path("results/gss-debug/commands.log")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        except OSError as exc:
            self.output.appendPlainText("日志保存失败: " + str(exc))

    def refresh(self, busy):
        self.setEnabled(not busy and self.worker is None)

    def submit(self, command):
        if self.worker is not None or self.window.worker is not None:
            return
        try:
            port = int(self.port.text())
            if not 1 <= port <= 65535 or not self.host.text().strip():
                raise ValueError("请填写有效仪器地址及端口")
            if not command.strip() or "\n" in command or "\r" in command:
                raise ValueError("请输入单条指令")
            command.encode("ascii")
        except ValueError as exc:
            self.append(str(exc))
            return
        if QMessageBox.question(self, "确认仪器操作",
                "请确认 RF 屏蔽、指令含义及参数单位。\n发送: " + command) != QMessageBox.StandardButton.Yes:
            return
        self.invalidate_power()
        self.append("发送: " + command)
        self.worker = Probe((self.host.text().strip(), port, command,
                             ENDS[self.tx.currentText()], XML_END if self.rx.currentText() == "XML" else ENDS[self.rx.currentText()]))
        self.worker.result.connect(self.append)
        self.worker.finished.connect(self.done)
        self.window.set_busy(False)
        self.worker.start()

    def done(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.window.set_busy(self.window.worker is not None)
        if getattr(self.window, "closing", False):
            self.window.close()
