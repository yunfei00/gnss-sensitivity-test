"""CMW500 SCPI socket adapter; commands from instrument-automation-platform."""
import socket
import math
import re
from time import monotonic, sleep
from .core import DeviceError

FIELDS = {
    "duplex": "CONFigure:LTE:SIGN:PCC:DMODe",
    "band": "CONFigure:LTE:SIGN:PCC:BAND",
    "channel": "CONFigure:LTE:SIGN:RFSettings:PCC:CHANnel:DL",
    "bandwidth": "CONFigure:LTE:SIGN:CELL:BANDwidth:PCC:DL",
    "power": "CONFigure:LTE:SIGN:DL:PCC:RSEPre:LEVel",
    "route": "ROUTe:LTE:SIGN:SCENario:SCELl",
}
CELL = "SOURce:LTE:SIGN:CELL"
IDENTITY = ("*IDN?", "SYSTem:BASE:OPTion:VERSion?", "SYSTem:BASE:OPTion:LIST?")

def validate(key, value):
    value = value.strip().upper()
    if key == "duplex" and value in ("FDD", "TDD"):
        return value
    if key == "band" and re.fullmatch(r"OB[1-9][0-9]*", value):
        return value
    if key == "channel" and re.fullmatch(r"[0-9]+", value):
        return str(int(value))
    if key == "bandwidth" and value in ("B014","B030","B050","B100","B150","B200"):
        return value
    if key == "power":
        try:
            number = float(value)
            if math.isfinite(number):
                return str(number)
        except ValueError:
            pass
    raise DeviceError("无效参数: " + key)

class CmwSession:
    def __init__(self, host, port, emit, timeout=5):
        self.host, self.port, self.emit, self.timeout = host, port, emit, timeout
    def __enter__(self):
        self.sock = socket.create_connection((self.host,self.port), self.timeout)
        self.sock.settimeout(self.timeout)
        self.reader = self.sock.makefile("rb")
        return self
    def __exit__(self, *args):
        self.reader.close()
        self.sock.close()
    def send(self, command):
        if not command or any(c in command for c in "\r\n"):
            raise DeviceError("仅允许单条 SCPI 指令")
        self.emit("发送: " + command)
        self.sock.sendall((command+"\n").encode("ascii"))
    def query(self, command):
        self.send(command)
        raw = self.reader.readline(65537)
        if not raw or len(raw)>65536 or not raw.endswith(b"\n"):
            raise DeviceError("响应为空、不完整或超限")
        value = raw.decode("ascii").strip()
        self.emit("响应: " + value)
        return value
    def check(self):
        error = self.query("SYSTem:ERRor?")
        if not re.match(r"^\+?0\s*,", error):
            raise DeviceError("SCPI error: " + error)
    def read(self, command):
        result = self.query(command)
        self.check()
        return result
    def write(self, command):
        self.send(command)
        self.check()
    def cell(self):
        return self.read(CELL+":STATe?").split(",")[0].strip().upper()
    def switch(self, target):
        self.write(CELL+":STATe "+target)
        deadline = monotonic()+30
        while monotonic()<deadline:
            if self.cell()==target:
                return target
            sleep(0.5)
        raise DeviceError("小区状态未达到 "+target)
    def rrc(self):
        return self.read("SENSe:LTE:SIGN:RRCState?").strip().upper()
    def wait_connected(self):
        deadline = monotonic()+30
        while monotonic()<deadline:
            if self.rrc()=="CONN":
                return "CONN"
            sleep(0.2)
        raise DeviceError("等待 RRC CONN 超时")
    def configure(self, key, value):
        value = validate(key,value)
        if key != "power" and self.cell()!="OFF":
            raise DeviceError("请先关闭小区")
        self.write(FIELDS[key]+" "+value)
        actual = self.read(FIELDS[key]+"?")
        try:
            same = abs(float(actual)-float(value))<0.01 if key=="power" else actual.strip().upper()==value
        except ValueError:
            same = False
        if not same:
            raise DeviceError("读回不一致: "+actual)
        return actual
