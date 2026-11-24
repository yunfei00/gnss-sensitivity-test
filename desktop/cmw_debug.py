"""Independent compact CMW500 debug page."""
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import QThread, Signal, QSettings
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,QComboBox,QPlainTextEdit,QMessageBox
from .cmw_remote import CmwSession,FIELDS,IDENTITY

class Worker(QThread):
    log = Signal(str)
    result = Signal(str,str)
    def __init__(self,host,port,op,key,value):
        super().__init__()
        self.args=host,port,op,key,value
    def run(self):
        host,port,op,key,value=self.args
        try:
            with CmwSession(host,port,self.log.emit) as cmw:
                cmw.check()
                if op=="identity":
                    for cmd in IDENTITY:
                        cmw.read(cmd)
                elif op=="read":
                    self.result.emit(key,cmw.read(FIELDS[key]+"?"))
                elif op=="all":
                    for field,cmd in FIELDS.items():
                        self.result.emit(field,cmw.read(cmd+"?"))
                    self.result.emit("cell",cmw.cell())
                elif op=="cell":
                    self.result.emit("cell",cmw.cell())
                elif op=="rrc":
                    self.result.emit("rrc",cmw.rrc())
                elif op=="attach":
                    self.result.emit("rrc",cmw.wait_connected())
                elif op=="switch":
                    self.result.emit("cell",cmw.switch(value))
                elif op=="set":
                    self.result.emit(key,cmw.configure(key,value))
                elif op=="query":
                    if not value.endswith("?") or ";" in value:
                        raise ValueError("仅允许单条查询指令")
                    cmw.read(value)
            self.log.emit("PASS: "+op)
        except Exception as exc:
            self.log.emit("FAIL / 状态可能未知: "+str(exc))

class CmwDebugPage(QWidget):
    def __init__(self,window):
        super().__init__()
        self.window=window
        self.worker=None
        self.settings=QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,"GNSS-Sensitivity","CMW500")
        layout=QVBoxLayout(self)
        layout.setSpacing(5)
        def row(*items):
            r=QHBoxLayout()
            for item in items:
                r.addWidget(QLabel(item) if isinstance(item,str) else item)
            layout.addLayout(r)
        def button(title,op,key="",value=""):
            b=QPushButton(title)
            b.clicked.connect(lambda checked=False:self.begin(op,key,value))
            return b
        self.host=QLineEdit(str(self.settings.value("host","")))
        self.port=QLineEdit(str(self.settings.value("port","5025")))
        self.port.setMaximumWidth(85)
        row("IP / 主机",self.host,"Socket 端口",self.port,button("连接 / 仪表信息","identity"))
        self.fields={}
        self.status=QLabel("小区状态：未知；NAS 注册：尚未独立验证")
        row(button("读取全部配置","all"),button("查询小区","cell"),button("启动小区","switch",value="ON"),button("停止小区","switch",value="OFF"))
        for key,title in (("duplex","双工 FDD/TDD"),("band","Band (OBn)"),("channel","DL EARFCN"),("bandwidth","带宽 (Bxxx)"),("power","RS EPRE dBm"),("route","RF 路由")):
            edit=QLineEdit()
            self.fields[key]=edit
            if key=="route":
                edit.setReadOnly(True)
                row(title,edit,button("读取","read",key))
            else:
                row(title,edit,button("读取","read",key),button("设置","set",key))
        row(button("查询 RRC","rrc"),button("等待手机连接","attach"))
        self.rrc_status=QLabel("RRC：未知（不等同 NAS 注册）")
        layout.addWidget(self.rrc_status)
        layout.addWidget(self.status)
        self.raw=QLineEdit()
        self.raw.setPlaceholderText("已核对的 SCPI 查询（注册命令待确认）")
        row(self.raw,button("查询","query"))
        self.output=QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(2000)
        layout.addWidget(self.output,1)
        self.host.textChanged.connect(self.save)
        self.port.textChanged.connect(self.save)
    def save(self,*_):
        self.settings.setValue("host",self.host.text())
        self.settings.setValue("port",self.port.text())
        self.settings.sync()
        self.rrc_status.setText("RRC：未知")
        self.status.setText("小区状态：未知；手机注册：尚未远程验证")
    def append(self,message):
        line=datetime.now().isoformat(timespec="seconds")+" "+message
        self.output.appendPlainText(line)
        try:
            path=Path("results/cmw-debug/commands.log")
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open("a",encoding="utf-8") as f:
                f.write(line+"\n")
        except OSError as exc:
            self.output.appendPlainText(str(exc))
    def show_result(self,key,value):
        if key=="rrc":
            self.rrc_status.setText("RRC："+value+("（已连接）" if value=="CONN" else "（未确认连接）"))
        elif key=="cell":
            self.status.setText("小区状态："+value+"；手机注册：尚未远程验证")
        else:
            self.fields[key].setText(value)
    def begin(self,op,key,value):
        if self.worker or self.window.worker or self.window.debug_page.worker or self.window.gss_page.worker:
            return
        try:
            host=self.host.text().strip()
            port=int(self.port.text())
            if not host or not 1<=port<=65535:
                raise ValueError("无效地址或端口")
            if op=="set":
                value=self.fields[key].text()
            if op=="query":
                value=self.raw.text().strip()
            if op in ("set","switch") and QMessageBox.question(self,"确认仪表操作","确认屏蔽箱、RF 路由、功率和当前测试配置后执行？")!=QMessageBox.StandardButton.Yes:
                return
            self.status.setText("小区状态：未知；手机注册：尚未远程验证")
            self.worker=Worker(host,port,op,key,value)
            self.worker.log.connect(self.append)
            self.worker.result.connect(self.show_result)
            self.worker.finished.connect(self.done)
            self.window.set_busy(False)
            self.worker.start()
        except Exception as exc:
            self.append(str(exc))
    def refresh(self,busy):
        self.setEnabled(not busy and self.worker is None)
    def done(self):
        worker,self.worker=self.worker,None
        worker.deleteLater()
        self.window.set_busy(self.window.worker is not None)
        if self.window.closing:
            self.window.close()
