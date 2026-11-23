"""Phone transport contract. Phase 1 implements loopback JSONL over USB ADB."""
import socket
from abc import ABC, abstractmethod

from .adb import run_adb
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

    def check_connection(self):
        """Raise if a previously observed transport loss prevents further work."""


class AdbTransport(PhoneTransport):
    def __init__(self, usb, adb="adb"):
        self.usb = usb
        self.adb = adb
        self._socket = None
        self._reader = None
        self._port = None

    def _run_adb(self, *args):
        return run_adb(self.adb, *args, serial=self.usb.device.serial)

    def check_connection(self):
        self.usb.check()

    def connect(self):
        self.check_connection()
        # Allocate a host port to avoid overwriting another application's forward.
        try:
            self._port = int(self._run_adb("forward", "tcp:0", "tcp:18765"))
            self._socket = socket.create_connection(("127.0.0.1", self._port), timeout=2)
            self._reader = self._socket.makefile("rb")
            self.check_connection()
        except (OSError, ValueError, LinkError) as exc:
            self.disconnect()
            raise LinkError(f"ADB 转发无法连接，请检查手机采集服务（{exc}）") from exc

    def send_command(self, command):
        self.check_connection()
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
        except (OSError, LinkError) as exc:
            raise LinkError(f"USB 通信异常：{self.usb.device.serial} 未返回有效响应（{exc}）") from exc

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
                    if not self.usb.lost.is_set():
                        self._run_adb("forward", "--remove", f"tcp:{self._port}")
                except LinkError:
                    pass
                finally:
                    self._port = None
