"""P4/P5 integrated hardware operator page. No simulated data in real runs."""
from datetime import datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QThread, Signal, QSettings, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QPlainTextEdit, QInputDialog, QMessageBox,
                               QFormLayout, QComboBox, QGridLayout, QScrollArea)

from .gss_calibration import GssCalibration
from .stage4_fixed import FixedPowerPlan, run_fixed_power
from .stage5_sweep import SweepPlan, run_sensitivity_sweep
from .stage45_instruments import CmwLteAdapter, GssCalibratedAdapter
from .stage45_phone import UsbGnssAdapter
from .stage45_reports import export_stage45
from .core import DeviceError, UserStop


class Stage45Worker(QThread):
    log = Signal(str)
    completed = Signal(object)
    ask = Signal(object)

    def __init__(self, mode, settings, usb, adb, directory):
        super().__init__()
        self.mode, self.values, self.usb, self.adb = mode, settings, usb, adb
        self.directory = Path(directory)
        self.stop = Event()

    def evidence(self, prompt):
        ready = Event()
        output = {}
        self.ask.emit((prompt, ready, output))
        while not ready.wait(0.1):
            if self.stop.is_set():
                raise UserStop("USER_STOP")
        value = output.get("value", "")
        if not value:
            raise UserStop("OPERATOR_CANCELLED")
        return value

    def run(self):
        v = self.values
        try:
            calibration = GssCalibration(
                v["version"], float(v["measured"]), float(v["reference_db"]),
                v["calibration"], v["plane"], float(v["range_min"]), float(v["range_max"]))
            def cmw():
                return CmwLteAdapter(v["cmw_host"], int(v["cmw_port"]), self.log.emit)
            def gss():
                return GssCalibratedAdapter(
                    v["gss_host"], calibration, int(v["gss_port"]),
                    confirm_power=lambda target, c: self.evidence(
                        f"请独立核验 DUT 参考平面 GNSS 功率 {target:g} dBm。"
                        "核对仪表实际输出/功率计、线损与校准记录，填写本档核验证据编号。"),
                    log=self.log.emit)
            count = [0]
            def phone():
                count[0] += 1
                return UsbGnssAdapter(self.usb, self.adb,
                    self.directory / f"phone_audit_{count[0]}.sqlite",
                    lambda mode: self.evidence(
                        f"第 {count[0]} 档本轮 {mode} 启动准备：请确认独立测试已准备并填写证据。"),
                    self.log.emit, self.stop)
            notify = lambda event, data: self.log.emit(event + ": " + str(data))
            if self.mode == "P4":
                plan = FixedPowerPlan(-120.0, float(v["lat"]), float(v["lon"]),
                                      v["scenario"], v["calibration"])
                result = run_fixed_power(plan, cmw(), gss(), phone(),
                                         self.directory / "fixed.json", self.stop, notify)
            else:
                plan = SweepPlan(int(v["min_power"]), int(v["levels"]),
                                 float(v["lat"]), float(v["lon"]),
                                 v["scenario"], v["calibration"])
                result = run_sensitivity_sweep(plan, cmw, gss, phone,
                                               self.directory, self.stop, notify)
            report_html, report_csv = export_stage45(self.directory)
            result["report_html"] = str(report_html)
            result["report_csv"] = str(report_csv)
            self.completed.emit(result)
        except Exception as exc:
            self.completed.emit({"status": "PAUSED", "reason": str(exc)})


