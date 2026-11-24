"""Configurable TCP command probe. No assumed SimREPLAYplus command dialect."""
import socket
from .core import DeviceError


def exchange(host, port, command, tx_end, rx_end, timeout=3):
    if not command.strip() or "\r" in command or "\n" in command:
        raise DeviceError("请输入单条仪器指令")
    if not 1 <= port <= 65535 or not host.strip():
        raise DeviceError("请输入有效地址和端口")
    if tx_end not in (b"", b"\n", b"\r", b"\r\n") or rx_end not in (b"", b"\n", b"\r", b"\r\n"):
        raise DeviceError("无效结束符")
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(command.encode("ascii") + tx_end)
        if not rx_end:
            return "已发送；未请求响应，不代表执行成功"
        data = bytearray()
        from time import monotonic
        deadline = monotonic() + timeout
        while len(data) < 65536:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise DeviceError("响应超时；执行状态未知，不自动重试")
            sock.settimeout(remaining)
            chunk = sock.recv(min(4096, 65536 - len(data)))
            if not chunk:
                raise DeviceError("连接关闭，未收到完整响应")
            data.extend(chunk)
            if rx_end in data:
                return data.decode("utf-8", errors="replace")
        raise DeviceError("响应超过 64 KiB")


def render_command(template, value=None):
    if not template.strip():
        raise DeviceError("尚未配置并核对该指令")
    if value is None:
        if "{" in template or "}" in template:
            raise DeviceError("查询指令不允许参数占位符")
        return template
    if template.count("{value}") != 1:
        raise DeviceError("设置指令须包含一个 {value}")
    return template.replace("{value}", str(value))
