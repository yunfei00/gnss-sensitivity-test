"""Qt widgets and styling for the operator console."""
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QHeaderView,
    QLabel, QLineEdit, QPlainTextEdit, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .presentation import quantity, reason_text

STYLE = """
QMainWindow, QDialog, QWidget#workspace { background: #eef2f7; color: #17283e; }
QWidget { font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; color: #17283e; }
QLabel { background: transparent; }
QLabel[role="title"] { font-size: 24px; font-weight: 700; }
QLabel[role="heading"] { font-size: 16px; font-weight: 700; }
QLabel[role="value"] { font-size: 23px; font-weight: 700; }
QLabel[role="muted"] { color: #50647b; }
QLabel[role="issue"] { color: #9d3328; }
QFrame[role="card"] { background: #ffffff; border: 1px solid #d6e0eb; border-radius: 12px; }
QFrame#topbar { background: #142941; }
QFrame#topbar QLabel { color: #ffffff; }
QFrame#topbar QLabel[role="muted"] { color: #c7d7eb; }
QLabel#modeBadge { background: #29435f; border-radius: 8px; padding: 6px 11px; font-weight: 700; }
QLabel#modeBadge[simulated="true"] { color: #ffe1a8; background: #493821; }
QTabWidget::pane { border: 0; }
QTabBar::tab { color: #425870; background: #e5ecf4; padding: 9px 21px; margin-right: 5px;
               border: 1px solid #d6e0eb; border-radius: 8px; }
QTabBar::tab:selected { background: #dbeafe; color: #154685; border-color: #9fc1e9; font-weight: 700; }
QPushButton { background: #ffffff; border: 1px solid #abbcd0; border-radius: 7px;
              padding: 7px 14px; min-height: 21px; font-weight: 600; }
QPushButton:hover { background: #e9f2fc; border-color: #5886b9; }
QPushButton[role="primary"] { background: #1956a5; color: white; border-color: #1956a5; }
QPushButton[role="primary"]:hover { background: #134887; }
QPushButton[role="stop"] { color: #9d3328; border-color: #d1a29b; }
QPushButton:disabled { background: #e7edf4; color: #64778e; border-color: #d4dee9; }
QLineEdit, QComboBox, QPlainTextEdit { background: #ffffff; padding: 5px 8px; border: 1px solid #abbcd0;
                                      border-radius: 6px; selection-background-color: #bedbfa; }
QLineEdit, QComboBox { min-height: 23px; }
QComboBox::drop-down { width: 22px; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QPushButton:focus {
    border: 2px solid #2266b2;
}
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled { background: #edf2f7; }
QTableWidget { background: white; alternate-background-color: #f2f6fb; border: 1px solid #d6e0eb;
               gridline-color: #dfe8f1; selection-background-color: #d7e9fd; selection-color: #17283e; }
QHeaderView::section { border: 0; background: #e6eef7; color: #263e59; padding: 7px; font-weight: 700; }
QScrollArea { border: 0; background: transparent; }
QProgressBar { border: 0; border-radius: 4px; background: #dbe5f1; }
QProgressBar::chunk { border-radius: 4px; background: #2774c4; }
"""


def label(value, role=None, wrap=False):
    widget = QLabel(value)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


def card(title=None):
    frame = QFrame()
    frame.setProperty("role", "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 12)
    layout.setSpacing(7)
    if title:
        layout.addWidget(label(title, "heading"))
    return frame, layout


def scroll(content):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(content)
    return area


def table(headers, stretch_last=False):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    widget.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerItem)
    widget.setAlternatingRowColors(True)
    widget.setShowGrid(False)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(29)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    if stretch_last:
        widget.horizontalHeader().setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((92, 122, 86, 94, 98, 85)):
            widget.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            widget.setColumnWidth(column, width)
    return widget


def fill_attempt(widget, row, item):
    values = (quantity(item.get("power_dbm")), item["attempt_id"][:8], item.get("status") or "—",
              quantity(item.get("ttff_s"), digits=3), quantity(item.get("horizontal_error_m"), digits=2),
              quantity(item.get("used_in_fix")), reason_text(item.get("reason")))
    for column, value in enumerate(values):
        cell = QTableWidgetItem(value)
        cell.setToolTip(item["attempt_id"] if column == 1 else value)
        if column <= 5:
            cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if column == 2:
            cell.setForeground(QColor({"PASS": "#12634c", "FAIL": "#9d3328", "INVALID": "#805500"}.get(value, "#17283e")))
        widget.setItem(row, column, cell)


CONFIG_GROUPS = (
    ("功率与观察", (
        ("min_power_dbm", "最低功率 (dBm)", int), ("max_levels", "最大档数", int),
        ("startup_mode", "启动模式", ("HOT", "WARM", "COLD", "AGPS")),
        ("observation_s", "观察窗口 (s)", float), ("settle_s", "功率稳定等待 (s)", float),
        ("power_tolerance_db", "读回容差 (dB)", float),
        ("satellite_tolerance_ms", "卫星关联窗口 (ms)", int),
    )),
    ("场景与校准", (
        ("scenario_id", "场景 ID", str), ("scenario_hash", "场景哈希", str),
        ("scenario_signals", "场景信号", str), ("reference_lat", "参考纬度 (°)", float),
        ("reference_lon", "参考经度 (°)", float), ("power_definition", "功率定义", str),
        ("calibration_ref", "校准引用", str),
    )),
)


