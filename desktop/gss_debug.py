"""Independent GSS7000 remote command workbench."""
from datetime import datetime
from PySide6.QtCore import QThread, Signal, QSettings
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel, QPlainTextEdit, QMessageBox, QDoubleSpinBox)
from .gss_remote import exchange, render_command, describe_response, XML_END

OPERATIONS = (("identify", "型号 / 版本"), ("state", "查询状态"),
              ("current", "当前场景"), ("scenario", "加载场景"), ("trigger", "软件触发模式"), ("start", "启动场景"), ("stop", "停止场景"),
              ("power", "设置 GPS 功率（参考 dB）"), ("read_power", "读取功率"))
DEFAULTS = {"identify": "*IDN?", "state": "NULL", "current": "SC_NAME",
            "scenario": "SC,{value}", "trigger": "TR,0", "start": "RU", "stop": "-,EN,1",
            "power": "-,POW_LEV,v1,{value},GPS,23,0,0,1,1,1,1"}
ENDS = {"LF": b"\n", "CRLF": b"\r\n", "CR": b"\r", "无": b""}


class Probe(QThread):
    result = Signal(str)
    def __init__(self, args):
        super().__init__()
        self.args = args
    def run(self):
        try:
            raw = exchange(*self.args)
            self.result.emit("响应: " + raw)
            if self.args[4] == XML_END:
                self.result.emit(describe_response(raw))
        except Exception as exc:
            self.result.emit("异常（执行状态未知）: " + str(exc))


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
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(2000)
        layout.addWidget(self.output, 1)
        self.load_template()

    def load_template(self):
        self.template.setText(str(self.settings.value("commands/" + self.operation.currentData(), "") or DEFAULTS.get(self.operation.currentData(), "")))

    def save_template(self):
        self.settings.setValue("commands/" + self.operation.currentData(), self.template.text())
        self.settings.setValue("host", self.host.text())
        self.settings.setValue("port", self.port.text())
        self.settings.setValue("tx", self.tx.currentText())
        self.settings.setValue("rx", self.rx.currentText())
        self.settings.sync()

    def execute(self):
        try:
            key = self.operation.currentData()
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
        self.output.appendPlainText(datetime.now().isoformat(timespec="seconds") + " " + message)

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