class Stage45Page(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.worker = None
        self.settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                                  "GNSS-Sensitivity", "P4P5")
        gss = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                        "GNSS-Sensitivity", "GSS7000")
        cmw = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                        "GNSS-Sensitivity", "CMW500")
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.addWidget(QLabel("P4：-120 dBm 固定功率 20 次；P5：-120 dBm 起逐档 -1 dB，首次失败停止。"))
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(5)
        self.fields = {}
        defaults = {
            "gss_host": str(gss.value("host", "")), "gss_port": str(gss.value("port", "15650")),
            "cmw_host": str(cmw.value("host", "")), "cmw_port": str(cmw.value("port", "5025")),
            "scenario": str(gss.value("scenario_path", "")),
            "measured": "", "reference_db": "", "range_min": "", "range_max": "",
            "calibration": "", "plane": "DUT antenna input",
            "lat": "", "lon": "", "min_power": "-130", "levels": "11"}
        labels = {
            "gss_host": "GSS7000 IP", "gss_port": "GSS 端口",
            "cmw_host": "CMW500 IP", "cmw_port": "CMW 端口",
            "scenario": "仪表场景路径", "measured": "校准实测输出 (dBm)",
            "reference_db": "对应 POW_LEV 参考值 (dB)",
            "range_min": "已校准下限 (dBm)", "range_max": "已校准上限 (dBm)",
            "calibration": "校准证据编号", "plane": "功率参考平面",
            "lat": "场景纬度", "lon": "场景经度",
            "min_power": "P5 最低功率 (dBm)", "levels": "P5 最大档数"}
        for index, (key, default) in enumerate(defaults.items()):
            edit = QLineEdit(str(self.settings.value(key, default)))
            self.fields[key] = edit
            edit.textChanged.connect(self.save)
            row, column = divmod(index, 2)
            form.addWidget(QLabel(labels[key]), row, column * 2)
            form.addWidget(edit, row, column * 2 + 1)
        self.version = QComboBox()
        self.version.addItems(["6.00.02", "10.02.00"])
        self.version.setCurrentText(str(self.settings.value("version", gss.value("version", "6.00.02"))))
        self.version.currentTextChanged.connect(self.save)
        form.addWidget(QLabel("SimREPLAYplus 版本"), 9, 0)
        form.addWidget(self.version, 9, 1)
        layout.addLayout(form)
        layout.addWidget(QLabel("校准要求：必须在整个扫描范围核验 1 dB 线性响应，不能只凭单点测量推算。"
                                "V6 无 SIG_LEVEL 远程功率读回，每档须提供独立核验证据。"))
        buttons = QHBoxLayout()
        self.p4 = QPushButton("开始 P4 固定 20 次")
        self.p5 = QPushButton("开始 P5 逐档扫描")
        self.cancel = QPushButton("取消并安全停止")
        self.open_report = QPushButton("打开本次报告")
        self.open_report.setEnabled(False)
        self.report_path = None
        self.open_report.clicked.connect(self.show_report)
        self.cancel.setEnabled(False)
        self.p4.clicked.connect(lambda: self.begin("P4"))
        self.p5.clicked.connect(lambda: self.begin("P5"))
        self.cancel.clicked.connect(self.stop)
        for button in (self.p4, self.p5, self.cancel, self.open_report):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.status = QLabel("待开始；需先核对屏蔽环境、NAS 注册及校准证据")
        layout.addWidget(self.status)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(4000)
        layout.addWidget(self.output, 1)

    def save(self, *_):
        for key, edit in self.fields.items():
            self.settings.setValue(key, edit.text())
        self.settings.setValue("version", self.version.currentText())
        self.settings.sync()

    def append(self, message):
        line = datetime.now().isoformat(timespec="seconds") + " " + message
        self.output.appendPlainText(line)
        try:
            path = Path("results/stage45/commands.log")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as out:
                out.write(line + "\n")
        except OSError as exc:
            self.output.appendPlainText("日志保存失败: " + str(exc))

    def begin(self, mode):
        if self.worker is not None or self.window.worker is not None or (
            self.window.debug_page.worker is not None or
            self.window.gss_page.worker is not None or self.window.cmw_page.worker is not None):
            return
        device = self.window.serial.currentData()
        if device is None:
            self.append("FAIL: 请先选择在线 USB 手机")
            return
        v = {k: field.text().strip() for k, field in self.fields.items()}
        v["version"] = self.version.currentText()
        try:
            for key in ("gss_host", "cmw_host", "scenario", "calibration", "plane"):
                if not v[key]:
                    raise ValueError(key + " 不能为空")
            for key in ("gss_port", "cmw_port"):
                if not 1 <= int(v[key]) <= 65535:
                    raise ValueError(key + " 端口无效")
            calibration = GssCalibration(v["version"], float(v["measured"]),
                                         float(v["reference_db"]), v["calibration"], v["plane"],
                                         float(v["range_min"]), float(v["range_max"]))
            if mode == "P4":
                calibration.to_reference_db(-120)
            else:
                plan = SweepPlan(int(v["min_power"]), int(v["levels"]),
                                 float(v["lat"]), float(v["lon"]),
                                 v["scenario"], v["calibration"])
                calibration.to_reference_db(-120)
                calibration.to_reference_db(max(plan.minimum_dbm, -120-plan.maximum_levels+1))
            if QMessageBox.question(self, "确认真实 RF 联合测试",
                "确认已在屏蔽环境内、CMW500 LTE NAS 注册已人工核对、"
                "校准证据真实且覆盖扫描范围。开始后将控制真实 RF 仪表，是否继续？"
                ) != QMessageBox.StandardButton.Yes:
                return
            usb = self.window.adb_monitor.claim(device)
            directory = Path("results/stage45") / str(uuid4())
            self.report_path = None
            self.open_report.setEnabled(False)
            self.worker = Stage45Worker(mode, v, usb, self.window.adb, directory)
            self.worker.log.connect(self.append)
            self.worker.ask.connect(self.ask)
            self.worker.completed.connect(self.complete)
            self.worker.finished.connect(self.done)
            self.status.setText(mode + " 运行中；输出：" + str(directory))
            self.window.set_busy(False)
            self.worker.start()
        except Exception as exc:
            self.append("FAIL: " + str(exc))

    def ask(self, request):
        prompt, event, output = request
        value, ok = QInputDialog.getMultiLineText(self, "现场证据", prompt, "")
        if ok and value.strip():
            output["value"] = value.strip()
        event.set()

    def stop(self):
        if self.worker is not None:
            self.worker.stop.set()
            self.append("正在取消；等待 RF 安全停止确认")

    def show_report(self):
        if self.report_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.report_path.resolve())))

    def complete(self, result):
        self.report_path = Path(result["report_html"]) if result.get("report_html") else None
        self.open_report.setEnabled(self.report_path is not None and self.report_path.is_file())
        self.status.setText("运行状态: " + result.get("status", "未知") +
                            "；" + str(result.get("reason", result.get("verdict", ""))))
        self.append("最终结果: " + str(result))

    def done(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.window.adb_monitor.release()
        self.window.update_usb(self.window.adb_monitor.snapshot)
        self.window.set_busy(self.window.worker is not None)
        if self.window.closing:
            self.window.close()

    def refresh(self, busy):
        running = self.worker is not None
        self.p4.setEnabled(not busy and not running)
        self.p5.setEnabled(not busy and not running)
        self.cancel.setEnabled(running)
        for edit in self.fields.values():
            edit.setEnabled(not busy and not running)
        self.version.setEnabled(not busy and not running)
