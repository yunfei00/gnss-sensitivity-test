"""Local ADB server discovery and a USB identity pinned to one run."""
import ast
import re
import socket
import subprocess
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from select import select
from threading import Event
from time import monotonic

from .core import LinkError

ADB_SERVER = ("127.0.0.1", 5037)
SCAN_INTERVAL_S = 10


def run_adb(adb, *args, serial=None):
    host, port = ADB_SERVER
    if args == ("start-server",):
        command = [adb, "-L", f"tcp:localhost:{port}"]
    else:
        command = [adb, "-H", host, "-P", str(port)]
    if serial is not None:
        command.extend(("-s", serial))
    try:
        result = subprocess.run([*command, *args], check=True, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=5,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.stdout.strip()
    except subprocess.TimeoutExpired as exc:
        raise LinkError(f"ADB {args[0]} 命令超时（5 秒）") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = (getattr(exc, "stderr", None) or str(exc)).strip()
        raise LinkError(f"ADB {args[0]} 执行失败：{detail}") from exc


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    transport_id: int
    state: str = "DEVICE"
    usb: bool = True
    model: str = ""

    @property
    def label(self):
        return f"{self.serial} · {self.model}" if self.model else self.serial


@dataclass(frozen=True)
class AdbSnapshot:
    devices: tuple[AdbDevice, ...] = ()
    error: str = ""

    @property
    def selectable(self):
        duplicates = Counter(device.serial for device in self.devices)
        return tuple(device for device in self.devices if device.usb and device.state == "DEVICE"
                     and device.transport_id > 0 and duplicates[device.serial] == 1)

    @property
    def description(self):
        if self.error:
            return self.error
        states = {"UNAUTHORIZED": "unauthorized（请在手机上允许 USB 调试）",
                  "OFFLINE": "offline（请检查手机及 USB 连接）"}
        selectable = {device.serial for device in self.selectable}
        issues = [f"{device.serial} · {states.get(device.state, device.state.lower() if device.state != 'DEVICE' else 'ADB 序列号或传输标识无法唯一确认')}"
                  for device in self.devices if device.usb and device.serial not in selectable]
        prefix = f"发现 {len(selectable)} 台可用 USB 设备" if selectable else "未发现 USB 设备"
        return "；".join((prefix, *issues))


class UsbRun:
    """A lost transport stays lost for this execution, even if its serial reappears."""
    def __init__(self, device: AdbDevice):
        self.device = device
        self.lost = Event()

    @property
    def reason(self):
        return f"USB 通信异常：锁定的设备 {self.device.serial} 已断开或无法确认"

    def observe(self, snapshot):
        if not any((phone.serial, phone.transport_id) == (self.device.serial, self.device.transport_id)
                   for phone in snapshot.selectable):
            self.lost.set()

    def check(self):
        if self.lost.is_set():
            raise LinkError(self.reason)


# AOSP track-devices text protobuf includes the connection type even on Windows
# backends where devices -l does not print a USB address.
def parse_snapshot(payload):
    devices = []
    fields = None
    try:
        for line in payload.decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            if line == "device {" and fields is None:
                fields = {}
            elif line == "}" and fields is not None:
                serial = ast.literal_eval(fields.get("serial", '""'))
                if isinstance(serial, str) and serial:
                    model = ast.literal_eval(fields.get("model", '""'))
                    if not isinstance(model, str):
                        raise ValueError("invalid model")
                    devices.append(AdbDevice(serial, int(fields.get("transport_id", "0")),
                                             fields.get("state", "ANY"), fields.get("connection_type") == "USB",
                                             model.replace("_", " ")))
                fields = None
            elif fields is not None:
                match = re.fullmatch(r"(\w+): (.+)", line)
                if not match:
                    raise ValueError("invalid device field")
                fields[match[1]] = match[2]
            else:
                raise ValueError("invalid device record")
        if fields is not None:
            raise ValueError("incomplete device record")
    except (ValueError, SyntaxError, TypeError) as exc:
        raise LinkError("ADB USB 设备列表格式无效") from exc
    return AdbSnapshot(tuple(devices))


def _read_exact(sock, size):
    received = bytearray()
    while len(received) < size:
        chunk = sock.recv(size - len(received))
        if not chunk:
            raise LinkError("ADB 服务连接已断开")
        received.extend(chunk)
    return bytes(received)


def _frame(sock):
    try:
        length = int(_read_exact(sock, 4), 16)
        if length < 0:
            raise ValueError("negative length")
    except ValueError as exc:
        raise LinkError("ADB 设备列表长度无效") from exc
    return _read_exact(sock, length)


@contextmanager
def _tracker():
    query = b"host:track-devices-proto-text"
    with socket.create_connection(ADB_SERVER, timeout=2) as sock:
        sock.sendall(f"{len(query):04x}".encode("ascii") + query)
        status = _read_exact(sock, 4)
        if status == b"FAIL":
            detail = _frame(sock).decode("utf-8", "replace")
            raise LinkError(f"ADB 不支持 USB 类型发现，请更新 SDK Platform Tools（{detail}）")
        if status != b"OKAY":
            raise LinkError("ADB 服务响应无效")
        yield sock


def monitor_devices(publish, stop, adb="adb"):
    """Subscribe to push updates and renew the initial snapshot every ten seconds."""
    start_server = True
    while not stop.is_set():
        end = monotonic() + SCAN_INTERVAL_S
        try:
            if start_server:
                run_adb(adb, "start-server")
            with _tracker() as sock:
                publish(parse_snapshot(_frame(sock)))
                start_server = False
                while not stop.is_set() and monotonic() < end:
                    if select([sock], [], [], min(0.2, max(0, end - monotonic())))[0]:
                        publish(parse_snapshot(_frame(sock)))
        except (LinkError, OSError) as exc:
            reason = "ADB USB 扫描超时" if isinstance(exc, TimeoutError) else str(exc)
            publish(AdbSnapshot(error=f"ADB USB 扫描失败：{reason}"))
            start_server = True
        stop.wait(max(0, end - monotonic()))
