"""Phone transport contract. Phase 1 implements loopback JSONL over USB ADB."""
import socket
import subprocess
from abc import ABC, abstractmethod

from .core import LinkError
from .protocol import MAX_LINE, decode, dump


class PhoneTransport(ABC):
    mock = False

    @abstractmethod
    def connect(self): ...

    @abstractmethod
    def send_command(self, command): ...

    @abstractmethod
    def receive_event(self): ...

    @abstractmethod
    def disconnect(self): ...

    def reconnect(self):
        self.disconnect()
        self.connect()


class AdbTransport(PhoneTransport):
    def __init__(self, serial="", adb="adb"):
        self.serial = serial
        self.adb = adb
        self._socket = None
        self._reader = None
        self._port = None
        self._device_serial = None

    def _run_adb(self, *args, serial=None):
        command = [self.adb, *([] if serial is None else ["-s", serial]), *args]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=5)
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise LinkError(f"ADB {args[0]} 失败: {getattr(exc, 'stderr', None) or exc}") from exc

    def connect(self):
        devices = []
        for line in self._run_adb("devices", "-l").splitlines()[1:]:
            columns = line.split()
            if len(columns) >= 2 and columns[1] == "device" and any(
                field.startswith("usb:") for field in columns[2:]
            ):
                devices.append(columns[0])
        requested = self._device_serial or self.serial
        if not devices:
            # Some ADB USB backends omit usb: from the long list. -d is USB-only.
            selected = self._run_adb("-d", "get-serialno")
            if selected and selected != "unknown":
                devices = [selected]
        if requested:
            devices = [serial for serial in devices if serial == requested]
        if len(devices) != 1:
            raise LinkError("ADB 需要恰好一台已授权的 USB 手机。多设备时请指定序列号。")
        self._device_serial = devices[0]
        # Allocate a host port to avoid overwriting another application's forward.
        try:
            self._port = int(self._run_adb("forward", "tcp:0", "tcp:18765", serial=self._device_serial))
            self._socket = socket.create_connection(("127.0.0.1", self._port), timeout=2)
            self._reader = self._socket.makefile("rb")
        except (OSError, ValueError, LinkError) as exc:
            self.disconnect()
            raise LinkError("ADB 转发无法连接，请检查手机采集服务") from exc

    def send_command(self, command):
        if self._socket is None:
            raise LinkError("ADB 尚未连接")
        try:
            encoded = (dump(command) + "\n").encode("utf-8")
            if len(encoded) > MAX_LINE:
                raise LinkError("命令超出 JSONL 帧大小")
            self._socket.sendall(encoded)
        except OSError as exc:
            raise LinkError("ADB 写入中断") from exc

    def receive_event(self):
        if self._reader is None:
            raise LinkError("ADB 尚未连接")
        try:
            return decode(self._reader.readline(MAX_LINE + 1))
        except OSError as exc:
            raise LinkError("ADB 读取中断或超时") from exc

    def disconnect(self):
        try:
            if self._reader is not None:
                self._reader.close()
            if self._socket is not None:
                self._socket.close()
        finally:
            self._reader = self._socket = None
            if self._port is not None:
                try:
                    self._run_adb("forward", "--remove", f"tcp:{self._port}", serial=self._device_serial)
                except LinkError:
                    pass
                finally:
                    self._port = None