class ConfigurationForm(QWidget):
    def __init__(self):
        super().__init__()
        self.fields = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        for column, (title, fields) in enumerate(CONFIG_GROUPS):
            group, body = card(title)
            form = QFormLayout()
            for key, name, kind in fields:
                editor = QComboBox() if isinstance(kind, tuple) else QLineEdit()
                if isinstance(kind, tuple):
                    editor.addItems(kind)
                editor.setAccessibleName(name)
                self.fields[key] = editor, name, kind
                form.addRow(name, editor)
            body.addLayout(form)
            grid.addWidget(group, 0, column)

    def set_values(self, values):
        for key, (editor, _name, _kind) in self.fields.items():
            value = values.get(key)
            if isinstance(editor, QComboBox):
                editor.setCurrentText(str(value))
            else:
                editor.setText("" if value is None else str(value))

    def draft(self):
        return {key: editor.currentText() if isinstance(editor, QComboBox) else editor.text()
                for key, (editor, _name, _kind) in self.fields.items()}

    def config_values(self):
        values = self.draft()
        for key, (_editor, name, kind) in self.fields.items():
            if isinstance(kind, tuple):
                continue
            try:
                values[key] = kind(values[key].strip())
            except ValueError as exc:
                raise ValueError(f"请输入有效的{name}") from exc
        return values


EVIDENCE_FIELDS = {
    "model": "仪器型号", "software": "场景软件", "version": "软件版本",
    "min_power_dbm": "最低功率 (dBm)", "max_power_dbm": "最高功率 (dBm)",
    "scenario_id": "场景 ID", "scenario_hash": "场景哈希", "static": "静态场景",
    "latitude": "参考纬度 (°)", "longitude": "参考经度 (°)", "signals": "信号",
    "calibration_ref": "校准引用", "power_definition": "功率定义", "running": "场景正在运行",
    "rf_off": "GNSS RF 已关闭", "set_power_dbm": "已设功率 (dBm)",
    "power_dbm": "当前功率 (dBm)", "readback_dbm": "实测读回 (dBm)",
    "registered": "DUT 已注册到 LTE 小区", "firmware": "固件版本", "options": "启用的选件",
    "cell": "LTE 小区", "band": "LTE 频段", "dut": "被测手机标识",
    "mode": "启动模式", "verified": "已按规程完成启动准备", "evidence": "现场证据",
}
BOOLEAN_FIELDS = {"static", "running", "rf_off", "registered", "verified"}


class EvidenceDialog(QDialog):
    def __init__(self, parent, prompt, template, safety):
        super().__init__(parent)
        self.setWindowTitle("确认 GNSS RF 已停止" if safety else "现场操作确认")
        self.setMinimumWidth(500)
        self.values = None
        self.template = template
        self.fields = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        layout.addWidget(label(self.windowTitle(), "heading"))
        layout.addWidget(label(prompt, wrap=True))
        form = QFormLayout()
        definitions = {key: value for key, value in template.items() if key != "reference"}
        if "reference" in template:
            definitions.update(latitude=None, longitude=None)
        for key, value in definitions.items():
            if key in BOOLEAN_FIELDS:
                editor = QComboBox()
                for name, choice in (("请选择", None), ("是", True), ("否", False)):
                    editor.addItem(name, choice)
            elif key == "evidence":
                editor = QPlainTextEdit()
                editor.setPlaceholderText("记录编号、日志路径或现场操作说明")
                editor.setFixedHeight(72)
            else:
                editor = QLineEdit("" if value is None else str(value))
            name = EVIDENCE_FIELDS.get(key, key)
            editor.setAccessibleName(name)
            self.fields[key] = editor
            form.addRow(name, editor)
        layout.addLayout(form)
        self.problem = label("", "issue", wrap=True)
        layout.addWidget(self.problem)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认并记录")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.submit)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def submit(self):
        data = {}
        reference = {}
        for key, editor in self.fields.items():
            name = EVIDENCE_FIELDS[key]
            try:
                if isinstance(editor, QComboBox):
                    value = editor.currentData()
                    if value is None:
                        raise ValueError(f"请确认{name}")
                else:
                    value = (editor.toPlainText() if isinstance(editor, QPlainTextEdit) else editor.text()).strip()
                    if key.endswith("_dbm") or key in {"latitude", "longitude"}:
                        if key == "power_dbm" and not value and data.get("running") is False:
                            value = None
                        else:
                            try:
                                value = float(value)
                            except ValueError:
                                raise ValueError(f"请输入有效的{name}") from None
                            if not math.isfinite(value):
                                raise ValueError(f"请输入有限的{name}")
                    elif not value:
                        raise ValueError(f"请填写{name}")
            except ValueError as exc:
                self.problem.setText(str(exc))
                editor.setFocus()
                return
            if key in {"latitude", "longitude"}:
                reference[key] = value
            else:
                data[key] = value
        if reference:
            data["reference"] = reference
        self.values = data
        self.accept()
